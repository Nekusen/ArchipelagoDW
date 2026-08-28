"""Enemy drop randomization (:mod:`worlds.digimon_world.drops`)."""

from __future__ import annotations

import unittest
from collections import Counter
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import drops, enemies
from .. import rom as rom_module
from ..data.addresses import ROM_DIGIMON_DATA_OFFSET, digimon_data_bin_offset
from ..data.enemy_records import ITEMS, SPECIES
from .bases import DigimonWorldTestBase


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestVanillaTables(unittest.TestCase):
    def test_items(self) -> None:
        self.assertEqual(len(ITEMS), 128)
        self.assertEqual(drops.ITEM_NAMES[38], "Meat")
        meat = drops.ITEM_PROPS[38]
        self.assertTrue(meat.is_food and meat.is_consumable and meat.dropable and not meat.is_evo)
        self.assertTrue(drops.ITEM_PROPS[0x53].is_banned)                 # Electo ring = AP chest sentinel
        self.assertFalse(drops.ITEM_PROPS[115].dropable)                  # a quest item

    def test_species_drops(self) -> None:
        rates = Counter(row[6] for row in SPECIES)
        self.assertTrue(set(rates) <= set(drops.DROP_RATE_LADDER) | {drops.NEVER_DROP, drops.ALWAYS_DROP})
        self.assertEqual(rates[drops.ALWAYS_DROP], 22)
        goburimon = enemies.SPECIES_BY_ID[80]
        self.assertEqual((goburimon.drop_item, goburimon.drop_chance), (38, 30))
        self.assertEqual((enemies.SPECIES_BY_ID[3].drop_item, enemies.SPECIES_BY_ID[3].drop_chance), (0, 50))


class TestPlanner(unittest.TestCase):
    def test_pool(self) -> None:
        cheap = drops.drop_item_pool(38, True, 1000)
        any_value = drops.drop_item_pool(38, False, 1000)
        self.assertTrue(set(cheap) < set(any_value))
        for pool in (cheap, any_value):
            for item_id in pool:
                props = drops.ITEM_PROPS[item_id]
                self.assertTrue(props.is_consumable and props.dropable and not props.is_evo and not props.is_banned)
        self.assertTrue(all(drops.ITEM_PROPS[i].price < 1000 for i in cheap))
        valuable = drops.drop_item_pool(next(r[0] for r in ITEMS if r[2] >= 1000 and r[0] in any_value), True, 1000)
        self.assertTrue(all(drops.ITEM_PROPS[i].price >= 1000 for i in valuable))

    def test_rate_ladder(self) -> None:
        rng = Random(4)
        self.assertEqual(drops.randomize_drop_rate(rng, drops.ALWAYS_DROP), drops.ALWAYS_DROP)
        for _ in range(50):
            self.assertIn(drops.randomize_drop_rate(rng, drops.NEVER_DROP), drops.DROP_RATE_LADDER)
            self.assertIn(drops.randomize_drop_rate(rng, 10), (1, 5, 10, 20, 25))
            self.assertIn(drops.randomize_drop_rate(rng, 1), (1, 5, 10))
            self.assertIn(drops.randomize_drop_rate(rng, 50), (30, 40, 50))

    def test_items_only_and_rates_only(self) -> None:
        items_only = drops.randomize_drops(Random(1), items=True, rates=False, match_value=True, cutoff=1000)
        for species_id, (item, rate) in items_only.items():
            self.assertEqual(rate, enemies.SPECIES_BY_ID[species_id].drop_chance)
            self.assertNotEqual(item, enemies.SPECIES_BY_ID[species_id].drop_item)
        rates_only = drops.randomize_drops(Random(1), items=False, rates=True, match_value=True, cutoff=1000)
        for species_id, (item, rate) in rates_only.items():
            self.assertEqual(item, enemies.SPECIES_BY_ID[species_id].drop_item)
            self.assertNotEqual(rate, enemies.SPECIES_BY_ID[species_id].drop_chance)
        self.assertTrue(all(enemies.SPECIES_BY_ID[s].drop_chance != drops.ALWAYS_DROP for s in rates_only))

    def test_deterministic(self) -> None:
        a = drops.randomize_drops(Random(9), items=True, rates=True, match_value=False, cutoff=1000)
        b = drops.randomize_drops(Random(9), items=True, rates=True, match_value=False, cutoff=1000)
        self.assertEqual(a, b)


class TestTokens(unittest.TestCase):
    def test_tokens(self) -> None:
        plan = drops.DropPlan({80: (39, 50), 0: (1, 2)})
        patch = _TokenCollector()
        rom_module._write_drop_tokens(patch, plan)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        self.assertEqual(tokens[digimon_data_bin_offset(80, 33)], bytes((39, 50)))
        self.assertEqual(tokens[ROM_DIGIMON_DATA_OFFSET + 33], bytes((1, 2)))
        self.assertEqual(len(patch.tokens), 2)


class TestDropOptions(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"enemy_drop_items": True, "enemy_drop_rates": True}

    def test_plan(self) -> None:
        plan = self.world.drop_plan
        self.assertFalse(plan.empty)
        self.assertGreater(len(plan.overrides), 150)


class TestDropOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.assertTrue(self.world.drop_plan.empty)
