# Deterministic Commander analysis

Spellbinder analyzes saved Commander decks without calling Claude, another AI model, or an external API. The implementation is in `backend/app/services/commander_engine.py` and is exposed through:

```text
GET /api/decks/{deck_id}/analysis
```

The Deck detail page displays the same report and refreshes it after edits.

## Formal legality

Formal errors are kept separate from advisory deck-health findings. The engine checks:

- Exactly 100 cards including one or two commanders.
- Commander eligibility for legendary creatures, cards with explicit permission, and legendary Vehicles or Spacecraft with printed power/toughness.
- Compatible Partner, Partner With, Friends Forever, Choose a Background, and Doctor's Companion pairs.
- Combined commander color identity, including hybrid colors supplied by Scryfall.
- Scryfall's current Commander legality value for every Oracle card.
- One card per English name except basic lands and rules-text overrides such as “any number” or “up to seven.”
- Positive quantities and exclusion/warning for sideboard rows.

Rules references:

- [Official Commander deck-construction rules](https://mtgcommander.net/rules.html)
- [Magic Comprehensive Rules, rule 903 and partner rules](https://media.wizards.com/2026/downloads/MagicCompRules%2020260619.pdf)
- [2025 Vehicle and Spacecraft commander update](https://magic.wizards.com/en/news/feature/edge-of-eternities-release-notes)

## Collection availability

Required quantities are compared with inventory totals by `oracle_id`, not by artwork or set. Owning one copy from one set and two copies from another therefore satisfies a requirement for three copies of that Oracle card. The report lists required, owned, and shortfall quantities without modifying inventory or reserving cards between decks.

## Advisory health metrics

Health checks are deterministic heuristics rather than format rules:

- Lands: general target 35–40.
- Direct mana sources: general minimum 38, with W/U/B/R/G/C source counts and colored-symbol demand.
- Mana curve: weighted average and buckets for 0–1, 2, 3, 4, 5, 6, and 7+ mana value.
- High curve warnings: average above 4.0 or more than 15 cards costing 6+.
- Functional roles: ramp, card draw, spot removal, board wipes, protection, recursion, graveyard hate, counterspells, and tutors.

Role detection uses explicit Oracle-text patterns. A card can fill multiple roles. Lands are not counted as ramp merely because they tap for mana; direct mana production is tracked separately. Fetch lands count as sources for the colors their search text can access.

These targets are visible in the API response so future tuning remains testable and does not silently change the definition of a healthy deck.

## Test coverage

`backend/tests/test_commander_engine.py` covers exact deck size, color identity, banned cards, singleton and rules-text quantity exceptions, invalid quantities, all commander eligibility paths, Background pairs, alternate-printing availability, shortfalls, lands, colored sources, fetch lands, curve buckets, and every functional role. The API is called twice in a test to verify identical deterministic output.
