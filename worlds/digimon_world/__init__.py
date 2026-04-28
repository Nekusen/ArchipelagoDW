"""Digimon World 1 (PS1, SLUS-01032) Archipelago world package.

Importing this module:

* triggers :class:`AutoWorldRegister` registration of
  :class:`DigimonWorldWorld` under ``game = "Digimon World"``;
* registers :class:`worlds.digimon_world.rom.DigimonWorldPatchExtension`
  with :class:`AutoPatchExtensionRegister`, plus declares
  ``.apdw1`` as the patch file ending;
* registers :class:`worlds.digimon_world.client.DigimonWorldClient` with
  :class:`worlds._bizhawk.client.AutoBizHawkClientRegister`, which also
  appends ``.apdw1`` to the in-tree BizHawk Client component's
  :class:`SuffixIdentifier`. The Launcher therefore opens any
  ``.apdw1`` via the BizHawk Client component automatically; the world
  package does **not** register a separate Component.

See :mod:`.world` for the actual class and :doc:`/PLAN.md` for the
phased plan. The address manifest at :mod:`.data.addresses` is consumed
by :mod:`.rom` (Phase 3) and :mod:`.client` (Phase 4).
"""

from . import client as client
from . import rom as rom
from .world import DigimonWorldWorld as DigimonWorldWorld
