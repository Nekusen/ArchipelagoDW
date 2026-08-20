""":class:`World` subclass for Digimon World 1 (PS1, SLUS-01032).

What works in this revision:

* The world registers with :class:`AutoWorldRegister` under
  ``game = "Digimon World"``.
* ``python Generate.py`` produces both a multiworld archive and a
  per-player ``.apdw1`` patch file (the Phase 3 deliverable).
* The Launcher recognises ``.apdw1`` files via :mod:`.components`.
* The generic test suite under :mod:`test.general` passes.

What is intentionally still stubbed:

* Phase 4's :mod:`.client` — no :class:`BizHawkClient` subclass yet, no
  Lua wiring, no in-game item delivery. ``.apdw1`` opens the in-tree
  BizHawk client until then.
* Phase 3's token list is intentionally minimal (only an ISO9660
  volume-id marker). Per-byte chest/recruit ROM rewrites land once
  their offsets in :mod:`.data.addresses` are individually verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from worlds.AutoWorld import World

from . import (
    chest_assignments,
    items,
    locations,
    regions,
    rom,
    rules,
)
from .options import DigimonWorldOptions
from .rom import DigimonWorldSettings


class DigimonWorldWorld(World):
    """Digimon World 1 (PS1, SLUS-01032 USA build).

    This package is in active development on the ``digimon-world-ps1``
    branch of the ArchipelagoDW fork. It is a from-scratch rewrite — the
    older community implementation (see ``references/DWAP``) is studied
    only, never imported. See ``PLAN.md`` for the full phased plan and
    ``REFERENCES_NOTES.md`` for the upstream-reference bibliography.
    """

    game: ClassVar[str] = "Digimon World"
    options_dataclass = DigimonWorldOptions
    options: DigimonWorldOptions

    settings_key = "digimon_world_options"
    settings: ClassVar[DigimonWorldSettings]

    item_name_to_id = items.ITEM_NAME_TO_ID
    location_name_to_id = locations.LOCATION_NAME_TO_ID

    item_name_groups = items.ITEM_NAME_GROUPS
    location_name_groups = locations.LOCATION_NAME_GROUPS

    # Populated lazily on first :attr:`chest_grants` access (post-fill).
    # Maps each chest AP location name to its resolved grant decision.
    _chest_grants: dict[str, chest_assignments.ChestGrant] | None = None

    def generate_early(self) -> None:
        """Pre-collect the bootstrap kit for ``region_locking`` modes.

        Under ``region_locking: all`` (and eventually under the future
        ``starting_region`` option), the player needs at least one
        region's access item already in inventory to have anywhere to
        go on a fresh save. We push-precollect those items so AP fill
        treats them as starting inventory, and :func:`items.create_all_items`
        skips them from the itempool to avoid double-shipping.

        For PR 2 the default bootstrap when ``region_locking == all`` is
        just ``Native Forest Region Access`` (the implicit "vanilla"
        starting region from File City). PR 3's ``starting_region``
        option will override this default with a randomized starting
        kit (e.g. ``Birdramon Recruit + Flight: Freezeland + Freezeland
        Region Access`` for a Freezeland start).
        """

        for name in items.get_bootstrap_items(self):
            self.multiworld.push_precollected(self.create_item(name))

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)
        locations.create_events(self)

    def create_items(self) -> None:
        items.create_all_items(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_item(self, name: str) -> items.DigimonWorldItem:
        return items.create_item(self, name)

    def get_filler_item_name(self) -> str:
        # Phase 8: filler insertions go through the proportional
        # distribution so AP-internal filler (e.g., when an item is
        # removed mid-fill) follows the same per-seed shape as
        # ``items.create_all_items``.
        return items.pick_random_filler(self.random)

    @property
    def chest_grants(self) -> dict[str, chest_assignments.ChestGrant]:
        """Per-chest grant decisions built from the post-fill placement.

        Must only be accessed after ``fill`` has populated
        ``Location.item``; in practice that means inside
        :meth:`fill_slot_data` or later (e.g. :meth:`generate_output`).
        Cached on first access for cheap re-use across the patcher and
        slot_data construction.
        """

        if self._chest_grants is None:
            self._chest_grants = chest_assignments.build_chest_grants(self)
        return self._chest_grants

    def fill_slot_data(self) -> Mapping[str, Any]:
        # Per-chest vanilla-grant decisions depend on AP fill outcomes
        # and must be shipped: the client uses the list to suppress
        # redundant bank deliveries for items the chest already handed
        # to the player in-game. The QoL toggles that the client
        # enforces in RAM (fast Drimogemon, easy Monochromon) also
        # ride along here; the patcher-side QoL options don't need to
        # be shipped because their effect is baked into the .apdw1.
        slot_data = dict(self.options.as_dict(
            "goal",
            "prosperity_goal",
            "fast_drimogemon",
            "easy_monochromon",
            "stat_gain_multiplier",
            "bridge_unlock",
            "great_canyon_unlock",
            "lava_cave_access",
            "god_mode",
            "recycle_shop_locations",
            "merit_shop_locations",
            "fishing_locations",
        ))
        slot_data["vanilla_grant_chests"] = sorted(
            name for name, grant in self.chest_grants.items() if grant.vanilla_grant
        )
        # Locked-region set for the client's region-gate bit reconciler:
        # Region Access trigger bits are pinned only for these regions,
        # and the Birdramon flight bits compose with the destination's
        # Region Access item only when the destination appears here.
        # Mirrors rules._apply_region_locks / rom._write_region_gate_tokens.
        from .options import get_locked_regions
        slot_data["locked_regions"] = sorted(get_locked_regions(self.options))
        return slot_data

    def generate_output(self, output_directory: str) -> None:
        """Phase 3 entry point — emit the per-player ``.apdw1`` patch.

        Generation does **not** read the user's ``.bin``. The token
        blob is composed entirely from in-memory data; the source ROM
        is only consulted later, at patch-apply time, by
        :class:`worlds.digimon_world.rom.DigimonWorldProcedurePatch`.
        """

        rom.write_patch(self, output_directory)
