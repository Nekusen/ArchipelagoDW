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
from typing import Any, ClassVar, TextIO

from worlds.AutoWorld import World

from . import (
    chest_assignments,
    drops,
    enemies,
    evolutions,
    gifts,
    items,
    locations,
    music,
    raising,
    regions,
    rom,
    rules,
    technique_lists,
    techniques,
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

        from .options import validate_shop_price_options
        validate_shop_price_options(
            self.options, self.multiworld.player_name[self.player],
        )

        for name in items.get_bootstrap_items(self):
            self.multiworld.push_precollected(self.create_item(name))

        # Static SLUS-table rewrites that need no placement: resolved here so
        # post_fill's enemy scaling can read the technique powers this seed ships.
        self.technique_plan = techniques.build_technique_plan(self)
        self.list_plan = technique_lists.build_list_plan(self)
        self.drop_plan = drops.build_drop_plan(self)
        self.gift_plan = gifts.build_gift_plan(self)
        self.evolution_plan = evolutions.build_evolution_plan(self)
        self.raise_plan = raising.build_raise_plan(self)
        self.bgm_plan = music.build_bgm_plan(self)

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
            "infinite_auto_pilot",
            "stat_gain_multiplier",
            "bridge_unlock",
            "great_canyon_unlock",
            "lava_cave_access",
            "god_mode",
            "recycle_shop_locations",
            "merit_shop_locations",
            "item_shop_locations",
            "secret_shop_locations",
            "fishing_locations",
            "in_game_notifications",
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

    #: Enemy stat-scaling / species-randomization decisions, resolved in
    #: :meth:`post_fill` (sphere walk needs the finished placement) and
    #: consumed by :func:`rom.write_patch`.
    enemy_plan: enemies.EnemyPlan = enemies.EMPTY_PLAN
    #: Technique-data / element-matrix and enemy-drop rewrites, resolved in
    #: :meth:`generate_early` (static SLUS tables) and consumed by
    #: :func:`rom.write_patch`; the enemy planner reads the technique powers.
    technique_plan: techniques.TechniquePlan = techniques.EMPTY_PLAN
    list_plan: technique_lists.ListPlan = technique_lists.EMPTY_PLAN
    drop_plan: drops.DropPlan = drops.EMPTY_PLAN
    gift_plan: gifts.GiftPlan = gifts.EMPTY_PLAN
    evolution_plan: evolutions.EvolutionPlan = evolutions.EMPTY_PLAN
    raise_plan: raising.RaisePlan = raising.EMPTY_PLAN
    bgm_plan: music.BgmPlan = music.EMPTY_PLAN

    def post_fill(self) -> None:
        self.enemy_plan = enemies.build_enemy_plan(self)

    def write_spoiler(self, spoiler_handle: TextIO) -> None:
        name = self.multiworld.player_name[self.player]
        self._write_technique_spoiler(spoiler_handle, name)
        self._write_drop_spoiler(spoiler_handle, name)
        self._write_gift_spoiler(spoiler_handle, name)
        self._write_evolution_spoiler(spoiler_handle, name)
        if not self.raise_plan.empty:
            spoiler_handle.write(f"\n\nPartner raising ({name}):\n")
            for species, row in sorted(self.raise_plan.overrides.items()):
                spoiler_handle.write(f"  {raising.species_name(species)}: {raising.describe_row(row)}\n")
        if not self.bgm_plan.empty:
            spoiler_handle.write(f"\n\nMusic ({name}):\n")
            for line in music.describe_plan(self.bgm_plan):
                spoiler_handle.write(f"  {line}\n")
        plan = self.enemy_plan
        if plan.empty:
            return

        def describe(target: enemies.Targets) -> str:
            level = "vanilla" if target.tech_level is None else f"~{target.tech_level:.0f} power"
            return f"stats x{target.stat_factor:.2f}, techniques {level}"

        if plan.region_targets:
            spoiler_handle.write(f"\n\nEnemy stats, progressive ({name}):\n")
            for region in sorted(plan.region_targets, key=lambda r: (plan.region_depths.get(r, 0), r)):
                spoiler_handle.write(
                    f"  {region}: sphere {plan.region_depths.get(region, '?')}, "
                    f"{describe(plan.region_targets[region])}\n"
                )
        if plan.screen_targets:
            spoiler_handle.write(f"\n\nEnemy stats, full random ({name}):\n")
            for map_id in sorted(plan.screen_targets):
                screen = enemies.SCREEN_FILENAMES.get(map_id, str(map_id))
                spoiler_handle.write(f"  {screen}: {describe(plan.screen_targets[map_id])}\n")
        if plan.substitutions:
            spoiler_handle.write(f"\n\nEnemy randomization ({name}):\n")
            for (map_id, species), substitute in sorted(plan.substitutions.items()):
                screen = enemies.SCREEN_FILENAMES.get(map_id, str(map_id))
                spoiler_handle.write(
                    f"  {screen}: {enemies.SPECIES_BY_ID[species].name} -> {enemies.SPECIES_BY_ID[substitute].name}\n"
                )

    def _write_technique_spoiler(self, spoiler_handle: TextIO, name: str) -> None:
        plan = self.technique_plan
        if plan.moves:
            spoiler_handle.write(f"\n\nTechnique data ({name}):\n")
            for tech_id, values in sorted(plan.moves.items()):
                spoiler_handle.write(
                    f"  {techniques.MOVE_NAMES[tech_id]}: {techniques.describe_values(values)}"
                    f"  (vanilla {techniques.describe_values(techniques.VANILLA_VALUES[tech_id])})\n"
                )
        if self.list_plan.lists:
            spoiler_handle.write(f"\n\nSpecies technique lists ({name}):\n")
            for species_id, moves in sorted(self.list_plan.lists.items()):
                spoiler_handle.write(
                    f"  {enemies.SPECIES_BY_ID[species_id].name}: {technique_lists.describe_list(moves)}\n"
                )
        if plan.matrix is not None:
            spoiler_handle.write(f"\n\nType effectiveness ({name}), technique element x target specialty:\n")
            spoiler_handle.write("  " + " " * 8 + "".join(f"{e:>8}" for e in techniques.ELEMENT_NAMES) + "\n")
            for element, row in zip(techniques.ELEMENT_NAMES, plan.matrix, strict=True):
                spoiler_handle.write(f"  {element:<8}" + "".join(f"{v:>8}" for v in row) + "\n")

    def _write_gift_spoiler(self, spoiler_handle: TextIO, name: str) -> None:
        plan = self.gift_plan
        if plan.tech_gifts:
            spoiler_handle.write(f"\n\nTechnique gifts ({name}):\n")
            for site, tech in sorted(plan.tech_gifts.items()):
                spoiler_handle.write(
                    f"  {gifts.TECH_GIFT_SITE_NAMES[site]}: {techniques.MOVE_NAMES[tech]}"
                    f"  (vanilla {techniques.MOVE_NAMES[gifts.TECH_GIFT_VANILLA[site]]})\n"
                )
        if plan.tokomon_gifts:
            spoiler_handle.write(f"\n\nTokomon gifts ({name}):\n")
            for site, (item, count) in sorted(plan.tokomon_gifts.items()):
                vanilla_item, vanilla_count = gifts.TOKOMON_GIFT_VANILLA[site]
                spoiler_handle.write(
                    f"  gift {site + 1}: {count}x {drops.ITEM_NAMES[item]}"
                    f"  (vanilla {vanilla_count}x {drops.ITEM_NAMES[vanilla_item]})\n"
                )

    def _write_evolution_spoiler(self, spoiler_handle: TextIO, name: str) -> None:
        plan = self.evolution_plan
        if plan.empty:
            return
        if plan.paths:
            spoiler_handle.write(f"\n\nDigivolution tree ({name}):\n")
            for species, path in sorted(plan.paths.items()):
                if path.targets or evolutions.VANILLA_PATHS[species].targets:
                    spoiler_handle.write(f"  {evolutions.describe_path(species, path)}\n")
        if plan.requirements:
            spoiler_handle.write(f"\n\nDigivolution requirements ({name}):\n")
            for species, reqs in sorted(plan.requirements.items()):
                if reqs != evolutions.NO_REQUIREMENTS:
                    spoiler_handle.write(
                        f"  {evolutions.SPECIES_NAME[species]}: {evolutions.describe_requirements(reqs)}\n"
                    )
        if plan.special:
            spoiler_handle.write(f"\n\nSpecial digivolutions ({name}):\n")
            for index, target in sorted(plan.special.items()):
                spoiler_handle.write(
                    f"  {evolutions.SPECIAL_EVOLUTION_NAMES[index]} -> {evolutions.SPECIES_NAME[target]}\n"
                )
        if plan.gains:
            spoiler_handle.write(f"\n\nDigivolution stat gains ({name}):\n")
            for species, gains in sorted(plan.gains.items()):
                spoiler_handle.write(
                    f"  {evolutions.SPECIES_NAME[species]}: {evolutions.describe_gains(gains)}"
                    f"  (vanilla {evolutions.describe_gains(evolutions.VANILLA_GAINS[species])})\n"
                )

    def _write_drop_spoiler(self, spoiler_handle: TextIO, name: str) -> None:
        plan = self.drop_plan
        if plan.empty:
            return
        spoiler_handle.write(f"\n\nEnemy drops ({name}):\n")
        for species_id, (item, chance) in sorted(plan.overrides.items()):
            species = enemies.SPECIES_BY_ID[species_id]
            spoiler_handle.write(
                f"  {species.name}: {drops.ITEM_NAMES[item]} {chance}%"
                f"  (vanilla {drops.ITEM_NAMES[species.drop_item]} {species.drop_chance}%)\n"
            )

    def generate_output(self, output_directory: str) -> None:
        """Phase 3 entry point — emit the per-player ``.apdw1`` patch.

        Generation does **not** read the user's ``.bin``. The token
        blob is composed entirely from in-memory data; the source ROM
        is only consulted later, at patch-apply time, by
        :class:`worlds.digimon_world.rom.DigimonWorldProcedurePatch`.
        """

        rom.write_patch(self, output_directory)
