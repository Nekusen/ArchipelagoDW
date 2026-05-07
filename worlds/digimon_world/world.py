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
from .data.addresses import AP_RECRUIT_ITEM_DIGIMON
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

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)
        # Lock recruit items to their own AP locations when
        # :class:`worlds.digimon_world.options.RecruitRandomization` is
        # off. Must run before :meth:`create_items` so the pool sizing
        # (which depends on ``get_unfilled_locations``) accounts for
        # the 48 pre-placed recruit slots.
        self._lock_recruit_items_if_disabled()
        locations.create_events(self)

    def _lock_recruit_items_if_disabled(self) -> None:
        """Self-place each ``<Name> Recruit`` item at its AP location
        when recruit randomization is off.

        With the option off, ``items.create_all_items`` separately
        skips the 48 recruit items from the pool — they're created
        fresh here and locked, so each recruit's join-city item is
        delivered exclusively by the player completing that recruit's
        encounter, never sourced from another player's slot. The
        recruit AP location's other roles (firing on cutscene
        completion, gating progression via ``Has(Birdramon Recruit)``
        etc.) are unaffected.
        """

        if int(self.options.recruit_randomization.value):
            return  # randomization on — nothing to lock

        for name in AP_RECRUIT_ITEM_DIGIMON:
            try:
                location = self.get_location(name)
            except KeyError:
                # Defensive: a recruit AP location should always exist
                # in v7+, but skip if it's somehow been excluded.
                continue
            location.place_locked_item(self.create_item(f"{name} Recruit"))

    def create_items(self) -> None:
        items.create_all_items(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_item(self, name: str) -> items.DigimonWorldItem:
        return items.create_item(self, name)

    def get_filler_item_name(self) -> str:
        return items.FILLER_ITEM_NAME

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
            "fast_drimogemon",
            "easy_monochromon",
            "stat_gain_multiplier",
            "bridge_unlock",
            "great_canyon_unlock",
            "lava_cave_access",
            "god_mode",
        ))
        slot_data["vanilla_grant_chests"] = sorted(
            name for name, grant in self.chest_grants.items() if grant.vanilla_grant
        )
        return slot_data

    def generate_output(self, output_directory: str) -> None:
        """Phase 3 entry point — emit the per-player ``.apdw1`` patch.

        Generation does **not** read the user's ``.bin``. The token
        blob is composed entirely from in-memory data; the source ROM
        is only consulted later, at patch-apply time, by
        :class:`worlds.digimon_world.rom.DigimonWorldProcedurePatch`.
        """

        rom.write_patch(self, output_directory)
