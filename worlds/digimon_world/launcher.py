"""Launcher Components for the Digimon World 1 client.

Registers two buttons with Archipelago's Launcher:

1. **Digimon World Client** — the unified client (BizHawk + Duckstation
   auto-detect). Claims ``.apdw1`` for "Open Patch".
2. **Digimon World: Patch ROM only** — patches an ``.apdw1`` to a
   playable ISO and exits without starting an AP client. Useful for
   solo testing or for users who want to run the patched ISO on a
   different emulator without going through the multiworld client.
   Reached only from the Launcher's own button list (no ``.apdw1``
   suffix association, so "Open Patch" always routes to the unified
   client).
"""

from __future__ import annotations

import logging
import os

from worlds.LauncherComponents import (
    Component,
    SuffixIdentifier,
    Type,
    components,
    launch as launch_component,
)

logger = logging.getLogger("Client")


def _launch_unified_client(*args: str) -> None:
    """Spawn the unified DW1 client in a subprocess via the Launcher's
    standard helper."""

    from .context import launch
    launch_component(launch, name="DigimonWorldClient", args=args)


def _patch_only(*args: str) -> None:
    """Patch a ``.apdw1`` to a playable ISO without starting a client.

    Either accepts the patch path as a positional arg (from the
    Launcher's CLI dispatch) or opens its own file picker.
    """

    from Utils import messagebox, open_filename
    import Patch

    patch_path = args[0] if args else ""
    if not patch_path:
        try:
            patch_path = open_filename(
                "Select Digimon World 1 patch", (("Digimon World 1 Patch", (".apdw1",)),),
            )
        except Exception as exc:
            messagebox("Error", str(exc), error=True)
            return

    if not patch_path:
        return

    try:
        _metadata, output_file = Patch.create_rom_file(patch_path)
    except Exception as exc:
        logger.exception(exc)
        messagebox("Error Patching Game", str(exc), error=True)
        return

    messagebox(
        "Patched ROM ready",
        f"Patched ISO written to:\n\n{os.path.abspath(output_file)}\n\n"
        "Load it in any PS1 emulator (BizHawk, Duckstation, PCSX-Redux, "
        "real hardware via ODE, etc.). For multiworld play, also start "
        "the Digimon World Client and connect to your server.",
    )


unified_client_component = Component(
    "Digimon World Client",
    "DigimonWorldClient",
    component_type=Type.CLIENT,
    func=_launch_unified_client,
    file_identifier=SuffixIdentifier(".apdw1"),
    description=(
        "Open the unified Digimon World 1 client. Auto-detects whether "
        "BizHawk (Lua connector) or Duckstation (PINE) is running and "
        "uses whichever appears first."
    ),
)

patch_only_component = Component(
    "Digimon World: Patch ROM only",
    component_type=Type.MISC,
    func=_patch_only,
    description=(
        "Apply a Digimon World 1 patch (.apdw1) to your base ISO and "
        "write the patched ISO to disk. Does not start a client — use "
        "this if you want to play offline, test the patcher, or load "
        "the patched ISO in an emulator other than BizHawk/Duckstation."
    ),
)

components.append(unified_client_component)
components.append(patch_only_component)
