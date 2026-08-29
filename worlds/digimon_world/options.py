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
from typing import NamedTuple

from Options import (
    Choice,
    DefaultOnToggle,
    OptionError,
    OptionGroup,
    OptionSet,
    PerGameCommonOptions,
    Range,
    Toggle,
)

from .regions import LOCKABLE_REGIONS


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


class InfiniteAutoPilot(Toggle):
    """Always keep one Auto Pilot in the on-hand inventory.

    The Auto Pilot consumable warps the player back to File City from
    anywhere. With this on, the client checks the inventory every tick
    and adds a single Auto Pilot (count 1) whenever none is present
    and a slot is free — so using one simply makes it reappear a
    moment later, and warping home never costs a banking trip.

    Never stacks extras and never displaces another item: with a full
    inventory the top-up waits until a slot frees up. Client-side
    only (no ROM change); shipped to the client via slot_data.
    """

    display_name = "Infinite Auto Pilot"


class BridgeUnlock(Choice):
    """Tropical Jungle bridge unlock state.

    Vanilla DW1 keeps the bridge from Native Forest to Tropical Jungle
    broken until the player triggers a cutscene by walking near it on
    the Tropical Jungle side (which they can only reach after Coelamon
    ferries them across the first time). The original ``vanilla`` mode
    (bridge fixed by that organic cutscene) is not shipped: in
    ``shuffled`` mode the take-across ferry is intentionally closed so
    the bridge state is exclusively AP-driven, and in ``always_open``
    mode it is moot.

    Either way the Coelamon AP location (restored 2026-08-22) stays
    reachable: his recruit cutscene at Coela Point plays once the
    bridge is fixed — immediately in ``always_open``, after the
    ``Tropical Jungle Bridge`` item lands in ``shuffled``. The
    pre-bridge ferry (only ever seen in ``shuffled`` seeds before the
    item arrives) is closed gracefully — Coelamon's shore stays quiet.

    * ``always_open`` — the bridge is open from the start (default).
      The client pins bit 1 of :data:`RAM_TROPICAL_JUNGLE_BRIDGE_FIXED`
      so the bit is always 1, even on a fresh save.
    * ``shuffled`` — the ``Tropical Jungle Bridge`` AP item must be
      delivered before the bridge is fixed; receiving the item pins
      the bit. The bridge is an AP item only — there is no associated
      AP location.
    """

    display_name = "Tropical Jungle Bridge"
    option_always_open = 0
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


class RegionLocking(Choice):
    """Whether walking into a region requires an AP "Region Access" item.

    Pure logic option — adds no in-game gates. Each lockable region
    gets a ``<region> Region Access`` AP item; AP placement treats the
    region's checks as unreachable until that item is delivered. The
    player can still physically walk into the region without the item
    (no script patch); they just find whatever filler AP placed there
    rather than progression. Lets seeds break the "one new region opens
    a sphere of N checks at once" cascade.

    * ``off`` — no region locking (default). Vanilla AP behavior.
    * ``all`` — every region in
      :data:`worlds.digimon_world.regions.LOCKABLE_REGIONS` is locked.
      Pairs naturally with :class:`StartingRegion` to randomize where
      the player begins.
    * ``custom`` — only regions listed in :class:`RegionLockingList`
      are locked. Empty list under custom = identical to ``off``.
    """

    display_name = "Region Locking"
    option_off = 0
    option_all = 1
    option_custom = 2
    default = option_off


class RegionLockingList(OptionSet):
    """Which regions to lock when :class:`RegionLocking` is ``custom``.

    Ignored under ``off`` and ``all``. Each entry is the canonical
    region name as used in :data:`worlds.digimon_world.regions.REGION_NAMES`.
    Regions not in :data:`worlds.digimon_world.regions.LOCKABLE_REGIONS`
    can't be added (they're either always-reachable hubs, already
    strongly gated by another mechanism, or trivial sub-areas).
    """

    display_name = "Region Locking List"
    valid_keys = frozenset(LOCKABLE_REGIONS)
    default = frozenset()


class StartingRegion(Choice):
    """Which region the player begins with access to (besides File City).

    **Only takes effect when** :class:`RegionLocking` **is** ``all``.
    Under ``off`` and ``custom`` modes this option is ignored; the
    player simply walks out of File City through whatever isn't
    locked. Combine with ``region_locking: all`` to get the full
    "fly in to your starting area, all other regions locked" feel.

    The chosen region's Access item is added to the start_inventory,
    along with the means to get there from File City:

    * ``native_forest`` (default) — degenerate case; only Native
      Forest Region Access is bootstrapped. Player walks File City →
      Native Forest like vanilla.
    * ``gear_savanna``, ``ancient_dino_region``, ``freezeland``,
      ``misty_trees``, ``beetle_land`` — bootstrap kit is
      ``Birdramon Recruit + Birdramon Flight: <region> + <region>
      Region Access``. Player flies in via the Birdra-Messenger menu.
    * ``great_canyon`` — bootstrap kit is ``Birdramon Recruit +
      Great Canyon Region Access``. There's no separate ``Flight:``
      item — the kit stands in for the in-game "you've been here
      once" precondition for G Canyon Top in the Birdra-Messenger menu.
      AP logic models the ``File City → Great Canyon`` flight edge
      as accessible **only** under ``starting_region: great_canyon``;
      every other start (and ``region_locking: off`` / ``custom``)
      leaves that edge logically inaccessible — the GC-Bridge AP item
      remains the way to walk in.
    * ``factorial_town`` — bootstrap kit is ``Whamon Recruit +
      Factorial Town Region Access``. Asymmetric with the Birdramon
      starts because Factorial Town is reached via Whamon's ferry,
      not Birdramon.

    To randomize across all starts, use the AP YAML's per-value
    weights (or the ``random`` keyword) — no separate "random" option
    is needed. To stay at the vanilla start, leave at the default.
    """

    display_name = "Starting Region"
    option_native_forest = 0
    option_gear_savanna = 1
    option_ancient_dino_region = 2
    option_freezeland = 3
    option_misty_trees = 4
    option_beetle_land = 5
    option_great_canyon = 6
    option_factorial_town = 7
    default = option_native_forest


# Map :class:`StartingRegion` option values to their canonical region
# name in :data:`worlds.digimon_world.regions.REGION_NAMES`. Used by
# :func:`get_starting_region_name` so callers don't have to hand-roll
# the int-to-name translation.
_STARTING_REGION_BY_VALUE: dict[int, str] = {
    StartingRegion.option_native_forest:       "Native Forest",
    StartingRegion.option_gear_savanna:        "Gear Savanna",
    StartingRegion.option_ancient_dino_region: "Ancient Dino Region",
    StartingRegion.option_freezeland:          "Freezeland",
    StartingRegion.option_misty_trees:         "Misty Trees",
    StartingRegion.option_beetle_land:         "Beetle Land",
    StartingRegion.option_great_canyon:        "Great Canyon",
    StartingRegion.option_factorial_town:      "Factorial Town",
}


def get_starting_region_name(options: "DigimonWorldOptions") -> str:
    """Canonical region name for the configured :class:`StartingRegion`.

    Returns the name regardless of whether :class:`RegionLocking` is
    actually ``all`` — the option's "active only under all" semantics
    are enforced by callers (e.g. :func:`worlds.digimon_world.items.get_bootstrap_items`).
    """

    return _STARTING_REGION_BY_VALUE[int(options.starting_region.value)]


class ItemStatGain(Toggle):
    """Grant stat gains and lifetime increases when digivolving via a
    Digivolution Item.

    Vanilla DW1 skips both for item-driven digivolutions — only training
    digivolutions grant stats and reset lifetime. With this on, item
    digivolutions follow the same gain path. Single-byte ROM patch
    mirrored from the standalone DW1 randomizer's ``EvoItemStatGain``
    flag (``references/digimon_world_randomizer/digimon/handler.py:2429``).
    """

    display_name = "Item Stat Gain"


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


class CardTradeMultiplier(Range):
    """Multiply the Merit Points ShogunGekomon pays per traded Digimon card.

    Vanilla DW1 values cards at 100 / 30 / 10 / 5 / 1 Merit Points by
    rarity tier, which makes earning merits by card-trading very slow.
    This option rewrites the per-card value table in the ROM so every
    card pays ``vanilla value x multiplier``.

    Note the in-game merit counter caps at **9999** — boosted trades
    still stop accumulating there (a single trade is also clamped so it
    can never display more than 9999). Default 1 leaves the table at
    vanilla values. Pure QoL: AP logic never depends on merit totals.
    """

    display_name = "Card Trade Value Multiplier"
    range_start = 1
    range_end = 20
    default = 1


class PiximonManualLocation(Toggle):
    """Make buying Piximon's Training Manual an AP location.

    Piximon occasionally staffs the File City item-shop **building**
    (the tier-3 shop) and offers a Training Manual for 50,000 Bits.
    His visit is a 2-in-10 roll each time the building screen loads
    (and only once Piximon is in the city, which the ``Progressive
    Item Shop`` tier-3 delivery handles) — if he isn't in, leave and
    re-enter the building until he shows up.

    With this on, paying his 50,000 Bits fires the ``Piximon's
    Training Manual`` AP location instead of delivering the vanilla
    Manual. The Manual is a genuinely useful item you're giving up in
    the exchange — the AP item pool compensates (a ``Trn. manual``
    copy ships among the pool's useful items), and whatever AP placed
    at the location is delivered normally. Logic gates the location on
    ``Progressive Item Shop`` x3.
    """

    display_name = "Piximon Training Manual Location"


class FrigimonRecruitLocation(DefaultOnToggle):
    """Include Frigimon's recruit as an AP location.

    On by default (matches previous seeds). Turn OFF to drop the
    ``Frigimon`` check from the pool — the in-game recruit chain is
    widely considered tedious, so players can opt out of having a
    multiworld item locked behind it.

    Only the AP **location** (the check) is affected. Frigimon's
    City-NPC delivery is untouched either way: she is bundled into
    ``Progressive Restaurant`` tier 2 (see
    :data:`worlds.digimon_world.items.PROGRESSIVE_BUNDLES`) and still
    joins File City when that item is delivered.
    """

    display_name = "Frigimon Recruit Location"


class MojyamonRecruitLocation(DefaultOnToggle):
    """Include Mojyamon's recruit as an AP location.

    On by default (matches previous seeds). Turn OFF to drop the
    ``Mojyamon`` check from the pool — the in-game recruit is tedious
    and, worse, RNG-dependent (Mojyamon's appearance is a random roll,
    so the check can demand long re-entry grinding through no fault of
    the player).

    Only the AP **location** (the check) is affected. Mojyamon's
    City-NPC delivery is untouched either way: he is bundled into
    ``Progressive Secret Shop`` tier 1 (see
    :data:`worlds.digimon_world.items.PROGRESSIVE_BUNDLES`) and still
    joins File City when that item is delivered.
    """

    display_name = "Mojyamon Recruit Location"


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


class TechniqueRewards(Choice):
    """Whether techniques can be received as AP item rewards.

    * ``vanilla`` — techniques are learned only through DW1's normal
      paths (training, brain rolls, NPC teach, starter init). No tech
      items ship in the AP pool.
    * ``ap_items`` — a random subset of the 56 player-masterable techs
      is added to the AP pool as ``Tech: <name>`` items (one per chosen
      tech, classification ``useful``). Receiving one ORs that tech's
      mastery bit on the partner Digimon's save block, which makes the
      tech immediately usable in combat (verified live 2026-05-11).
      Vanilla in-game learning of the same techs still works in
      parallel; the AP grant just flips the same bit earlier than the
      player would normally reach it. The client re-asserts every
      AP-granted bit each watcher tick so the mastery state survives
      partner death/rebirth and digivolution. (Default.)

    The subset is chosen per-seed via
    :func:`worlds.digimon_world.items.choose_technique_pool`, which
    picks ``world.random.randint(20, 30)`` techs uniformly from the
    56-tech pool. Two seeds with the same flag still ship different
    techs.
    """

    display_name = "Technique Rewards"
    option_vanilla = 0
    option_ap_items = 1
    default = option_ap_items


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


class ShopLocationsChoice(Choice):
    """Shared 3-mode base for the four shopsanity shop options.

    * ``off`` — the shop is vanilla; no AP locations exist for it.
    * ``coexist`` — the vanilla rows stay purchasable (delivering their
      vanilla items) and the AP rows are appended after them.
    * ``replace`` — only the AP rows are shown; the vanilla stock is
      gone for the seed.

    In both non-off modes each AP row is its own AP location: buying it
    deducts the displayed price, fires the location check, and delivers
    nothing in-game (AP routes whatever was placed there — your own
    items land in the bank).

    Legacy note: the pre-shopsanity ``recycle_shop_locations`` /
    ``merit_shop_locations`` toggles map ``true`` → ``replace`` (the
    shipped behavior of the old "on") and ``false`` → ``off``.
    """

    option_off = 0
    option_coexist = 1
    option_replace = 2
    default = option_off
    # Legacy toggle compatibility: bool True routes through
    # ``from_text("true")`` and lands on replace; "false" auto-aliases
    # to off via the option metaclass.
    alias_true = option_replace


class RecycleShopLocations(ShopLocationsChoice):
    """Add the Recycle Shop (Tinmon "Market Manager", Gear Savanna) as
    AP locations.

    DW1's recycle shop sells 7 fixed money-priced items
    (med.recovery / Medium MP / Off. Disk / Def. Disk / Hispeed dsk /
    Auto Pilot / Giant Meat). In ``coexist`` / ``replace`` mode each AP
    row becomes its own AP location (7 total), and the shop UI displays
    the multiworld AP item name + a "From <player>'s World" hover
    description.

    Mechanics: a one-time gen-time relocation of DW1's
    ``ITEM_DESC_PTR`` table out to free RAM frees up extended ITEM_PARA
    slots; we use 7 of them to hold per-shop-row AP names + prices. A
    screen-gated ROM wrapper at the money-shop list-builder callsite
    emits the AP rows synchronously when the shop opens (coexist
    appends them after the vanilla rows; replace shows only AP rows).
    A second wrapper at the shop's ``giveItem`` callsite fires the AP
    location signal and skips the vanilla item delivery so the
    AP-placed item at that location is delivered to the player's bank
    instead. Money is still deducted (vanilla shop logic deducts
    before the give-item callsite).

    Legacy: the old toggle's ``true`` maps to ``replace``.
    """

    display_name = "Recycle Shop Locations"


class FishingLocations(Toggle):
    """Add the 6 catchable DW1 fish as AP locations.

    DW1's fishing minigame (enabled on MAYO06 / MAYO10, the two Dragon
    Eye Lake screens) can produce 6 different fish species: Digianchovy,
    Digisnapper, DigiTrout, Black trout, Digicatfish, Digiseabass. With
    this on, each fish becomes its own AP location.

    Detection is client-side: the client tracks per-fish inventory counts
    and fires the corresponding AP location the first time a fish count
    *increases* while the player is on a fishing screen. AP-delivered
    fish items land in the bank, not the inventory, so foreign-world
    deliveries cannot cause a false fire. The only edge case is opening
    the Dragon Eye Lake chest while standing on screen 6 or 8 — accepted
    per design.

    Logic gating: each fishing AP location requires a fishing rod
    (``Old Fishrod`` or ``Amazing rod``) in addition to Greatlake region
    access. No ROM patching required.
    """

    display_name = "Fishing Locations"


class MeritShopLocations(ShopLocationsChoice):
    """Add the Merit Shop (ShogunGekomon, Volume Villa) as AP locations.

    DW1's merit shop sells 14 fixed merit-priced items (sup.recovery,
    Sup.restore, 6 Chips, Rainbowhorn, 4 500-merit consumables, and
    Amazing rod). In ``coexist`` / ``replace`` mode each AP row becomes
    its own AP location (``Merit Shop #1..#14``), and the shop UI
    displays the multiworld AP item name + a "From <player>'s World"
    hover description. The v1 ``Amazing Rod Pickup`` row at slot 83
    (300 merits) is preserved as an extra row in the shop — its AP
    location is unchanged.

    Mechanics: extends the recycle shop's relocated-ITEM_DESC_PTR
    infrastructure. The merit-shop scan loop's hard upper bound (vanilla
    ``< 0x80``) is bumped to ``< 0x95`` (= 149) so the scan reaches
    extended ITEM_PARA slots 135..148. The shop's existing
    ``giveItem``-callsite jal hijack (installed by v1) is re-targeted at
    an extended dispatch wrapper that handles 15 ``(item_id, trigger)``
    pairs. In ``replace`` mode the vanilla items' ``meritValue`` is
    zeroed so their rows disappear; in ``coexist`` mode the vanilla
    rows stay purchasable next to the AP rows. AP-slot ``meritValue``
    is set to the vanilla price of the slot it mirrors (preserves the
    displayed cost — the ``shop_price_*`` options never touch merit
    prices). Merits are still deducted (vanilla shop logic deducts
    before the give-item callsite).

    Legacy: the old toggle's ``true`` maps to ``replace`` (the shipped
    "on" behavior zeroed the vanilla rows).
    """

    display_name = "Merit Shop Locations"


class ItemShopLocations(ShopLocationsChoice):
    """Add the File City item shop (market stall + shop building) as AP
    locations.

    25 AP rows total, revealed with the ``Progressive Item Shop``
    ladder: tier 1 shows the first 5 rows, tier 2 fifteen, tier 3 all
    25. Both the early market stall and the later shop building share
    the same AP rows (same in-game shop backend). AP logic gates the
    row groups on ``Progressive Item Shop`` x1 / x2 / x3.

    Prices come from the ``shop_price_mode`` option (tiered default:
    500 / 1000 / 2000 bits per tier). ``coexist`` keeps the vanilla
    stock purchasable alongside; ``replace`` sells only AP rows.
    """

    display_name = "Item Shop Locations"


class SecretShopLocations(ShopLocationsChoice):
    """Add the Secret Item Shop (the sewer under File City's second
    item shop) as AP locations.

    12 AP rows: 3 per clerk (Numemon / Mojyamon / Mamemon / Devimon).
    The shop shows the on-duty clerk's 3 rows; leave and re-enter to
    rotate clerks. AP logic gates the Numemon / Mojyamon pools on
    ``Progressive Secret Shop`` x1 and the Mamemon / Devimon pools on
    x2, always together with ``Progressive Item Shop`` x2 (the sewer is
    only reachable through the second item shop).

    Prices come from the ``shop_price_mode`` option (tiered default:
    1000-3200 bits, scaling by clerk). ``coexist`` keeps the vanilla
    stock purchasable alongside; ``replace`` sells only AP rows.
    """

    display_name = "Secret Shop Locations"


class ShopPriceMode(Choice):
    """How the AP shop rows are priced (recycle / item / secret shops).

    * ``tiered`` — fixed defaults: recycle rows keep their vanilla
      prices; item shop rows cost 500 / 1000 / 2000 bits by tier;
      secret shop rows cost 1000-3200 bits scaling by clerk.
    * ``randomized`` — each AP row's price is rolled uniformly in
      ``[shop_price_min, shop_price_max]`` at generation time.

    Prices are purely an in-game money sink — AP logic never depends
    on affordability. Merit Shop prices are merit-currency and always
    stay at their vanilla values.
    """

    display_name = "Shop Price Mode"
    option_tiered = 0
    option_randomized = 1
    default = option_tiered


class ShopPriceMin(Range):
    """Lower bound (bits) for ``shop_price_mode: randomized``.

    Must be <= ``shop_price_max`` (validated at generation). Ignored
    under ``tiered``.
    """

    display_name = "Shop Price Minimum"
    range_start = 1
    range_end = 50_000
    default = 100


class ShopPriceMax(Range):
    """Upper bound (bits) for ``shop_price_mode: randomized``.

    Must be >= ``shop_price_min`` (validated at generation). Ignored
    under ``tiered``.
    """

    display_name = "Shop Price Maximum"
    range_start = 1
    range_end = 50_000
    default = 5000


class ArenaLocations(Choice):
    """Add the 5 Battle Arena cup-tier wins as AP locations.

    DW1's Battle Arena (south File City) runs 5 grade-tier tournaments
    (Grade D / C / B / A / S). With this option, each cup win fires
    multiple AP location checks (4 per cup). The cups themselves are
    gated by the ``Progressive Arena`` ladder item (3 tiers):

    * Grade D requires 1x Progressive Arena.
    * Grade C requires 2x Progressive Arena.
    * Grade B / A / S require 3x Progressive Arena.

    When AP-delivered, Progressive Arena drives a client-side enforcer
    that flips the in-game recruit-block bits the arena reads to
    decide which cup tiers can run. The enforcer only fires while the
    player is on an arena screen (ROOM13 / ROOM19), and recruit-bit AP
    location detection is paused on those screens so the enforcer's
    writes can't fire false location checks.

    Values:

    * ``off`` (default): no arena AP locations.
    * ``exclude_s``: 16 AP locations (Grades D / C / B / A only). Grade S
      requires winning the previous 4 cups in order, which is a long
      grind some players prefer to skip.
    * ``all``: 20 AP locations (every cup tier).
    """

    display_name = "Arena Locations"
    option_off = 0
    option_exclude_s = 1
    option_all = 2
    default = 0


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


class ShopModes(NamedTuple):
    """Resolved per-shop 3-mode values (0 = off, 1 = coexist, 2 = replace)."""

    recycle: int
    item: int
    secret: int
    merit: int

    @property
    def any_enabled(self) -> bool:
        return any(mode != 0 for mode in self)


def get_shop_modes(options: "DigimonWorldOptions") -> ShopModes:
    """Resolve the four shopsanity options to a :class:`ShopModes` tuple.

    Single source of truth for :mod:`.rom` (token emission),
    :mod:`.locations` (pool inclusion), and
    :meth:`worlds.digimon_world.world.DigimonWorldWorld.fill_slot_data`.
    """

    return ShopModes(
        recycle=int(options.recycle_shop_locations.value),
        item=int(options.item_shop_locations.value),
        secret=int(options.secret_shop_locations.value),
        merit=int(options.merit_shop_locations.value),
    )


def validate_shop_price_options(options: "DigimonWorldOptions", player_name: str) -> None:
    """Raise :class:`Options.OptionError` when the randomized price range
    is inverted. Called from ``generate_early``."""

    if int(options.shop_price_mode.value) != ShopPriceMode.option_randomized:
        return
    price_min = int(options.shop_price_min.value)
    price_max = int(options.shop_price_max.value)
    if price_min > price_max:
        raise OptionError(
            f"Player {player_name}: shop_price_min ({price_min}) must be "
            f"<= shop_price_max ({price_max})",
        )


def get_locked_regions(options: "DigimonWorldOptions") -> frozenset[str]:
    """Resolve the region-locking option triple to a concrete name set.

    Single source of truth for :mod:`.items` (pool gating) and
    :mod:`.rules` (entrance-rule augmentation), so the two never drift.

    * ``off``    → empty set.
    * ``all``    → every name in :data:`.regions.LOCKABLE_REGIONS`.
    * ``custom`` → exactly the user's ``region_locking_list`` (filtered
      to the LOCKABLE set as a defensive belt-and-suspenders; the
      OptionSet's ``valid_keys`` should already reject anything outside).
    """

    mode = int(options.region_locking.value)
    if mode == RegionLocking.option_off:
        return frozenset()
    if mode == RegionLocking.option_all:
        return frozenset(LOCKABLE_REGIONS)
    # custom
    return frozenset(options.region_locking_list.value) & frozenset(LOCKABLE_REGIONS)


class EnemyStats(Choice):
    """How every field Digimon's stats and techniques are set (wild fodder and bosses alike).

    * ``vanilla`` — stats and techniques as on the disc. A species swapped in by
      ``enemy_randomization`` receives the techniques of its own list closest in
      power to the ones the original used.
    * ``progressive`` — each region's vanilla difficulty (stat budget *and* technique
      power) is re-assigned by the region's logical depth in this seed, i.e. the
      sphere in which it first becomes reachable: the regions you can reach first
      get the weakest vanilla numbers, the deepest the strongest, so an area the
      item placement opens early plays like an early area wherever it sits in the
      vanilla game. All Digimon of a region scale by the same factor and re-pick
      their techniques around the region's target power, so bosses stay
      proportionally tougher than the fodder around them.
    * ``full_random`` — every screen borrows the difficulty of a random vanilla
      screen (stats stay inside the vanilla range) and its Digimon draw random
      techniques from their lists.

    A Digimon can only ever use the 16 techniques of its species list; AI weights
    and the number of techniques per Digimon never change. Combat stat gains and
    the Bits a fight pays follow the enemy's stats, as in vanilla. Pure data
    rewrite of the per-screen enemy records — no code hooks.
    """

    display_name = "Enemy Stats"
    option_vanilla = 0
    option_progressive = 1
    option_full_random = 2
    default = option_vanilla


class EnemyStatsStrength(Range):
    """How far ``enemy_stats: progressive`` moves a region from its vanilla numbers
    (percent). 0 leaves vanilla stats and techniques; 100 applies the full
    depth-based re-assignment; values in between blend the two. Ignored by the
    other modes.
    """

    display_name = "Enemy Stats Strength"
    range_start = 0
    range_end = 100
    default = 100


class EnemyRandomization(Choice):
    """Replace the field Digimon species on every screen.

    * ``off`` — vanilla species.
    * ``wild`` — every wild (non-story) species on a screen becomes another fighting
      species. Recruit fights, story bosses, town NPCs, the intro tutorial and
      cutscene rooms keep their vanilla species.
    * ``wild_and_story`` — recruit and story fights are swapped too (their stats stay
      exactly as they were, only the model and moveset change). Story cutscenes still
      play with their vanilla dialogue; a swapped boss may lack a cutscene-specific
      animation and stand still where the original posed.

    Substitutes are drawn from species whose 3D model needs no more memory than the
    original's, so no screen ever loads more model data than vanilla. A swapped
    Digimon keeps the original record's stats; its techniques come from its own
    list, chosen as ``enemy_stats`` dictates (power-equivalent under ``vanilla``).
    """

    display_name = "Enemy Randomization"
    option_off = 0
    option_wild = 1
    option_wild_and_story = 2
    default = option_off


class EnemyRandomizationTier(Choice):
    """Which species may stand in for a randomized enemy.

    * ``same_level`` — Rookies become Rookies, Champions Champions, Ultimates
      Ultimates (keeps the visual power curve honest).
    * ``any`` — any fighting species that fits the memory budget.
    """

    display_name = "Enemy Randomization Tier"
    option_same_level = 0
    option_any = 1
    default = option_same_level


class EnemyTechniqueWeights(Toggle):
    """Randomize how often each field Digimon uses each of its techniques: the AI
    weights of every fighter record are re-rolled (one random split of 100 over
    the techniques it carries). Independent of ``enemy_stats``, which never
    changes the weights on its own. Pure data rewrite of the per-screen enemy
    records.
    """

    display_name = "Enemy Technique Weights"


class TechniqueData(Choice):
    """Randomize the technique data table (``MOVE_DATA``): power, MP cost, accuracy,
    status effect and status chance of every technique, as chosen by the five
    ``technique_*`` toggles.

    * ``vanilla`` — the table as on the disc.
    * ``shuffle`` — the vanilla values are swapped around among the 58 techniques
      the partner can learn (finishers and bubble attacks keep theirs).
    * ``randomized`` — after the shuffle, every technique (enemy-only ones included)
      gets new values: power 70-130 % of the vanilla one (cap 999), MP cost
      10-140 % of the power, accuracy mostly between 50 and 100.

    The table is global: the partner, wild Digimon and bosses all read the same
    record for a technique. ``enemy_stats`` scales enemies by the powers this
    option ships, so the two compose. Mirrors the standalone DW1 randomizer's
    ``techs.Enabled`` + ``techs.RandomizationMode`` (``shuffle`` / ``random``).
    """

    display_name = "Technique Data"
    option_vanilla = 0
    option_shuffle = 1
    option_randomized = 2
    default = option_vanilla


class TechniquePower(DefaultOnToggle):
    """Include technique power in :class:`TechniqueData`. Buff techniques (power 0)
    stay at 0. Mirrors the standalone's ``techs.Power``."""

    display_name = "Technique Data: Power"


class TechniqueMPCost(DefaultOnToggle):
    """Include technique MP cost in :class:`TechniqueData`. Mirrors the standalone's
    ``techs.Cost``."""

    display_name = "Technique Data: MP Cost"


class TechniqueAccuracy(DefaultOnToggle):
    """Include technique accuracy in :class:`TechniqueData`. Mirrors the standalone's
    ``techs.Accuracy``."""

    display_name = "Technique Data: Accuracy"


class TechniqueEffect(DefaultOnToggle):
    """Re-roll the status effect of every partner-learnable technique in
    :class:`TechniqueData`: about half of the damaging techniques inflict one of
    poison, confusion, stun or flat; buffs never do. Not affected by the mode.
    Mirrors the standalone's ``techs.Effect``."""

    display_name = "Technique Data: Status Effect"


class TechniqueEffectChance(DefaultOnToggle):
    """Re-roll the status chance (1-70 %) of every partner-learnable technique that
    has a status effect in :class:`TechniqueData`. Not affected by the mode. Mirrors
    the standalone's ``techs.EffectChance``."""

    display_name = "Technique Data: Status Chance"


class SpeciesTechniqueLists(Toggle):
    """Randomize which techniques each species can use and learn: every populated
    slot of every species' 16-slot technique list is re-drawn among the
    techniques of the same class (normal / enemy finisher / bubble) and the same
    element, without repeats. Lists never grow (a model only carries animations
    for its vanilla slots) and keep their element mix, so the partner can still
    learn every technique in its list from battle and brain training. Wild Digimon
    use whatever now sits in their slots; ``enemy_stats`` reads the shuffled lists.
    Independent of ``technique_data`` (the techniques' own numbers).
    """

    display_name = "Species Technique Lists"


class TypeEffectiveness(Toggle):
    """Randomize the 7x7 element affinity matrix (Fire / Battle / Air / Nature / Ice /
    Mech / Filth): every cell becomes one of the vanilla values 2, 5, 10, 15 or 20.
    The matrix is a damage multiplier: every hit is scaled by the sum of the
    cells for the technique's element against the defender's three specialties,
    over 30 (so a 20/20/20 defender takes double damage, a 2/2/2 one a fifth), for
    the partner and enemies alike, in the field, the arena and versus mode. The
    partner's auto-battle AI also ranks techniques by it. Independent of
    :class:`TechniqueData`. Mirrors the standalone's ``techs.TypeEffectiveness``.
    """

    display_name = "Type Effectiveness"


class EnemyDropItems(Toggle):
    """Randomize the item each Digimon species drops after a won battle. Replacements
    are consumables that are neither quest nor digivolution items, drawn as
    :class:`EnemyDropsMatchValue` and :class:`EnemyDropsValueCutoff` dictate.
    Mirrors the standalone DW1 randomizer's ``digimon.DroppedItem``.
    """

    display_name = "Enemy Drop Items"


class EnemyDropRates(Toggle):
    """Randomize the chance each Digimon species drops its item. Rates move a step or
    two along the vanilla ladder (1 / 5 / 10 / 20 / 25 / 30 / 40 / 50 %), species that
    never dropped anything get a rate, and 100 % drops stay 100 %. Mirrors the
    standalone's ``digimon.DropRate``.
    """

    display_name = "Enemy Drop Rates"


class EnemyDropsMatchValue(DefaultOnToggle):
    """Keep randomized drop items within the same value band as the vanilla drop:
    cheap items replace cheap items, valuable items replace valuable ones, split at
    :class:`EnemyDropsValueCutoff`. Mirrors the standalone's ``digimon.MatchValue``.
    """

    display_name = "Enemy Drops: Match Value Band"


class EnemyDropsValueCutoff(Range):
    """Price threshold separating "cheap" and "valuable" items for
    :class:`EnemyDropsMatchValue`. Mirrors the standalone's
    ``digimon.ValuableItemCutoff`` (default 1000).
    """

    display_name = "Enemy Drops: Value Cutoff"
    range_start = 1
    range_end = 50_000
    default = 1000


class TechGifts(Toggle):
    """Randomize the techniques taught by NPCs: the Beetle Land Bug and Seadramon's
    three teaches each hand out a random partner-learnable technique instead of
    the vanilla one. Independent of ``technique_rewards`` (the AP technique items).
    Mirrors the standalone DW1 randomizer's ``techGifts.Enabled``.
    """

    display_name = "Technique Gifts"


class TokomonGifts(Toggle):
    """Randomize the six items Tokomon gives at the start of the game: each becomes
    1-3 copies of a random non-quest, non-digivolution item, cheaper items more
    likely to come in larger quantities. Mirrors the standalone's ``tokomon.Enabled``.
    """

    display_name = "Tokomon Gifts"


class TokomonGiftsConsumableOnly(Toggle):
    """Restrict :class:`TokomonGifts` to consumable items (no Enemy Repel, Training
    Manual and the like). Mirrors the standalone's ``tokomon.ConsumableOnly``.
    """

    display_name = "Tokomon Gifts: Consumable Only"


class QuestItemsDroppable(Toggle):
    """Let quest items (Mansion Key, Gear, Blue Flute, …) be dropped from the item
    menu like any other item. Mirrors the standalone's ``patches.QuestItemsDroppable``.
    """

    display_name = "Quest Items Droppable"


class IncreaseLearnChance(Toggle):
    """Double every technique's learn chance, both from battle and from brain
    training (brain cells that were 0 become 5 %). Mirrors the standalone's
    ``patches.IncreaseLearnChance``.
    """

    display_name = "Increase Technique Learn Chance"


class BrainTrainingTierOne(Toggle):
    """Brain training can teach a tier-1 technique (30 % chance) when the partner does
    not know it yet — vanilla never offers the first tier there. Mirrors the
    standalone's ``patches.BrainTrainTierOne``.
    """

    display_name = "Brain Training Teaches Tier 1"


class UnrigSlots(Toggle):
    """Make the bonus-try training slots purely skill-based: vanilla rigs the reels
    so most attempts lose regardless of timing. Mirrors the standalone's
    ``patches.UnrigSlots``.
    """

    display_name = "Unrig Bonus Try Slots"


class LearnMoveAndCommand(Toggle):
    """Allow learning a technique and a command in the same brain-training session
    (vanilla skips the technique roll once a command is learned). Mirrors the
    standalone's ``patches.LearnMoveAndCommand``.
    """

    display_name = "Learn Move And Command Together"


class DigivolutionRandomization(Toggle):
    """Randomize the natural digivolution tree: which Rookies each In-Training can
    become, which Champions each Rookie, which Ultimates each Champion. Every
    In-Training gets 2 Rookie targets, every Rookie 4-6 Champions, every Champion
    1-2 Ultimates (Fresh -> In-Training is hard-coded in the game and stays).
    Kunemon, Numemon, Sukamon, Nanimon, Vademon, Panjyamon, Gigadramon and
    MetalEtemon stay special-only; Devimon joins the natural tree when
    ``digivolution_requirements`` is on. The in-game digivolution chart follows.

    **Warning — read before enabling.** A few checks sit behind partner-specific
    gates: Greylord's Mansion wants a Virus partner, Ice Sanctuary a Vaccine one,
    and Toy Town opens for Monzaemon (the Numemon suit). With a random tree,
    reaching the right species or type can take much longer or plain luck, and
    the AP logic cannot account for it. Keep ``type_lock_unlocks`` on (its
    default) to remove those three gates, or accept that risk knowingly. The
    seed is never impossible: every starting line is guaranteed a natural path
    to at least one Vaccine and one Virus species, and Numemon (the Toy Town
    suit) stays the fallback digivolution of every Rookie.

    Mirrors the standalone DW1 randomizer's ``evolution.Enabled``.
    """

    display_name = "Digivolution Randomization"


class DigivolutionObtainAll(Toggle):
    """With :class:`DigivolutionRandomization`, guarantee that every natural-tree
    species keeps at least one predecessor, so every Rookie, Champion and Ultimate
    that can be reached by digivolving in vanilla still can. Off, some species may
    only be reachable through special digivolutions or not at all. Mirrors the
    standalone's ``evolution.ObtainAllMode``.
    """

    display_name = "Digivolution: Obtain All"


class DigivolutionRequirements(Toggle):
    """With :class:`DigivolutionRandomization`, also randomize the requirements to
    digivolve into each species. Rookies: three stats flagged (the partner's best
    stat must be one of them), weight 15, no care-mistake limit. Champions: 1-4
    stats at 100 (HP / MP 1000), a care-mistake minimum or maximum, a weight, a
    techniques count and one or two bonus conditions (discipline, battles, coming
    from a given species). Ultimates: 4-6 stats at 200-500 (sometimes 300-700) and
    stricter bonuses. Devimon becomes a natural target (its stats are kept on that
    digivolution — the game scales rather than adds for Devimon).
    Mirrors the standalone's ``evolution.Requirements``.
    """

    display_name = "Digivolution: Requirements"


class DigivolutionStatGains(Toggle):
    """Randomize the stat gains of digivolving into each Rookie, Champion and
    Ultimate, uniformly inside the vanilla range of that level (Rookies roughly
    +500-1000 HP / MP and +50-100 elsewhere, Champions +1000-2500 / +100-250,
    Ultimates +3000-9000 / +300-900). The game applies a gain as it always did: a
    stat below the gain jumps halfway to it, a stat above it adds a tenth.
    Devimon, Numemon, Sukamon, Nanimon and the Fresh / In-Training targets keep
    their vanilla rows (the game scales instead of adding for those). Independent
    of :class:`DigivolutionRandomization`.
    """

    display_name = "Digivolution: Stat Gains"


class SpecialDigivolutions(Toggle):
    """With :class:`DigivolutionRandomization`, randomize the result of the special
    digivolutions: the death digivolutions (Bakemon, Devimon, SkullGreymon,
    Phoenixmon), the MetalMamemon / Giromon upgrades, the Numemon suit (Toy Town
    then opens for the suit's new result), and Airdramon, Ninjamon, Monochromon,
    Kunemon, Coelamon, Nanimon, Vademon and Sukamon. Each becomes a random
    partner species of the same level. Mirrors the standalone's
    ``evolution.SpecialEvolutions``.
    """

    display_name = "Digivolution: Special Digivolutions"


class PartnerRaising(Toggle):
    """Randomize every Rookie, Champion and Ultimate species' raising parameters:
    favourite food (any food item), sleep schedule (one of the six normal
    schedules), home region (the biome that cheers the partner up), training
    aptitude (which stats train 10 % better or worse) and birth weight (inside the
    level's vanilla band). Meals, energy and toilet timing — the care-mistake
    economy — are never touched. The spoiler lists every species' new profile.
    """

    display_name = "Partner Raising Parameters"


class BgmShuffle(Choice):
    """Randomize the background music of the field and town screens.

    * ``off`` — vanilla music.
    * ``areas`` — every vanilla theme is replaced by one other theme everywhere it
      played (the one-theme-per-area feel is kept).
    * ``screens`` — every screen draws its own theme.
    * ``chaos`` — like ``screens``, and the looping battle themes join the draw.

    Day / night pairs follow the theme; scripted music overrides (bosses, Toy Town,
    Mt. Infinity, the arena jingles) stay vanilla. Pure data rewrite of the screen
    scripts — the game streams whichever theme is asked for.
    """

    display_name = "Music Shuffle"
    option_off = 0
    option_areas = 1
    option_screens = 2
    option_chaos = 3
    default = option_off


class InGameNotifications(DefaultOnToggle):
    """Show Archipelago events in the game: an item received from the
    multiworld ("Got: Meat from Link") or one you found for another player
    ("Sent: Master Sword to Link") appears as a short banner in the top-right
    corner of the screen for about five seconds while you walk around, drawn
    the way area names are; the other player's name is dropped when the
    message would not fit. Messages are deferred — never lost — while a menu,
    a dialog, a battle or a screen change is in progress, and shown one at a
    time.
    """

    display_name = "In-Game Notifications"


class FixDVChipText(DefaultOnToggle):
    """Correct the three DV chip descriptions to say what the chips actually do
    (DV Chip E boosts HP and MP, not Offense and Speed). Text only. Mirrors the
    standalone's ``patches.FixDVChips``.
    """

    display_name = "Fix DV Chip Descriptions"


@dataclass
class DigimonWorldOptions(PerGameCommonOptions):
    goal: Goal
    prosperity_goal: ProsperityGoal
    fast_drimogemon: FastDrimogemon
    easy_monochromon: EasyMonochromon
    skip_intro: SkipIntro
    infinite_auto_pilot: InfiniteAutoPilot
    item_stat_gain: ItemStatGain
    type_lock_unlocks: TypeLockUnlocks
    bridge_unlock: BridgeUnlock
    great_canyon_unlock: GreatCanyonUnlock
    lava_cave_access: LavaCaveAccess
    region_locking: RegionLocking
    region_locking_list: RegionLockingList
    starting_region: StartingRegion
    spawn_rate_boost: SpawnRateBoost
    stat_gain_multiplier: StatGainMultiplier
    combat_stat_multiplier: CombatStatMultiplier
    chest_randomization: ChestRandomization
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
    card_trade_multiplier: CardTradeMultiplier
    piximon_manual_location: PiximonManualLocation
    frigimon_recruit_location: FrigimonRecruitLocation
    mojyamon_recruit_location: MojyamonRecruitLocation
    vending_locations: VendingLocations
    recycle_shop_locations: RecycleShopLocations
    merit_shop_locations: MeritShopLocations
    item_shop_locations: ItemShopLocations
    secret_shop_locations: SecretShopLocations
    shop_price_mode: ShopPriceMode
    shop_price_min: ShopPriceMin
    shop_price_max: ShopPriceMax
    fishing_locations: FishingLocations
    arena_locations: ArenaLocations
    technique_rewards: TechniqueRewards
    enemy_stats: EnemyStats
    enemy_stats_strength: EnemyStatsStrength
    enemy_randomization: EnemyRandomization
    enemy_randomization_tier: EnemyRandomizationTier
    enemy_technique_weights: EnemyTechniqueWeights
    technique_data: TechniqueData
    technique_power: TechniquePower
    technique_mp_cost: TechniqueMPCost
    technique_accuracy: TechniqueAccuracy
    technique_effect: TechniqueEffect
    technique_effect_chance: TechniqueEffectChance
    species_technique_lists: SpeciesTechniqueLists
    type_effectiveness: TypeEffectiveness
    enemy_drop_items: EnemyDropItems
    enemy_drop_rates: EnemyDropRates
    enemy_drops_match_value: EnemyDropsMatchValue
    enemy_drops_value_cutoff: EnemyDropsValueCutoff
    tech_gifts: TechGifts
    tokomon_gifts: TokomonGifts
    tokomon_gifts_consumable_only: TokomonGiftsConsumableOnly
    digivolution_randomization: DigivolutionRandomization
    digivolution_obtain_all: DigivolutionObtainAll
    digivolution_requirements: DigivolutionRequirements
    special_digivolutions: SpecialDigivolutions
    digivolution_stat_gains: DigivolutionStatGains
    partner_raising: PartnerRaising
    bgm_shuffle: BgmShuffle
    quest_items_droppable: QuestItemsDroppable
    increase_learn_chance: IncreaseLearnChance
    brain_training_tier_one: BrainTrainingTierOne
    unrig_slots: UnrigSlots
    learn_move_and_command: LearnMoveAndCommand
    fix_dv_chip_text: FixDVChipText
    in_game_notifications: InGameNotifications
    god_mode: GodMode


option_groups: list[OptionGroup] = [
    OptionGroup("Goal", [Goal, ProsperityGoal]),
    OptionGroup(
        "Randomization",
        [
            ChestRandomization, TechniqueRewards,
            GroundItemRandomization, GroundItemFoodOnly,
            GroundItemMatchValue, GroundItemValueCutoff,
            StarterRandomization, StarterAllowFresh,
            StarterAllowInTraining, StarterAllowRookie,
            StarterAllowChampion, StarterAllowUltimate,
            StarterUseWeakestTech,
            EnemyStats, EnemyStatsStrength,
            EnemyRandomization, EnemyRandomizationTier, EnemyTechniqueWeights,
            TechniqueData, TechniquePower, TechniqueMPCost, TechniqueAccuracy,
            TechniqueEffect, TechniqueEffectChance, SpeciesTechniqueLists, TypeEffectiveness,
            EnemyDropItems, EnemyDropRates, EnemyDropsMatchValue, EnemyDropsValueCutoff,
            TechGifts, TokomonGifts, TokomonGiftsConsumableOnly,
            DigivolutionRandomization, DigivolutionObtainAll, DigivolutionRequirements,
            SpecialDigivolutions, DigivolutionStatGains,
            PartnerRaising, BgmShuffle,
        ],
    ),
    OptionGroup(
        "Locations",
        [CardLocations, VendingLocations, RecycleShopLocations, MeritShopLocations,
         ItemShopLocations, SecretShopLocations, ShopPriceMode, ShopPriceMin,
         ShopPriceMax, FishingLocations, PiximonManualLocation,
         FrigimonRecruitLocation, MojyamonRecruitLocation],
    ),
    OptionGroup(
        "Quality of Life",
        [
            FastDrimogemon, EasyMonochromon, SkipIntro, InfiniteAutoPilot,
            ItemStatGain,
            TypeLockUnlocks, BridgeUnlock, GreatCanyonUnlock, LavaCaveAccess,
            RegionLocking, RegionLockingList, StartingRegion,
            SpawnRateBoost, StatGainMultiplier, CombatStatMultiplier,
            CardTradeMultiplier,
            QuestItemsDroppable, IncreaseLearnChance, BrainTrainingTierOne,
            UnrigSlots, LearnMoveAndCommand, FixDVChipText, InGameNotifications,
        ],
    ),
    OptionGroup("Testing", [GodMode]),
]
