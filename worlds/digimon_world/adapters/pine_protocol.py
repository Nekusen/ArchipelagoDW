"""Minimal PINE (Protocol for Instrumentation of Emulators) client.

PINE is the IPC protocol shared by PCSX2, RPCS3, and Duckstation. Wire
format and command set are documented at
https://github.com/PCSX2/pcsx2/blob/master/pcsx2/PINE/README.md.

Transport
---------

* **Windows**: named pipe at ``\\.\\pipe\\<slot_name>``. Duckstation's
  default ``slot_name`` is ``duckstation``.
* **Unix-likes**: filesystem socket under ``$XDG_RUNTIME_DIR`` (or
  ``/tmp`` if unset) named ``<slot_name>.sock.<slot_number>``.

Each PINE process uses exactly one slot — Duckstation has no
multi-instance support over PINE by default, so we don't try to
discover multiple slots.

Wire format
-----------

Every request and response is framed as::

    [u32_le total_length] [u8 opcode_or_status] [body...]

``total_length`` is the size in bytes of *the whole packet*, including
the 4 bytes of length itself. Multiple commands may be batched in one
packet by concatenating ``[opcode][body]`` tuples after the single
length header; the response packet then concatenates each command's
``[status][result]`` in the same order.

Status byte: ``0x00`` = OK, ``0xFF`` = FAIL.

This module only implements the opcodes the DW1 client needs: byte
reads and writes. Word-sized reads/writes are absent on purpose —
batching N ``Read8`` ops is what BizHawk's connector does internally
too, and the protocol overhead is fine for our ~100 ms tick budget.
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
from collections.abc import Sequence

# Default Duckstation slot identifier (same as the emulator's compiled
# default). Configurable via the ``DUCKSTATION_PINE_SLOT`` env var if
# the user has multiple emulators running.
DEFAULT_SLOT_NAME = "duckstation"
DEFAULT_SLOT_NUMBER = 28011

# Opcodes we actually use. Names match the PCSX2 source.
OPCODE_READ8 = 0x00
OPCODE_WRITE8 = 0x04
OPCODE_STATUS = 0x0F  # returns u32_le emulator status; used for ping

# Status codes.
STATUS_OK = 0x00
STATUS_FAIL = 0xFF


class PineError(Exception):
    """PINE protocol or transport error."""


def default_pipe_path() -> str:
    """Return the OS-appropriate default PINE endpoint for Duckstation.

    The user may override this via the ``DUCKSTATION_PINE_PATH`` env
    var. Otherwise we follow the documented defaults.
    """

    override = os.environ.get("DUCKSTATION_PINE_PATH")
    if override:
        return override

    slot = os.environ.get("DUCKSTATION_PINE_SLOT", DEFAULT_SLOT_NAME)

    if sys.platform == "win32":
        return rf"\\.\pipe\{slot}"

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(runtime_dir, f"{slot}.sock.{DEFAULT_SLOT_NUMBER}")


def _build_read8_batch(addresses: Sequence[int]) -> bytes:
    """Build a batched ``Read8`` request packet for ``addresses``."""

    # Body: per command, [u8 opcode][u32_le addr] = 5 bytes
    body = bytearray()
    for addr in addresses:
        body.append(OPCODE_READ8)
        body += struct.pack("<I", addr & 0xFFFFFFFF)
    total = 4 + len(body)
    return struct.pack("<I", total) + bytes(body)


def _build_write8_batch(writes: Sequence[tuple[int, int]]) -> bytes:
    """Build a batched ``Write8`` request packet.

    ``writes`` is a sequence of ``(addr, value)`` tuples; ``value`` is
    masked to 0..255.
    """

    # Body: per command, [u8 opcode][u32_le addr][u8 value] = 6 bytes
    body = bytearray()
    for addr, value in writes:
        body.append(OPCODE_WRITE8)
        body += struct.pack("<I", addr & 0xFFFFFFFF)
        body.append(value & 0xFF)
    total = 4 + len(body)
    return struct.pack("<I", total) + bytes(body)


def _parse_read8_responses(packet: bytes, count: int) -> list[int]:
    """Parse the response to a ``Read8`` batch into a list of bytes.

    Each command response is ``[u8 status][u8 value]`` (value omitted
    on fail). The leading u32 length has already been stripped.
    """

    out: list[int] = []
    pos = 0
    for _ in range(count):
        if pos + 1 > len(packet):
            raise PineError("PINE Read8 response truncated")
        status = packet[pos]
        pos += 1
        if status == STATUS_FAIL:
            raise PineError("PINE Read8 returned FAIL")
        if status != STATUS_OK:
            raise PineError(f"PINE Read8 returned unknown status 0x{status:02X}")
        if pos + 1 > len(packet):
            raise PineError("PINE Read8 response payload truncated")
        out.append(packet[pos])
        pos += 1
    return out


def _parse_write8_responses(packet: bytes, count: int) -> None:
    """Parse the response to a ``Write8`` batch. Raises on FAIL."""

    pos = 0
    for _ in range(count):
        if pos + 1 > len(packet):
            raise PineError("PINE Write8 response truncated")
        status = packet[pos]
        pos += 1
        if status == STATUS_FAIL:
            raise PineError("PINE Write8 returned FAIL")
        if status != STATUS_OK:
            raise PineError(f"PINE Write8 returned unknown status 0x{status:02X}")


class PineClient:
    """Async PINE client speaking the wire format above.

    Maintains a single underlying transport (a named pipe on Windows
    or a Unix socket elsewhere) and serialises requests behind a
    :class:`asyncio.Lock` so concurrent ``read`` / ``write`` calls
    from the watcher loop don't interleave frames.
    """

    # Soft cap on how many byte requests we'll pack into one packet.
    # PINE itself doesn't impose a limit, but Duckstation's response
    # buffer is sized around 64 KB. 4000 Read8 responses = 8000 bytes
    # response which is comfortably below.
    MAX_BATCH = 4000

    def __init__(self, pipe_path: str | None = None) -> None:
        self.pipe_path = pipe_path or default_pipe_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return (
            self._reader is not None
            and self._writer is not None
            and not self._writer.is_closing()
        )

    async def connect(self) -> bool:
        """Try to open the PINE endpoint. Returns False on any failure."""

        if self.connected:
            return True

        try:
            if sys.platform == "win32":
                self._reader, self._writer = await _open_windows_pipe(self.pipe_path)
            else:
                self._reader, self._writer = await asyncio.open_unix_connection(self.pipe_path)
            return True
        except (FileNotFoundError, ConnectionRefusedError, OSError, asyncio.TimeoutError):
            self._reader = None
            self._writer = None
            return False

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                # Drain any pending write before returning. The wait_closed
                # call can hang if the peer has already vanished, so we
                # apply a short timeout.
                try:
                    await asyncio.wait_for(self._writer.wait_closed(), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
            finally:
                self._writer = None
                self._reader = None

    async def _send_and_receive(self, packet: bytes) -> bytes:
        """Send one PINE packet and read back one response packet.

        Holds ``self._lock`` for the full round trip so concurrent
        callers don't interleave their frames.
        """

        async with self._lock:
            if not self.connected:
                raise PineError("PINE transport not connected")
            assert self._writer is not None and self._reader is not None
            try:
                self._writer.write(packet)
                await asyncio.wait_for(self._writer.drain(), timeout=5.0)
                # Length header is 4 bytes, little-endian, and includes
                # itself, so we read 4 bytes first and then ``total - 4``.
                header = await asyncio.wait_for(self._reader.readexactly(4), timeout=5.0)
                (total,) = struct.unpack("<I", header)
                if total < 4:
                    raise PineError(f"PINE response declares invalid length {total}")
                body = await asyncio.wait_for(
                    self._reader.readexactly(total - 4), timeout=5.0,
                )
                return body
            except (asyncio.IncompleteReadError, asyncio.TimeoutError,
                    ConnectionResetError, BrokenPipeError, OSError) as exc:
                await self.close()
                raise PineError(f"PINE transport failure: {exc}") from exc

    async def read_bytes(self, addr: int, size: int) -> bytes:
        """Read ``size`` consecutive bytes starting at ``addr``.

        For batches larger than :attr:`MAX_BATCH` the request is split
        into multiple round trips.
        """

        if size <= 0:
            return b""

        out = bytearray()
        for chunk_start in range(0, size, self.MAX_BATCH):
            chunk_size = min(self.MAX_BATCH, size - chunk_start)
            addrs = range(addr + chunk_start, addr + chunk_start + chunk_size)
            packet = _build_read8_batch(addrs)
            body = await self._send_and_receive(packet)
            values = _parse_read8_responses(body, chunk_size)
            out.extend(values)
        return bytes(out)

    async def write_bytes(self, addr: int, data: Sequence[int]) -> None:
        """Write ``data`` (sequence of bytes, 0..255) starting at ``addr``."""

        data = bytes(b & 0xFF for b in data)
        if not data:
            return

        for chunk_start in range(0, len(data), self.MAX_BATCH):
            chunk = data[chunk_start:chunk_start + self.MAX_BATCH]
            writes = [
                (addr + chunk_start + i, b)
                for i, b in enumerate(chunk)
            ]
            packet = _build_write8_batch(writes)
            body = await self._send_and_receive(packet)
            _parse_write8_responses(body, len(writes))

    async def status(self) -> int:
        """Send a Status command. Returns the emulator's status code.

        Used as a cheap keep-alive ping — a healthy emulator responds
        immediately with a 4-byte status code; a dead pipe raises.
        """

        # Status request: just the opcode, no args. total = 4 + 1 = 5.
        packet = struct.pack("<I", 5) + bytes([OPCODE_STATUS])
        body = await self._send_and_receive(packet)
        if len(body) < 5:
            raise PineError("PINE Status response too short")
        if body[0] == STATUS_FAIL:
            raise PineError("PINE Status returned FAIL")
        if body[0] != STATUS_OK:
            raise PineError(f"PINE Status returned unknown status 0x{body[0]:02X}")
        (value,) = struct.unpack("<I", body[1:5])
        return value


async def _open_windows_pipe(
    path: str,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a Windows named pipe and wrap it as asyncio streams.

    Python's stdlib ``asyncio.open_unix_connection`` has no Windows
    equivalent, and the ProactorEventLoop's named-pipe support is
    callback-based (not stream-based). We bridge the gap by opening
    the pipe synchronously via :func:`os.open` and wrapping the
    resulting fd in a :class:`asyncio.StreamReader` / ``StreamWriter``
    pair via the Proactor event loop's ``loop.create_pipe_connection``
    helper.

    On failure, the underlying OSError propagates.
    """

    # Defer the import: ``asyncio.windows_events`` is Windows-only.
    from asyncio import streams  # type: ignore[attr-defined]
    import asyncio.windows_events  # noqa: F401  (registers Proactor support)

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(loop=loop)
    protocol = streams.StreamReaderProtocol(reader, loop=loop)
    # Proactor exposes ``create_pipe_connection`` for named pipes;
    # on SelectorEventLoop (older default) it raises NotImplementedError.
    transport, _ = await loop.create_pipe_connection(  # type: ignore[attr-defined]
        lambda: protocol, path,
    )
    writer = streams.StreamWriter(transport, protocol, reader, loop)
    return reader, writer
