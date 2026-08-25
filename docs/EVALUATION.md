# Local MTG recommendation quality gate

Spellbinder includes a versioned, zero-network evaluation suite at
`backend/evals/mtg_mechanics_v1.json`. The Enrichment page can run it against
the current collection and stored mechanic profiles before any bulk paid
enrichment or reasoning rollout.

## Coverage

Suite version 1.0.0 contains 19 cases across five pipeline groups:

- profile classification: indirect mechanics, universal utility, and prevention;
- pairwise interaction reasoning: synergy, universal fit, anti-synergy, and conditional combos;
- collection-aware retrieval: indirect matches, universal mana, conflict penalties, and known combos;
- deterministic color-identity legality traps;
- deterministic revalidation of the latest stored feasible recommendation build.

These cases cover the core failure modes originally identified for this
project: matching only literal Oracle words, treating every thematic card as
interchangeable, missing universally useful infrastructure, recommending an
anti-synergy, hallucinating an interaction, and allowing an illegal color.

## Honest coverage and pass rate

The runner matches golden cases to actual cards by canonical Oracle name. A
profile or retrieval case is skipped when its required cards are not owned or
do not have current mechanic profiles. Skipped cases reduce coverage but do not
count as failures. Pass rate includes only cases the current database can
actually execute.

The report therefore publishes both:

- `coverage`: executed cases divided by all cases;
- `pass_rate`: passed cases divided by executed cases.

The UI lists every case with expected and actual values, so a high pass rate at
low coverage cannot masquerade as broad validation.

## No paid requests

`GET /api/evaluations/mtg-quality` performs no model or network requests. The
retrieval evaluator explicitly disables creation of remote query embeddings,
even when `OPENAI_REQUESTS_ENABLED=true`. It may use an already cached query
vector because that requires no request; otherwise it uses the deterministic
lexical fallback. The report records the semantic source and always reports
`network_requests: 0`.

## Changing behavior safely

When changing the mechanic taxonomy, evaluator, known-combo catalog, semantic
weights, legality rules, or optimizer behavior:

1. Add a failing golden case that represents the intended behavior.
2. Implement the change.
3. Run the backend test suite.
4. Run the Local MTG Quality Gate against representative stored profiles.
5. Bump the relevant suite or component version when expected behavior changes.

Golden fixtures validate the code path; the collection report validates the
profiles produced by the configured provider. Both are necessary before
scaling paid enrichment.
