"""Player options for the Digimon World 1 APWorld.

Phase 1 ships a minimal surface: just a goal choice. Heavier toggles
(starter/recruitment/digivolution randomization, prosperity goal, Drimogemon
fast-dig, etc.) belong in Phase 2 once the location pool that backs them
exists.

DeathLink is intentionally **not** offered yet. Per ``mvp_scope`` (locked
2026-04-27), DeathLink is deferred to v2; DW1 has no automatic respawn so
plumbing it correctly is a Phase 4+ topic.
"""

from dataclasses import dataclass

from Options import Choice, OptionGroup, PerGameCommonOptions


class Goal(Choice):
    """How the seed is completed.

    * ``machinedramon`` — defeat Machinedramon, the canonical DW1 ending.
    * ``prosperity`` — reach a prosperity threshold (matches DWAP's alt goal;
      the threshold itself is a Phase 2 option).
    """

    display_name = "Goal"
    option_machinedramon = 0
    option_prosperity = 1
    default = option_machinedramon


@dataclass
class DigimonWorldOptions(PerGameCommonOptions):
    goal: Goal


option_groups: list[OptionGroup] = [
    OptionGroup("Goal", [Goal]),
]
