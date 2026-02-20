# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

We take the security of the Capivarex project seriously. If you discover a security vulnerability, please follow the responsible disclosure process below.

### How to Report

1. **DO NOT** create a public GitHub issue for security vulnerabilities.
2. Send an email to the project maintainers with the subject line: `[SECURITY] Vulnerability Report - Capivarex`.
3. Include the following information in your report:
   - Description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact assessment
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within **48 hours**.
- **Assessment**: We will investigate and assess the vulnerability within **7 business days**.
- **Resolution**: Critical vulnerabilities will be patched within **14 days**. Non-critical issues will be addressed in the next scheduled release.
- **Credit**: We will credit you in the release notes (unless you prefer to remain anonymous).

## Security Measures in Place

### Authentication & Authorization
- JWT-based authentication with configurable expiration
- Bcrypt password hashing with salt
- OAuth2 Bearer token scheme
- Plan-based rate limiting

### Infrastructure Security
- Non-root Docker container execution
- Multi-stage Docker builds (minimal attack surface)
- Health checks on all services
- Resource limits on containers
- Automated dependency vulnerability scanning via Dependabot

### Application Security
- Security headers middleware (CSP, HSTS, X-Frame-Options, etc.)
- CORS restricted to configured origins only
- Input validation via Pydantic schemas
- SQL injection prevention via Supabase parameterized queries
- Rate limiting on sensitive endpoints
- No credentials in git history

### Dependency Management
- Weekly automated dependency updates via Dependabot
- Regular `pip-audit` scans for known CVEs
- Minimal dependency tree (removed transitive vulnerability sources)

## Security Best Practices for Contributors

1. Never commit secrets, API keys, or credentials to the repository
2. Always use environment variables for sensitive configuration
3. Run `pip-audit` before submitting PRs that change dependencies
4. Follow the principle of least privilege in all code
5. Validate all user input at the API boundary
