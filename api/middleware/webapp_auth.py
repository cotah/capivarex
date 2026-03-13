"""
Middleware for authenticating webapp requests via Supabase JWT.

All /api/webapp/* endpoints use ``verify_webapp_user`` as a FastAPI dependency
to extract and validate the authenticated user's UUID from the Supabase JWT.

Supports two signing algorithms:
- **ES256** (asymmetric) — modern Supabase tokens signed with an EC key.
  The public key is derived from hardcoded JWK coordinates (P-256 curve).
- **HS256** (symmetric) — legacy/Telegram tokens signed with the JWT secret.
"""

import base64
import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

# auto_error=False prevents FastAPI from automatically returning a 403 with
# the WWW-Authenticate: Bearer header when the Authorization header is
# missing. That header causes Chromium to block cross-origin responses with
# net::ERR_FAILED, making the error unreadable by the frontend.
security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Supabase ES256 public key (from JWKS)
# ---------------------------------------------------------------------------

# JWK coordinates for the Supabase signing key (alg: ES256, crv: P-256).
# Source: https://gakybwrvpwyvufovweis.supabase.co/auth/v1/.well-known/jwks.json
_JWK_X = os.environ.get("SUPABASE_JWT_JWK_X", "")
_JWK_Y = os.environ.get("SUPABASE_JWT_JWK_Y", "")


def _b64url_to_int(b64url: str) -> int:
    """Decode a Base64url-encoded string to an integer."""
    padded = b64url + "=" * (4 - len(b64url) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def _build_supabase_ec_key():
    """Build the EC public key from JWK x/y coordinates (P-256)."""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
            EllipticCurvePublicNumbers,
        )

        x = _b64url_to_int(_JWK_X)
        y = _b64url_to_int(_JWK_Y)
        pub_numbers = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP256R1())
        return pub_numbers.public_key(default_backend())
    except Exception as exc:
        logger.warning(f"WebApp auth: failed to build ES256 public key: {exc}")
        return None


# Built once at import time so we don't reconstruct on every request.
SUPABASE_PUBLIC_KEY = _build_supabase_ec_key()


async def verify_webapp_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Verify a Supabase JWT and return the ``user_id`` (``sub`` claim).

    Uses a multi-strategy approach (tried in order):
    1. **ES256** with the Supabase EC public key (modern webapp tokens)
    2. **HS256** with audience verification (legacy / Telegram tokens)
    3. **HS256** without audience verification (fallback)

    Raises:
        HTTPException 401: If all strategies fail or ``sub`` is missing.
    """
    # credentials is None when the Authorization header is absent entirely.
    # We raise 401 WITHOUT the WWW-Authenticate header so that Chrome does
    # not treat it as an HTTP Basic-Auth challenge (which causes ERR_FAILED
    # for cross-origin requests and breaks the frontend).
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials

    # Strip known invalid prefixes — defence-in-depth against frontend bugs
    _INVALID_PREFIXES = ("Bearer ", "base64-", "undefined", "null")
    for _pfx in _INVALID_PREFIXES:
        if token.startswith(_pfx):
            logger.warning(
                "WebApp auth: stripped invalid token prefix '{}'"
                " — possible frontend bug",
                _pfx,
            )
            token = token[len(_pfx):]
            break

    # Validate JWT structure (must have exactly 3 dot-separated parts)
    parts = token.split(".")
    if len(parts) != 3:
        logger.error(
            "WebApp auth: malformed JWT — expected 3 parts, got {}."
            " Token prefix: '{}'",
            len(parts),
            token[:30],
        )
        raise HTTPException(
            status_code=401, detail="Invalid token format"
        )

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

    strategies: list[tuple[str, dict]] = []

    # Strategy 1: ES256 with Supabase EC public key
    if SUPABASE_PUBLIC_KEY:
        strategies.append(("es256_pubkey", {
            "key": SUPABASE_PUBLIC_KEY,
            "algorithms": ["ES256"],
            "options": {"verify_aud": False},
        }))

    # Strategy 2: HS256 with audience check
    if jwt_secret:
        strategies.append(("hs256_with_aud", {
            "key": jwt_secret,
            "algorithms": ["HS256"],
            "audience": "authenticated",
        }))
        # Strategy 3: HS256 without audience check
        strategies.append(("hs256_no_aud", {
            "key": jwt_secret,
            "algorithms": ["HS256"],
            "options": {"verify_aud": False},
        }))

    last_error = None
    for strategy_name, decode_kwargs in strategies:
        try:
            payload = jwt.decode(token, **decode_kwargs)
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=401, detail="Invalid token: no user ID"
                )

            if strategy_name == "es256_pubkey":
                logger.info(
                    f"WebApp auth: verified user_id={user_id} via ES256"
                )
            elif strategy_name == "hs256_with_aud":
                logger.info(
                    f"WebApp auth: verified user_id={user_id} via HS256"
                )
            else:
                logger.warning(
                    f"WebApp auth: used fallback strategy '{strategy_name}'"
                    f" for user {user_id}"
                )

            return user_id
        except HTTPException:
            raise
        except Exception as e:
            last_error = e
            logger.debug(
                f"WebApp auth: strategy '{strategy_name}' failed:"
                f" {type(e).__name__}: {e}"
            )
            continue

    logger.error(
        f"WebApp auth: ALL strategies failed."
        f" Last error: {type(last_error).__name__}: {last_error}"
    )
    logger.error(
        f"WebApp auth: JWT_SECRET set: {bool(jwt_secret)},"
        f" ES256_KEY set: {SUPABASE_PUBLIC_KEY is not None},"
        f" token prefix: {token[:20]}..."
    )
    raise HTTPException(
        status_code=401, detail="Invalid or expired token"
    )
