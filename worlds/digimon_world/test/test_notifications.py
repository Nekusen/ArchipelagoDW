"""In-game AP notifications: the patch tokens (``rom._write_notification_tokens``), the client's
text sanitiser / queue / mailbox contract, and the option wiring. The hook itself was
lab-validated through the three PATCH_PROCESS nets on 2026-08-29
(``work/dw1_re/decomp/notifications/NOTES.md``)."""

from __future__ import annotations

import asyncio
import inspect
import os
import struct
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from worlds.Files import APTokenTypes

from .. import client as client_module
from .. import rom as rom_module
from ..client import DigimonWorldClient, NotificationQueue, notification_fits, sanitize_notification
from ..data.addresses import (
    NOTIFY_CALLBACK_WORDS,
    NOTIFY_FLAG_PENDING,
    NOTIFY_HOOK_ADDIU_PATCHED,
    NOTIFY_HOOK_ADDIU_VANILLA,
    NOTIFY_HOOK_LUI_PATCHED,
    NOTIFY_HOOK_LUI_VANILLA,
    NOTIFY_MAILBOX_RAM,
    NOTIFY_MAILBOX_SIZE,
    NOTIFY_MAP_NAME_PTR_VANILLA,
    NOTIFY_MAP_NAME_SLOT,
    NOTIFY_TEXT_MAX_CHARS,
    NOTIFY_TOP_F1_RAM,
    NOTIFY_TOP_F1_VANILLA_WORDS,
    NOTIFY_TOP_F1_WORDS,
    NOTIFY_TOP_F2_RAM,
    NOTIFY_TOP_F2_VANILLA_WORDS,
    NOTIFY_TOP_F2_WORDS,
    NOTIFY_TOP_HOOK_ADDIU_PATCHED,
    NOTIFY_TOP_HOOK_ADDIU_VANILLA,
    NOTIFY_TOP_HOOK_LUI_PATCHED,
    NOTIFY_TOP_HOOK_LUI_VANILLA,
    NOTIFY_TOP_RENDER_MAP_NAME_RAM,
    NOTIFY_TOP_Y,
    RAM_NOTIFY_FLAG,
    RAM_NOTIFY_TEXT,
    ROM_ISTRIGGERSET_WRAPPER_RAM,
    ROM_NOTIFY_CALLBACK_OFFSET,
    ROM_NOTIFY_HOOK_ADDIU_OFFSET,
    ROM_NOTIFY_HOOK_LUI_OFFSET,
    ROM_NOTIFY_LOADING_NAME_OFFSET,
    ROM_NOTIFY_MAILBOX_OFFSET,
    ROM_NOTIFY_MAP_NAME_PTR_OFFSET,
    ROM_NOTIFY_TOP_F1_OFFSET,
    ROM_NOTIFY_TOP_F2_OFFSET,
    ROM_NOTIFY_TOP_HOOK_ADDIU_OFFSET,
    ROM_NOTIFY_TOP_HOOK_LUI_OFFSET,
    _build_notify_top_words,
)
from .bases import DigimonWorldTestBase

_VANILLA_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class _Names:
    def __init__(self, by_slot: dict[int, dict[int, str]]) -> None:
        self._by_slot = by_slot

    def lookup_in_slot(self, code: int, slot: int) -> str:
        return self._by_slot[slot][code]

    def lookup_in_game(self, code: int, game: str | None = None) -> str:
        return self._by_slot[1][code]


class _Item:
    def __init__(self, item: int, player: int) -> None:
        self.item = item
        self.player = player


class _Ctx:
    def __init__(self) -> None:
        self.bizhawk_ctx = object()
        self.slot = 1
        self.item_names = _Names({1: {10: "Meat"}, 2: {20: "Master Sword"}})
        self.player_names = {1: "Rt", 2: "Link"}


def _words(words: tuple[int, ...]) -> bytes:
    return b"".join(struct.pack("<I", w) for w in words)


class TestTokens(unittest.TestCase):
    def test_ten_writes(self) -> None:
        patch = _TokenCollector()
        rom_module._write_notification_tokens(patch)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        self.assertEqual(len(patch.tokens), 10)
        self.assertEqual(tokens[ROM_NOTIFY_CALLBACK_OFFSET], _words(NOTIFY_CALLBACK_WORDS))
        self.assertEqual(tokens[ROM_NOTIFY_MAILBOX_OFFSET], bytes(NOTIFY_MAILBOX_SIZE))
        self.assertEqual(tokens[ROM_NOTIFY_HOOK_LUI_OFFSET], struct.pack("<I", NOTIFY_HOOK_LUI_PATCHED))
        self.assertEqual(tokens[ROM_NOTIFY_HOOK_ADDIU_OFFSET], struct.pack("<I", NOTIFY_HOOK_ADDIU_PATCHED))
        self.assertEqual(tokens[ROM_NOTIFY_MAP_NAME_PTR_OFFSET], struct.pack("<I", NOTIFY_MAILBOX_RAM + 4))
        self.assertEqual(tokens[ROM_NOTIFY_LOADING_NAME_OFFSET], bytes([NOTIFY_MAP_NAME_SLOT]))
        self.assertEqual(tokens[ROM_NOTIFY_TOP_F1_OFFSET], _words(NOTIFY_TOP_F1_WORDS))
        self.assertEqual(tokens[ROM_NOTIFY_TOP_F2_OFFSET], _words(NOTIFY_TOP_F2_WORDS))
        self.assertEqual(tokens[ROM_NOTIFY_TOP_HOOK_LUI_OFFSET], struct.pack("<I", NOTIFY_TOP_HOOK_LUI_PATCHED))
        self.assertEqual(tokens[ROM_NOTIFY_TOP_HOOK_ADDIU_OFFSET], struct.pack("<I", NOTIFY_TOP_HOOK_ADDIU_PATCHED))

    def test_callback_shape(self) -> None:
        self.assertEqual(len(NOTIFY_CALLBACK_WORDS), 28)
        self.assertEqual(NOTIFY_CALLBACK_WORDS[-2], 0x03E00008)        # jr ra
        self.assertEqual(NOTIFY_CALLBACK_WORDS[-1], 0)                 # delay slot nop

    def test_top_renderer_shape(self) -> None:
        """The two fragments of ``renderMapNameAp``: sizes, control flow, the y immediate, and the
        vanilla path leaving the stack pointer where it found it."""
        self.assertEqual((len(NOTIFY_TOP_F1_WORDS), len(NOTIFY_TOP_F2_WORDS)), (12, 17))
        f1, f2 = NOTIFY_TOP_F1_WORDS, NOTIFY_TOP_F2_WORDS
        self.assertEqual(f1[0], 0x240100EF)                                    # at = 239
        self.assertEqual(f1[1], 0x10810003)                                    # beq a0, at, +3
        self.assertEqual(f1[3], 0x08000000 | ((NOTIFY_TOP_RENDER_MAP_NAME_RAM >> 2) & 0x03FFFFFF))   # j renderMapName
        self.assertEqual((f1[2] & 0xFFFF, f1[4] & 0xFFFF), (0xFFD8, 0x0028))   # open / close the frame
        self.assertEqual(f1[10], 0x08000000 | ((NOTIFY_TOP_F2_RAM >> 2) & 0x03FFFFFF))   # hop to F2
        self.assertEqual(f2[10], 0x24060000 | (NOTIFY_TOP_Y & 0xFFFF))         # a2 = y
        self.assertEqual(f2[-2:], (0x03E00008, 0))                             # jr ra; nop
        self.assertEqual(((NOTIFY_TOP_HOOK_LUI_PATCHED & 0xFFFF) << 16) | (NOTIFY_TOP_HOOK_ADDIU_PATCHED & 0xFFFF),
                         NOTIFY_TOP_F1_RAM)

    def test_top_renderer_right_mode(self) -> None:
        """The right-aligned variant differs from the shipped words only where the lab's
        ``notification_top_right.json`` did: the x constant and the three width-dependent words."""
        f1, f2 = _build_notify_top_words(-112, "right", 12, 148)
        diff1 = [i for i, (a, b) in enumerate(zip(f1, NOTIFY_TOP_F1_WORDS, strict=True)) if a != b]
        diff2 = [i for i, (a, b) in enumerate(zip(f2, NOTIFY_TOP_F2_WORDS, strict=True)) if a != b]
        self.assertEqual((diff1, diff2), ([9], [5, 6, 9]))
        self.assertEqual(f1[9], 0x24050098)                                    # a1 = 152
        self.assertEqual((f2[5], f2[6], f2[9]), (0, 0, 0x00A72823))            # nop, nop, subu a1, a1, a3

    def test_dormant_istriggerset_wrapper_stays_retired(self) -> None:
        """Its Cave6 range overlaps fragment 1 (and the AP item description string): the writer
        exists for its design notes only and must never be called."""
        self.assertGreater(ROM_ISTRIGGERSET_WRAPPER_RAM + 80, NOTIFY_TOP_F1_RAM)   # the overlap this guards
        source = inspect.getsource(rom_module)
        calls = [ln for ln in source.splitlines()
                 if "_write_istriggerset_wrapper_tokens(" in ln and not ln.lstrip().startswith("def ")]
        self.assertEqual(calls, [])


@unittest.skipUnless(_VANILLA_BIN.exists() or os.environ.get("DW1_VANILLA_BIN"), "vanilla disc not available")
class TestVanillaBytesOnDisc(unittest.TestCase):
    def test_hook_sites(self) -> None:
        rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()
        self.assertEqual(struct.unpack_from("<I", rom, ROM_NOTIFY_HOOK_LUI_OFFSET)[0], NOTIFY_HOOK_LUI_VANILLA)
        self.assertEqual(struct.unpack_from("<I", rom, ROM_NOTIFY_HOOK_ADDIU_OFFSET)[0], NOTIFY_HOOK_ADDIU_VANILLA)
        self.assertEqual(struct.unpack_from("<I", rom, ROM_NOTIFY_MAP_NAME_PTR_OFFSET)[0],
                         NOTIFY_MAP_NAME_PTR_VANILLA)
        self.assertEqual(rom[ROM_NOTIFY_LOADING_NAME_OFFSET], 0)

    def test_top_renderer_sites(self) -> None:
        rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()
        self.assertEqual(struct.unpack_from("<I", rom, ROM_NOTIFY_TOP_HOOK_LUI_OFFSET)[0],
                         NOTIFY_TOP_HOOK_LUI_VANILLA)
        self.assertEqual(struct.unpack_from("<I", rom, ROM_NOTIFY_TOP_HOOK_ADDIU_OFFSET)[0],
                         NOTIFY_TOP_HOOK_ADDIU_VANILLA)
        self.assertEqual(rom[ROM_NOTIFY_TOP_F1_OFFSET:ROM_NOTIFY_TOP_F1_OFFSET + 48],
                         _words(NOTIFY_TOP_F1_VANILLA_WORDS))
        self.assertEqual(rom[ROM_NOTIFY_TOP_F2_OFFSET:ROM_NOTIFY_TOP_F2_OFFSET + 68],
                         _words(NOTIFY_TOP_F2_VANILLA_WORDS))


class TestSanitizer(unittest.TestCase):
    def test_charset_and_length(self) -> None:
        self.assertEqual(sanitize_notification("Got: Meat"), "Got: Meat")
        self.assertEqual(sanitize_notification('Got: "Meat" (x2) <now>'), "Got: Meat x2 now")
        self.assertEqual(sanitize_notification("   spaced   out   "), "spaced out")
        long = sanitize_notification("Sent: Progressive Item Shop Voucher of Doom")
        self.assertLessEqual(len(long), NOTIFY_TEXT_MAX_CHARS)
        self.assertTrue(notification_fits(long))
        self.assertEqual(sanitize_notification("é\x80\x81"), "")

    def test_width_rule_trims_all_caps(self) -> None:
        caps = sanitize_notification("MASTER SWORD OF LEGEND HERE")
        self.assertTrue(notification_fits(caps))
        self.assertLess(len(caps), len("MASTER SWORD OF LEGEND HERE"))
        self.assertTrue(notification_fits("Sent: Drill Tunnel Chest 03"))


class TestQueue(unittest.TestCase):
    def test_bounded_with_overflow_summary(self) -> None:
        queue = NotificationQueue()
        for i in range(10):
            queue.push(f"Got: item {i}")
        self.assertEqual(len(queue), 7)                                   # 6 pending + the summary
        popped = [queue.pop() for _ in range(8)]
        self.assertEqual(popped[:6], [f"Got: item {i}" for i in range(6)])
        self.assertEqual(popped[6], "...and 4 more")
        self.assertIsNone(popped[7])
        queue.push("")
        self.assertEqual(len(queue), 0)


class TestClientContract(unittest.TestCase):
    def _client(self) -> DigimonWorldClient:
        client = DigimonWorldClient()
        client._in_game_notifications = True
        return client

    def test_push_only_when_idle(self) -> None:
        for flag, expect_write in ((0, True), (1, False), (152, False)):
            client = self._client()
            client._notifications.push("Got: Meat")
            seen: list[Any] = []

            async def fake_read(_ctx: Any, _requests: list[Any], _flag: int = flag) -> list[bytes]:
                return [bytes([_flag])]

            async def fake_write(_ctx: Any, writes: list[Any], _seen: list[Any] = seen) -> None:
                _seen.extend(writes)

            with mock.patch.object(client_module.bizhawk, "read", fake_read), \
                    mock.patch.object(client_module.bizhawk, "write", fake_write):
                _run(client._push_notifications(_Ctx()))
            if expect_write:
                self.assertEqual(len(seen), 2)
                addr, data, _domain = seen[0]
                self.assertEqual(addr, RAM_NOTIFY_TEXT)
                self.assertEqual(len(data), 64)
                self.assertEqual(bytes(data).rstrip(b"\x00"), b"Got: Meat")
                self.assertEqual(seen[1][:2], (RAM_NOTIFY_FLAG, [NOTIFY_FLAG_PENDING]))
                self.assertEqual(len(client._notifications), 0)
            else:
                self.assertEqual(seen, [])
                self.assertEqual(len(client._notifications), 1)

    def test_disabled_client_never_touches_ram(self) -> None:
        client = DigimonWorldClient()
        self.assertIsNone(client._in_game_notifications)
        client._notifications.push("Got: Meat")
        called = []

        async def fake_read(_ctx: Any, _requests: list[Any]) -> list[bytes]:
            called.append("read")
            return [b"\x00"]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            _run(client._push_notifications(_Ctx()))
        self.assertEqual(called, [])

    def test_received_and_sent_messages(self) -> None:
        client = self._client()
        ctx = _Ctx()
        client._notify_received(ctx, _Item(10, 2), "Meat")
        self.assertEqual(client._notifications.pop(), "Got: Meat from Link")
        client._notify_received(ctx, _Item(10, 1), "Meat")
        self.assertEqual(client._notifications.pop(), "Got: Meat")
        client.on_package(ctx, "PrintJSON", {"type": "ItemSend", "item": _Item(20, 1), "receiving": 2})  # type: ignore[arg-type]
        self.assertEqual(client._notifications.pop(), "Sent: Master Sword")
        client.on_package(ctx, "PrintJSON", {"type": "ItemSend", "item": _Item(10, 2), "receiving": 1})  # type: ignore[arg-type]
        client.on_package(ctx, "PrintJSON", {"type": "Hint", "item": _Item(20, 1), "receiving": 2})  # type: ignore[arg-type]
        self.assertIsNone(client._notifications.pop())


class TestNotificationOption(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_on_and_in_slot_data(self) -> None:
        self.assertTrue(self.world.options.in_game_notifications)
        self.assertEqual(self.world.fill_slot_data()["in_game_notifications"], 1)
