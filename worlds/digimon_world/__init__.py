"""Digimon World 1 (PS1, SLUS-01032) Archipelago world package.

Importing this module:

* triggers :class:`AutoWorldRegister` registration of
  :class:`DigimonWorldWorld` under ``game = "Digimon World"``;
* registers :class:`worlds.digimon_world.rom.DigimonWorldPatchExtension`
  with :class:`AutoPatchExtensionRegister`, plus declares
  ``.apdw1`` as the patch file ending;
* registers two Launcher Components for ``.apdw1`` via
  :mod:`.launcher` — the unified DW1 client (auto-detects BizHawk or
  Duckstation) and a "Patch ROM only" button for users who want a
  randomised ISO without starting the multiworld client.

See :mod:`.world` for the actual class and :doc:`/PLAN.md` for the
phased plan. The address manifest at :mod:`.data.addresses` is consumed
by :mod:`.rom` (Phase 3) and :mod:`.client` (Phase 4).
"""

from . import launcher as launcher  # noqa: F401 — Component registration side-effect
from . import rom as rom
from .world import DigimonWorldWorld as DigimonWorldWorld
