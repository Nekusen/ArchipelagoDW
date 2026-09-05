"""Adapter-agnostic DW1 client context.

This module hosts the :class:`CommonContext` subclass and the game
watcher loop that every DW1 client (BizHawk-based or Duckstation-
based) shares. The transport differs per client; everything else
— GUI shell, server protocol handling, slot data, game-watcher cadence
— is identical.

Each client process picks *one* :class:`EmulatorAdapter` at startup
and passes it to :func:`launch`. The context binds it to ``ctx.emu``
(and ``ctx.bizhawk_ctx`` as a source-compat alias for
:mod:`worlds.digimon_world.client`'s legacy call shape) and the
watcher loop never thinks about more than one transport at a time.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Any, Callable

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
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)

logger = logging.getLogger("Client")


# How long the watcher waits per tick for the server to push state
# before forcing a poll. Same value the BizHawk context uses.
WATCHER_TIMEOUT = 0.5

# How long to wait between failed connect attempts. We don't want a
# tight loop slamming the emulator with reconnect attempts if it's not
# up yet.
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
        if ctx.emu is None or not ctx.emu.is_connected():
            ap_logger.info(f"Emulator ({ctx.adapter_label}): not connected")
            return
        ap_logger.info(f"Emulator: connected via {ctx.emu.name}")

    def _cmd_bits(self) -> None:
        """Grant yourself bits (testing aid). Repeat for more."""

        from .client import DEBUG_BITS_GRANT_AMOUNT

        ctx = self.ctx
        assert isinstance(ctx, DigimonWorldClientContext)
        # Commands run on the console/GUI thread, which owns neither the
        # event loop nor the emulator transport. Queue the grant and let
        # the game watcher apply it on its next tick, like every other
        # RAM write in this client.
        ctx.pending_bit_grants += 1
        ap_logger.info(
            f"Queued {DEBUG_BITS_GRANT_AMOUNT} bits "
            f"({ctx.pending_bit_grants} pending); "
            f"applied on the next watcher tick with the game running.",
        )


class DigimonWorldClientContext(CommonContext):
    """:class:`CommonContext` specialised for DW1.

    Owns one :class:`EmulatorAdapter` for the lifetime of the process.
    The handler (the :class:`DigimonWorldClient` class in
    :mod:`.client`) reaches RAM through ``ctx.emu``.
    """

    command_processor = DigimonWorldCommandProcessor

    # The single adapter this process uses. Set at construction time.
    emu: EmulatorAdapter
    # Source-compat alias for :attr:`emu`. Legacy client code calls
    # ``bizhawk.read(ctx.bizhawk_ctx, reads)``; the compat shim in
    # :mod:`.client` forwards that to ``ctx.bizhawk_ctx.read(reads)``,
    # so ``bizhawk_ctx`` just *is* the active adapter.
    bizhawk_ctx: EmulatorAdapter
    # Human-readable label used in log lines and the GUI window
    # title, e.g. ``"BizHawk"`` or ``"Duckstation"``.
    adapter_label: str
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
    # Number of ``/bits`` grants the console has queued and the watcher
    # has not applied yet. Owned by the command processor (producer) and
    # ``DigimonWorldClient._grant_pending_bits`` (consumer).
    pending_bit_grants: int

    def __init__(
        self,
        server_address: str | None,
        password: str | None,
        adapter: EmulatorAdapter,
        adapter_label: str,
    ) -> None:
        super().__init__(server_address, password)
        self.emu = adapter
        self.bizhawk_ctx = adapter
        self.adapter_label = adapter_label
        self.auth_status = AuthStatus.NOT_AUTHENTICATED
        self.password_requested = False
        self.server_seed_name = None
        self.slot_data = None
        self.rom_hash = None
        self.client_handler = None
        self.watcher_timeout = WATCHER_TIMEOUT
        self.pending_bit_grants = 0

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = f"Archipelago Digimon World Client ({self.adapter_label})"
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

        if not self.emu.is_connected():
            ap_logger.info(
                f"Awaiting connection to {self.adapter_label} before authenticating"
            )
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

    Each tick: ensure the adapter is connected, ping it, optionally
    re-validate the ROM, then call the game-specific handler. Lost
    connections are caught and the loop reconnects automatically.
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
        if not ctx.emu.is_connected():
            showed_connected = False

            if not showed_connecting:
                ap_logger.info(f"Waiting for {ctx.adapter_label}...")
                showed_connecting = True

            connect_task = asyncio.create_task(ctx.emu.connect(), name="EmuConnect")
            exit_task = asyncio.create_task(ctx.exit_event.wait(), name="ExitWait")
            await asyncio.wait(
                [connect_task, exit_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if exit_task.done():
                connect_task.cancel()
                return

            if not connect_task.result():
                # Not up yet — sleep briefly, then retry.
                await asyncio.sleep(RECONNECT_DELAY)
                continue

            showed_connecting = False
            ap_logger.info(f"Connected to {ctx.adapter_label}")
            showed_invalid_rom = False

        # ----- Per-tick keep-alive + handler -----------------------------
        try:
            await ctx.emu.ping()

            if not showed_connected:
                showed_connected = True
                ap_logger.info(f"Emulator handshake OK ({ctx.adapter_label})")

            # ROM-hash change detection. The BizHawk adapter implements
            # this; Duckstation returns ``None`` (PINE-style hash isn't
            # exposed). Skipped when the adapter returns ``None``.
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
            # it refuses (wrong game loaded, RAM not initialised yet)
            # we just keep polling — the user may still be at the
            # BIOS splash and will land on a valid save shortly.
            if ctx.client_handler is None:
                ok = await handler.validate_rom(ctx)
                if not ok:
                    if not showed_invalid_rom:
                        ap_logger.info(
                            f"Couldn't validate the running ROM yet. "
                            f"Load the patched Digimon World 1 ISO in "
                            f"{ctx.adapter_label} and boot to the title "
                            f"screen / a save."
                        )
                        showed_invalid_rom = True
                    continue
                showed_invalid_rom = False
                ctx.client_handler = handler
                ap_logger.info("Running handler for Digimon World")

        except RequestFailedError as exc:
            ap_logger.info(f"Lost connection to {ctx.adapter_label}: {exc}")
            try:
                await ctx.emu.disconnect()
            except Exception:
                pass
            continue
        except NotConnectedError:
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
            ap_logger.info(f"Lost connection to {ctx.adapter_label}: {exc}")
            try:
                await ctx.emu.disconnect()
            except Exception:
                pass


def launch(
    adapter_factory: Callable[[], EmulatorAdapter],
    adapter_label: str,
    logging_name: str,
    *launch_args: str,
) -> None:
    """Generic launch entry point used by both DW1 client variants.

    ``adapter_factory`` is a zero-arg callable returning the
    :class:`EmulatorAdapter` to use for this process. The top-level
    launcher shims (:file:`DigimonWorldClient.py` for BizHawk,
    :file:`DigimonWorldClientDuckstation.py` for Duckstation) call
    this with their respective factories.

    ``adapter_label`` is the human-readable name shown in the GUI
    title and log messages (``"BizHawk"``, ``"Duckstation"``).

    ``logging_name`` is what the framework uses for the log file name
    (``"DigimonWorldClient"`` / ``"DigimonWorldClientDuckstation"``).
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

        adapter = adapter_factory()
        ctx = DigimonWorldClientContext(
            args.connect, args.password, adapter, adapter_label,
        )
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

    Utils.init_logging(logging_name, exception_logger="Client")
    import colorama
    colorama.just_fix_windows_console()
    asyncio.run(main())
    colorama.deinit()
