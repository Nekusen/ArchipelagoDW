"""Abstract :class:`EmulatorAdapter` interface and shared exceptions.

The interface is intentionally minimal: only what
:mod:`worlds.digimon_world.client` actually uses (``read``, ``write``,
``ping``, plus connect/disconnect lifecycle and a couple of validation
helpers). BizHawk's full surface (guarded reads/writes, locks,
display_message, etc.) is deliberately *not* mirrored here — DW1
doesn't use those features, and adding them would force the
:class:`PineAdapter` to emulate semantics PINE doesn't natively
provide.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence


class NotConnectedError(Exception):
    """Raised when an emulator request is issued before connecting."""


class RequestFailedError(Exception):
    """Raised when the underlying transport fails mid-request.

    The semantics mirror :class:`worlds._bizhawk.RequestFailedError`
    (transient — caller is expected to handle and let the connection
    loop reconnect on the next tick).
    """


class EmulatorAdapter(abc.ABC):
    """Common transport interface for BizHawk and Duckstation."""

    #: Human-readable adapter name (``"bizhawk"`` / ``"duckstation"``).
    #: Used in log lines and the client's status messages.
    name: str = "emulator"

    @abc.abstractmethod
    async def connect(self) -> bool:
        """Try to establish a connection.

        Must return ``True`` on success, ``False`` if the emulator
        wasn't reachable (no exception — non-fatal, just "not up yet").
        Network/IO exceptions should be caught and converted to
        ``False`` as well.
        """

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection. Idempotent."""

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` if the transport currently looks healthy."""

    @abc.abstractmethod
    async def ping(self) -> None:
        """Keep-alive request.

        Must raise :class:`RequestFailedError` if the transport is
        dead. Used by the watcher loop to notice a closed pipe / socket
        and trigger a reconnect.
        """

    @abc.abstractmethod
    async def read(
        self,
        reads: Sequence[tuple[int, int, str]],
    ) -> list[bytes]:
        """Read 1+ contiguous ranges from emulator memory.

        Each request is ``(address, size, domain)``. ``domain`` is the
        legacy BizHawk domain name; the only domain DW1 uses is
        ``"MainRAM"`` (the PSX physical RAM). Adapters MAY reject
        other domains.

        Returns one ``bytes`` per request, in the order requested.
        """

    @abc.abstractmethod
    async def write(
        self,
        writes: Sequence[tuple[int, Sequence[int], str]],
    ) -> None:
        """Write 1+ byte ranges to emulator memory.

        Each request is ``(address, value, domain)``. ``value`` is an
        iterable of byte values (0..255), in the order they should
        appear starting at ``address``.
        """

    @abc.abstractmethod
    async def get_system(self) -> str:
        """Return the running emulator's system identifier.

        BizHawk returns its in-tree system name (e.g. ``"PSX"``). The
        PINE adapter has no analogue and synthesises ``"PSX"`` if the
        connection is established (Duckstation is PSX-only).
        """

    async def get_hash(self) -> str | None:
        """Return the loaded ROM's hash, if the transport supports it.

        BizHawk implements this; PINE does not, so the default is
        ``None``. The client treats ``None`` as "skip the hash check".
        """

        return None
