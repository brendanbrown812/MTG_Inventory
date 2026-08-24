# Card identity and migration 4

Spellbinder separates the three identities that were previously combined in `card_cache`:

- `oracle_cards` contains printing-independent game data: name, rules text, mana value, colors, legalities, Scryfall keywords, and AI synergy tags.
- `card_printings` contains a Scryfall printing ID, set, collector number, rarity, language, artwork URL, and the raw Scryfall printing payload.
- `inventory_lines` records physical holdings and points to a printing. Foil status, condition, language, purchase data, and quantity remain holding data.

Deck cards carry an `oracle_id` as their game identity and retain the original `scryfall_id` as a preferred-printing/display hint. This means two printings of the same card merge into one conceptual deck entry while existing API responses and artwork remain compatible.

## Forward migration

Schema migration 4 runs automatically during API startup. For an existing database it:

1. Creates and populates `oracle_cards` and `card_printings`.
2. Validates that every legacy card has both normalized identities.
3. Adds Oracle identity to commanders and deck cards.
4. Rebuilds holding/deck foreign keys to target the normalized tables.
5. Checks copied row counts and runs SQLite `foreign_key_check` before recording the migration version.

The original `card_cache` table is intentionally retained as a read-only rollback artifact. New application writes go to the normalized tables. Migration 4 is forward-only and idempotent; a completed migration is not run again.

## Verified local migration

Before applying migration 4 to the active local database, Spellbinder created:

- `backups/pre-oracle-printing-migration-20260823.db` — untouched recovery snapshot.
- `backups/oracle-printing-migration-trial-20260823.db` — disposable migrated trial.

The trial preserved 4,412 inventory lines totaling 8,730 owned cards, two decks, and 163 deck-card rows. It produced 4,013 Oracle cards and 4,516 printings with zero orphaned references or foreign-key violations. Inventory, deck list, deck detail, and enrichment API reads all returned successfully.

The same verified migration was then applied to `backend/mtg_inventory.db`. Post-migration integrity, row-count, relationship, second-startup idempotency, and API checks all passed with the same totals.

The `backups` directory is ignored by Git and should not be committed because it contains personal collection data.

## Recommendation history

Migration 6 adds recommendation workflow data without changing collection or deck ownership:

- `recommendation_runs` stores the bounded candidate pool, reasoning proposal, and deterministic optimizer result used for a build.
- `recommendation_feedback` stores the submitted final draft, outcome, optional rating/notes, edit deltas, and an optional saved deck link.
- `recommendation_card_preferences` stores conservative accepted/rejected counts by Oracle identity for the transparent retrieval preference component.

These records point to Oracle cards and saved decks but do not replace either model. See [RECOMMENDATION_WORKSPACE.md](RECOMMENDATION_WORKSPACE.md) for the editor, validation, save, and learning lifecycle.
