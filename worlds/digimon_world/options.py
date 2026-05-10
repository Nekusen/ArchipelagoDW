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


class ProsperityGoal(Range):
    """Prosperity Points threshold tied to the seed's goal.

    Applies to **both** goal modes:

    * ``goal: prosperity`` — reach the threshold to win.
    * ``goal: machinedramon`` — reach the threshold AND defeat
      Machinedramon. The threshold opens the Mt. Infinity entrance
      in-game (vanilla DW1 hard-codes 50 PP; this option rewrites that
      literal), so reaching it is a real prerequisite to completing
      the Machinedramon questline as well.

    * Range: 20 – 100. Lower threshold = faster path to the endgame.
    * Default: ``50`` (vanilla).
    * Supports ``random``, ``random-low``, ``random-high``.

    Mechanics: the patcher rewrites the ``pstat(1) < 50`` literal in
    Script 210 §51 to the configured value; the AP pool scales to
    ``ceil(threshold / 3) * 1.2`` Prosperity Point items (each delivers
    3 PP); rules.py uses the same threshold for Mt. Infinity / Tower /
    Final Battle entrance gates and the Final Battle completion
    condition; the client fires ``GoalComplete`` when the in-game
    prosperity counter meets the threshold (prosperity goal) or when
    Machinedramon is defeated (machinedramon goal).
    """

    display_name = "Prosperity Goal"
    range_start = 20
    range_end = 100
    default = 50


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
      means before AP delivers. The bridge is an AP item only — there
      is no associated AP location.
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
      bridge is an AP item only — there is no associated AP location.
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
      then move it). The boulder is an AP item only — there is no
      associated AP location. Default.
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
    bits and sees the vanilla menu / result text, but no vanilla item
    is granted — the AP-placed item at that location is delivered to
    the player's bank instead. Each location's region matches the
    in-game machine location.

    The Ancient Dino "Try" gacha also gets a one-line ROM bug-fix
    patch: vanilla DW1's MP Floppy outcome only awards the item when
    the player's bag is full, leaving 1 of 4 prizes effectively
    unreachable. With this option on, the patcher rewrites the gating
    conditional so all 4 prizes ping their AP location reliably.
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


class GroundItemRandomization(DefaultOnToggle):
    """Shuffle the items that randomly spawn on field maps.

    DW1 places ~460 ``spawnItem`` opcodes throughout its world maps;
    each is a spot where, on a given visit, the game may roll out an
    item the player can pick up. Vanilla items at these spots aren't AP
    locations and aren't tracked individually — items respawn each map
    visit per vanilla behavior, so a single one-and-done detection isn't
    feasible without a per-spot first-pickup flag (deferred to v2).

    With this on, the patcher rewrites each spot's item-id byte at
    apply time, picking from a constrained replacement pool driven by
    the three follow-up options. With it off, every spot keeps its
    vanilla item.

    Mirrors the standalone DW1 randomizer's ``mapItems.Enabled`` master
    toggle.
    """

    display_name = "Ground Item Randomization"


class GroundItemFoodOnly(Toggle):
    """When a ground-item spot holds a food item in vanilla, restrict
    its replacement to food items only.

    Off (default): any consumable item may replace any consumable.
    On: spots that originally spawned food keep spawning food (any
    food); spots that originally spawned non-food are unconstrained.

    Mirrors the standalone's ``mapItems.FoodOnly`` flag.
    """

    display_name = "Ground Items: Food For Food"


class GroundItemMatchValue(DefaultOnToggle):
    """Keep ground-item replacements within the same value band as the
    vanilla item.

    With this on, replacements stay on the same side of
    :class:`GroundItemValueCutoff` as the vanilla item — cheap items
    replace cheap items, valuable items replace valuable items. Off, no
    such constraint applies and any pool member is eligible.

    Mirrors the standalone's ``mapItems.MatchValue`` flag.
    """

    display_name = "Ground Items: Match Value Band"


class GroundItemValueCutoff(Range):
    """Price threshold separating "cheap" and "valuable" items for the
    :class:`GroundItemMatchValue` constraint.

    Vanilla DW1 prices range up to several thousand bits. The default
    1000 mirrors the standalone DW1 randomizer's
    ``mapItems.ValuableItemCutoff`` default. Has no effect when
    :class:`GroundItemMatchValue` is off.
    """

    display_name = "Ground Items: Value Cutoff"
    range_start = 1
    range_end = 50_000
    default = 1000


class StarterRandomization(DefaultOnToggle):
    """Shuffle the two starter Digimon offered at the "pick your
    partner" screen.

    With this on, the patcher rewrites both starter slots at apply
    time — Digimon id, the tech taught when "starting fresh" with that
    Digimon, and the equipped-tech animation. Eligibility is gated by
    the five level toggles below; the four ``starter_allow_*`` non-
    Rookie toggles are off by default to keep vanilla pacing.

    Mirrors the standalone DW1 randomizer's ``starter.Enabled`` master
    toggle.
    """

    display_name = "Starter Randomization"


class StarterAllowFresh(Toggle):
    """Allow Fresh-level Digimon (Botamon, Punimon, Yuramon, Poyomon,
    etc.) as starter candidates.

    Off by default. Fresh Digimon have very limited tech lists in
    vanilla — most can only use the Bubble placeholder which the
    standalone treats as non-learnable, so a Fresh starter often ends
    up with no usable starter tech.

    Mirrors the standalone's ``starter.Fresh`` flag.
    """

    display_name = "Starters: Allow Fresh"


class StarterAllowInTraining(Toggle):
    """Allow In-Training Digimon (Koromon, Tsunomon, Tokomon, etc.) as
    starter candidates. Off by default — see :class:`StarterAllowFresh`
    for the tech-list caveat. Mirrors ``starter.InTraining``.
    """

    display_name = "Starters: Allow In-Training"


class StarterAllowRookie(DefaultOnToggle):
    """Allow Rookie Digimon (Agumon, Gabumon, Patamon, etc.) as starter
    candidates. On by default — Rookies are vanilla starter material.
    Mirrors ``starter.Rookie``.
    """

    display_name = "Starters: Allow Rookie"


class StarterAllowChampion(Toggle):
    """Allow Champion Digimon (Greymon, Garurumon, etc.) as starter
    candidates.

    Off by default. **Caveat:** starting at Champion trivializes early
    combat and can desync evolution-driven progression assumptions in
    the AP rules — recruit / prosperity gating is balanced around a
    Rookie starter that evolves naturally. Use for chaos seeds.

    Mirrors ``starter.Champion``.
    """

    display_name = "Starters: Allow Champion"


class StarterAllowUltimate(Toggle):
    """Allow Ultimate Digimon (MetalGreymon, MetalMamemon, etc.) as
    starter candidates.

    Off by default. **Caveat:** even more disruptive than Champion-
    level starts — Ultimate stats overpower nearly every fight in the
    early-to-mid game. Mirrors ``starter.Ultimate``.
    """

    display_name = "Starters: Allow Ultimate"


class StarterUseWeakestTech(DefaultOnToggle):
    """Choose the weakest viable starter tech rather than a random one.

    On (default): the patcher picks the lowest-slot damaging,
    non-finisher, non-Counter technique the chosen Digimon can learn
    — matches the standalone's ``UseWeakestTech=True`` flow and keeps
    starters' damage output close to vanilla.

    Off: any damaging non-finisher non-Counter technique from the
    Digimon's tech list may be selected, including high-tier ones the
    Digimon would normally have to train into.

    Mirrors ``starter.UseWeakestTech``.
    """

    display_name = "Starters: Use Weakest Tech"


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
    prosperity_goal: ProsperityGoal
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
    randomize_ground_items: GroundItemRandomization
    ground_items_food_only: GroundItemFoodOnly
    ground_items_match_value: GroundItemMatchValue
    ground_items_value_cutoff: GroundItemValueCutoff
    randomize_starter: StarterRandomization
    starter_allow_fresh: StarterAllowFresh
    starter_allow_in_training: StarterAllowInTraining
    starter_allow_rookie: StarterAllowRookie
    starter_allow_champion: StarterAllowChampion
    starter_allow_ultimate: StarterAllowUltimate
    starter_use_weakest_tech: StarterUseWeakestTech
    card_locations: CardLocations
    vending_locations: VendingLocations
    god_mode: GodMode


option_groups: list[OptionGroup] = [
    OptionGroup("Goal", [Goal, ProsperityGoal]),
    OptionGroup(
        "Randomization",
        [
            ChestRandomization, RecruitRandomization,
            GroundItemRandomization, GroundItemFoodOnly,
            GroundItemMatchValue, GroundItemValueCutoff,
            StarterRandomization, StarterAllowFresh,
            StarterAllowInTraining, StarterAllowRookie,
            StarterAllowChampion, StarterAllowUltimate,
            StarterUseWeakestTech,
        ],
    ),
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
