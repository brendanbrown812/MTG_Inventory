# Spellbinder authentication and deployment security

Spellbinder changes personal collection data and can make paid AI requests. CORS is not authentication. Docker deployments use Spellbinder's native session login by default.

## Native administrator login (recommended)

Set these values in the ignored project-root `.env` file:

```dotenv
AUTH_MODE=session
REQUIRE_AUTH=true
SESSION_COOKIE_SECURE=true
```

Use `SESSION_COOKIE_SECURE=true` when the browser reaches Spellbinder through an HTTPS address, including a Cloudflare Tunnel domain. Use `false` only for direct HTTP access such as `http://localhost:8888`; a browser will not send a Secure cookie over plain HTTP.

Create the first administrator after the containers are running:

```console
docker compose exec backend python -m app.auth_cli create-user brend --admin
```

For manual backend development, run the equivalent command from the `backend` folder:

```console
python -m app.auth_cli create-user brend --admin
```

The command prompts for the password without echoing it. Passwords are stored as Argon2id hashes. Browser sessions use opaque, server-side session records; the raw token is stored only in an HttpOnly/SameSite cookie (and Secure when configured). Write requests additionally require a session-bound CSRF token.

Useful account commands:

```console
python -m app.auth_cli list-users
python -m app.auth_cli reset-password brend
```

Resetting a password revokes that user's existing sessions. There is intentionally no public registration route. The schema includes a role field so read-only viewer accounts can be introduced later, but this release accepts administrators only.

## Legacy API-key mode

Scripts or older deployments can explicitly retain the shared-key flow:

```dotenv
AUTH_MODE=api_key
APP_API_KEY=replace-with-a-long-random-value
```

The frontend retains an API-key unlock screen for this compatibility mode. The key is held in the browser tab's session storage and sent as `X-Spellbinder-Key`.

## External authentication

A Cloudflare Tunnel by itself is not authentication. If an upstream service such as Cloudflare Access blocks unauthenticated traffic before it reaches Spellbinder, use:

```dotenv
AUTH_MODE=external
EXTERNAL_AUTH_ENABLED=true
```

## Local-only use

The manual backend and Vite development server bind to `127.0.0.1`. With `AUTH_MODE=auto`, no API key, and `REQUIRE_AUTH=false`, authentication remains disabled for that local workflow. To test native login locally, set `AUTH_MODE=session` and `SESSION_COOKIE_SECURE=false` before starting the backend.

## Public endpoints

`/api/health`, `/api/auth/status`, and `/api/auth/login` are public so health checks and sign-in work. Login responses use generic errors and repeated failed attempts are throttled. All other `/api/` routes require the configured authentication mode. In session mode, mutations require the CSRF token returned after login.
