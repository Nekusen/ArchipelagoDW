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
    NOTIFY_TEXT_MAX_PADDED,
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
    NOTIFY_TOP_X_MODE,
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
        self.item_names = _Names({1: {10: "Meat"}, 2: {20: "Master Sword", 21: "Ultimate Digivolver"}})
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

    def test_top_renderer_x_modes(self) -> None:
        """The shipped words are the right-aligned build (the user's pick); it differs from the
        centre build only where the lab's two specs did: the x constant and the three
        width-dependent words."""
        self.assertEqual(NOTIFY_TOP_X_MODE, "right")
        self.assertEqual(_build_notify_top_words(-112, "right", 12, 148), (NOTIFY_TOP_F1_WORDS, NOTIFY_TOP_F2_WORDS))
        c1, c2 = _build_notify_top_words(-112, "centre", 12, 148)
        diff1 = [i for i, (a, b) in enumerate(zip(c1, NOTIFY_TOP_F1_WORDS, strict=True)) if a != b]
        diff2 = [i for i, (a, b) in enumerate(zip(c2, NOTIFY_TOP_F2_WORDS, strict=True)) if a != b]
        self.assertEqual((diff1, diff2), ([9], [5, 6, 9]))
        self.assertEqual((c1[9], NOTIFY_TOP_F1_WORDS[9]), (0x2405000C, 0x24050098))       # a1 = 12 / 152
        self.assertEqual((c2[5], c2[6], c2[9]), (0x00022042, 0x000420C0, 0x00A42823))   # srl, sll, subu a1, a1, a0
        self.assertEqual((NOTIFY_TOP_F2_WORDS[5], NOTIFY_TOP_F2_WORDS[6], NOTIFY_TOP_F2_WORDS[9]),
                         (0, 0, 0x00A72823))                                            # nop, nop, subu a1, a1, a3

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
        self.assertLessEqual(len(long.rstrip()), NOTIFY_TEXT_MAX_CHARS)
        self.assertLessEqual(len(long), NOTIFY_TEXT_MAX_PADDED)
        self.assertTrue(notification_fits(long))
        self.assertEqual(sanitize_notification("é\x80\x81"), "")

    def test_width_rule_trims_all_caps(self) -> None:
        caps = sanitize_notification("MASTER SWORD OF LEGEND HERE")
        self.assertTrue(notification_fits(caps))
        self.assertLess(len(caps.rstrip()), len("MASTER SWORD OF LEGEND HERE"))
        self.assertLessEqual(len(caps), NOTIFY_TEXT_MAX_PADDED)
        self.assertTrue(notification_fits("Sent: Drill Tunnel Chest 03"))

    def test_wide_glyphs_are_padded_not_trimmed(self) -> None:
        """Capitals and ``-`` draw 12 px against the 8 px/char blit rect: the sanitizer now pads
        with trailing spaces instead of dropping the tail (2026-09-07 playtest: "E-Crystals"
        showed as "E", "FurryZX" as "FurryZ")."""

        from ..client import notification_width, pad_notification

        for text in ("Got: E-Crystals", "from FurryZX", "Sent: E-Crystals", "Got: MP Floppy"):
            out = sanitize_notification(text)
            self.assertEqual(out.rstrip(), text, text)
            self.assertTrue(notification_fits(out), text)
            self.assertLessEqual(len(out), NOTIFY_TEXT_MAX_PADDED)
            self.assertLessEqual(notification_width(out), len(out) * 8 + 4, text)
        self.assertEqual(sanitize_notification("Got: E-Crystals"), "Got: E-Crystals ")
        self.assertEqual(sanitize_notification("from FurryZX"), "from FurryZX ")
        self.assertEqual(pad_notification("Got: Meat"), "Got: Meat")      # nothing to pad


class TestQueue(unittest.TestCase):
    def test_unbounded_every_message_shows(self) -> None:
        # User decision 2026-09-01: no overflow collapse — every message
        # queues and shows, however long the burst (at ~1 s per banner).
        queue = NotificationQueue()
        for i in range(40):
            queue.push(f"Got: item {i}")
        self.assertEqual(len(queue), 40)
        popped = [queue.pop() for _ in range(41)]
        self.assertEqual(popped[:40], [f"Got: item {i}" for i in range(40)])
        self.assertIsNone(popped[40])
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

    def test_redelivery_stays_silent(self) -> None:
        # A game reboot (title screen) or an older-save load rolls the
        # in-RAM items counter back, so _deliver_items re-delivers the
        # whole tail. The items must land again; the banners must not
        # (2026-08-31 playtest: every reboot replayed the history).
        client = self._client()
        ctx = _Ctx()
        client._notify_received(ctx, _Item(10, 1), "Meat", 0)
        client._notify_received(ctx, _Item(11, 1), "Omnipotent", 1)
        self.assertEqual(len(client._notifications), 2)
        client._notifications.pop()
        client._notifications.pop()
        # Counter rollback: indices 0 and 1 delivered again.
        client._notify_received(ctx, _Item(10, 1), "Meat", 0)
        client._notify_received(ctx, _Item(11, 1), "Omnipotent", 1)
        self.assertEqual(len(client._notifications), 0)
        # A genuinely new item still announces.
        client._notify_received(ctx, _Item(12, 1), "Meat", 2)
        self.assertEqual(client._notifications.pop(), "Got: Meat")

    def test_mark_advances_even_with_notifications_off(self) -> None:
        # The high-water mark tracks deliveries, not banners: if the
        # option turns out disabled, replays after a later reconnect
        # must still know these indices were seen.
        client = DigimonWorldClient()
        client._in_game_notifications = False
        client._notify_received(_Ctx(), _Item(10, 1), "Meat", 0)
        self.assertEqual(client._notified_through, 1)
        self.assertEqual(len(client._notifications), 0)

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
        client._notify_received(ctx, _Item(10, 2), "Meat", 0)
        self.assertEqual(client._notifications.pop(), "Got: Meat from Link")
        client._notify_received(ctx, _Item(10, 1), "Meat", 1)
        self.assertEqual(client._notifications.pop(), "Got: Meat")
        client.on_package(ctx, "PrintJSON", {"type": "ItemSend", "item": _Item(20, 1), "receiving": 2})  # type: ignore[arg-type]
        self.assertEqual(client._notifications.pop(), "Sent: Master Sword to Link")
        # The receiver's name is dropped, never the item, when the message would not fit the banner.
        client.on_package(ctx, "PrintJSON", {"type": "ItemSend", "item": _Item(21, 1), "receiving": 2})  # type: ignore[arg-type]
        # Too long for one banner: the receiver now gets a follow-up
        # banner instead of being dropped (2026-09-01).
        self.assertEqual(client._notifications.pop(), "Sent: Ultimate Digivolver")
        self.assertEqual(client._notifications.pop(), "to Link")
        # Wide glyphs (2026-09-07): every character survives; each banner is padded to its rect.
        ctx.player_names[3] = "FurryZX"
        client._notify_received(ctx, _Item(10, 3), "E-Crystals", 2)
        self.assertEqual(client._notifications.pop(), "Got: E-Crystals ")
        self.assertEqual(client._notifications.pop(), "from FurryZX ")
        client._notify_received(ctx, _Item(10, 2), "E-Crystals", 3)
        self.assertEqual(client._notifications.pop(), "Got: E-Crystals from Link")
        ctx.item_names._by_slot[2][22] = "E-CRYSTALS"
        sent = {"type": "ItemSend", "item": _Item(22, 1), "receiving": 2}
        client.on_package(ctx, "PrintJSON", sent)  # type: ignore[arg-type]
        self.assertEqual(client._notifications.pop(), "Sent: E-CRYSTALS" + " " * 9)
        self.assertEqual(client._notifications.pop(), "to Link")
        client.on_package(ctx, "PrintJSON", {"type": "ItemSend", "item": _Item(10, 2), "receiving": 1})  # type: ignore[arg-type]
        client.on_package(ctx, "PrintJSON", {"type": "Hint", "item": _Item(20, 1), "receiving": 2})  # type: ignore[arg-type]
        self.assertIsNone(client._notifications.pop())


class TestGameEnteredGuard(unittest.TestCase):
    """Second watcher gate (2026-08-31): _game_alive passes at the TITLE
    SCREEN (boot init fills the save block with new-game defaults), so the
    client re-delivered the whole item history into pre-save RAM on every
    reboot. Nothing is delivered until a save is actually loaded."""

    def test_verdicts(self) -> None:
        from ..client import DigimonWorldClient
        from ..data.addresses import RAM_GAME_ENTERED_FLAG, RAM_TAMER_ENTITY_PTR

        zero = b"\x00\x00\x00\x00"
        flag_on = b"\x01\x00\x00\x00"
        tamer_on = b"\x6c\x57\x15\x80"   # observed ENTITY_TABLE[0] value
        cases = [
            ((zero, zero), False),        # cold title
            ((flag_on, zero), False),     # CONTINUE slot-pick microwindow
            ((zero, tamer_on), False),    # post-credits stale entity slot
            ((flag_on, tamer_on), True),  # in game
            ((b"\x01", tamer_on), False),  # short read
        ]
        for (flag, tamer), expected in cases:
            client = DigimonWorldClient()

            async def fake_read(_ctx: Any, requests: list[Any],
                                _flag: bytes = flag, _tamer: bytes = tamer) -> list[bytes]:
                assert [r[0] for r in requests] == [RAM_GAME_ENTERED_FLAG, RAM_TAMER_ENTITY_PTR]
                return [_flag, _tamer]

            with mock.patch.object(client_module.bizhawk, "read", fake_read):
                verdict = _run(client._game_entered(_Ctx()))
            self.assertIs(verdict, expected, (flag, tamer))


class TestGameAliveGuard(unittest.TestCase):
    """The watcher polls nothing until the SLUS is resident and its boot tables are loaded — a disc
    stuck at the BIOS must not turn emulator-initialised RAM into phantom checks (2026-08-29)."""

    def test_verdicts(self) -> None:
        from ..data.addresses import RAM_GAME_ALIVE_MAPHEAD, RAM_GAME_ALIVE_SLUS_MARKER
        marker_addr, marker = RAM_GAME_ALIVE_SLUS_MARKER
        cases = [
            ({marker_addr: b"\x00\x00\x00\x00", RAM_GAME_ALIVE_MAPHEAD: b"\x00\x00\x00\x00"}, False),  # BIOS
            ({marker_addr: marker, RAM_GAME_ALIVE_MAPHEAD: b"\x00\x00\x00\x00"}, False),              # boot hook hang
            ({marker_addr: b"\xff\xff\xff\xff", RAM_GAME_ALIVE_MAPHEAD: b"\x68\x04\x00\x00"}, False),  # junk RAM
            ({marker_addr: marker, RAM_GAME_ALIVE_MAPHEAD: b"\x68\x04\x00\x00"}, True),               # running
        ]
        for memory, expected in cases:
            client = DigimonWorldClient()

            async def fake_read(_ctx: Any, requests: list[Any], _m: dict[int, bytes] = memory) -> list[bytes]:
                return [_m[addr] for addr, _size, _dom in requests]

            with mock.patch.object(client_module.bizhawk, "read", fake_read):
                self.assertEqual(_run(client._game_alive(_Ctx())), expected, memory)


class TestNotificationOption(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_on_and_in_slot_data(self) -> None:
        self.assertTrue(self.world.options.in_game_notifications)
        self.assertEqual(self.world.fill_slot_data()["in_game_notifications"], 1)
