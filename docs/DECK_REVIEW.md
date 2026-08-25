# Provider-neutral Suggest and Audit

The Deckbuilding page's Suggest and Audit modes no longer call Claude directly
or require `ANTHROPIC_API_KEY`. They use a provider-neutral review contract with
OpenAI `gpt-5.6-luna` as the optional default and a deterministic local fallback.

## Trust boundaries

Before any optional model call, Spellbinder resolves the pasted deck against
the local Oracle-card database and retrieves at most 200 owned,
Commander-legal candidate additions. The model receives structured local card
facts and retrieval explanations rather than unrestricted access to the
collection or database.

Both response contracts use strict Pydantic structured output. Code then
canonicalizes and validates every name:

- additions must be exact members of the bounded owned candidate pool;
- cuts must be exact cards from the recognized pasted deck;
- replacement targets must be exact cards from the recognized pasted deck;
- duplicate recommendations, unknown names, extra fields, and oversized output
  are rejected.

If the provider request, parsing, or boundary validation fails, the request is
retried through the deterministic reviewer. The model cannot expand its own
candidate pool or make an unowned card actionable.

## Paid lock and configuration

```dotenv
OPENAI_REQUESTS_ENABLED=false
REVIEW_PROVIDER=openai
REVIEW_MODEL=gpt-5.6-luna
REVIEW_REASONING_EFFORT=low
REVIEW_MAX_OUTPUT_TOKENS=4000
REVIEW_FALLBACK_MODEL=rules-v1
```

When paid calls are locked, the endpoints still return useful local results.
The deterministic reviewer ranks additions with the existing role, mechanic,
semantic, combo, universal-utility, and feedback scorer. It identifies missing
core functions, reviews the land count for complete decks, and flags expensive
or functionally unrecognized cards as manual cut candidates.

Every response includes `review_provenance` so the frontend shows whether the
review came from OpenAI or local rules. Audit also runs deterministic decklist
validation and returns its warnings independently of model output.

OpenAI requests use the Responses API with strict structured output,
`store=false`, configured timeout/retries, and bounded output tokens. Logs
include mode, model, response ID, candidate count, token usage, and latency but
never API keys or full prompts.
