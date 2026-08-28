r"""Cross-reference this world's address manifest against the dw_decomp symbol map.

The community decompilation of SLUS-01032 (``references/dw_decomp``, jype0/dw_decomp, MIT) is
byte-matching, so for any RAM address our manifest names there is usually a symbol -- and for a
function, a C file that IS the original code. This tool answers, for every RAM literal in
``data/addresses.py`` (and optionally other files): what does dw_decomp call it, what symbol
contains it and at which offset, and if it is a function, is it in C (which file) or still an
``INCLUDE_ASM`` stub?

Usage (from the repo root):

    python worlds/digimon_world/tools/dw1_decomp_xref.py                 # report to stdout
    python worlds/digimon_world/tools/dw1_decomp_xref.py -o worlds/digimon_world/tools/DW_DECOMP_XREF.md
    python worlds/digimon_world/tools/dw1_decomp_xref.py --files worlds/digimon_world/client.py
    python worlds/digimon_world/tools/dw1_decomp_xref.py --lookup 0x801BE174 --lookup 0x80100948

``--lookup`` skips the file scan and resolves the given addresses directly. Physical offsets
(``0x001BE174``) are accepted anywhere and normalised to KSEG0.

Only ``references/`` is read; nothing game-derived is written. The report contains our addresses
and dw_decomp's identifiers, both of which are fine to commit.
"""

from __future__ import annotations

import argparse
import bisect
import glob
import os
import re
import sys
from dataclasses import dataclass, field

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
DECOMP = os.path.join(REPO, "references", "dw_decomp")
DEFAULT_FILES = [os.path.join(REPO, "worlds", "digimon_world", "data", "addresses.py")]

RAM_LO, RAM_HI = 0x80000000, 0x80200000
SYM_RE = re.compile(r"^\s*(\w+)\s*=\s*0x([0-9A-Fa-f]+)\s*;(?:\s*//\s*(.*))?")
ATTR_RE = re.compile(r"(\w+):(\S+)")
LIT_RE = re.compile(r"0x([0-9A-Fa-f]{5,8})\b")
INCLUDE_ASM_RE = re.compile(r"INCLUDE_ASM\([^)]*,\s*(\w+)\s*\)")
# A definition with a body: return type + name + params + '{' (prototypes end in ';' and are
# excluded by the [^;{] class). Control-flow keywords are excluded by the lookahead.
DEF_RE = re.compile(
    r"^(?!\s*(?:if|for|while|switch|return|else)\b)"
    r"[A-Za-z_][\w\s\*,]*?\b(\w+)\s*\([^;{}]*\)\s*\{",
    re.M,
)


@dataclass
class Symbol:
    name: str
    addr: int
    size: int | None
    kind: str  # "func" or "data" ("data" also covers untyped)
    source: str  # symbols file basename


@dataclass
class FuncStatus:
    status: str  # "C" | "ASM" | "none"
    file: str = ""


@dataclass
class Hit:
    addr: int
    exact: Symbol | None
    container: Symbol | None
    offset: int
    func: FuncStatus | None
    mentions: list[str] = field(default_factory=list)


def norm(addr: int) -> int:
    """Physical RAM offset -> KSEG0; KSEG0/KSEG1 left as KSEG0."""
    if addr < 0x00200000:
        return 0x80000000 | addr
    if 0xA0000000 <= addr < 0xA0200000:
        return 0x80000000 | (addr & 0x1FFFFF)
    return addr


def load_symbols() -> list[Symbol]:
    syms: list[Symbol] = []
    for path in sorted(glob.glob(os.path.join(DECOMP, "config", "symbols*.txt"))):
        src = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = SYM_RE.match(line)
                if not m:
                    continue
                attrs = dict(ATTR_RE.findall(m.group(3) or ""))
                size = int(attrs["size"], 16) if "size" in attrs else None
                kind = "func" if attrs.get("type") == "func" else "data"
                syms.append(Symbol(m.group(1), int(m.group(2), 16), size, kind, src))
    syms.sort(key=lambda s: s.addr)
    return syms


def load_func_status() -> dict[str, FuncStatus]:
    """Every function name that has a C definition or an INCLUDE_ASM stub, and where."""
    status: dict[str, FuncStatus] = {}
    for path in glob.glob(os.path.join(DECOMP, "src", "**", "*.c"), recursive=True):
        rel = os.path.relpath(path, DECOMP).replace("\\", "/")
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"//.*", "", text)
        for name in INCLUDE_ASM_RE.findall(text):
            status[name] = FuncStatus("ASM", rel)
        for name in DEF_RE.findall(text):
            status.setdefault(name, FuncStatus("C", rel))
    return status


def scan_literals(files: list[str]) -> dict[int, list[str]]:
    """Distinct RAM addresses -> up to three 'file:line' mentions."""
    found: dict[int, list[str]] = {}
    for path in files:
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        with open(path, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for lit in LIT_RE.findall(line):
                    v = int(lit, 16)
                    if v >= 0x10000000 and not (RAM_LO <= v < RAM_HI or 0xA0000000 <= v < 0xA0200000):
                        continue  # ROM offsets and other constants
                    if v < 0x00010000:
                        continue  # small ints that happen to be written in hex
                    a = norm(v)
                    if not RAM_LO <= a < RAM_HI:
                        continue
                    lst = found.setdefault(a, [])
                    if len(lst) < 3:
                        lst.append(f"{rel}:{n}")
    return found


def resolve(addr: int, syms: list[Symbol], addrs: list[int], fstat: dict[str, FuncStatus]) -> Hit:
    """Exact symbol, else the sized symbol containing ``addr``, else the function whose span
    (up to the next symbol) covers it.

    dw_decomp's symbol files almost never carry ``type:func`` (3 lines in 6600), so "is this a
    function" is decided by whether the name has a C definition or an INCLUDE_ASM stub in
    ``src/`` -- not by the symbol file. Functions also have no ``size:``; their span is taken
    to end at the next symbol, which is how the free space our patches claim inside a
    function's tail resolves to ``thatFunction +0xNN``.
    """

    i = bisect.bisect_right(addrs, addr) - 1
    exact = container = None
    offset = 0
    j = i
    exacts = []
    while j >= 0 and syms[j].addr == addr:
        exacts.append(syms[j])
        j -= 1
    if exacts:
        exact = next((s for s in exacts if s.name in fstat), exacts[-1])
    else:
        k = i
        while k >= 0 and addr - syms[k].addr < 0x10000:
            s = syms[k]
            if s.size and s.addr <= addr < s.addr + s.size:
                container, offset = s, addr - s.addr
                break
            k -= 1
        if container is None and i >= 0:
            # No sized symbol: fall back to the nearest preceding symbol, bounded by the next
            # one. For a function that is the code it sits in; for a PsyQ library routine
            # (no C in src/, so `kind` stays unknown) it is still the right neighbourhood --
            # that is exactly the information a Cave6 free-space address needs.
            s = syms[i]
            nxt = addrs[i + 1] if i + 1 < len(addrs) else RAM_HI
            if addr < nxt and addr - s.addr < 0x4000:
                container, offset = s, addr - s.addr
                if s.name not in fstat:
                    s.kind = "span?"
    sym = exact or container
    func = None
    if sym and sym.name in fstat:
        sym.kind = "func"
        func = fstat[sym.name]
    return Hit(addr, exact, container, offset, func)


def fmt_row(h: Hit) -> str:
    if h.exact:
        name, where = h.exact.name, h.exact.source
    elif h.container:
        name, where = f"{h.container.name} +0x{h.offset:X}", h.container.source
    else:
        name, where = "(none)", ""
    kind = (h.exact or h.container).kind if (h.exact or h.container) else ""
    if kind == "func" and h.func and h.func.status == "none":
        kind = "func?"
    if h.func is None:
        src = ""
    elif h.func.status == "C":
        src = f"C: `{h.func.file}`"
    elif h.func.status == "ASM":
        src = f"**ASM stub** in `{h.func.file}`"
    else:
        src = "no source (library?)"
    mentions = ", ".join(h.mentions)
    return f"| `0x{h.addr:08X}` | `{name}` | {kind} | {src} | {where} | {mentions} |"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--files", nargs="*", default=None, help="files to scan (default: data/addresses.py)")
    ap.add_argument("--lookup", action="append", default=[], help="resolve one address (repeatable)")
    ap.add_argument("-o", "--out", default=None, help="write the Markdown report here instead of stdout")
    args = ap.parse_args(argv)

    if not os.path.isdir(DECOMP):
        sys.stderr.write(f"dw_decomp not found at {DECOMP} -- clone jype0/dw_decomp into references/\n")
        return 2

    syms = load_symbols()
    addrs = [s.addr for s in syms]
    fstat = load_func_status()

    if args.lookup:
        for text in args.lookup:
            h = resolve(norm(int(text, 16)), syms, addrs, fstat)
            sys.stdout.write(fmt_row(h) + "\n")
        return 0

    files = args.files or DEFAULT_FILES
    found = scan_literals([os.path.join(REPO, f) if not os.path.isabs(f) else f for f in files])
    hits = []
    for a in sorted(found):
        h = resolve(a, syms, addrs, fstat)
        h.mentions = found[a]
        hits.append(h)

    n_exact = sum(1 for h in hits if h.exact)
    n_cont = sum(1 for h in hits if not h.exact and h.container)
    n_none = sum(1 for h in hits if not h.exact and not h.container)
    n_func = sum(1 for h in hits if h.func)
    n_c = sum(1 for h in hits if h.func and h.func.status == "C")
    n_asm = sum(1 for h in hits if h.func and h.func.status == "ASM")
    head = os.popen(f'git -C "{DECOMP}" log -1 --format=%h').read().strip() or "?"

    out = []
    out.append("# Address manifest x dw_decomp symbol map")
    out.append("")
    out.append(f"Generated by `tools/dw1_decomp_xref.py` against dw_decomp `{head}`. Regenerate after")
    out.append("either side changes; do not edit by hand.")
    out.append("")
    out.append(f"Scanned: {', '.join(os.path.relpath(f, REPO).replace(chr(92), '/') for f in files)}.")
    out.append(f"{len(hits)} distinct RAM addresses: **{n_exact} exact symbol**, {n_cont} inside a sized symbol, "
               f"{n_none} unnamed. {n_func} resolve to functions: **{n_c} in C**, {n_asm} ASM stubs.")
    out.append("")
    out.append("`+0xN` = offset inside the containing symbol. The last column is where our code mentions the")
    out.append("address (first three). Names are dw_decomp's, not ours -- treat this as the bridge between")
    out.append("the two vocabularies, not as a rename list.")
    out.append("")
    out.append("| Address | dw_decomp symbol | kind | source | symbols file | mentioned at |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    out.extend(fmt_row(h) for h in hits)
    text = "\n".join(out) + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        sys.stdout.write(f"wrote {args.out}: {len(hits)} addresses ({n_exact} exact, {n_c} functions in C)\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
