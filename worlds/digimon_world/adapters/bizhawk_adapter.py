"""BizHawk transport adapter.

Thin wrapper around :mod:`worlds._bizhawk`'s socket transport. We
reuse the in-tree connector and its proven JSON-RPC handshake; this
adapter just renames the entry points to fit the
:class:`EmulatorAdapter` shape and converts BizHawk's exception
classes to ours.
"""

from __future__ import annotations

from collections.abc import Sequence

import worlds._bizhawk as bizhawk

from .base import (
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)


class BizHawkAdapter(EmulatorAdapter):
    name = "bizhawk"

    def __init__(self) -> None:
        self._ctx = bizhawk.BizHawkContext()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        try:
            return await bizhawk.connect(self._ctx)
        except Exception:
            return False

    async def disconnect(self) -> None:
        bizhawk.disconnect(self._ctx)

    def is_connected(self) -> bool:
        return self._ctx.connection_status == bizhawk.ConnectionStatus.CONNECTED

    # ------------------------------------------------------------------
    # Per-frame requests
    # ------------------------------------------------------------------

    async def ping(self) -> None:
        try:
            await bizhawk.ping(self._ctx)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc

    async def read(
        self,
        reads: Sequence[tuple[int, int, str]],
    ) -> list[bytes]:
        try:
            return await bizhawk.read(self._ctx, reads)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc

    async def write(
        self,
        writes: Sequence[tuple[int, Sequence[int], str]],
    ) -> None:
        try:
            await bizhawk.write(self._ctx, writes)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def get_system(self) -> str:
        try:
            return await bizhawk.get_system(self._ctx)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc

    async def get_hash(self) -> str | None:
        try:
            return await bizhawk.get_hash(self._ctx)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc

    async def get_script_version(self) -> int:
        """BizHawk-specific. Used at connect time to refuse a
        mismatched Lua connector version."""

        try:
            return await bizhawk.get_script_version(self._ctx)
        except bizhawk.NotConnectedError as exc:
            raise NotConnectedError(str(exc)) from exc
        except bizhawk.RequestFailedError as exc:
            raise RequestFailedError(str(exc)) from exc
