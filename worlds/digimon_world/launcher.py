"""Launcher Components for the Digimon World 1 clients.

Three Launcher buttons:

1. **Digimon World Client (BizHawk)** — the BizHawk-based client.
   Type.CLIENT, claims ``.apdw1`` for "Open Patch", uses the in-tree
   Lua connector.
2. **Digimon World Client (Duckstation)** — the Duckstation-based
   client. Type.CLIENT, but with NO suffix association so "Open
   Patch" never routes here — the user launches this manually from
   the Launcher's button list and points it at a DuckStation that's
   already running the patched ISO.
3. **Digimon World: Patch ROM only** — patches an ``.apdw1`` to a
   playable ISO and exits without starting any AP client. Type.MISC.
   Useful for solo testing or for running the patched ISO on
   emulators outside the two supported clients.
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


# ---------------------------------------------------------------------------
# Component launchers
# ---------------------------------------------------------------------------


def _launch_bizhawk_client(*args: str) -> None:
    """Spawn the BizHawk-based DW1 client."""

    from .context import launch
    from .adapters import BizHawkAdapter

    launch_component(
        launch,
        name="DigimonWorldClient",
        args=(BizHawkAdapter, "BizHawk", "DigimonWorldClient", *args),
    )


def _launch_duckstation_client(*args: str) -> None:
    """Spawn the Duckstation-based DW1 client."""

    from .context import launch
    from .adapters import DuckstationAdapter

    launch_component(
        launch,
        name="DigimonWorldClientDuckstation",
        args=(DuckstationAdapter, "Duckstation", "DigimonWorldClientDuckstation", *args),
    )


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
        "the matching Digimon World Client and connect to your server.",
    )


# ---------------------------------------------------------------------------
# Component registrations
# ---------------------------------------------------------------------------


bizhawk_client_component = Component(
    "Digimon World Client (BizHawk)",
    "DigimonWorldClient",
    component_type=Type.CLIENT,
    func=_launch_bizhawk_client,
    file_identifier=SuffixIdentifier(".apdw1"),
    description=(
        "Open the Digimon World 1 client backed by BizHawk + the "
        "in-tree Lua connector. This is the default — Open Patch on "
        "any .apdw1 routes here."
    ),
)

duckstation_client_component = Component(
    "Digimon World Client (Duckstation)",
    "DigimonWorldClientDuckstation",
    component_type=Type.CLIENT,
    func=_launch_duckstation_client,
    # No file_identifier on purpose: Open Patch picks the first
    # component whose SuffixIdentifier claims .apdw1 (first-match
    # wins), so leaving this empty keeps the BizHawk client as the
    # default Open Patch target. Duckstation users launch this
    # button manually.
    description=(
        "Open the Digimon World 1 client backed by Duckstation via "
        "process memory hooking. Launch this AFTER you have started "
        "Duckstation and loaded the patched ISO. Patch the ISO first "
        "via Open Patch or the 'Patch ROM only' button."
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

components.append(bizhawk_client_component)
components.append(duckstation_client_component)
components.append(patch_only_component)
