"""
v2 deck matching — hard gates for legality/color identity, weighted synergy terms,
core-theme concentration, commander-text synergy, role-gap scoring vs. EDH norms,
and per-deck profile caching across a card batch.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.models import CardCache, Deck, DeckCard

# Specificity weights: higher = rarer / more archetype-defining in Commander.
# Tier 3 (2.5-3.0): narrow mechanics that define a single archetype.
# Tier 2 (1.2-2.0): strong archetype signals, common in specific strategies.
# Tier 1 (0.4-0.8): generic effects present in the majority of Commander decks.
SYNERGY_TERMS: dict[str, float] = {
    # Tier 3 — very narrow, almost always deck-defining
    "storm": 3.0,
    "landfall": 3.0,
    "magecraft": 3.0,
    "proliferate": 3.0,
    "cascade": 3.0,
    "convoke": 2.5,
    "delve": 2.5,
    "populate": 2.5,
    "foretell": 2.5,
    "mutate": 2.5,
    "energy": 2.5,
    "venture": 2.5,
    "discover": 2.5,
    "investigate": 2.0,
    "fabricate": 2.0,
    "emerge": 2.0,
    "evoke": 2.0,
    "adapt": 2.0,
    "amass": 2.0,
    "learn": 2.0,
    "boast": 2.0,
    "modified": 2.0,
    "dungeon": 2.0,
    "party": 2.0,
    "vote": 2.0,
    "role": 2.0,
    # Tier 2 — strong archetype signals
    "+1/+1": 2.0,
    "sacrifice": 1.8,
    "graveyard": 1.8,
    "zombie": 1.8,
    "goblin": 1.8,
    "elf": 1.8,
    "dragon": 1.8,
    "spirit": 1.8,
    "vampire": 1.8,
    "food": 1.8,
    "dies": 1.6,
    "token": 1.6,
    "enters the battlefield": 1.6,
    "wizard": 1.6,
    "clue": 1.6,
    "blood": 1.6,
    "copy": 1.5,
    "blink": 1.5,
    "treasure": 1.5,
    "mill": 1.5,
    "equip": 1.4,
    "discard": 1.4,
    "counter": 1.4,
    "artifact creature": 1.4,
    "lose life": 1.4,
    "enchantment": 1.3,
    "artifact": 1.2,
    "gain life": 1.2,
    # Tier 1 — generic, present in most Commander decks
    "draw": 0.8,
    "fight": 0.8,
    "exile": 0.7,
    "flash": 0.6,
    "hexproof": 0.6,
    "protection": 0.6,
    "lifelink": 0.6,
    "deathtouch": 0.6,
    "flying": 0.5,
    "trample": 0.5,
    "haste": 0.5,
    "destroy": 0.5,
    "damage": 0.4,
}

ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("removal", re.compile(r"destroy target|exile target|deals damage to (any )?target|-[0-9]+/-[0-9]+")),
    ("draw", re.compile(r"draw (a|one|two|three|cards?) card")),
    ("ramp", re.compile(r"add \{[^{}]+\}|search your library for.*land|put.*land.*onto the battlefield")),
    ("tutor", re.compile(r"search your library for")),
    ("board_wipe", re.compile(r"destroy all creatures|destroy all permanents|deals damage to each creature")),
    ("counterspell", re.compile(r"counter target spell")),
    ("recursion", re.compile(r"return.*from your graveyard")),
    ("protection", re.compile(r"hexproof|indestructible|protection from|ward")),
]

# Expected count ranges for each functional role in a tuned 99-card Commander deck.
# Under lo → deck genuinely needs this; lo-hi → fits fine; at/above hi → deck has enough.
ROLE_EDH_NORMS: dict[str, tuple[int, int]] = {
    "removal": (6, 10),
    "ramp": (8, 12),
    "draw": (8, 12),
    "board_wipe": (2, 4),
    "counterspell": (0, 4),
    "recursion": (2, 5),
    "tutor": (1, 4),
    "protection": (2, 5),
}

# Minimum points a card must earn from commander synergy + theme concentration before
# role/curve bonuses are considered. Prevents format-legal, right-color generic cards
# from passing just by filling a curve gap or role.
_MIN_SYNERGY = 15.0


def _parse_legalities(row: CardCache | None) -> dict[str, str]:
    if not row or not row.legalities_json:
        return {}
    try:
        return json.loads(row.legalities_json)
    except json.JSONDecodeError:
        return {}


def _legal_for_format(legalities: dict[str, str], fmt: str) -> bool:
    fmt = (fmt or "commander").lower()
    if fmt == "edh":
        fmt = "commander"
    return legalities.get(fmt) == "legal"


def _ci_set(s: str) -> frozenset[str]:
    if not s:
        return frozenset()
    return frozenset(x.strip() for x in s.split(",") if x.strip())


def _oracle_blob(card: CardCache) -> str:
    return " ".join([card.name or "", card.type_line or "", card.oracle_text or ""]).lower()


def _weighted_terms(text: str) -> dict[str, float]:
    """Returns {term: specificity_weight} for every SYNERGY_TERMS entry found in text."""
    return {t: w for t, w in SYNERGY_TERMS.items() if t in text}


def _roles(text: str) -> set[str]:
    return {name for name, pat in ROLE_PATTERNS if pat.search(text)}


def _cmc_bucket(cmc: float) -> str:
    if cmc <= 1:
        return "0-1"
    if cmc <= 2:
        return "2"
    if cmc <= 3:
        return "3"
    if cmc <= 4:
        return "4"
    return "5+"


def _is_land(type_line: str | None) -> bool:
    if not type_line:
        return False
    tl = type_line.lower()
    return "land" in tl and "creature" not in tl


@dataclass
class MatchResult:
    deck_id: int
    deck_name: str
    deck_status: str
    score: float
    reasons: list[str]
    kind: str  # "synergy" | "upgrade"


def _deck_cards_excluding_lands(db: Session, deck: Deck) -> list[CardCache]:
    out: list[CardCache] = []
    for dc in deck.cards:
        if dc.is_commander:
            continue
        c = dc.card
        if c and not _is_land(c.type_line):
            out.extend([c] * max(1, dc.quantity))
    return out


def _allowed_ci_for_commander_deck(db: Session, deck: Deck) -> frozenset[str]:
    if deck.commander_scryfall_id:
        cmd = db.get(CardCache, deck.commander_scryfall_id)
        if cmd:
            return _ci_set(cmd.color_identity)
    u: set[str] = set()
    for dc in deck.cards:
        if dc.card:
            u |= set(_ci_set(dc.card.color_identity))
    return frozenset(u)


def build_deck_profile(cards: list[CardCache]) -> dict:
    """
    Build a strategic profile of the deck's non-land cards.

    core_themes: terms present in ≥15% of non-land cards (minimum 3 cards), keyed to their
    specificity weight. These represent the deck's actual strategic identity rather than
    incidental mentions — a 30-card sacrifice deck has 'sacrifice' as a core theme; a deck
    with one card that mentions 'flying' does not have a flying theme.
    """
    if not cards:
        return {
            "cmc_buckets": Counter(),
            "creature_ratio": 0.0,
            "noncreature_spell_ratio": 0.0,
            "core_themes": {},
            "deck_roles": Counter(),
            "avg_cmc": 0.0,
        }

    buckets: Counter[str] = Counter()
    creatures = 0
    noncreature_nonland = 0
    term_counts: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    cmcs: list[float] = []

    for c in cards:
        if _is_land(c.type_line):
            continue
        cmc = float(c.cmc or 0)
        cmcs.append(cmc)
        buckets[_cmc_bucket(cmc)] += 1
        blob = _oracle_blob(c)
        for t in SYNERGY_TERMS:
            if t in blob:
                term_counts[t] += 1
        for r in _roles(blob):
            roles[r] += 1
        tl = (c.type_line or "").lower()
        if "creature" in tl:
            creatures += 1
        elif "instant" in tl or "sorcery" in tl or "enchantment" in tl:
            noncreature_nonland += 1

    n = len(cmcs) or 1
    min_count = max(3, n * 0.15)
    core_themes: dict[str, float] = {
        t: SYNERGY_TERMS[t]
        for t, cnt in term_counts.items()
        if cnt >= min_count
    }

    return {
        "cmc_buckets": buckets,
        "creature_ratio": creatures / n,
        "noncreature_spell_ratio": noncreature_nonland / n,
        "core_themes": core_themes,
        "deck_roles": roles,
        "avg_cmc": sum(cmcs) / n,
    }


@dataclass
class _DeckCtx:
    """Pre-built per-deck data shared across all cards in a match batch."""
    non_land_cards: list[CardCache]
    profile: dict
    commander: CardCache | None
    allowed_ci: frozenset[str]

    @classmethod
    def build(cls, db: Session, deck: Deck) -> "_DeckCtx":
        cards = _deck_cards_excluding_lands(db, deck)
        return cls(
            non_land_cards=cards,
            profile=build_deck_profile(cards),
            commander=db.get(CardCache, deck.commander_scryfall_id) if deck.commander_scryfall_id else None,
            allowed_ci=_allowed_ci_for_commander_deck(db, deck),
        )


def score_card_for_deck(
    db: Session,
    deck: Deck,
    new_card: CardCache,
    ctx: _DeckCtx | None = None,
) -> MatchResult | None:
    if ctx is None:
        ctx = _DeckCtx.build(db, deck)

    fmt = deck.format or "commander"
    legalities = _parse_legalities(new_card)

    # Hard gates — binary pass/fail, contribute zero to score.
    # Previously these added 22+25=47 pts, pushing virtually every legal on-color card
    # past the 35-point threshold before any synergy check ran.
    if not _legal_for_format(legalities, fmt):
        return None
    new_ci = _ci_set(new_card.color_identity)
    if fmt.lower() in ("commander", "edh"):
        if ctx.allowed_ci and not new_ci <= ctx.allowed_ci:
            return None

    blob = _oracle_blob(new_card)
    card_terms = _weighted_terms(blob)
    reasons: list[str] = []
    score = 0.0

    # 1. Commander text synergy (0-40).
    # Overlap between the candidate card's oracle terms and the commander's own oracle
    # terms, weighted by specificity. A sacrifice commander rewards sacrifice cards; a
    # storm commander rewards storm payoffs. Contributes 0 when no commander is set.
    cmd_score = 0.0
    if ctx.commander is not None:
        cmd_terms = _weighted_terms(_oracle_blob(ctx.commander))
        overlap = {t: w for t, w in cmd_terms.items() if t in card_terms}
        if overlap:
            cmd_score = min(40.0, sum(w * 9 for w in overlap.values()))
            top = sorted(overlap, key=lambda t: -overlap[t])[:3]
            reasons.append("Commander synergy: " + ", ".join(top))
    score += cmd_score

    # 2. Core theme concentration (0-40).
    # Overlap with terms that appear in ≥15% of the deck's non-land cards, weighted by
    # specificity. Filters out incidental mentions of generic effects and focuses on what
    # the deck is actually built around.
    core_themes: dict[str, float] = ctx.profile["core_themes"]
    theme_score = 0.0
    if core_themes:
        matched = {t: w for t, w in core_themes.items() if t in card_terms}
        if matched:
            theme_score = min(40.0, sum(w * 11 for w in matched.values()))
            top = sorted(matched, key=lambda t: -matched[t])[:4]
            reasons.append("Theme match: " + ", ".join(top))
    elif ctx.non_land_cards:
        # Deck has cards but no dominant theme yet — mild any-overlap bonus.
        all_deck_terms: set[str] = set()
        for c in ctx.non_land_cards:
            all_deck_terms |= _weighted_terms(_oracle_blob(c)).keys()
        any_overlap = set(card_terms.keys()) & all_deck_terms
        if any_overlap:
            theme_score = min(10.0, len(any_overlap) * 1.5)
            reasons.append("Some thematic overlap (deck theme not yet established)")
    score += theme_score

    # Minimum synergy gate: card must earn ≥15 pts from commander + theme before role/curve
    # bonuses count. This is the primary filter against generic good-stuff cards that are
    # merely legal and the right colors.
    if score < _MIN_SYNERGY:
        return None

    # 3. Role-gap scoring (0-15).
    # Compare the deck's current role counts against typical EDH deckbuilding targets.
    # Cards filling genuine gaps score higher; cards adding to already-covered roles score 0.
    deck_roles: Counter = ctx.profile["deck_roles"]
    card_roles = _roles(blob)
    role_score = 0.0
    role_reasons: list[str] = []
    kind = "synergy"

    for r in card_roles:
        current = deck_roles.get(r, 0)
        if r in ROLE_EDH_NORMS:
            lo, hi = ROLE_EDH_NORMS[r]
            if current < lo:
                role_score += 12.0
                role_reasons.append(f"deck needs {r} ({current}/{lo}+)")
            elif current < hi:
                role_score += 5.0
                role_reasons.append(f"fits {r}")
            # At or above hi: no bonus — deck already has enough
        else:
            role_score += 3.0

        # Upgrade detection for completed decks: same role, lower mana value.
        if deck.status == "complete":
            same_role = [c for c in ctx.non_land_cards if r in _roles(_oracle_blob(c))]
            worse = [c for c in same_role if float(c.cmc or 0) > float(new_card.cmc or 0) + 0.5]
            if worse:
                kind = "upgrade"
                role_score += 8.0
                role_reasons.append(f"upgrade vs {worse[0].name} ({r})")
                break

    role_score = min(15.0, role_score)
    if role_reasons:
        reasons.append("Role: " + "; ".join(role_reasons[:2]))
    score += role_score

    # 4. Curve fit (0-5) — minor bonus only. Curve should not drive recommendations.
    bucket = _cmc_bucket(float(new_card.cmc or 0))
    total_spells = sum(ctx.profile["cmc_buckets"].values()) or 1
    if ctx.profile["cmc_buckets"][bucket] / total_spells < 0.10:
        score += 5.0
        reasons.append(f"Fills curve gap at {bucket} MV")

    return MatchResult(
        deck_id=deck.id,
        deck_name=deck.name,
        deck_status=deck.status,
        score=min(100.0, round(score, 1)),
        reasons=reasons,
        kind=kind,
    )


def match_new_cards(
    db: Session,
    scryfall_ids: list[str],
    min_score: float = 35.0,
) -> dict[str, list[dict]]:
    """
    Return deck matches above min_score for each scryfall_id.
    Deck contexts (profile, commander, color identity) are built once per deck and
    reused across every card being evaluated.
    """
    decks = (
        db.query(Deck)
        .options(joinedload(Deck.cards).joinedload(DeckCard.card))
        .all()
    )

    deck_ctxs: dict[int, _DeckCtx] = {d.id: _DeckCtx.build(db, d) for d in decks}

    results: dict[str, list[dict]] = {}
    for sfid in scryfall_ids:
        card = db.get(CardCache, sfid)
        if not card:
            continue
        matches: list[dict] = []
        for d in decks:
            mr = score_card_for_deck(db, d, card, ctx=deck_ctxs[d.id])
            if mr and mr.score >= min_score:
                matches.append({
                    "deck_id": mr.deck_id,
                    "deck_name": mr.deck_name,
                    "deck_status": mr.deck_status,
                    "score": mr.score,
                    "reasons": mr.reasons,
                    "kind": mr.kind,
                })
        matches.sort(key=lambda x: -x["score"])
        results[sfid] = matches

    return results
