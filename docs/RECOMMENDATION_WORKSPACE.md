# Recommendation workspace

Spellbinder's deckbuilding result is an editable draft, not a model-authored decklist. The reasoning provider receives a bounded, collection-aware candidate pool and proposes strategic packages. Deterministic code then assembles the deck and enforces Commander legality, availability, singleton, commander, and exact-size constraints.

## Inspect and edit

Each build response includes a recommendation run ID, the reasoning proposal, optimizer diagnostics, transparent retrieval scores, and the complete bounded candidate pool used for that run. The Deckbuilding page uses that immutable snapshot to:

- inspect card roles, ownership, score components, reasoning packages, and validation results;
- change quantities, remove cards, choose a different commander, and add another card from the bounded pool;
- copy the current decklist or reset it to the optimizer result; and
- revalidate every edited printing, Oracle identity, name, quantity, and hard Commander constraint on the server.

Edits invalidate the previous validation result. An edited draft cannot be saved until a current server validation passes.

## Save and feedback

Saving creates an ordinary Spellbinder deck and deck-card rows, then links that deck to the recommendation run. The workspace also accepts an optional one-to-five rating and notes. A result can instead be marked accepted, edited, or rejected without saving a deck.

Feedback is stored as both an auditable event and conservative per-Oracle-card counters. Future collection-aware retrieval exposes a `user_feedback` score component and a plain-language reason showing accepted and rejected counts. Feedback cannot change card mechanics, legality, ownership, or any hard validator rule; it only contributes a bounded preference signal.

For edited results, cards added or increased receive positive evidence and cards removed or decreased receive negative evidence. Saved or accepted results treat the submitted final list as positive evidence. Rejected results treat the original optimizer list as negative evidence.

## Persistence and recovery

Schema migration 6 adds `recommendation_runs`, `recommendation_feedback`, and `recommendation_card_preferences`. Recommendation runs retain the candidate, proposal, and optimizer snapshots needed to explain and safely validate later edits.

On August 23, 2026, migration 6 was rehearsed against `backups/recommendation-workspace-migration-trial-20260823-200512.db` after creating the untouched recovery snapshot `backups/pre-recommendation-workspace-migration-20260823-200512.db`. The rehearsal and live migration preserved 4,013 Oracle cards, 4,516 printings, 4,412 inventory rows, two decks, and 163 deck-card rows. SQLite integrity and foreign-key checks passed, and a second migration run was idempotent.

The backup files contain personal collection data and remain excluded from Git. See [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md) before restoring or moving a database.
