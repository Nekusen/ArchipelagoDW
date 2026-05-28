"""Emulator transport adapters for the Digimon World 1 clients.

DW1 ships two separate clients, one per emulator:

* :class:`BizHawkAdapter` — BizHawk + Nymashock PSX core, via the
  in-tree ``connector_bizhawk_generic.lua`` connector
  (TCP socket on ``127.0.0.1:43055..43059``). Used by the BizHawk
  client, which is what ``Open Patch`` routes to.
* :class:`DuckstationAdapter` — Duckstation, via Win32 process memory
  hooking (the MMLAP / Archipelago.Core mechanism: look up the ``RAM``
  exported symbol from ``duckstation.exe``'s PE export table to find
  the live PSX MainRAM base). Used by the Duckstation client, which
  the user launches from a separate Launcher button.

Both adapters expose the same :class:`EmulatorAdapter` interface so
:mod:`worlds.digimon_world.client` doesn't care which one is in use —
each client process picks an adapter at startup and binds it to
``ctx.emu``.
"""

from .base import (
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)
from .bizhawk_adapter import BizHawkAdapter
from .duckstation_adapter import DuckstationAdapter

__all__ = [
    "BizHawkAdapter",
    "DuckstationAdapter",
    "EmulatorAdapter",
    "NotConnectedError",
    "RequestFailedError",
]
