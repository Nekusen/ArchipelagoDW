"""Regenerate ``data/model_budget.py`` from the ``model_budget`` lab unit's output.

Inputs, all under the gitignored ``work/`` tree and produced by
``work/dw1_re/decomp/model_budget/``:

* ``species_models.csv``  -- each species' ``.MMD`` malloc3 request.
* ``screen_budget.csv``   -- the non-dominated MAPHEAD traces per screen.
* ``work/dw1_re/SLUS_010.32`` -- read directly for each species' ``DigimonPara.bone``,
  the multiplier behind the per-entity cost.

Verify a regeneration by re-deriving every screen's peak from the emitted tables and
comparing it against ``screen_budget.csv``'s ``peak`` column: they must agree on all
180 screens.

Usage: ``python worlds/digimon_world/tools/dw1_model_budget_table.py``
"""

from __future__ import annotations

import csv
import pathlib
import struct
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from dw1_enemy_census import DIGIMON_DATA, slus_bytes  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[3]
UNIT = REPO / "work" / "dw1_re" / "decomp" / "model_budget"
SLUS = REPO / "work" / "dw1_re" / "SLUS_010.32"
OUT = REPO / "worlds" / "digimon_world" / "data" / "model_budget.py"

SPECIES_COUNT = 180
BONE_FIELD_OFFSET = 20
DIGIMON_PARA_STRIDE = 52


def round8(value: int) -> int:
    return (value + 7) & ~7


def read_costs() -> tuple[dict[int, int], dict[int, int]]:
    """``(model cost, entity cost)`` per species, both in malloc3 bytes."""

    slus = SLUS.read_bytes()
    model: dict[int, int] = {}
    entity: dict[int, int] = {}
    for row in csv.DictReader((UNIT / "species_models.csv").open(encoding="utf-8")):
        species_id = int(row["id"])
        request = int(row["malloc_req"])
        model[species_id] = request + 8 if request else 0
        bone = struct.unpack_from(
            "<i", slus_bytes(slus, DIGIMON_DATA + species_id * DIGIMON_PARA_STRIDE
                             + BONE_FIELD_OFFSET, 4))[0]
        entity[species_id] = round8(82 * bone) + 8 + 136 * bone + 8
    return model, entity


def read_screens() -> tuple[dict[int, tuple], dict[int, int]]:
    """``(traces, script extra)`` per screen."""

    traces: dict[int, tuple] = {}
    extra: dict[int, int] = {}
    for row in csv.DictReader((UNIT / "screen_budget.csv").open(encoding="utf-8")):
        map_id = int(row["map"])
        parsed = tuple(
            ops for ops in (
                tuple((op[0], int(op[1:])) for op in trace.split(",") if op)
                for trace in row["traces"].split(";")
            ) if ops
        )
        if parsed:
            traces[map_id] = parsed
        if int(row["script_extra"]):
            extra[map_id] = int(row["script_extra"])
    return traces, extra


def emit_ints(table: dict[int, int]) -> str:
    body = ", ".join(f"{key}: {value}" for key, value in sorted(table.items()))
    return "\n".join("    " + line for line in textwrap.wrap(body, 112))


def emit_traces(table: dict[int, tuple]) -> str:
    lines = []
    for map_id, traces in sorted(table.items()):
        rendered = ", ".join(
            "(" + ", ".join(f'("{kind}", {species})' for kind, species in trace) + ",)"
            for trace in traces
        )
        lines.append("\n".join(
            "    " + line for line in
            textwrap.wrap(f"{map_id}: ({rendered},),", 112, subsequent_indent="    ")))
    return "\n".join(lines)


HEADER = '''"""Per-screen model-memory budget for Digimon World 1 -- GENERATED, do not edit by hand.

Regenerate with ``tools/dw1_model_budget_table.py``.  Produced by the ``model_budget`` lab
unit (``work/dw1_re/decomp/model_budget``), whose model is exact on 31 live screens and
validated by stress probes on both arenas, including real disc builds and real battles.

The game streams each field Digimon's ``.MMD`` model into the ``malloc3`` arena, whole,
rounded up to 2 KB.  Exceeding the arena is fatal but **not immediate**: ``handleNullModel()``
is empty, so a failed allocation leaves ``NPC_MODEL[i].useCount > 0`` with ``mmdPtr == 0``,
the screen finishes loading, and the address error lands a few frames later at
``pc 0x80000080`` when ``readFile(path, NULL)`` runs.  A budget rule must therefore be a hard
bound -- there is no graceful degradation to fall back on.

The player's partner and the tamer do NOT compete for this arena: ``loadMMD``'s
``modelType == 2 / 3`` paths contain no ``malloc3`` at all and read straight into static
``.bss`` buffers (``PARTNER_MODEL_BUFFER`` 0x801878DC, 100,352 B; ``TAMER_MODEL_BUFFER``
0x801A1398, 57,344 B).  That is why the partner may be any species in the game.  Both paths
still build the same ``CHDAT\\\\MMD<n>\\\\`` filename as a field enemy of that species -- there is
one model file per species -- and their transient texture stage never overlaps a loaded
screen (measured: partner models load before the map script runs, and digivolution takes
``loadMMDAsync``'s pre-streamed arm, which allocates nothing).

Four tables:

* :data:`SPECIES_MODEL_COST` -- ``species id -> malloc3 bytes`` for its model (file size
  rounded to 2 KB, plus the 8-byte block header).  Charged once per distinct species
  resident on the screen: ``loadMMD`` refcounts repeats through ``useCount`` and the
  short circuit returns before the texture stage.
* :data:`SPECIES_ENTITY_COST` -- ``species id -> malloc3 bytes`` per *placed* entity,
  ``round8(82*bone) + 8 + 136*bone + 8`` where ``bone`` is ``DIGIMON_DATA[id].bone`` (1..30).
  Up to 6,560 B each; OGRE03 spends 23,208 B on entity arrays alone.
* :data:`SCREEN_TRACES` -- ``screen -> non-dominated MAPHEAD traces``.  Each trace is the
  ordered sequence of ``("L", species)`` model loads and ``("P", species)`` entity
  placements one reachable path through the screen's MAPHEAD section performs.  Sections
  branch on triggers, the partner tier ``pstat(107)`` and File City's ``pstat(38)``, so the
  union of a section's ``loadDigimon`` opcodes badly over-counts what is ever simultaneously
  resident -- no reachable path loads more than three distinct models.
* :data:`SCREEN_SCRIPT_EXTRA` -- bytes the screen's own resident script can add on top.

Peak of a trace = the running total, with :data:`TEXTURE_STAGE_BYTES` live just before each
*first* load of a species (``loadDigimonTexture``'s transient buffer, freed before the model
allocation).  Measured boundary: a screen peaking at ``arena - 152`` plays; ``arena + 416``
faults.
"""

from __future__ import annotations

from typing import Final

#: Transient texture buffer live just before each species' first model load.
TEXTURE_STAGE_BYTES: Final = 18_440
'''


def main() -> int:
    model, entity = read_costs()
    traces, extra = read_screens()
    OUT.write_text(
        HEADER
        + "\n#: ``species id -> malloc3 bytes`` for the model (once per distinct resident species).\n"
        f"SPECIES_MODEL_COST: Final[dict[int, int]] = {{\n{emit_ints(model)}\n}}\n"
        + "\n#: ``species id -> malloc3 bytes`` per placed entity.\n"
        f"SPECIES_ENTITY_COST: Final[dict[int, int]] = {{\n{emit_ints(entity)}\n}}\n"
        + "\n#: ``screen -> extra malloc3 bytes the screen's own resident script can add``.\n"
        f"SCREEN_SCRIPT_EXTRA: Final[dict[int, int]] = {{\n{emit_ints(extra)}\n}}\n"
        + '\n#: ``screen -> non-dominated MAPHEAD traces`` (``("L", species)`` load /'
          ' ``("P", species)`` place).\n'
        "SCREEN_TRACES: Final[dict[int, tuple[tuple[tuple[str, int], ...], ...]]] = {\n"
        f"{emit_traces(traces)}\n}}\n",
        encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} B): {len(model)} species, {len(traces)} screens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
