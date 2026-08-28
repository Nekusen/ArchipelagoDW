# Savestate requests — the RE lab's shopping list

The decomp bar is 100% replay of **emulator-captured** call vectors ([DECOMP_PROCESS.md](DECOMP_PROCESS.md)).
Capturing them needs the game to actually execute the function, which needs a savestate that
reaches it. The lab already holds 32 states in `work\dw1_re\` (inventoried in DECOMP_PROCESS.md
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

**Most screens no longer need a human at all** (2026-08-28):
`python worlds/digimon_world/tools/dw1_warp_state.py --map <id> --out <name>` warps there through
the debug map and saves once `CURRENT_SCREEN` confirms the landing. What still needs a person is
*state* the warp cannot set up -- a dialog open at the right line, a battle in progress, an item
in hand -- so the rows below describe that.

Positioning rule of thumb: **stop one input short of the event**. The most useful states in the
lab are the ones sitting on an open dialog or one step from a transition, because the capture
harness can then drive the event itself.

## Captured 2026-08-28 (user session, vanilla ISO, PCSX-Redux)

| State | Position | Facts |
| --- | --- | --- |
| `training_gym.state` | Green Gym, HP machine, menu open, cursor on **Begin** | Fresh Agumon 80/60/70/70, HP 800 / MP 600, 0 Bits -- **no god mode**, gains are real |
| `fishing.state` | At a fishing spot, rod equipped, one input before casting | Triggers 45+46 (old + Amazing rod), bait Meat/Giant Meat/Sirloin x5 in slots 0-2 |
| `debug_warp.state` | **Debug map** (Jijimon's house area), Mr. Warp dialog open | Debug triggers 54/55 clear. **Teleport hub**: the resident script 164 sits at 0x1B9ED8; poke byte +1941 (map id of "Near -> peak of Mt. Panorama", vanilla 0x12) to any map id and that menu entry warps there. Used for the three below. |
| `machinedramon.state` | Mt. Infinity L13 (map 225 MGEN99), walking UP starts the final boss | God mode; trigger 50 NOT set |
| `mt_infinity.state` | Mid Mt. Infinity (map 219 MGEN05) | God mode |
| `back_dimension.state` | Back Dimension (map 226 MGEN11) | God mode; trigger 50 (game beaten) SET |

Session rules learned the hard way (three emulator crashes): during a user-driven session use
**no per-frame Lua listeners** (`dw1_redux_input.lua`), **no REST data GETs** (`peek`/screenshot
-- both now pause the emulator or read via Lua), and save with `PCSX.pauseEmulator()` around
`createSaveState()`. Full log: `work/dw1_re/session_2026-08-28_savestates.md`.

## Open requests

**Re-triaged 2026-08-28 after adopting dw_decomp.** Every branch these rows were opened for has
since been read in dw_decomp's byte-matching C and found to agree with our models (cross-check
recorded in each unit's NOTES.md and the ledger). So **no row below is needed for
understanding any more**. What a state still buys is one of two things, named in the last
column:

- **patch validation** — exercising a shipped or planned patch in the real game (the reason
  that survives; these keep their priority);
- **provenance** — turning a PARTIAL ledger row into VERIFIED with natural vectors instead of
  a synthetic sweep or a C cross-check (nice to have; priority lowered).

| Priority | Filename | Position it at | Unblocks |
| --- | --- | --- | --- |
| Low (provenance) | `species_raised.state` | Any save where at least one Digimon species has already been **raised** — a partner that reached Champion and later died or was reborn, so the "ever raised" flag is set. | `hasDigimonRaised` @ 0x800FF824 PARTIAL → VERIFIED. dw_decomp confirms `isTriggerSet(id + 0x200)` and that the flag is set only by `setDigimonRaised` at reincarnation (family 512..574). Nothing shipped depends on the `v0 == 1` path. |
| Low (provenance) | `numeric_ui.state` | A screen whose text contains bracket/backtick punctuation. **Digits are already covered.** | `convertAsciiToJis` punctuation runs — C-confirmed (`main.c:929-938`). |
| Low (config change) | *(no state needed)* | Re-run the `renderString` capture with the `0x801BE958` window at **0xE10** plus a `pre` region on `renderCharacter`. | Converts 446 window-limited skips; no new gameplay. |
| Low (provenance) | `long_text.state` | A line long enough to push a string past x = 0xF4 (max observed 0xF0). | `renderCharacter` 0xF4 clamps — C-confirmed (`script_draw.c:789-795`). |
| Medium (patch validation) | `post_battle_learn.state` | Mid-battle, one input before the finishing blow, partner not yet knowing the technique it is about to learn — ideally Dynamite Kick (slot 44) or Horizontal Kick (slot 55). | Natural evidence for the shipped companion-bit fix (`d8048b33`) and the first state on the **enemy-stat scaling** validation path (`battleStatsGainsAndDrops`). The `learnMove` model itself is C-confirmed. |
| Medium (patch validation) | `digivolve_accepted.state` | Holding a digivolution item, one input before the requirement evaluation, partner near a requirement boundary. | Validation of any future AP digivolution item against `calculateRequirementScore` (in C: `evolution.c`; the "ever raised" veto and the OR-ed bonus conditions are now known). `getNumMasteredMoves` PARTIAL → VERIFIED as a by-product. |
| Low (provenance) | `script_vm_cold_start.state` | Before the first script of a screen runs. | `callScriptSection`'s 43 replay-invisible stores are all C-confirmed with exact widths (`script_engine.c:95-120`). Only needed for provenance, or to test a script-start hook if one is ever designed. |
| Medium (patch validation) | `dialog_columns.state` | A dialog using the tab/skip control codes (multi-column stat readout, arena board). | The seven control codes are C-confirmed (`script_common.c:2601-2701`). The state is now for **testing an injected notification string** that uses them — the in-game notifications feature. |

## Anticipated gaps

Systems with no state in the lab at all. Not blocking anything today; listed so a future capture
session can cover them in one pass rather than one interruption at a time.

| Priority | Filename | Position it at | Unblocks |
| --- | --- | --- | --- |
| Medium | `card_trade.state` | ShogunGekomon, **"Show a Digimon card"** submenu open, holding a high count of many card types | The card-value path. `shop_merit.state` stops at the dialog root; the trade submenu is the part that was patched for the card multiplier and it has never been vector-captured. |
| Low | `rebirth.state` | Partner about to die / one input before rebirth | The rebirth + technique-mastery reconciliation path (mastery bitmap survives rebirth — asserted, never replayed). |
| Low | `piximon_shop.state` | Inside the item-shop building **with Piximon present** (2-in-10 roll per entry — re-enter until he shows) | The Piximon Training Manual check, currently shipped on static analysis plus one live confirmation. |

## Known non-savestate blockers

These look like savestate problems but are not — do **not** add states for them:

- **Battle internals.** `battle_pending.state` already reaches a real battle, and since
  2026-08-28 the battle overlay is readable as C in `references/dw_decomp/src/btl/` (94 % of it).
  What is left there is design work, not capture work. (Before dw_decomp the blocker was that
  no overlay was imported into Ghidra; that import is now only needed to vector-capture an
  overlay function that is ASM-only upstream.)
- **Arena post-fight exit.** Hangs deterministically in PCSX-Redux only (BIOS busy-wait at
  0x800C8F98); fine on BizHawk/DuckStation. `arena_hang_repro.state` preserves it. Nothing a new
  state can fix.
- **Gekomon recruit** and the **Whamon / Ogremon quest softlocks.** These need the user's *text*
  (the vanilla recruit method; the repro recipes), not a savestate. Tracked in the `dw1-backlog`
  memory.
