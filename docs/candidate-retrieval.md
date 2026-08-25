# Collection-aware candidate retrieval

Candidate retrieval is local, deterministic, and does not call an AI model. It operates only on owned, Commander-legal Oracle cards and aggregates quantities across physical printings.

The scorer combines:

- deterministic deck-health roles shared with the Commander engine;
- versioned mechanic-profile roles and producer/consumer/reward/prevention relationships;
- OpenAI semantic similarity from the persistent Oracle-card index, when both
  a current card vector and a cached or enabled query vector are available;
- deterministic MTG concept expansion and TF-IDF as an explicit no-key,
  paid-lock, stale-index, and provider-failure fallback;
- a versioned curated known-combo catalog;
- universal utility and missing functional-role coverage;
- explicit anti-synergy penalties.

Commander color identity is applied before scoring when a commander is supplied. Existing deck cards can be supplied as seeds; their profiles and Oracle text form the retrieval context. Basic lands owned in the permitted color identity are guaranteed into full-sized candidate pools.

Every candidate contains `retrieval.total_score`, all individual
`retrieval.components`, human-readable `retrieval.reasons`, and
`retrieval.semantic` provenance. The latter reports whether the score came
from `openai_embedding` or `lexical_fallback`, plus both similarities when
available. The public response also publishes each component's possible range.

Semantic vectors never replace legality, color-identity, ownership, quantity,
known-combo, role, or anti-synergy checks. Those deterministic filters and
scores remain authoritative. See [SEMANTIC_INDEX.md](SEMANTIC_INDEX.md) for
index lifecycle, billing controls, and storage details.

Use `POST /api/deckbuilding/candidates` to inspect retrieval without invoking a deckbuilding model:

```json
{
  "query": "aristocrats with treasure tokens",
  "seed_names": ["Chatterfang, Squirrel General"],
  "commander_name": "Chatterfang, Squirrel General",
  "exclude_names": [],
  "limit": 100
}
```

Known interactions live in `backend/data/known_combos_v1.json`. Additions must use exact Oracle card names, an interaction kind, and a concise rules explanation. Bump the catalog version when changing its contents and add a retrieval test for the interaction.
