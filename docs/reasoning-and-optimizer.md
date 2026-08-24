# Reasoning model and deterministic deck optimizer

Full deck construction uses two stages with a hard trust boundary.

## 1. Strategic reasoning

The configured reasoning provider receives at most the bounded collection-aware candidate pool. It may return only:

- a recommended commander;
- a strategy summary;
- named strategic packages with priorities and desired bounds;
- candidate-level priorities.

Every referenced name is canonicalized against the candidate pool. Unknown names, extra fields, duplicate package cards, invalid bounds, and out-of-range priorities are rejected. The proposal schema intentionally has no decklist or quantity field.

Configuration uses `REASONING_PROVIDER` and `REASONING_MODEL`. The current adapter is Anthropic, while the proposal contract and optimizer are provider-neutral.

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
