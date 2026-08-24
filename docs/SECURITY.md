# Spellbinder deployment security

Spellbinder changes personal collection data and can make paid AI requests. CORS is not authentication. Set `REQUIRE_AUTH=true` for every LAN, tunnel, or public deployment; the backend then refuses to start unless one of the protections below is explicitly configured. Docker Compose enables this requirement by default.

## Option 1: Spellbinder API key

Generate a long random value and place it in the ignored project-root `.env` file:

```dotenv
APP_API_KEY=replace-with-a-long-random-value
REQUIRE_AUTH=true
EXTERNAL_AUTH_ENABLED=false
```

When an API key is configured, the frontend shows an unlock screen. The key is retained only in that browser tab's session storage and is sent as `X-Spellbinder-Key` on API requests. Closing the tab clears it.

Do not commit or paste the real key into `.env.example`, screenshots, logs, or support messages.

## Option 2: Cloudflare Access or another authenticating proxy

A Cloudflare Tunnel by itself is not authentication. Configure an Access application and policy that blocks unauthenticated requests before they reach Spellbinder, then set:

```dotenv
APP_API_KEY=
REQUIRE_AUTH=true
EXTERNAL_AUTH_ENABLED=true
```

Only set `EXTERNAL_AUTH_ENABLED=true` when the upstream proxy actually enforces authentication. This flag is an explicit acknowledgement; Spellbinder cannot verify the proxy policy itself.

## Local-only use

The manual backend and Vite development server bind to `127.0.0.1`, so `REQUIRE_AUTH` may remain false and existing local behavior is unchanged. A stale remote CORS origin produces a warning but does not block that local process. Docker sets `REQUIRE_AUTH=true` by default because its published port can be reached beyond loopback unless the host firewall prevents it.

## Public endpoints

`/api/health` and `/api/auth/status` remain public so container health checks and the unlock screen work. All other `/api/` routes require the configured API key unless authentication is disabled or delegated upstream.
