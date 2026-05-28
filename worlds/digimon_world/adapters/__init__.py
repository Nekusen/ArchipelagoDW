"""Emulator transport adapters for the Digimon World 1 client.

The DW1 client supports two emulators with a single code path:

* :class:`BizHawkAdapter` — BizHawk + Nymashock PSX core, via the
  in-tree ``connector_bizhawk_generic.lua`` connector
  (TCP socket on ``127.0.0.1:43055..43059``).
* :class:`PineAdapter` — Duckstation, via the PINE IPC protocol
  (named pipe on Windows, Unix socket elsewhere).

Both adapters expose the same :class:`EmulatorAdapter` interface so
:mod:`worlds.digimon_world.client` doesn't care which one is in use.
:func:`race_connect` brings up whichever emulator the user fires up
first.
"""

from .base import (
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)
from .bizhawk_adapter import BizHawkAdapter
from .pine_adapter import PineAdapter
from .race import race_connect

__all__ = [
    "BizHawkAdapter",
    "EmulatorAdapter",
    "NotConnectedError",
    "PineAdapter",
    "RequestFailedError",
    "race_connect",
]
