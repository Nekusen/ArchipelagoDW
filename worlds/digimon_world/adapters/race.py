"""Connection race for the unified DW1 client.

Tries all available emulator adapters in parallel and returns the
first one to come up. If none are reachable on a given round, the
caller is expected to sleep briefly and re-invoke ``race_connect``
(the canonical retry policy lives in the watcher loop, not here, so
this module stays single-purpose).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from .base import EmulatorAdapter


async def race_connect(
    adapters: Sequence[EmulatorAdapter],
) -> EmulatorAdapter | None:
    """Attempt to connect to every adapter in ``adapters`` in parallel.

    Returns the first adapter whose :meth:`EmulatorAdapter.connect`
    returns ``True``; the other connect tasks are cancelled and any
    that also raced to success are disconnected so we leave them
    available for next time. Returns ``None`` if no adapter connected.
    """

    if not adapters:
        return None

    tasks: dict[asyncio.Task[bool], EmulatorAdapter] = {
        asyncio.create_task(a.connect(), name=f"connect-{a.name}"): a
        for a in adapters
    }

    winner: EmulatorAdapter | None = None
    try:
        while tasks and winner is None:
            done, _ = await asyncio.wait(
                tasks.keys(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                adapter = tasks.pop(task)
                try:
                    if task.result():
                        winner = adapter
                        break
                except Exception:
                    # Adapter raised during connect — treat as a failed
                    # attempt and move on. The adapter is expected to
                    # have already cleaned up its own transport state.
                    continue
    finally:
        # Cancel any still-pending connect attempts. If one of them
        # was about to succeed too, disconnect it so we don't leave a
        # lingering pipe/socket open.
        for task in list(tasks):
            task.cancel()
        # Drain cancellations and clean up late winners.
        for task, adapter in tasks.items():
            try:
                connected = await task
            except (asyncio.CancelledError, Exception):
                connected = False
            if connected and adapter is not winner:
                try:
                    await adapter.disconnect()
                except Exception:
                    pass

    return winner
