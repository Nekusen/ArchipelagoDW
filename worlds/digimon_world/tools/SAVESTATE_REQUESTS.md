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
| Low | `numeric_ui.state` | A screen whose text contains bracket/backtick punctuation (`[ \ ] ^ _ ` `` ` `` `{ | } ~`) — a credits roll or similar. **Digits are already covered — do not capture for those.** | `convertAsciiToGameChar` @ 0x800F18C8. The 2026-08-23 widened capture closed the digit gap (54 calls on 0x30-0x39, all replayed green). Still uncovered: the 0x5B-0x60 (bias 0x25) and 0x7B-0x7E (bias 0x3F) punctuation runs and the out-of-range `return 0` — 3 of 30 mutants survive on exactly those. |
| Low | *(no state needed — a capture-config change)* | Re-run the `renderString` unit's capture with the `0x801BE958` window at **0xE10** instead of 0x8A0, plus a `pre` region for the staging array on `renderCharacter`. The same savestates regenerate it; no new gameplay. | `renderString` @ 0x8010CF24: 446 of 780 replayable vectors are window-limited skips purely because staging slots 30..49 were never dumped, and 1226 `renderCharacter` vectors are store-target-only for want of a pre snapshot. |
| Low | `long_text.state` | A dialog or menu line long enough to push a string past x = 0xF4 — a wide item/technique description, or the credits. The maximum `xPos`/`yPos` ever observed is **0xF0**, so the line need only run about four pixels further. | `renderCharacter` @ 0x8010CC28. 2034 vectors, none with `xPos >= 0xF4` or `yPos >= 0xF4`, so both clamp branches are unreplayed. |
| High | `post_battle_learn.state` | Mid-battle, one input before the finishing blow, with the partner **not yet** having mastered the technique it is about to learn — ideally a Rookie/Champion whose next mastery is Dynamite Kick (slot 44) or Horizontal Kick (slot 55). | `learnMove` @ 0x800E5F14. Its 6 natural vectors are all `learnMove(2)` from partner spawn onto an already-set bit, so the natural class catches only 2 of 6 mutants. The companion-pair behaviour, the word index and the negative path are proven by a synthetic sweep only. |
| High | `digivolve_accepted.state` | Holding a digivolution item, **one input before** the digivolution is evaluated, on a partner whose stats sit near a requirement boundary so the "techniques mastered" requirement is actually consulted. | `getNumMasteredMoves` @ 0x800E3510 — **zero** natural vectors; ships PARTIAL despite 232 synthetic ones with excellent coverage. Also the only route to natural vectors for its sole caller `calculateRequirementScore` @ 0x800E26B8 and the digivolution requirement table at 0x8012ABEC. |
| Medium | `script_vm_cold_start.state` | **Before** the first script of a screen runs — a screen transition, or a cold boot into the intro — rather than mid-dialog. Ideally save several, on different screens, so more than 20 distinct `(scriptId, sectionId, value)` triples become reachable. | `callScriptSection` @ 0x80105B14. 43 of its 58 stores are *invisible* to any comparator because every existing capture is mid-dialog: the target already holds the value being written (0x80134E30 already 1, pstat 0 always 0, 0x80134C9C never >= 0x80, slot +0x14 already 1, tag entries already 0xFF). The lab can poke those to non-default values between reloads, but only if capture starts before a script does. Also the only way to reach a `getScript` cache-MISS inside this function — currently 0 of 183. |
| Medium | `dialog_columns.state` | A dialog whose text uses the *tab* and *skip* control codes rather than the shop-list column setters — most likely a multi-column stat/status readout (technique list, digimon status page, arena results board) or a screen with inline icon/wait markers. Dialog already open, one input before the page that lays out in columns. | `dialogRenderString` @ 0x80100948. Its 2609 vectors execute only 0x01/0x0F/0x16/0x18/0x19/0x1A; the seven remaining opcodes — 0x02/0x03 (2- and 4-byte skips), 0x0C/0x0E (tab to the next 8-/11-cell boundary) and 0x17/0x1B/0x1C (column setters) — are asm-derived only, and 7 of 40 mutants survive on exactly those. They are also the codes an injected notification string would want. Secondary: no capture has `0x80134F98 != 0`, and no call ever passes `x != 0`. |

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
