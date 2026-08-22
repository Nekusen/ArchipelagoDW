# Savestate requests — the RE lab's shopping list

The decomp bar is 100% replay of **emulator-captured** call vectors ([DECOMP_PROCESS.md](DECOMP_PROCESS.md)).
Capturing them needs the game to actually execute the function, which needs a savestate that
reaches it. The lab already holds 26 states in `work\dw1_re\` (inventoried in DECOMP_PROCESS.md
step 4) and they cover a lot — but not everything.

**This file is the queue.** When a decomp is blocked only by "no savestate reaches this code",
the unit is recorded as `PROVISIONAL` in `work\dw1_re\decomp\LEDGER.md` and a row is added here.
The user captures the batch in one sitting whenever convenient; the blocked units then get
verified without any further human involvement.

## How to capture one (5 minutes, no tooling knowledge needed)

1. Launch the lab emulator on the **vanilla** ISO:
   `powershell -ExecutionPolicy Bypass -File worlds\digimon_world\tools\dw1_redux_launch.ps1`
2. Play to the moment described in the row below. The god-mode / debug-menu accelerators in
   `dw1_debug_enable.lua` and the `dw1_debug_menu` memory make this much faster than a real run.
3. Save a state and name it exactly as the row's **filename** column says, into `work\dw1_re\`.
4. Nothing else — no dumps, no notes. The row says what the state must be positioned at; getting
   the position right matters more than the surrounding save data.

Positioning rule of thumb: **stop one input short of the event**. The most useful states in the
lab are the ones sitting on an open dialog or one step from a transition, because the capture
harness can then drive the event itself.

## Open requests

These rows are **live**: each one is a decomp that captured vectors but could not reach a branch
or an input class, so the unit ships PARTIAL until the state exists. Raised by the 2026-08-22
batch (callScriptSection / renderString / hasDigimonRaised / scriptIdToEntityId / isKeyDown /
dailyPStatTrigger).

| Priority | Filename | Position it at | Unblocks |
| --- | --- | --- | --- |
| High | `species_raised.state` | Any save where at least one Digimon species has already been **raised** — a partner that reached Champion and later died or was reborn, so the "ever raised" flag is set. The collection/graveyard list must show at least one entry. | `hasDigimonRaised` @ 0x800FF824. All 2866 captured vectors return 0, even on the all-50-recruits `shop_secret` save, because **trigger 512+X is an "ever raised" flag, not a recruit bit**. The `v0 == 1` branch has never been observed; without it the unit can only be PARTIAL. |
| Medium | `numeric_ui.state` | Any screen drawing **digits** as text — a shop with prices visible, or the Bits counter mid-change; ideally with punctuation on screen too. | `convertAsciiToGameChar` @ 0x800F18C8. 41 distinct inputs captured, not one a digit. The entire digit class (base 0x824F / bias 0x30) and the out-of-range `return 0` branch are asm-derived only. |
| Low | `long_text.state` | A dialog or menu line long enough to push a string past x = 0xF4 — a wide item/technique description, or the credits. | `renderCharacter` @ 0x8010CC28. 2034 vectors, none with `xPos >= 0xF4` or `yPos >= 0xF4`, so both clamp branches are unreplayed. |

## Anticipated gaps

Systems with no state in the lab at all. Not blocking anything today; listed so a future capture
session can cover them in one pass rather than one interruption at a time.

| Priority | Filename | Position it at | Unblocks |
| --- | --- | --- | --- |
| High | `fishing.state` | Standing at a fishing spot with a rod equipped, **one input before** casting; ideally with several bait items in the bag | The whole fishing subsystem. The lab has **no** fishing state at all, and 6 of the 31 ITEM_PARA reader sites live in `FISH_REL` — they have only ever been checked statically, never replayed. |
| High | `training_gym.state` | In front of a training machine, dialog open, one input before starting a session | Stat-gain routines — the prerequisite for the deferred **enemy-stat scaling** feature, which needs to know how the game's own stat maths works. |
| Medium | `mt_infinity.state` | Anywhere inside Mt. Infinity, mid-run | Late-game scripts and the **heap-margin** question flagged in the BizHawk checklist (the 8 KB ITEM_PARA claim vs late-game allocations is unmeasured post-game). |
| Medium | `machinedramon.state` | At the final fight, one input before it starts | The ending sequence and `trigger 50` (game-beaten) path. |
| Medium | `back_dimension.state` | Inside Back Dimension | Post-game region scripts; same heap question as Mt. Infinity. |
| Medium | `card_trade.state` | ShogunGekomon, **"Show a Digimon card"** submenu open, holding a high count of many card types | The card-value path. `shop_merit.state` stops at the dialog root; the trade submenu is the part that was patched for the card multiplier and it has never been vector-captured. |
| Low | `rebirth.state` | Partner about to die / one input before rebirth | The rebirth + technique-mastery reconciliation path (mastery bitmap survives rebirth — asserted, never replayed). |
| Low | `piximon_shop.state` | Inside the item-shop building **with Piximon present** (2-in-10 roll per entry — re-enter until he shows) | The Piximon Training Manual check, currently shipped on static analysis plus one live confirmation. |

## Known non-savestate blockers

These look like savestate problems but are not — do **not** add states for them:

- **Battle internals.** `battle_pending.state` already reaches a real battle. The blocker is that
  `BTL_REL` (and the other 15 overlays) are **not imported into the Ghidra project** — see the
  T4 tier note in DECOMP_PROCESS.md. That is tooling work, not capture work.
- **Arena post-fight exit.** Hangs deterministically in PCSX-Redux only (BIOS busy-wait at
  0x800C8F98); fine on BizHawk/DuckStation. `arena_hang_repro.state` preserves it. Nothing a new
  state can fix.
- **Gekomon recruit** and the **Whamon / Ogremon quest softlocks.** These need the user's *text*
  (the vanilla recruit method; the repro recipes), not a savestate. Tracked in the `dw1-backlog`
  memory.
