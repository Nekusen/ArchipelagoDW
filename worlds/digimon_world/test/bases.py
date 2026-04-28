"""Shared :class:`WorldTestBase` subclass for the Digimon World 1 APWorld.

All world-local tests should inherit from :class:`DigimonWorldTestBase`
(directly or transitively). The base wires the test harness to our
``game = "Digimon World"`` registration so the generic test infrastructure
in :mod:`test.bases` and :mod:`test.general` runs against this world.
"""

from test.bases import WorldTestBase

from ..world import DigimonWorldWorld


class DigimonWorldTestBase(WorldTestBase):
    game = "Digimon World"
    world: DigimonWorldWorld
