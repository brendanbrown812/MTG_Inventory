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

## Shared guest link

When signed in as the native administrator, open **Guest access** in the top
navigation. **Generate guest link** creates one private link for all friends;
no guest accounts or passwords are needed. Guest sharing starts disabled.
Guests can browse the collection, deck list, and individual decks, including
commanders and sideboards. Deck notes remain private. The guest interface has
image galleries for owned collection printings and assigned deck printings,
including set/collector numbers, foil treatments, and click-to-enlarge previews.
Copies with no assigned printing are labelled as example artwork. It has
no editing, import, export, settings, assembly, or AI tools. The backend also
rejects guest requests to every administrator endpoint, including GET routes
that can fetch external data or change cached state.

Generate the link while visiting your hosted site's public HTTPS address.
A link generated at `127.0.0.1` or `localhost` only works on that computer.
The Mac development launcher still binds only to loopback. Guest sharing does
not publish your Mac or change your deployment's existing network access rules.
If an upstream proxy requires authentication, friends must also satisfy that
proxy's access rules.

Use **Show existing guest link** to retrieve and copy the current link again.
This administrator-only action does not change the link, its creation time,
or existing guest sessions. To support retrieval, the active invite secret is
stored in the application's private database alongside its verification digest;
protect the database and its backups as credentials. Browser session tokens
remain stored only as digests. The retrieval response is marked private and
no-store, and guest/anonymous clients cannot access it.

**Regenerate guest link** replaces the link and revokes all existing guest
sessions. **Disable guest access** revokes the link and sessions and removes
the saved invite secret. These changes take effect on each subsequent API
request; content already viewed cannot be recalled.

Older installations stored only an invite digest. The schema upgrade preserves
those links and sessions. If the existing link cannot yet be shown, have a
holder open the original invite once: a successful redemption saves that same
secret for future administrator retrieval without rotation or revocation. An
existing guest session alone cannot reconstruct the invite. If no one has a
copy of the original link, regenerating it is necessary.

The link carries its secret in a URL fragment (`/#guest=...`), which is removed
from the browser address bar before it is exchanged in a POST body for a
separate HttpOnly, SameSite=Strict guest cookie. Guest sessions last 30 days
unless revoked sooner. Production HTTPS deployments should keep
`SESSION_COOKIE_SECURE=true`; local HTTP uses `false`. Invite digests and guest
session digests live in new SQLite tables created automatically on startup.
Administrator sessions and credentials are independent of guest sessions.

Guest sharing requires `AUTH_MODE=session`. API-key, external-proxy, and
disabled authentication modes do not offer the guest-link management controls.
Anyone who receives or is forwarded the link can use it until it is revoked;
this first version does not identify or revoke individual friends separately.
