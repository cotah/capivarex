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
# Can be set via env vars OR fetched automatically from Supabase JWKS endpoint.
_JWK_X = os.environ.get("SUPABASE_JWT_JWK_X", "")
_JWK_Y = os.environ.get("SUPABASE_JWT_JWK_Y", "")


def _b64url_to_int(b64url: str) -> int:
    """Decode a Base64url-encoded string to an integer."""
    padded = b64url + "=" * (4 - len(b64url) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def _build_ec_key_from_coords(x_b64: str, y_b64: str):
    """Build EC public key from JWK x/y coordinates (P-256)."""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
            EllipticCurvePublicNumbers,
        )

        x = _b64url_to_int(x_b64)
        y = _b64url_to_int(y_b64)
        pub_numbers = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP256R1())
        return pub_numbers.public_key(default_backend())
    except Exception as exc:
        logger.warning(f"WebApp auth: failed to build ES256 key from coords: {exc}")
        return None


def _fetch_supabase_jwks():
    """Fetch JWKS from Supabase and extract ES256 key coordinates."""
    supabase_url = os.getenv("SUPABASE_URL", "")
    if not supabase_url:
        return None, None

    try:
        import httpx

        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        resp = httpx.get(jwks_url, timeout=3)
        if resp.status_code != 200:
            logger.warning(f"WebApp auth: JWKS fetch failed: {resp.status_code}")
            return None, None

        jwks = resp.json()
        for key in jwks.get("keys", []):
            if key.get("kty") == "EC" and key.get("crv") == "P-256":
                logger.info("WebApp auth: fetched ES256 key from Supabase JWKS")
                return key.get("x", ""), key.get("y", "")

        logger.warning("WebApp auth: no ES256 key found in JWKS")
        return None, None
    except Exception as exc:
        logger.warning(f"WebApp auth: JWKS fetch error (non-blocking): {exc}")
        return None, None


def _build_supabase_ec_key():
    """Build the EC public key — from env vars or fetched from JWKS."""
    # Try env vars first
    if _JWK_X and _JWK_Y:
        key = _build_ec_key_from_coords(_JWK_X, _JWK_Y)
        if key:
            logger.info("WebApp auth: ES256 key built from env vars")
            return key

    # Fallback: fetch from Supabase JWKS endpoint
    x, y = _fetch_supabase_jwks()
    if x and y:
        key = _build_ec_key_from_coords(x, y)
        if key:
            return key

    logger.warning("WebApp auth: ES256 key not available — ES256 tokens will fail")
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

    If ES256 fails, attempts to rebuild the key from JWKS on the fly.

    Raises:
        HTTPException 401: If all strategies fail or ``sub`` is missing.
    """
    global SUPABASE_PUBLIC_KEY

    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials

    # Strip known invalid prefixes
    _INVALID_PREFIXES = ("Bearer ", "base64-", "undefined", "null")
    for _pfx in _INVALID_PREFIXES:
        if token.startswith(_pfx):
            logger.warning(
                "WebApp auth: stripped invalid token prefix '{}'",
                _pfx,
            )
            token = token[len(_pfx) :]
            break

    # Validate JWT structure
    parts = token.split(".")
    if len(parts) != 3:
        logger.error(
            "WebApp auth: malformed JWT — expected 3 parts, got {}. Token prefix: '{}'",
            len(parts),
            token[:30],
        )
        raise HTTPException(status_code=401, detail="Invalid token format")

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")

    # Try up to 2 rounds: first with current key, then rebuild if ES256 fails
    for attempt in range(2):
        strategies: list[tuple[str, dict]] = []

        # Strategy 1: ES256 with Supabase EC public key
        if SUPABASE_PUBLIC_KEY:
            strategies.append(
                (
                    "es256_pubkey",
                    {
                        "key": SUPABASE_PUBLIC_KEY,
                        "algorithms": ["ES256"],
                        "options": {"verify_aud": False},
                    },
                )
            )

        # Strategy 2: HS256 with audience check
        if jwt_secret:
            strategies.append(
                (
                    "hs256_with_aud",
                    {
                        "key": jwt_secret,
                        "algorithms": ["HS256"],
                        "audience": "authenticated",
                    },
                )
            )
            # Strategy 3: HS256 without audience check
            strategies.append(
                (
                    "hs256_no_aud",
                    {
                        "key": jwt_secret,
                        "algorithms": ["HS256"],
                        "options": {"verify_aud": False},
                    },
                )
            )

        last_error = None
        es256_failed = False
        for strategy_name, decode_kwargs in strategies:
            try:
                payload = jwt.decode(token, **decode_kwargs)
                user_id = payload.get("sub")
                if not user_id:
                    raise HTTPException(
                        status_code=401, detail="Invalid token: no user ID"
                    )

                if strategy_name == "es256_pubkey":
                    logger.info(f"WebApp auth: verified user_id={user_id} via ES256")
                elif strategy_name == "hs256_with_aud":
                    logger.info(f"WebApp auth: verified user_id={user_id} via HS256")
                else:
                    logger.warning(
                        f"WebApp auth: used fallback strategy"
                        f" '{strategy_name}' for user {user_id}"
                    )

                return user_id
            except HTTPException:
                raise
            except Exception as e:
                last_error = e
                if strategy_name == "es256_pubkey":
                    es256_failed = True
                logger.debug(
                    f"WebApp auth: strategy '{strategy_name}' failed:"
                    f" {type(e).__name__}: {e}"
                )
                continue

        # If ES256 failed on first attempt, try rebuilding the key
        if es256_failed and attempt == 0:
            logger.warning("WebApp auth: ES256 failed, rebuilding key from JWKS...")
            new_key = _build_supabase_ec_key()
            if new_key and new_key != SUPABASE_PUBLIC_KEY:
                SUPABASE_PUBLIC_KEY = new_key
                logger.info("WebApp auth: ES256 key rebuilt — retrying")
                continue  # Retry with new key
            else:
                break  # Key didn't change, no point retrying
        else:
            break

    logger.error(
        f"WebApp auth: ALL strategies failed."
        f" Last error: {type(last_error).__name__}: {last_error}"
    )
    logger.warning(
        f"WebApp auth: JWT_SECRET set: {bool(jwt_secret)},"
        f" ES256_KEY set: {SUPABASE_PUBLIC_KEY is not None},"
        f" token prefix: {token[:20]}..."
    )
    raise HTTPException(status_code=401, detail="Invalid or expired token")
