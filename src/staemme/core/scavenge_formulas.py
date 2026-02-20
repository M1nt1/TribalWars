"""Scavenging game formulas for Die Stämme (Tribal Wars).

Loot and duration calculations use the real game formulas.
"""

from __future__ import annotations

import math

# Loot factor per scavenge option (1-4)
LOOT_RATIOS: dict[int, float] = {1: 0.10, 2: 0.25, 3: 0.50, 4: 0.75}

# Units eligible for scavenging (no siege or noble)
SCAVENGE_UNITS = ["spear", "sword", "axe", "archer", "light", "marcher", "heavy"]


def calculate_carry_capacity(
    troops: dict[str, int], unit_carries: dict[str, int]
) -> int:
    """Total carry capacity for a troop allocation."""
    return sum(
        count * unit_carries.get(unit, 0)
        for unit, count in troops.items()
        if count > 0
    )


def calculate_duration(carry_cap: int, tier: int, world_speed: float) -> float:
    """Scavenge duration in seconds.

    Formula: ((cap² × 100 × ratio²)^0.45 + 1800) × speed^(-0.55)
    """
    if carry_cap <= 0:
        return 0.0
    ratio = LOOT_RATIOS.get(tier, 0.10)
    inner = (carry_cap ** 2) * 100 * (ratio ** 2)
    return (inner ** 0.45 + 1800) * (world_speed ** -0.55)


def calculate_loot(carry_cap: int, tier: int) -> float:
    """Expected loot (resources) from a scavenge mission."""
    ratio = LOOT_RATIOS.get(tier, 0.10)
    return carry_cap * ratio


def calculate_rph(carry_cap: int, tier: int, world_speed: float) -> float:
    """Resources per hour for a scavenge mission."""
    duration = calculate_duration(carry_cap, tier, world_speed)
    if duration <= 0:
        return 0.0
    loot = calculate_loot(carry_cap, tier)
    return loot / duration * 3600


def equal_runtime_weights(tiers: set[int]) -> dict[int, float]:
    """Compute troop weights for equal scavenge duration across tiers.

    For equal runtime: cap_i × loot_ratio_i must be constant across options,
    so weight_i = 1 / loot_ratio_i.

    Example with 3 options and 1000 spears:
        weights = {1: 10, 2: 4, 3: 2}, sum = 16
        opt1 = floor(1000 × 10/16) = 625
        opt2 = floor(1000 × 4/16) = 250
        opt3 = floor(1000 × 2/16) = 125
    """
    return {tier: 1.0 / LOOT_RATIOS[tier] for tier in tiers if tier in LOOT_RATIOS}


def allocate_by_ratio(
    available: dict[str, int],
    option_weights: dict[int, float],
    unit_carries: dict[str, int] | None = None,
) -> dict[int, dict[str, int]]:
    """Split available troops across tiers by carry-capacity targets.

    Calculates target carry capacity per tier from weights, then fills
    tiers from highest to 2nd-lowest greedily. ALL remaining troops are
    dumped into the lowest tier so zero troops stay idle.

    Args:
        available: {unit_name: count} of idle scavengeable troops.
        option_weights: {tier: weight} — higher weight = more troops.
        unit_carries: {unit_name: carry_per_unit} from world config.

    Returns:
        {tier: {unit_name: count}} allocation per option.
    """
    weight_sum = sum(option_weights.values())
    if weight_sum <= 0:
        return {}

    pool = {u: c for u, c in available.items() if u in SCAVENGE_UNITS and c > 0}
    if not pool:
        return {}

    carries = unit_carries or {}
    total_carry = sum(c * carries.get(u, 25) for u, c in pool.items())
    if total_carry <= 0:
        return {}

    dump_tier = min(option_weights.keys())
    allocations: dict[int, dict[str, int]] = {tier: {} for tier in option_weights}
    remaining = dict(pool)

    # Fill from highest tier down, skipping dump tier (it gets the rest)
    for tier in sorted(option_weights.keys(), reverse=True):
        if tier == dump_tier:
            continue

        target = total_carry * option_weights[tier] / weight_sum
        filled = 0.0

        # Sort units by carry capacity descending for efficient packing
        units_by_carry = sorted(
            remaining.keys(),
            key=lambda u: carries.get(u, 25),
            reverse=True,
        )

        for unit in units_by_carry:
            avail = remaining.get(unit, 0)
            if avail <= 0:
                continue
            carry_per = carries.get(unit, 25)
            if carry_per <= 0:
                continue

            gap = target - filled
            if gap <= 0:
                break

            take = min(avail, math.floor(gap / carry_per))
            if take > 0:
                allocations[tier][unit] = take
                remaining[unit] -= take
                filled += take * carry_per

    # Dump ALL remaining into lowest tier — zero troops stay idle
    for unit, count in remaining.items():
        if count > 0:
            allocations[dump_tier][unit] = allocations[dump_tier].get(unit, 0) + count

    return {t: troops for t, troops in allocations.items() if troops}
