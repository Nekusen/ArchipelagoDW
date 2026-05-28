"""Unified DW1 client context.

Replaces the previous ``worlds._bizhawk.context.BizHawkClientContext``
usage with a slimmer :class:`DigimonWorldClientContext` that holds an
:class:`~.adapters.EmulatorAdapter` instead of being hard-wired to
BizHawk's transport. The game watcher loop here is the DW1-specific
adaptation of ``worlds._bizhawk.context._game_watcher`` — same
high-level shape (connect → identify game → call handler), but the
"identify" step delegates to a single :class:`DigimonWorldClient`
instead of BizHawk's pluggable :class:`AutoBizHawkClientRegister`
machinery (we only ever ship one handler for one game).

The watcher races every connection cycle through both adapters and
uses whichever connects first.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Any

from CommonClient import (
    ClientCommandProcessor,
    CommonContext,
    gui_enabled,
    logger as ap_logger,
    server_loop,
    get_base_parser,
)
import Utils

from .adapters import (
    BizHawkAdapter,
    EmulatorAdapter,
    NotConnectedError,
    PineAdapter,
    RequestFailedError,
    race_connect,
)

logger = logging.getLogger("Client")


# How long the watcher waits per tick for the server to push state
# before forcing a poll. Same value the BizHawk context uses.
WATCHER_TIMEOUT = 0.5

# How long to wait between failed connection-race rounds. Two
# disconnected adapters racing in a tight loop would peg the event
# loop, so we sleep briefly between rounds.
RECONNECT_DELAY = 1.0


class AuthStatus(enum.IntEnum):
    NOT_AUTHENTICATED = 0
    NEED_INFO = 1
    PENDING = 2
    AUTHENTICATED = 3


class DigimonWorldCommandProcessor(ClientCommandProcessor):
    def _cmd_emu(self) -> None:
        """Show which emulator the client is currently connected to."""

        ctx = self.ctx
        assert isinstance(ctx, DigimonWorldClientContext)
        if ctx.emu is None:
            ap_logger.info("Emulator: not connected")
            return
        ap_logger.info(f"Emulator: connected via {ctx.emu.name}")


class DigimonWorldClientContext(CommonContext):
    """:class:`CommonContext` specialised for DW1's unified client.

    Owns the active :class:`EmulatorAdapter`. The handler (the
    :class:`DigimonWorldClient` class in :mod:`.client`) reaches RAM
    through ``ctx.emu``; it never imports the BizHawk transport
    directly.
    """

    command_processor = DigimonWorldCommandProcessor

    # Filled in by the watcher loop once an adapter has connected.
    emu: EmulatorAdapter | None
    # Source-compat alias for :attr:`emu`. The legacy client code calls
    # ``bizhawk.read(ctx.bizhawk_ctx, reads)`` etc.; the compat shim in
    # :mod:`.client` forwards that to ``ctx.bizhawk_ctx.read(reads)``,
    # so ``bizhawk_ctx`` simply needs to *be* the active adapter.
    bizhawk_ctx: EmulatorAdapter | None
    # All adapters we'll race on each reconnect cycle.
    available_adapters: list[EmulatorAdapter]
    # AP auth bookkeeping (mirrors the BizHawk context).
    auth_status: AuthStatus
    password_requested: bool
    server_seed_name: str | None
    slot_data: dict[str, Any] | None
    rom_hash: str | None
    # Lazy-initialised on first watcher tick after auth.
    client_handler: Any | None
    # Wired through to the watcher loop.
    watcher_timeout: float

    def __init__(self, server_address: str | None, password: str | None) -> None:
        super().__init__(server_address, password)
        self.emu = None
        self.bizhawk_ctx = None
        self.available_adapters = [BizHawkAdapter(), PineAdapter()]
        self.auth_status = AuthStatus.NOT_AUTHENTICATED
        self.password_requested = False
        self.server_seed_name = None
        self.slot_data = None
        self.rom_hash = None
        self.client_handler = None
        self.watcher_timeout = WATCHER_TIMEOUT

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Digimon World Client"
        return ui

    def on_package(self, cmd: str, args: dict) -> None:
        if cmd == "Connected":
            self.slot_data = args.get("slot_data", None)
            self.auth_status = AuthStatus.AUTHENTICATED
        elif cmd == "RoomInfo":
            self.server_seed_name = args.get("seed_name", None)

        if self.client_handler is not None:
            self.client_handler.on_package(self, cmd, args)

    async def server_auth(self, password_requested: bool = False) -> None:
        self.password_requested = password_requested

        if self.emu is None or not self.emu.is_connected():
            ap_logger.info("Awaiting connection to an emulator before authenticating")
            return

        if self.client_handler is None:
            return

        if self.auth is None:
            self.auth_status = AuthStatus.NEED_INFO
            await self.client_handler.set_auth(self)
            if self.auth is None:
                await self.get_username()

        if password_requested and not self.password:
            self.auth_status = AuthStatus.NEED_INFO
            await super().server_auth(password_requested)

        await self.send_connect()
        self.auth_status = AuthStatus.PENDING

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        self.auth_status = AuthStatus.NOT_AUTHENTICATED
        self.server_seed_name = None
        await super().disconnect(allow_autoreconnect)


async def _game_watcher(ctx: DigimonWorldClientContext) -> None:
    """Connect → validate ROM → poll game state, on a loop.

    The loop is structurally close to
    :func:`worlds._bizhawk.context._game_watcher` but delegates to
    :class:`EmulatorAdapter` for transport and to a single
    :class:`DigimonWorldClient` instance for game-specific work.
    """

    from .client import DigimonWorldClient

    handler = DigimonWorldClient()

    showed_connecting = False
    showed_connected = False
    showed_invalid_rom = False

    while not ctx.exit_event.is_set():
        try:
            await asyncio.wait_for(ctx.watcher_event.wait(), ctx.watcher_timeout)
        except asyncio.TimeoutError:
            pass
        ctx.watcher_event.clear()

        # ----- Connection phase -----------------------------------------
        if ctx.emu is None or not ctx.emu.is_connected():
            ctx.emu = None
            ctx.bizhawk_ctx = None
            showed_connected = False

            if not showed_connecting:
                ap_logger.info("Waiting for BizHawk or Duckstation...")
                showed_connecting = True

            # Race both adapters concurrently with an interruptible
            # exit-event wait, so closing the client doesn't have to
            # block on a connect timeout.
            race_task = asyncio.create_task(
                race_connect(ctx.available_adapters), name="RaceConnect",
            )
            exit_task = asyncio.create_task(ctx.exit_event.wait(), name="ExitWait")
            await asyncio.wait(
                [race_task, exit_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if exit_task.done():
                race_task.cancel()
                return

            winner = await race_task
            if winner is None:
                # Nobody answered — sleep briefly, then retry.
                await asyncio.sleep(RECONNECT_DELAY)
                continue

            ctx.emu = winner
            ctx.bizhawk_ctx = winner
            showed_connecting = False
            ap_logger.info(f"Connected via {ctx.emu.name}")
            showed_invalid_rom = False

        # ----- Per-tick keep-alive + handler -----------------------------
        try:
            await ctx.emu.ping()

            if not showed_connected:
                showed_connected = True
                ap_logger.info(f"Emulator handshake OK ({ctx.emu.name})")

            # ROM-hash change detection (BizHawk only — Duckstation has
            # no PINE hash command). The check is skipped when the
            # adapter returns ``None``.
            rom_hash = await ctx.emu.get_hash()
            if rom_hash is not None:
                if ctx.rom_hash is not None and ctx.rom_hash != rom_hash:
                    if ctx.server is not None and not ctx.server.socket.closed:
                        ap_logger.info("ROM changed. Disconnecting from server.")
                    ctx.auth = None
                    ctx.username = None
                    ctx.client_handler = None
                    ctx.finished_game = False
                    await ctx.disconnect(False)
                ctx.rom_hash = rom_hash

            # validate_rom claims the connection on first contact. If
            # it refuses (e.g. wrong game loaded, RAM not initialised
            # yet) we just keep polling — the user may still be at the
            # BIOS splash and will land on a valid save shortly.
            if ctx.client_handler is None:
                ok = await handler.validate_rom(ctx)
                if not ok:
                    if not showed_invalid_rom:
                        ap_logger.info(
                            "Couldn't validate the running ROM yet. "
                            "Load the patched Digimon World 1 ISO and "
                            "boot to the title screen / a save."
                        )
                        showed_invalid_rom = True
                    continue
                showed_invalid_rom = False
                ctx.client_handler = handler
                ap_logger.info("Running handler for Digimon World")

        except RequestFailedError as exc:
            ap_logger.info(f"Lost connection to {ctx.emu.name}: {exc}")
            try:
                await ctx.emu.disconnect()
            except Exception:
                pass
            ctx.emu = None
            ctx.bizhawk_ctx = None
            continue
        except NotConnectedError:
            ctx.emu = None
            continue

        # Server auth
        if ctx.server is not None and not ctx.server.socket.closed:
            if ctx.auth_status == AuthStatus.NOT_AUTHENTICATED:
                Utils.async_start(ctx.server_auth(ctx.password_requested))
        else:
            ctx.auth_status = AuthStatus.NOT_AUTHENTICATED

        # Game-specific tick.
        try:
            await ctx.client_handler.game_watcher(ctx)
        except RequestFailedError as exc:
            ap_logger.info(f"Lost connection to {ctx.emu.name}: {exc}")
            try:
                await ctx.emu.disconnect()
            except Exception:
                pass
            ctx.emu = None


def launch(*launch_args: str) -> None:
    """Entry point used by :mod:`worlds.digimon_world.launcher`.

    Mirrors ``worlds._bizhawk.context.launch`` so the existing patch
    flow (Open Patch → patch ROM → start client) keeps working with
    the same call-shape the Launcher already uses.
    """

    import Patch

    async def main() -> None:
        parser = get_base_parser()
        parser.add_argument(
            "patch_file", default="", type=str, nargs="?",
            help="Path to an Archipelago patch file",
        )
        args = parser.parse_args(launch_args)

        if args.patch_file:
            try:
                metadata, _ = Patch.create_rom_file(args.patch_file)
                if "server" in metadata:
                    args.connect = metadata["server"]
            except Exception as exc:
                logger.exception(exc)
                Utils.messagebox("Error Patching Game", str(exc), True)

        ctx = DigimonWorldClientContext(args.connect, args.password)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        watcher_task = asyncio.create_task(_game_watcher(ctx), name="GameWatcher")
        try:
            await watcher_task
        except Exception as exc:
            logger.exception(exc)

        await ctx.exit_event.wait()
        await ctx.shutdown()

    Utils.init_logging("DigimonWorldClient", exception_logger="Client")
    import colorama
    colorama.just_fix_windows_console()
    asyncio.run(main())
    colorama.deinit()
