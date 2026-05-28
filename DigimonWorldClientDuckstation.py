from __future__ import annotations

import sys
import ModuleUpdate
ModuleUpdate.update()

from worlds.digimon_world.adapters import DuckstationAdapter
from worlds.digimon_world.context import launch

if __name__ == "__main__":
    launch(DuckstationAdapter, "Duckstation", "DigimonWorldClientDuckstation", *sys.argv[1:])
