# Reasoning model and deterministic deck optimizer

Full deck construction uses two stages with a hard trust boundary.

## 1. Strategic reasoning

The configured reasoning provider receives at most the bounded collection-aware candidate pool. It may return only:

- a recommended commander;
- a strategy summary;
- named strategic packages with priorities and desired bounds;
- candidate-level priorities.

Every referenced name is canonicalized against the candidate pool. Unknown names, extra fields, duplicate package cards, invalid bounds, and out-of-range priorities are rejected. The proposal schema intentionally has no decklist or quantity field.

Configuration uses `REASONING_PROVIDER` and `REASONING_MODEL`. The default
`openai` provider sends the bounded pool to the OpenAI Responses API and uses
strict structured output matching the provider-neutral reasoning contract.
Responses are not stored by the API request. Request timeout, retry count,
reasoning effort, and maximum output tokens are configurable.

Paid requests require both `OPENAI_REQUESTS_ENABLED=true` and a configured
`OPENAI_API_KEY`. Otherwise, the app derives theme, known-interaction, and
deck-function packages entirely from the bounded owned candidate pool. This
deterministic fallback makes no network call and is also used if the OpenAI
request, refusal handling, or proposal validation fails. Provider calls log
model, response ID, latency, candidate count, and token usage but never the API
key or full prompt.

Anthropic remains available only as an explicitly selected enrichment or
build-strategy provider. Suggest and Audit use the separate provider-neutral
review pipeline described in `DECK_REVIEW.md`. Regardless of provider, a build
proposal remains advisory and cannot supply a decklist or quantities.

### Local configuration

Copy `.env.example` to `.env`, then set only:

```dotenv
OPENAI_API_KEY=your-project-key
OPENAI_REQUESTS_ENABLED=false
REASONING_PROVIDER=openai
REASONING_MODEL=gpt-5.6-luna
```

Do not paste a key into source code, commit it, or send it through the browser.
Restart the backend after changing `.env`. Leave `OPENAI_REQUESTS_ENABLED=false`
while developing; switch it to `true` only when you intentionally want paid
reasoning calls. A blank key also keeps deck construction local.

## 2. Deterministic assembly

Code chooses every final card and quantity. It treats model package preferences as advisory, then fills deterministic deck-health roles, curve value, nonland slots, utility lands, and owned basic lands.

The returned deck is accepted only when all hard checks pass:

- every card belongs to the bounded candidate pool;
- exactly 100 cards including exactly one eligible commander;
- Commander legality;
- commander color identity;
- singleton and card-specific copy limits;
- owned quantities aggregated across printings.

If the pool cannot satisfy the constraints, the optimizer returns `feasible: false`, an empty or partial diagnostic deck, and explicit validation errors. It never asks the model to repair or bypass a failed constraint.

The build response includes reasoning provenance, package fulfillment, optimizer version, objective score, every hard-check result, and the optimizer-authored decklist.
