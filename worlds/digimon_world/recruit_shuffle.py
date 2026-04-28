"""Closed-shuffle recruit trigger remap (vanilla-style).

For every Digimon in
:data:`worlds.digimon_world.data.addresses.SHUFFLE_INCLUDED_RECRUITS`,
pick a partner from the same set (uniform random, with replacement
allowed — i.e. a Digimon may be paired with itself). The patcher then
writes the partner's vanilla trigger ID at every ROM offset belonging
to the spawn-point Digimon. Result: visiting Digimon X's spawn fires
the encounter for X (geometry/sprite unchanged) but completion runs
partner Y's recruit cutscene and sets Y's recruit bit.

This is **purely a visual / in-game randomization** — AP location
detection still polls the spawn-point Digimon's recruit bit. Whether
X or Y ends up in city is independent of AP semantics.

Non-shuffleable Digimon (the 12 outside SHUFFLEABLE_RECRUITS) are
not touched; their vanilla trigger stays.

Determinism: derived from ``world.random``, so the same seed produces
the same shuffle. The remap is committed to the patch token blob, so
clients don't need slot data for it — the patch itself encodes the
shuffle outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .data.addresses import SHUFFLE_INCLUDED_RECRUITS

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


def build_recruit_remap(world: DigimonWorldWorld) -> dict[str, str]:
    """Return ``{spawn_digimon: partner_digimon}`` for the closed shuffle.

    Each spawn point gets a uniformly random partner from
    :data:`SHUFFLE_INCLUDED_RECRUITS`. Identity pairings (``X -> X``)
    are allowed — they happen to occur with probability ``1/N`` per
    spawn and produce no patch token (vanilla bytes already say ``X``).
    """

    spawns = sorted(SHUFFLE_INCLUDED_RECRUITS)
    return {spawn: world.random.choice(spawns) for spawn in spawns}


__all__ = ["build_recruit_remap"]
