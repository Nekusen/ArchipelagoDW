"""Duckstation transport adapter (PINE IPC).

Sits on top of :mod:`pine_protocol`. The ``domain`` argument is
accepted for source compatibility with the BizHawk adapter but only
``"MainRAM"`` is valid — Duckstation's PINE exposes a single flat
PSX physical RAM space at the bare addresses we already store in
:mod:`worlds.digimon_world.data.addresses`.
"""

from __future__ import annotations

from collections.abc import Sequence

from .base import (
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)
from .pine_protocol import PineClient, PineError, default_pipe_path

# Mirror of BizHawk's domain name for PSX main RAM. The PINE protocol
# has no concept of a "domain"; we accept the string for source
# compatibility but only treat ``MainRAM`` as valid.
_MAIN_RAM = "MainRAM"


class PineAdapter(EmulatorAdapter):
    name = "duckstation"

    def __init__(self, pipe_path: str | None = None) -> None:
        self._client = PineClient(pipe_path=pipe_path or default_pipe_path())

    @property
    def pipe_path(self) -> str:
        return self._client.pipe_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not await self._client.connect():
            return False
        # Validate that the peer actually speaks PINE — opening the pipe
        # alone isn't enough (something else could be listening). A
        # round-trip Status request confirms it.
        try:
            await self._client.status()
        except PineError:
            await self._client.close()
            return False
        return True

    async def disconnect(self) -> None:
        await self._client.close()

    def is_connected(self) -> bool:
        return self._client.connected

    # ------------------------------------------------------------------
    # Per-frame requests
    # ------------------------------------------------------------------

    async def ping(self) -> None:
        if not self._client.connected:
            raise NotConnectedError("Duckstation PINE client is not connected")
        try:
            await self._client.status()
        except PineError as exc:
            raise RequestFailedError(str(exc)) from exc

    async def read(
        self,
        reads: Sequence[tuple[int, int, str]],
    ) -> list[bytes]:
        if not self._client.connected:
            raise NotConnectedError("Duckstation PINE client is not connected")

        results: list[bytes] = []
        try:
            for addr, size, domain in reads:
                _ensure_main_ram(domain)
                results.append(await self._client.read_bytes(addr, size))
        except PineError as exc:
            raise RequestFailedError(str(exc)) from exc
        return results

    async def write(
        self,
        writes: Sequence[tuple[int, Sequence[int], str]],
    ) -> None:
        if not self._client.connected:
            raise NotConnectedError("Duckstation PINE client is not connected")

        try:
            for addr, value, domain in writes:
                _ensure_main_ram(domain)
                await self._client.write_bytes(addr, value)
        except PineError as exc:
            raise RequestFailedError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def get_system(self) -> str:
        # Duckstation is PSX-only; synthesise the BizHawk-style label
        # so the client's "PSX" check passes uniformly.
        return "PSX"

    async def get_hash(self) -> str | None:
        # PINE has no exposed ROM-hash command for Duckstation. The
        # client treats None as "skip the hash check".
        return None


def _ensure_main_ram(domain: str) -> None:
    if domain != _MAIN_RAM:
        raise RequestFailedError(
            f"PineAdapter only supports the {_MAIN_RAM!r} domain; got {domain!r}"
        )
