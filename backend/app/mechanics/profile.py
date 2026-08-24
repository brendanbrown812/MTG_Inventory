from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROFILE_SCHEMA_VERSION = "1.0.0"
TAXONOMY_VERSION = "2026.1"


class Role(str, Enum):
    mana_acceleration = "mana_acceleration"
    mana_fixing = "mana_fixing"
    card_advantage = "card_advantage"
    card_selection = "card_selection"
    removal = "removal"
    board_wipe = "board_wipe"
    protection = "protection"
    recursion = "recursion"
    graveyard_recycling = "graveyard_recycling"
    graveyard_hate = "graveyard_hate"
    sacrifice_outlet = "sacrifice_outlet"
    token_generator = "token_generator"
    token_multiplier = "token_multiplier"
    counter_multiplier = "counter_multiplier"
    trigger_multiplier = "trigger_multiplier"
    poison_payoff = "poison_payoff"
    combat_enabler = "combat_enabler"
    combo_enabler = "combo_enabler"
    stax = "stax"
    direct_damage = "direct_damage"
    tutor = "tutor"
    counterspell = "counterspell"
    land_ramp = "land_ramp"
    cost_reduction = "cost_reduction"
    ritual = "ritual"
    looting = "looting"
    wheel = "wheel"
    discard = "discard"
    mill = "mill"
    self_mill = "self_mill"
    blink = "blink"
    reanimation = "reanimation"
    life_gain_payoff = "life_gain_payoff"
    spellslinger_payoff = "spellslinger_payoff"
    artifact_payoff = "artifact_payoff"
    enchantment_payoff = "enchantment_payoff"
    land_payoff = "land_payoff"
    typal_payoff = "typal_payoff"
    equipment_payoff = "equipment_payoff"
    aura_payoff = "aura_payoff"
    counter_payoff = "counter_payoff"
    token_payoff = "token_payoff"
    sacrifice_payoff = "sacrifice_payoff"
    graveyard_payoff = "graveyard_payoff"
    cast_payoff = "cast_payoff"
    extra_combat = "extra_combat"
    extra_turn = "extra_turn"
    copy_effect = "copy_effect"
    theft = "theft"
    hate_piece = "hate_piece"
    evasion = "evasion"
    finisher = "finisher"


class Mechanic(str, Enum):
    mana = "mana"
    deathtouch = "deathtouch"
    lifelink = "lifelink"
    poison_counters = "poison_counters"
    combat_damage = "combat_damage"
    card_draw = "card_draw"
    token_creation = "token_creation"
    creature_tokens = "creature_tokens"
    artifact_tokens = "artifact_tokens"
    treasure_tokens = "treasure_tokens"
    sacrifice = "sacrifice"
    creature_death = "creature_death"
    graveyard = "graveyard"
    graveyard_recycling = "graveyard_recycling"
    cast_from_graveyard = "cast_from_graveyard"
    enter_battlefield_triggers = "enter_battlefield_triggers"
    activated_abilities = "activated_abilities"
    artifact_activated_abilities = "artifact_activated_abilities"
    counters = "counters"
    direct_damage = "direct_damage"
    untap = "untap"
    life_gain = "life_gain"
    replacement_effects = "replacement_effects"
    land_search = "land_search"
    lands_entering = "lands_entering"
    lands_in_graveyard = "lands_in_graveyard"
    spell_casting = "spell_casting"
    instant_or_sorcery_casting = "instant_or_sorcery_casting"
    permanent_casting = "permanent_casting"
    noncreature_casting = "noncreature_casting"
    card_discard = "card_discard"
    milling = "milling"
    exile = "exile"
    cast_from_exile = "cast_from_exile"
    enter_battlefield = "enter_battlefield"
    leave_battlefield = "leave_battlefield"
    attack_triggers = "attack_triggers"
    damage = "damage"
    commander_damage = "commander_damage"
    equipment = "equipment"
    auras = "auras"
    artifacts = "artifacts"
    enchantments = "enchantments"
    creatures = "creatures"
    creature_types = "creature_types"
    power = "power"
    toughness = "toughness"
    plus_one_counters = "plus_one_counters"
    minus_one_counters = "minus_one_counters"
    charge_counters = "charge_counters"
    proliferate = "proliferate"
    copying_spells = "copying_spells"
    copying_permanents = "copying_permanents"
    extra_combat = "extra_combat"
    extra_turn = "extra_turn"
    control_change = "control_change"
    life_loss = "life_loss"
    life_payment = "life_payment"
    commander_casting = "commander_casting"


class HookVerb(str, Enum):
    produces = "produces"
    consumes = "consumes"
    rewards = "rewards"
    enables = "enables"
    grants = "grants"
    amplifies = "amplifies"
    prevents = "prevents"
    replaces = "replaces"


class Scope(str, Enum):
    self = "self"
    controlled_creatures = "controlled_creatures"
    other_controlled_creatures = "other_controlled_creatures"
    attacking_creatures = "attacking_creatures"
    equipped_creature = "equipped_creature"
    controlled_squirrels = "controlled_squirrels"
    opponents = "opponents"
    any_target = "any_target"
    all_graveyards = "all_graveyards"
    your_graveyard = "your_graveyard"
    all_creatures = "all_creatures"
    controlled_permanents = "controlled_permanents"
    your_tokens = "your_tokens"
    controlled_artifacts = "controlled_artifacts"
    controlled_enchantments = "controlled_enchantments"
    controlled_lands = "controlled_lands"
    controlled_equipment = "controlled_equipment"
    controlled_creature_type = "controlled_creature_type"
    cards_in_hand = "cards_in_hand"
    spells_you_cast = "spells_you_cast"
    opponents_spells = "opponents_spells"
    opponents_permanents = "opponents_permanents"
    opponents_graveyards = "opponents_graveyards"
    any_graveyard = "any_graveyard"
    exile_zone = "exile_zone"
    top_of_library = "top_of_library"
    all_players = "all_players"
    each_opponent = "each_opponent"


class Condition(str, Enum):
    tap = "tap"
    while_attacking = "while_attacking"
    activated_ability = "activated_ability"
    combat_damage_to_player = "combat_damage_to_player"
    deathtouch_combat_damage = "deathtouch_combat_damage"
    replacement_effect = "replacement_effect"
    cast_or_play_permanent = "cast_or_play_permanent"
    once_each_permanent_type_each_turn = "once_each_permanent_type_each_turn"
    static_ability = "static_ability"
    artifact_or_creature_entering = "artifact_or_creature_entering"
    equipped = "equipped"
    creature_dies = "creature_dies"
    other_controlled_creature_dies = "other_controlled_creature_dies"
    dies = "dies"
    sacrifice_cost = "sacrifice_cost"
    spell_cast = "spell_cast"
    instant_or_sorcery_cast = "instant_or_sorcery_cast"
    permanent_cast = "permanent_cast"
    land_enters = "land_enters"
    permanent_enters = "permanent_enters"
    leaves_battlefield = "leaves_battlefield"
    attacks = "attacks"
    deals_damage = "deals_damage"
    card_drawn = "card_drawn"
    card_discarded = "card_discarded"
    life_gained = "life_gained"
    life_lost = "life_lost"
    counter_added = "counter_added"
    from_graveyard = "from_graveyard"
    from_exile = "from_exile"
    during_upkeep = "during_upkeep"
    end_step = "end_step"
    once_each_turn = "once_each_turn"
    mana_payment = "mana_payment"


class UniversalTier(str, Enum):
    none = "none"
    contextual = "contextual"
    broad = "broad"


class MechanicHook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: HookVerb
    mechanic: Mechanic
    scope: Scope
    condition: Condition
    evidence: str = Field(min_length=1, max_length=500)


class UniversalUtility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: UniversalTier = UniversalTier.none
    reasons: list[Role] = Field(default_factory=list, max_length=5)

    @field_validator("reasons")
    @classmethod
    def unique_reasons(cls, value: list[Role]) -> list[Role]:
        if len(value) != len(set(value)):
            raise ValueError("universal utility reasons must be unique")
        return value


class MechanicProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[PROFILE_SCHEMA_VERSION] = PROFILE_SCHEMA_VERSION
    taxonomy_version: Literal[TAXONOMY_VERSION] = TAXONOMY_VERSION
    oracle_id: str = Field(min_length=1, max_length=64)
    card_name: str = Field(min_length=1, max_length=500)
    roles: list[Role] = Field(default_factory=list, max_length=12)
    hooks: list[MechanicHook] = Field(default_factory=list, max_length=24)
    universal_utility: UniversalUtility = Field(default_factory=UniversalUtility)
    confidence: float = Field(ge=0, le=1)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[Role]) -> list[Role]:
        if len(value) != len(set(value)):
            raise ValueError("roles must be unique")
        return value

    @field_validator("hooks")
    @classmethod
    def unique_hooks(cls, value: list[MechanicHook]) -> list[MechanicHook]:
        keys = {(hook.verb, hook.mechanic, hook.scope, hook.condition) for hook in value}
        if len(value) != len(keys):
            raise ValueError("mechanic hooks must be structurally unique")
        return value
