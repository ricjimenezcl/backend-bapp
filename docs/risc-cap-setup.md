# Google RISC/CAP setup for backend-bapp

This backend now exposes a RISC receiver endpoint:
- POST /api/v1/auth/risc/events

## 1) Required backend environment variables

Add these variables in your deployment environment:

- RISC_GOOGLE_CLIENT_IDS
  - List of OAuth client IDs allowed in RISC token audience.
  - Accepted formats:
    - JSON array:
      ["123.apps.googleusercontent.com", "456.apps.googleusercontent.com"]
    - CSV:
      123.apps.googleusercontent.com,456.apps.googleusercontent.com

Notes:
- OAUTH_GOOGLE_CLIENT_ID is also accepted as fallback audience.
- Keep using the same Google Cloud project used by Sign in with Google.

## 2) Endpoint behavior implemented

The receiver validates:
- Google RISC discovery document:
  - https://accounts.google.com/.well-known/risc-configuration
- JWKS signature key by JWT kid
- RS256 signature
- iss claim
- aud claim against configured OAuth client IDs
- jti deduplication (retries are ignored)

For critical events, it revokes local sessions globally for affected users.

## 3) Stream management script

A helper script is included:
- scripts/risc_stream_manager.py

Commands:

```bash
python scripts/risc_stream_manager.py token \
  --service-account /secure/path/service-account.json
```

```bash
python scripts/risc_stream_manager.py update \
  --service-account /secure/path/service-account.json \
  --receiver-url https://api.your-domain.com/api/v1/auth/risc/events
```

```bash
python scripts/risc_stream_manager.py get \
  --service-account /secure/path/service-account.json
```

```bash
python scripts/risc_stream_manager.py verify \
  --service-account /secure/path/service-account.json \
  --state risc-smoke-test-001
```

```bash
python scripts/risc_stream_manager.py status \
  --service-account /secure/path/service-account.json \
  --value enabled
```

## 4) Suggested event types

Default list used by update command:
- https://schemas.openid.net/secevent/risc/event-type/sessions-revoked
- https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked
- https://schemas.openid.net/secevent/oauth/event-type/token-revoked
- https://schemas.openid.net/secevent/risc/event-type/account-disabled
- https://schemas.openid.net/secevent/risc/event-type/account-credential-change-required
- https://schemas.openid.net/secevent/risc/event-type/verification

## 5) Operational checklist

- Ensure receiver URL is HTTPS and in authorized domains in Google project.
- Confirm OAuth consent screen is configured in the same project.
- Grant service account role: roles/riscconfigs.admin.
- Store service account JSON in a secure secret manager.
- Run verify command and confirm event reaches backend logs.

## 6) Smoke test flow

1. Configure stream with update command.
2. Trigger verify command.
3. Check backend logs for accepted event.
4. Re-send the same token (if captured) and confirm dedupe path.
