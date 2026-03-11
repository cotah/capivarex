# Security Policy — Capivarex

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Active    |

## Reporting a Vulnerability

If you discover a security vulnerability in Capivarex, please report it responsibly.

**Email:** security@capivarex.com

**Do NOT:**
- Open a public GitHub issue for security vulnerabilities
- Share vulnerability details publicly before it's fixed
- Attempt to access other users' data

**We will:**
- Acknowledge receipt within 48 hours
- Provide an initial assessment within 5 business days
- Work on a fix and coordinate disclosure

## Security Measures

Capivarex implements the following security measures:

- **Encryption at rest:** All OAuth tokens encrypted with Fernet (AES-128-CBC)
- **HTTPS only:** All traffic encrypted in transit (enforced by Railway)
- **Row Level Security:** Database-level tenant isolation via Supabase RLS
- **Rate limiting:** API rate limiting to prevent abuse
- **Security headers:** CSP, X-Frame-Options, X-Content-Type-Options
- **Input validation:** All inputs validated via Pydantic schemas
- **Audit logging:** Security-relevant events logged with structured format
- **Dependency scanning:** Regular dependency audits via pip-audit

## Data Privacy

- User data is isolated per account (never shared between users)
- OAuth tokens are encrypted before storage
- Credentials are never logged or exposed in error messages
- Users can disconnect services and delete their data at any time

## Environment Variables

All secrets are stored as environment variables, never in code:
- `ENCRYPTION_KEY` — Required for OAuth token encryption
- `JWT_SECRET_KEY` — Required for API authentication
- Database credentials, API keys — All via environment variables

## Contact

For security concerns: security@capivarex.com
For general support: support@capivarex.com
