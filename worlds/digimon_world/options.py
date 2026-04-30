"""Player options for the Digimon World 1 APWorld.

Phase 5 polish surface. Heavier randomization toggles (recruit shuffle,
prosperity goal threshold, digivolution shuffle) are still pending; what
ships here are pure quality-of-life tweaks that don't change AP item
placement, plus the existing goal choice.

DeathLink is intentionally **not** offered yet. Per ``mvp_scope`` (locked
2026-04-27), DeathLink is deferred to v2; DW1 has no automatic respawn so
plumbing it correctly is a Phase 4+ topic.
"""

from dataclasses import dataclass

from Options import Choice, DefaultOnToggle, OptionGroup, PerGameCommonOptions, Range


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


class FastDrimogemon(DefaultOnToggle):
    """Skip Drimogemon's 10-day dig wait.

    Once the player beats Drimogemon, the client immediately marks the
    Lava Cave tunnel as already dug and the dig pile as empty. The
    player can walk straight through instead of waiting in-game days.
    """

    display_name = "Fast Drimogemon"


class EasyMonochromon(DefaultOnToggle):
    """Auto-win the Monochromon meat-trade minigame.

    The minigame requires earning enough profit selling meat over
    several in-game days. With this on, the client writes the maximum
    profit value (4000) any time the player is on the Monochromon
    business map (id 49), so the trade resolves immediately.
    """

    display_name = "Easy Monochromon"


class SkipIntro(DefaultOnToggle):
    """Skip most of the Jijimon intro dialogue.

    Replaces two textbox sequences with ``jumpTo`` opcodes that
    fast-forward to the end of each intro stage. The player still sees
    the title card and partner-pick prompt; the long expository
    dialogue in between is bypassed. Patcher-side, applied at
    generation time.
    """

    display_name = "Skip Intro"


class TypeLockUnlocks(DefaultOnToggle):
    """Remove the Vaccine/Data/Virus/Monzaemon type gates on Greylord's
    Mansion, Ice Sanctuary, and Toy Town.

    Vanilla DW1 blocks these areas unless the player's partner Digimon
    is the right type. With this on, anyone can enter regardless of
    type. Patcher-side bytecode rewrite.

    **TODO (logic):** when this option is on, the AP rules currently
    don't account for early access to these regions. The full logic
    rework that accompanies recruit randomization should also branch
    on this option — see ``rules.py`` for the gating points.
    """

    display_name = "Type-Lock Unlocks"


class StatGainMultiplier(Range):
    """Multiply training stat-gain by this value (1 = vanilla rate).

    Mirrors DWAP's "Exp Multiplier" QoL option. The client writes the
    DW1 stat-gain multiplier at RAM ``0x001384AE`` to ``value * 10``
    each tick, and unlocks the stat cap so the boosted gain isn't
    immediately clamped. Helpful for testing and for shorter playthroughs.

    Default 1 (vanilla rate). Set to 5-10 for noticeably faster
    training. Values around 100 effectively skip training entirely —
    a single session caps the stat (which is then clamped to 9999 by
    the unlocked cap). Useful for testing recruitment/progression
    without grinding.
    """

    display_name = "Stat Gain Multiplier"
    range_start = 1
    range_end = 100
    default = 1


class SpawnRateBoost(Range):
    """Encounter percentage for the four rare-spawn Digimon (Mamemon,
    Piximon, MetalMamemon, Otamamon).

    Vanilla DW1 uses very low spawn rates (~1-2%) for these encounters,
    making them frustrating to recruit. The value here is interpreted
    as a percentage and rewritten into each spawn-check site:

    * Mamemon, Piximon, MetalMamemon use a 0..99 random — written as
      ``value - 1`` (so 100 = always spawn).
    * Otamamon uses a 0..2 random — written as ``floor(value / 33)``
      (so 100 → 3, which is always-spawn given the comparator).

    Default 50 splits the difference: rare-spawns become noticeably
    common but not guaranteed. Set to 1 for vanilla rates.
    """

    display_name = "Rare-Spawn Boost (%)"
    range_start = 1
    range_end = 100
    default = 50


@dataclass
class DigimonWorldOptions(PerGameCommonOptions):
    goal: Goal
    fast_drimogemon: FastDrimogemon
    easy_monochromon: EasyMonochromon
    skip_intro: SkipIntro
    type_lock_unlocks: TypeLockUnlocks
    spawn_rate_boost: SpawnRateBoost
    stat_gain_multiplier: StatGainMultiplier


option_groups: list[OptionGroup] = [
    OptionGroup("Goal", [Goal]),
    OptionGroup(
        "Quality of Life",
        [
            FastDrimogemon, EasyMonochromon, SkipIntro, TypeLockUnlocks,
            SpawnRateBoost, StatGainMultiplier,
        ],
    ),
]
