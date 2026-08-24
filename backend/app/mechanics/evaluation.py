from __future__ import annotations

from dataclasses import dataclass

from app.mechanics.profile import HookVerb, Mechanic, MechanicProfile, UniversalTier


@dataclass(frozen=True)
class InteractionResult:
    outcome: str
    mechanics: tuple[str, ...]
    reasons: tuple[str, ...]


def _expanded(mechanic: Mechanic) -> set[str]:
    values = {mechanic.value}
    if mechanic in {Mechanic.creature_tokens, Mechanic.artifact_tokens, Mechanic.treasure_tokens}:
        values.add(Mechanic.token_creation.value)
    if mechanic is Mechanic.cast_from_graveyard:
        values.add(Mechanic.graveyard.value)
    return values


def profile_satisfies_expectation(profile: MechanicProfile, expectation: dict) -> bool:
    roles = {role.value for role in profile.roles}
    if not set(expectation.get("required_roles", [])) <= roles:
        return False
    if expectation.get("universal_tier") != profile.universal_utility.tier.value and "universal_tier" in expectation:
        return False
    hooks = [
        {"verb": hook.verb.value, "mechanic": hook.mechanic.value, "scope": hook.scope.value}
        for hook in profile.hooks
    ]
    for required in expectation.get("required_hooks", []):
        if not any(all(hook.get(key) == value for key, value in required.items()) for hook in hooks):
            return False
    return True


def evaluate_interaction(left: MechanicProfile, right: MechanicProfile) -> InteractionResult:
    mechanics: set[str] = set()
    reasons: list[str] = []

    for blocker, other in ((left, right), (right, left)):
        prevented = {
            expanded
            for hook in blocker.hooks if hook.verb is HookVerb.prevents
            for expanded in _expanded(hook.mechanic)
        }
        used = {
            expanded
            for hook in other.hooks
            if hook.verb in {
                HookVerb.consumes, HookVerb.rewards, HookVerb.enables,
                HookVerb.amplifies, HookVerb.produces, HookVerb.grants,
            }
            for expanded in _expanded(hook.mechanic)
        }
        conflicts = prevented & used
        if conflicts:
            mechanics.update(conflicts)
            reasons.append(f"{blocker.card_name} prevents mechanics used by {other.card_name}")

    if reasons:
        return InteractionResult("anti_synergy", tuple(sorted(mechanics)), tuple(reasons))

    if (
        left.universal_utility.tier is UniversalTier.broad
        or right.universal_utility.tier is UniversalTier.broad
    ):
        broad = left if left.universal_utility.tier is UniversalTier.broad else right
        mechanics.update(
            expanded for hook in broad.hooks for expanded in _expanded(hook.mechanic)
        )
        return InteractionResult(
            "universal_fit", tuple(sorted(mechanics)),
            (f"{broad.card_name} provides broadly useful infrastructure",),
        )

    complementary_edges = 0
    for producer, consumer in ((left, right), (right, left)):
        offered = {
            expanded
            for hook in producer.hooks
            if hook.verb in {HookVerb.produces, HookVerb.grants, HookVerb.enables, HookVerb.amplifies}
            for expanded in _expanded(hook.mechanic)
        }
        wanted = {
            expanded
            for hook in consumer.hooks
            if hook.verb in {HookVerb.consumes, HookVerb.rewards, HookVerb.amplifies}
            for expanded in _expanded(hook.mechanic)
        }
        overlap = offered & wanted
        if overlap:
            complementary_edges += 1
            mechanics.update(overlap)
            reasons.append(f"{producer.card_name} supplies mechanics used by {consumer.card_name}")

    # Deathtouch applies to damage dealt by the granted creature, including
    # noncombat pings. This captures Collar + Sharpshooter without a card-name rule.
    for granter, source in ((left, right), (right, left)):
        grants_deathtouch = any(
            hook.verb is HookVerb.grants and hook.mechanic is Mechanic.deathtouch
            for hook in granter.hooks
        )
        produces_damage = any(
            hook.verb is HookVerb.produces and hook.mechanic is Mechanic.direct_damage
            for hook in source.hooks
        )
        if grants_deathtouch and produces_damage:
            complementary_edges += 1
            mechanics.update({Mechanic.deathtouch.value, Mechanic.direct_damage.value})
            reasons.append(f"{granter.card_name} grants deathtouch to a repeatable damage source")

    both_combo_enablers = all(
        "combo_enabler" in {role.value for role in profile.roles}
        for profile in (left, right)
    )
    if both_combo_enablers and complementary_edges:
        # Include the concrete hooks that participate in a potential loop.
        mechanics.update(
            expanded
            for profile in (left, right)
            for hook in profile.hooks
            for expanded in _expanded(hook.mechanic)
            if hook.verb in {HookVerb.produces, HookVerb.consumes, HookVerb.rewards, HookVerb.amplifies}
        )
        return InteractionResult("conditional_combo", tuple(sorted(mechanics)), tuple(reasons))
    if complementary_edges:
        return InteractionResult("synergy", tuple(sorted(mechanics)), tuple(reasons))
    return InteractionResult("neutral", (), ())
