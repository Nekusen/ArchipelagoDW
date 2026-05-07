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

from Options import Choice, DefaultOnToggle, OptionGroup, PerGameCommonOptions, Range, Toggle


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


class BridgeUnlock(Choice):
    """Tropical Jungle bridge unlock state.

    Vanilla DW1 keeps the bridge from Native Forest to Tropical Jungle
    broken until the player triggers a cutscene by walking near it on
    the Tropical Jungle side (which they can only reach after Coelamon
    brings them across the first time).

    * ``always_open`` — the bridge is open from the start (default).
      The client pins bit 1 of :data:`RAM_TROPICAL_JUNGLE_BRIDGE_FIXED`
      so the bit is always 1, even on a fresh save.
    * ``vanilla`` — the unlock cutscene must trigger the bit organically.
    * ``shuffled`` — the ``Tropical Jungle Bridge`` AP item must be
      delivered before the bridge is fixed; receiving the item pins
      the bit (no cutscene played, bridge appears "as if always there"
      from that point on). The vanilla cutscene path also still works
      as a fallback if the player reaches the trigger tile by other
      means before AP delivers. The ``Tropical Jungle Bridge Fixed``
      AP location fires the first time the bit is set.
    """

    display_name = "Tropical Jungle Bridge"
    option_always_open = 0
    option_vanilla = 1
    option_shuffled = 2
    default = option_always_open


class GreatCanyonUnlock(Choice):
    """Great Canyon bridge unlock state.

    Vanilla DW1 keeps the Great Canyon bridge closed until the player
    has reached 6 prosperity AND walks onto a specific unlock spot,
    which fires a cutscene that opens the bridge.

    * ``always_open`` — the bridge is open from the start (default).
      The client pins bit 7 of :data:`RAM_GREAT_CANYON_BRIDGE_UNLOCKED`
      so the bit is always 1, even on a fresh save.
    * ``vanilla`` — the unlock cutscene must trigger the bit organically.
    * ``shuffled`` — the ``Great Canyon Bridge`` AP item must be
      delivered before the bridge is fixed; receiving the item pins
      the bit (no cutscene). The vanilla cutscene is patcher-disabled
      in this mode (its gate becomes self-contradictory) so reaching 6
      prosperity organically can no longer bypass the AP gate. The
      ``Great Canyon Bridge Fixed`` AP location fires when the bit
      is set.
    """

    display_name = "Great Canyon Bridge"
    option_always_open = 0
    option_vanilla = 1
    option_shuffled = 2
    default = option_always_open


class LavaCaveAccess(Choice):
    """Drill Tunnel boulder gate (path to Lava Cave / Meramon / Mt. Panorama).

    Vanilla DW1 gates the boulder behind a digimon-evolution-stage
    whitelist (Champion or above can move it). This option converts that
    gate into either a no-op or an AP-controlled progression item.

    * ``vanilla`` — keep DW1's original behavior. The boulder requires
      a Champion-class digimon to move; no AP item or location is created.
    * ``shuffled`` — the boulder check is rewritten to gate on an
      AP-controlled trigger bit. The ``Lava Cave Access`` AP item must be
      delivered before the boulder cutscene will succeed (any digimon may
      then move it). Triggering the cutscene fires the
      ``Drill Tunnel Boulder`` AP location. Default.
    """

    display_name = "Lava Cave Access"
    option_vanilla = 0
    option_shuffled = 1
    default = option_shuffled


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


class CombatStatMultiplier(Range):
    """Multiply combat stat-gain by this value (1 = vanilla rate).

    DW1's ``battleStatsGainsAndDrops`` writes per-stat gains to a
    6-entry table at RAM ``0x13D468`` at the end of each combat. This
    option installs three small ROM trampolines in the Cave6
    free-space region that scale each table write by the chosen factor
    before the game applies the gain to the partner. Independent from
    :class:`StatGainMultiplier` (which only affects training; the
    training-boost flags at ``0x001384AC..0x001384B0`` aren't read by
    combat code).

    Default 1 (vanilla rate). Values around 100 give stat explosions
    on most fights — useful for testing recruitment/progression
    without grinding combat. If gains appear to plateau, the partner's
    natural per-stat cap may be clamping them; raise
    :class:`StatGainMultiplier` too (it pins the training cap-unlock
    flag, which some downstream code paths consult).
    """

    display_name = "Combat Stat Multiplier"
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


class ChestRandomization(DefaultOnToggle):
    """Whether DW1's 65 chests participate in AP randomization.

    * **On (default)** — chests are AP locations. AP fill places any
      pool item at each chest; the patcher rewrites every
      ``spawnChest`` opcode's item byte to match what fill chose. The
      chestGiveItem wrapper short-circuits the AP-sentinel item id so
      foreign-world items don't pollute the player's inventory.
    * **Off** — chests are NOT AP locations. The 65 chests retain
      their vanilla items; the patcher emits no chest-related tokens
      (chest item bytes, AP_ITEM table entry, chestGiveItem wrapper).
      Players can open chests and get the vanilla item, with no AP
      check fired and no foreign-world item delivered through them.
    """

    display_name = "Chest Randomization"


class RecruitRandomization(DefaultOnToggle):
    """Whether ``<Name> Recruit`` items shuffle into the multiworld pool.

    * **On (default)** — each recruit's "<Name> Recruit" AP item can
      end up at any AP location in any world. To get Tyrannomon into
      File City, *somebody* (you, or another player) has to find and
      send Tyrannomon Recruit. Whoever beats Tyrannomon at his spawn
      gets the AP location check, but the recruit item itself is
      anywhere in the multiworld.
    * **Off** — each ``<Name> Recruit`` item is locked to its own
      recruit AP location. Beating Tyrannomon at his spawn fires the
      AP location *and* immediately delivers Tyrannomon Recruit to
      you. No recruit item ever leaves your slot; recruits play out
      essentially vanilla. Other AP items (chests, etc.) can still
      be placed at recruit locations if those slots are otherwise
      unconstrained — wait, no: with this off, the recruit item is
      locked-in, so the recruit location holds the recruit and
      nothing else.
    """

    display_name = "Recruit Randomization"


class VendingLocations(Toggle):
    """Add the consumable vending machines as AP locations.

    DW1 has four consumable vending machines:

    * **Greatlake** — Meat / DigiMushroom (2 items)
    * **Tropical Jungle** — Hund MP / Thous MP recovery (2)
    * **Gear Savanna** — Special Prizes (Small Recovery / Portable Potty)
      and a sub-vendor MP Stand (Hund MP / Thous MP) on the same screen (4)
    * **Ancient Dino Region** — Try gacha, random output (4)

    With this on, each item-purchase becomes its own AP location (12
    total). The patcher overwrites the vanilla ``giveItem`` /
    ``addStats`` opcodes with ``setTrigger N`` so the player still pays
    bits and sees a result message, but no vanilla item is granted —
    the AP-placed item at that location is delivered to the player's
    bank instead. Menu and result text get rewritten to show the
    AP item's *classification* (Quest / Bonus / Junk) instead of the
    vanilla item name. Each location's region matches the in-game
    machine location.
    """

    display_name = "Vending Machine Locations"


class CardLocations(Toggle):
    """Add the Digimon Card vending machines as AP locations.

    DW1's two card vending machines (Gear Savanna and the File City
    machine that opens after both Betamon and Patamon are in city) sell
    66 collectible Digimon cards. With this on, each unique card the
    player buys for the first time fires an AP location check. Detection
    uses DW1's vanilla per-card nibble counter starting at
    :data:`worlds.digimon_world.data.addresses.RAM_CARD_LIST_BASE` — no
    ROM patching required.

    Logic gating: cards are only considered reachable once the player
    can reach Gear Savanna OR has received both ``Betamon Recruit`` and
    ``Patamon Recruit`` (the prereq for the File City machine).
    """

    display_name = "Card Vending Locations"


class GodMode(Toggle):
    """Pin partner Digimon's combat stats to max each client tick.

    When on, the client writes the following values into the partner's
    stat block at ``0x001557E0..0x001557F3`` every game watcher iteration
    (only when any value drifts; cheap):

    * Offense, Defense, Speed, Brain: ``999`` (in-game cap)
    * Max HP, Max MP: ``9999``

    Strictly a testing aid — leaves AP item placement and progression
    logic untouched. **Do not enable for normal playthroughs**: with
    god mode on, the combat-difficulty curve is meaningless.
    """

    display_name = "God Mode"


@dataclass
class DigimonWorldOptions(PerGameCommonOptions):
    goal: Goal
    fast_drimogemon: FastDrimogemon
    easy_monochromon: EasyMonochromon
    skip_intro: SkipIntro
    type_lock_unlocks: TypeLockUnlocks
    bridge_unlock: BridgeUnlock
    great_canyon_unlock: GreatCanyonUnlock
    lava_cave_access: LavaCaveAccess
    spawn_rate_boost: SpawnRateBoost
    stat_gain_multiplier: StatGainMultiplier
    combat_stat_multiplier: CombatStatMultiplier
    chest_randomization: ChestRandomization
    recruit_randomization: RecruitRandomization
    card_locations: CardLocations
    vending_locations: VendingLocations
    god_mode: GodMode


option_groups: list[OptionGroup] = [
    OptionGroup("Goal", [Goal]),
    OptionGroup("Randomization", [ChestRandomization, RecruitRandomization]),
    OptionGroup("Locations", [CardLocations, VendingLocations]),
    OptionGroup(
        "Quality of Life",
        [
            FastDrimogemon, EasyMonochromon, SkipIntro, TypeLockUnlocks,
            BridgeUnlock, GreatCanyonUnlock, LavaCaveAccess, SpawnRateBoost,
            StatGainMultiplier, CombatStatMultiplier,
        ],
    ),
    OptionGroup("Testing", [GodMode]),
]
