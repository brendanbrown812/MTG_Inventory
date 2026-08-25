# Semantic Oracle-card index

Schema migration 7 adds a persistent, versioned semantic index without
changing collection, printing, deck, or inventory rows.

## What is embedded

Each Oracle card is represented once using its name, type line, mana cost,
Oracle text, Scryfall keywords, and current structured mechanic profile. The
profile contributes closed functional roles, mechanic relationships, universal
utility, and schema/taxonomy versions. A SHA-256 content hash makes indexing
resumable and automatically marks a vector stale when any of that source data
changes.

The default configuration is:

```dotenv
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=512
EMBEDDING_REQUEST_BATCH_SIZE=100
```

Vectors are normalized and stored as compact float32 blobs in
`oracle_embeddings`. At 512 dimensions, the raw vector payload is 2 KiB per
Oracle card. Historical vectors retain model, provider, index version, source
hash, dimensions, token usage, and creation time. Only a matching current
vector is eligible for retrieval.

Deck-strategy query vectors are stored in `semantic_query_embeddings` by
content hash. Repeating an identical request reuses the vector instead of
making another billable request.

## Building the index

The Enrichment page exposes **Step 3 — Semantic Candidate Index**. It shows
ready/stale counts, model and dimensions, a remaining-cost estimate, progress,
actual input-token usage, and estimated job cost. Each request commits a
bounded chunk, so rerunning after an interruption skips completed unchanged
cards.

Both card indexing and uncached query embedding honor
`OPENAI_REQUESTS_ENABLED`. With the default `false` value, the API rejects an
index request before contacting OpenAI. Candidate retrieval remains functional
and reports `lexical_fallback` provenance. Previously cached query vectors can
still be used while the lock is off, because that incurs no API request.

At the documented price of $0.02 per million input tokens, indexing a personal
collection is expected to cost only a small fraction of a dollar. The UI uses
a conservative seed token estimate until actual batch usage is available.

## Retrieval behavior

Ownership, Commander legality, commander color identity, and exclusions are
applied before vector scoring. Semantic similarity contributes at most 25
points and cannot override these hard filters. Deterministic mechanic
relationships, roles, known combos, universal utility, deck-health coverage,
feedback, and anti-synergy penalties remain separate inspectable components.

Every candidate publishes:

```json
{
  "semantic": {
    "source": "openai_embedding",
    "similarity": 0.71,
    "embedding_similarity": 0.71,
    "lexical_similarity": 0.08
  }
}
```

If a card vector is missing, corrupt, stale, or dimensionally incompatible,
that card safely uses lexical similarity for the request.
