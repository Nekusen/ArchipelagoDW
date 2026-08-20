# Patch-Testing Flow — PoC RESULT (2026-08-20) and next steps

**Status: PoC COMPLETE.** The loop works: decomp -> C-model net -> live-RAM net ->
one confirming build. Total confirming builds needed: **1** (vs the historical
dozens-of-builds cycle). The live-RAM net caught a design-breaking wrong assumption
(see below) in one iteration, before any ISO existed — exactly the failure class that
used to burn build-test cycles.

## What was proven

1. **Decomp**: `build_shop_runtime_list` @ 0x800FA834 VERIFIED 16/16 vectors
   (work\dw1_re\decomp\build_shop_runtime_list\, LEDGER row added). Stock is dynamic:
   trigger `384+id` per item id 0..127; flags = signed affordability + inventory-fit
   (ids @ 0x8013D474, counts @ 0x8013D492, capacity @ 0x8013D4CE, 0x63 = full stack).
2. **Discovery that killed design v1**: 0x800FA834 is the GENERIC money-shop builder
   (File City item shop + secret shop run it too; each shop's script pre-populates the
   384..511 stock triggers). An ungated body replacement would have corrupted every
   money shop — found in RAM iteration 1, fixed as v2 (screen-gated Cave6 wrapper
   @ 0x80095F40 + dispatcher jal redirect @ 0x800FC6AC).
3. **Tool**: `dw1_apply_patch.py` — one JSON spec drives `apply` (live-RAM pokes),
   `verify` (readback diff, works both on poked RAM and on a booted patched ISO),
   `to-iso` (sector-aware .bin writes + EDC diff-recalc via data/edc.py). Spec builder:
   `work\dw1_re\patches\build_recycle_poc_spec.py` -> `recycle_shop_poc.json`.
4. **Behavioral evidence (live RAM over shop_recycle.state)**: AP rows render with ext
   ITEM_PARA names/prices + desc strings; purchase deducts money, fires trigger 904,
   delivers nothing to inventory; money-gating greys rows; city/secret shops stay
   vanilla under the same patch. Confirming build boots; `verify` = 13/13 OK from a
   natural disc load.

## Production follow-up (needs the user's go)

Wire the v2 patch into `rom.py`'s `_write_recycle_shop_tokens` (wrapper bytes + jal
redirect as two more tokens; addresses into `data/addresses.py`) and DELETE the client's
`_reconcile_recycle_shop_array` polling reconciler. Bonus: this removes the latent
client hazard where ANY money shop with entry_count == 7 got AP-ified by the
fingerprint check. Cave6 free-space bookkeeping: the wrapper claims
0x80095F40..0x80095FB0 (112 B) — update the Cave6 layout comment when wiring.

## Next patch-testing targets

- **Zone-transition gating** (the second randomizer priority): dispatcher
  `FUN_80105bd8` @ 0x80105bd8 switches on destination map id; real changeMap
  `FUN_800d8e64`. OPEN THREAD to resolve first: field-edge walk transitions (LEFT at
  `zone_transition.state`) did not fire the screen-id write watchpoint nor the three
  static stores, while door/script transitions did (ra=0x80105c34) — find the
  field-walk path before designing the gate. Bundles in
  work\dw1_re\decomp\_scan_changeMap_orchestrator\.
- **Merit Shop QoL** (card-trade value): analyze the "Show a Digimon card" path.

## Session recipes that worked

Generalized into the standing runbook: [PATCH_PROCESS.md](PATCH_PROCESS.md) ("Session
recipes and gotchas"). Follow that document — this file only records the PoC outcome and
the target list above.
