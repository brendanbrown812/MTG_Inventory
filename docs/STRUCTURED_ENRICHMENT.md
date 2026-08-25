# Structured mechanic enrichment

Spellbinder enriches Oracle cards rather than physical printings. Each current
profile records a closed set of functional roles, evidence-backed mechanic
hooks, universal-utility classification, schema/taxonomy versions, provider,
model, confidence, and token usage. Previous profile versions are preserved.

## OpenAI provider

The default provider is OpenAI `gpt-5.6-luna` with low reasoning effort. Each
request contains at most 12 exact Oracle-card records and uses the Responses
API's Pydantic structured output. The prompt does not contain a hand-written
copy of the schema. Responses are requested with `store=false`.

Before persistence, the backend requires exactly one result for every supplied
Oracle ID, rejects extra or duplicate cards, verifies card names, validates the
closed taxonomy, and confirms every evidence excerpt occurs in that card's
Oracle text. A failed chunk is not committed. Completed chunks remain cached as
current profiles, so rerunning resumes with unprofiled cards.

## Cost lock

Both of these are required before enrichment can call OpenAI:

```dotenv
OPENAI_API_KEY=your-project-key
OPENAI_REQUESTS_ENABLED=true
```

The default is `OPENAI_REQUESTS_ENABLED=false`. With the lock disabled, the
Enrich page shows the configured model and estimated cost but disables profile
creation. Scryfall metadata backfill remains available because it makes no AI
request.

Provider responses log response ID, model, card count, latency, and token usage
to `backend/logs/spellbinder.log`. API keys and full prompts are not logged.

## Quality workflow

Start with a small batch when paid calls are eventually enabled. Review the
latest profiles on the Enrich page, compare representative results to
`backend/evals/mtg_mechanics_v1.json`, and only then increase the batch size.
Changing the schema or taxonomy version causes cards to become eligible for a
new version without deleting their prior profile history.

Run the Local MTG Quality Gate after each reviewed batch. It compares the
stored profiles and retrieval behavior to versioned golden expectations without
making an API request; see `EVALUATION.md`.
