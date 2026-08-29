"""Cave6 occupancy: every resident structure the patcher can write into the unused-libgs region
(``0x800957C0..0x80096BCC``) must stay pairwise disjoint — with the *largest* variant of each
(the EXTENDED 55-word ITEM_PARA boot hook, the full transition-gate table). The 2026-08-29
multi-game test found the notification render callback placed inside the extended hook's
footprint (the layout comment only knew the 37-word hook): the game hung at boot on every seed
whose shopsanity needed the second seed block. This test is the invariant that was missing."""

from __future__ import annotations

import itertools
import unittest

from ..data import addresses as a


def _cave6_occupants() -> list[tuple[str, int, int]]:
    """(name, start, end) of everything shipped into Cave6, largest variant of each."""

    occupants = [
        ("chest giveItem wrapper", a.ROM_CHEST_GIVEITEM_WRAPPER_RAM, len(a.ROM_CHEST_GIVEITEM_WRAPPER_BYTES)),
        ("setTrigger wrapper (reserved)", a.ROM_SETTRIGGER_WRAPPER_RAM, 32),
        ("merit shop wrapper", a.ROM_MERIT_SHOP_WRAPPER_RAM, len(a.ROM_MERIT_SHOP_WRAPPER_BYTES)),
        ("AP item description string", 0x80000000 | a.AP_ITEM_DESC_RAM, len(a.AP_ITEM_DESC_STRING)),
        ("notification top renderer F1", a.NOTIFY_TOP_F1_RAM, len(a.NOTIFY_TOP_F1_WORDS) * 4),
        ("combat trampolines tr1..tr3", a.ROM_COMBAT_TR1_RAM, a.ROM_COMBAT_TR3_RAM + 16 - a.ROM_COMBAT_TR1_RAM),
        ("notification top renderer F2", a.NOTIFY_TOP_F2_RAM, len(a.NOTIFY_TOP_F2_WORDS) * 4),
        ("relocated ITEM_DESC_PTR (written entries)", a.RELOC_ITEM_DESC_PTR_RAM,
         a.RELOC_ITEM_DESC_PTR_WRITTEN_ENTRIES * 4),
        ("notification render callback", a.NOTIFY_CALLBACK_RAM, len(a.NOTIFY_CALLBACK_WORDS) * 4),
        ("AP description strings", a.AP_DESC_STRINGS_RAM, a.AP_DESC_STRINGS_TOTAL_SIZE),
        ("icon clamp wrapper", a.ROM_ICON_CLAMP_WRAPPER_RAM, len(a.ROM_ICON_CLAMP_WRAPPER_BYTES)),
        ("icon-id table", a.AP_ICON_ID_TABLE_RAM, a.AP_ICON_ID_TABLE_SIZE),
        ("notification mailbox", a.NOTIFY_MAILBOX_RAM, a.NOTIFY_MAILBOX_SIZE),
        ("merit AP description strings", a.MERIT_AP_DESC_STRINGS_RAM, a.MERIT_AP_DESC_STRINGS_TOTAL_SIZE),
        ("merit shop ext wrapper", a.ROM_MERIT_SHOP_EXT_WRAPPER_RAM, len(a.ROM_MERIT_SHOP_EXT_WRAPPER_BYTES)),
        ("ITEM_PARA boot seed hook (EXTENDED)", a.ITEM_PARA_BOOT_HOOK_RAM, len(a.ITEM_PARA_BOOT_HOOK_EXT_BYTES)),
        ("transition-gate wrapper", a.TRANSITION_GATE_WRAPPER_RAM,
         a.TRANSITION_GATE_TABLE_RAM - a.TRANSITION_GATE_WRAPPER_RAM),
        ("transition-gate table (full)", a.TRANSITION_GATE_TABLE_RAM, a._TRANSITION_GATE_FULL_TABLE_LEN),
        ("shop AP config word", a.SHOP_AP_CONFIG_RAM, 4),
        ("EXT ITEM_PARA seed block", a.EXT_ITEM_PARA_SEED_RAM, a.EXT_ITEM_PARA_SEED_SIZE),
    ]
    return [(name, start, start + size) for name, start, size in occupants]


class TestCave6Layout(unittest.TestCase):
    def test_every_occupant_inside_cave6(self) -> None:
        for name, start, end in _cave6_occupants():
            self.assertTrue(0x800957C0 <= start < end <= a._CAVE6_END_RAM, f"{name}: {start:#x}..{end:#x}")

    def test_occupants_pairwise_disjoint(self) -> None:
        occupants = sorted(_cave6_occupants(), key=lambda t: t[1])
        for (n1, s1, e1), (n2, s2, e2) in itertools.pairwise(occupants):
            self.assertLessEqual(e1, s2, f"{n1} ({s1:#x}..{e1:#x}) overlaps {n2} ({s2:#x}..{e2:#x})")

    def test_callback_clear_of_both_boot_hooks(self) -> None:
        cb_start = a.NOTIFY_CALLBACK_RAM
        cb_end = cb_start + len(a.NOTIFY_CALLBACK_WORDS) * 4
        for hook in (a.ITEM_PARA_BOOT_HOOK_BYTES, a.ITEM_PARA_BOOT_HOOK_EXT_BYTES):
            h_start, h_end = a.ITEM_PARA_BOOT_HOOK_RAM, a.ITEM_PARA_BOOT_HOOK_RAM + len(hook)
            self.assertTrue(cb_end <= h_start or cb_start >= h_end)
        self.assertEqual(len(a.ITEM_PARA_BOOT_HOOK_EXT_BYTES), 220)
        self.assertEqual(a.ITEM_PARA_BOOT_HOOK_RAM + 220, 0x80096698)
