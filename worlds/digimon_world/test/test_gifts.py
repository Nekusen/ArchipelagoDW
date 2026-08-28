"""NPC gift randomization (:mod:`worlds.digimon_world.gifts`) and the standalone's QoL patch
toggles (``rom._write_standalone_patch_tokens``), plus a disc-gated check that every site's
vanilla bytes are what ``data/addresses.py`` pins."""

from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import drops, gifts, techniques
from .. import rom as rom_module
from ..data.addresses import (
    ROM_CHECK_MOVE_OFFSETS,
    ROM_DV_CHIP_TEXT_LENGTH,
    ROM_DV_CHIP_TEXT_PATCHES,
    ROM_ITEM_DROPABLE_BYTE_OFFSET,
    ROM_ITEM_TABLE_BASE,
    ROM_ITEM_TABLE_ENTRY_SIZE,
    ROM_LEARN_MOVE_AND_COMMAND_OFFSET,
    ROM_LEARN_MOVE_AND_COMMAND_VANILLA_WORDS,
    ROM_LEARN_MOVE_AND_COMMAND_WORDS,
    ROM_LEARN_MOVE_OFFSETS,
    ROM_QUEST_ITEMS_NOT_DROPABLE,
    ROM_TECH_LEARN_BATTLE,
    ROM_TECH_LEARN_BATTLE_VANILLA,
    ROM_TECH_LEARN_BRAIN,
    ROM_TECH_LEARN_BRAIN_VANILLA,
    ROM_TOKOMON_ITEM_OFFSETS,
    ROM_UNRIG_SLOTS_WORD_PATCHES,
    TECH_GIFT_LEARN_OPCODE,
    TECH_GIFT_VANILLA,
    TOKOMON_GIFT_OPCODE,
    TOKOMON_GIFT_VANILLA,
    _flat_to_user_data,
    _read_struct_block_user_data,
    read_item_table_user_data,
)
from .bases import DigimonWorldTestBase

_VANILLA_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class _Options:
    """Just the toggles ``_write_standalone_patch_tokens`` reads."""

    def __init__(self, **flags: bool) -> None:
        for name in ("quest_items_droppable", "increase_learn_chance", "brain_training_tier_one", "unrig_slots",
                     "learn_move_and_command", "fix_dv_chip_text"):
            setattr(self, name, flags.get(name, False))


class TestGiftPlanners(unittest.TestCase):
    def test_tech_gifts_stay_in_the_partner_pool(self) -> None:
        plan = gifts.randomize_tech_gifts(Random(3))
        self.assertTrue(plan)
        for site, tech in plan.items():
            self.assertTrue(0 <= site < 4)
            self.assertTrue(techniques.is_learnable(tech))
            self.assertNotEqual(tech, TECH_GIFT_VANILLA[site])

    def test_tokomon_pool(self) -> None:
        consumable = gifts.tokomon_item_pool(True)
        anything = gifts.tokomon_item_pool(False)
        self.assertTrue(set(consumable) < set(anything))
        for pool in (consumable, anything):
            for item_id in pool:
                props = drops.ITEM_PROPS[item_id]
                self.assertTrue(props.dropable and not props.is_evo and not props.is_banned)
        self.assertTrue(all(drops.ITEM_PROPS[i].is_consumable for i in consumable))
        self.assertNotIn(0x53, anything)                                  # AP chest sentinel
        for quest_item in ROM_QUEST_ITEMS_NOT_DROPABLE:
            self.assertNotIn(quest_item, anything)

    def test_tokomon_gifts(self) -> None:
        plan = gifts.randomize_tokomon_gifts(Random(3), consumable_only=True)
        self.assertTrue(plan)
        for site, (item, count) in plan.items():
            self.assertTrue(0 <= site < 6)
            self.assertIn(item, gifts.tokomon_item_pool(True))
            self.assertTrue(1 <= count <= 3)
        self.assertEqual(plan, gifts.randomize_tokomon_gifts(Random(3), consumable_only=True))

    def test_tokens(self) -> None:
        plan = gifts.GiftPlan({0: 5, 3: 40}, {1: (60, 2)})
        patch = _TokenCollector()
        rom_module._write_gift_tokens(patch, plan)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        self.assertEqual(tokens[ROM_LEARN_MOVE_OFFSETS[0] + 1], bytes([5]))
        self.assertEqual(tokens[ROM_CHECK_MOVE_OFFSETS[0]], bytes([5]))
        self.assertEqual(tokens[ROM_LEARN_MOVE_OFFSETS[3] + 1], bytes([40]))
        self.assertEqual(tokens[ROM_CHECK_MOVE_OFFSETS[3]], bytes([40]))
        self.assertEqual(tokens[ROM_TOKOMON_ITEM_OFFSETS[1] + 2], bytes((60, 2)))
        self.assertEqual(len(patch.tokens), 5)


class TestStandalonePatches(unittest.TestCase):
    def _tokens(self, **flags: bool) -> list[tuple[int, bytes]]:
        patch = _TokenCollector()
        rom_module._write_standalone_patch_tokens(patch, _Options(**flags))  # type: ignore[arg-type]
        return patch.tokens

    def test_nothing_by_default(self) -> None:
        self.assertEqual(self._tokens(), [])

    def test_quest_items_droppable(self) -> None:
        tokens = dict(self._tokens(quest_items_droppable=True))
        self.assertEqual(len(tokens), len(ROM_QUEST_ITEMS_NOT_DROPABLE))
        for item_id in ROM_QUEST_ITEMS_NOT_DROPABLE:
            table_offset = item_id * ROM_ITEM_TABLE_ENTRY_SIZE + ROM_ITEM_DROPABLE_BYTE_OFFSET
            self.assertEqual(tokens[_flat_to_user_data(ROM_ITEM_TABLE_BASE, table_offset)], b"\x01")

    def test_learn_chance_tables(self) -> None:
        tokens = self._tokens(increase_learn_chance=True)
        battle_tokens = [(off, data) for off, data in tokens if off != ROM_TECH_LEARN_BRAIN.offset]
        self.assertEqual(b"".join(data for _, data in battle_tokens),
                         bytes(v * 2 for v in ROM_TECH_LEARN_BATTLE_VANILLA))
        self.assertEqual(len(battle_tokens), 2)   # one sector hop inside the table
        self.assertEqual(battle_tokens[0][0], ROM_TECH_LEARN_BATTLE.offset)
        brain = dict(tokens)[ROM_TECH_LEARN_BRAIN.offset]
        self.assertEqual(brain, bytes(v * 2 if v else 5 for v in ROM_TECH_LEARN_BRAIN_VANILLA))

    def test_brain_tier_one(self) -> None:
        self.assertEqual(rom_module.brain_learn_table(True, False)[:3], bytes((30, 15, 10)))
        self.assertEqual(rom_module.brain_learn_table(True, True)[:3], bytes((60, 30, 20)))
        self.assertEqual(rom_module.brain_learn_table(False, True)[:3], bytes((5, 30, 20)))
        tokens = dict(self._tokens(brain_training_tier_one=True))
        self.assertEqual(list(tokens), [ROM_TECH_LEARN_BRAIN.offset])
        self.assertEqual(tokens[ROM_TECH_LEARN_BRAIN.offset][0], 30)

    def test_code_and_text_patches(self) -> None:
        tokens = dict(self._tokens(unrig_slots=True, learn_move_and_command=True, fix_dv_chip_text=True))
        for offset, word, _vanilla in ROM_UNRIG_SLOTS_WORD_PATCHES:
            self.assertEqual(tokens[offset], struct.pack("<I", word))
        self.assertEqual(tokens[ROM_LEARN_MOVE_AND_COMMAND_OFFSET],
                         struct.pack("<II", *ROM_LEARN_MOVE_AND_COMMAND_WORDS))
        for offset, text, _vanilla in ROM_DV_CHIP_TEXT_PATCHES:
            self.assertEqual(len(tokens[offset]), ROM_DV_CHIP_TEXT_LENGTH)
            self.assertTrue(tokens[offset].startswith(text + b"\x00"))


@unittest.skipUnless(_VANILLA_BIN.exists() or os.environ.get("DW1_VANILLA_BIN"), "vanilla disc not available")
class TestVanillaBytesOnDisc(unittest.TestCase):
    """Net 1 for the sites above: the disc holds exactly the vanilla bytes the manifest pins."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()

    def test_gift_sites(self) -> None:
        for site, offset in enumerate(ROM_TOKOMON_ITEM_OFFSETS):
            self.assertEqual(self.rom[offset], TOKOMON_GIFT_OPCODE, hex(offset))
            self.assertEqual(tuple(self.rom[offset + 2:offset + 4]), TOKOMON_GIFT_VANILLA[site], hex(offset))
        for site, (learn, check) in enumerate(zip(ROM_LEARN_MOVE_OFFSETS, ROM_CHECK_MOVE_OFFSETS, strict=True)):
            self.assertEqual(tuple(self.rom[learn:learn + 2]), (TECH_GIFT_LEARN_OPCODE, TECH_GIFT_VANILLA[site]),
                             hex(learn))
            self.assertEqual(self.rom[check], TECH_GIFT_VANILLA[site], hex(check))

    def test_patch_sites(self) -> None:
        items = read_item_table_user_data(self.rom)
        for item_id in range(128):
            dropable = int(item_id not in ROM_QUEST_ITEMS_NOT_DROPABLE)
            self.assertEqual(items[item_id * 32 + ROM_ITEM_DROPABLE_BYTE_OFFSET], dropable, item_id)
        self.assertEqual(_read_struct_block_user_data(self.rom, ROM_TECH_LEARN_BATTLE), ROM_TECH_LEARN_BATTLE_VANILLA)
        self.assertEqual(_read_struct_block_user_data(self.rom, ROM_TECH_LEARN_BRAIN), ROM_TECH_LEARN_BRAIN_VANILLA)
        for offset, _word, vanilla in ROM_UNRIG_SLOTS_WORD_PATCHES:
            self.assertEqual(struct.unpack_from("<I", self.rom, offset)[0], vanilla, hex(offset))
        self.assertEqual(struct.unpack_from("<II", self.rom, ROM_LEARN_MOVE_AND_COMMAND_OFFSET),
                         ROM_LEARN_MOVE_AND_COMMAND_VANILLA_WORDS)
        for offset, _text, vanilla in ROM_DV_CHIP_TEXT_PATCHES:
            self.assertEqual(self.rom[offset:offset + ROM_DV_CHIP_TEXT_LENGTH],
                             vanilla.ljust(ROM_DV_CHIP_TEXT_LENGTH, b"\x00"))


class TestGiftOptions(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"tech_gifts": True, "tokomon_gifts": True}

    def test_plan(self) -> None:
        plan = self.world.gift_plan
        self.assertTrue(plan.tech_gifts)
        self.assertTrue(plan.tokomon_gifts)


class TestGiftOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.assertTrue(self.world.gift_plan.empty)
