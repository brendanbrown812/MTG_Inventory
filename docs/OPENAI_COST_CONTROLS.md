# OpenAI cost controls

Spellbinder keeps paid OpenAI requests locked by default. Setting an API key alone does not
enable them; `OPENAI_REQUESTS_ENABLED=true` is also required.

Before every OpenAI request, the backend records a worst-case cost reservation using a
conservative local token estimate and the request's maximum output-token setting. A request is
blocked when it would exceed either:

- `OPENAI_SINGLE_REQUEST_LIMIT_USD` (default `$0.10`), or
- `OPENAI_MONTHLY_BUDGET_USD` (default `$1.00`).

Successful requests replace the reservation with the token usage returned by the API. Failed
requests release it. The Enrich page displays current-month spend, outstanding reservations,
remaining budget, and recent workflow-level usage. Records contain model and token metadata,
never the API key, prompts, card text, or response content.

These controls are local safety rails, not an authoritative bill. Prices are a dated application
snapshot and can change. Configure a project-level budget and alert in the OpenAI dashboard as a
second, independent guard.

The current snapshot uses the official [GPT-5.6 Luna model pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
and reconciles the token fields returned by the [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

## First paid canary

Do this only after reviewing the local MTG quality gate and the cost panel:

1. Keep the default `$1.00` monthly and `$0.10` request limits.
2. Set `OPENAI_REQUESTS_ENABLED=true` in the uncommitted `.env` file and restart the backend.
3. Enrich the default 12-card canary batch.
4. Build the default 100-card embedding canary batch.
5. Inspect profiles, run the local quality gate, and inspect the cost ledger.
6. Set `OPENAI_REQUESTS_ENABLED=false` again and restart if you do not want further paid calls.

The application never automatically unlocks paid requests or starts this canary.
