import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.DataUtilities;
import ghidra.program.model.data.DataUtilities.ClearDataMode;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

// Applies dw_decomp's global-variable types to the DW1 program. Reads every
//     extern <Type> [*]NAME[dims];
// line in include/dw/*.h, finds the symbol NAME (imported by DW1ImportSymbols.java) and sets the
// data type at its address -- so `PARTNER_ENTITY` becomes a PartnerEntity and the decompiler
// renders `PARTNER_ENTITY.learnedMoves[1]` instead of `*(int *)0x80155804`.
//
// Requires DW1ImportSymbols.java (names) and DW1ImportHeaders.java (types) to have run first.
// Existing data at the address is cleared to make room; code is never touched (a NAME that
// resolves to a function is skipped and reported).
//
// Headless usage (writes the project; serialize with other Ghidra runs):
//   powershell -File worlds\digimon_world\tools\dw1_ghidra.ps1 -Script DW1ApplyExternTypes.java
//       references\dw_decomp\include\dw
public class DW1ApplyExternTypes extends GhidraScript {
    // extern  Type  [*]  NAME  [N][M] ;   (Type may be `struct X` or `unsigned int` etc.)
    private static final Pattern EXTERN = Pattern.compile(
            "^\\s*extern\\s+((?:const\\s+)?(?:struct\\s+|unsigned\\s+|signed\\s+)?[A-Za-z_]\\w*)\\s*"
            + "(\\*?)\\s*([A-Za-z_]\\w*)\\s*((?:\\[[^\\]]*\\])*)\\s*;");
    private static final Pattern DIM = Pattern.compile("\\[\\s*(0x[0-9A-Fa-f]+|\\d+)\\s*\\]");

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("ERROR: need <include/dw dir>");
            return;
        }
        File dir = new File(args[0]);
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        int applied = 0, noSymbol = 0, noType = 0, isCode = 0, failed = 0, unsizedArray = 0, total = 0;

        // `extern Item ITEM_PARA[];` carries no length, but dw_decomp's symbols.txt does
        // (`ITEM_PARA = 0x801269DC; // size:0x1000`). With the optional second argument the
        // element count of an unsized array is derived from that: size / sizeof(element).
        java.util.Map<String, Integer> symSizes = new java.util.HashMap<>();
        if (args.length >= 2) {
            Pattern sym = Pattern.compile("^\\s*(\\w+)\\s*=\\s*0x[0-9A-Fa-f]+\\s*;.*size:0x([0-9A-Fa-f]+)");
            try (BufferedReader r = new BufferedReader(new FileReader(new File(args[1])))) {
                String line;
                while ((line = r.readLine()) != null) {
                    Matcher sm = sym.matcher(line);
                    if (sm.find()) symSizes.put(sm.group(1), Integer.parseInt(sm.group(2), 16));
                }
            }
            println("symbol sizes loaded: " + symSizes.size());
        }

        for (File h : dir.listFiles((d, n) -> n.endsWith(".h"))) {
            try (BufferedReader r = new BufferedReader(new FileReader(h))) {
                String line;
                while ((line = r.readLine()) != null) {
                    Matcher m = EXTERN.matcher(line);
                    if (!m.matches()) continue;
                    total++;
                    String typeName = m.group(1).replaceAll("^const\\s+", "").trim();
                    boolean pointer = !m.group(2).isEmpty();
                    String name = m.group(3);
                    String dims = m.group(4);

                    Symbol sym = null;
                    SymbolIterator it = currentProgram.getSymbolTable().getSymbols(name);
                    while (it.hasNext()) { sym = it.next(); break; }
                    if (sym == null) { noSymbol++; continue; }
                    Address addr = sym.getAddress();
                    if (getFunctionContaining(addr) != null && getFunctionAt(addr) != null) {
                        isCode++;
                        continue;
                    }

                    DataType dt = resolveType(dtm, typeName);
                    if (dt == null) { noType++; if (noType <= 8) println("no type: " + typeName + " for " + name); continue; }
                    if (pointer) dt = new PointerDataType(dt, dtm);

                    // Array dims, outermost first: `Foo NAME[4][8]` -> array of 4 (array of 8 Foo).
                    Matcher dm = DIM.matcher(dims);
                    java.util.List<Integer> sizes = new java.util.ArrayList<>();
                    boolean bad = false;
                    while (dm.find()) {
                        String v = dm.group(1);
                        sizes.add(v.startsWith("0x") ? Integer.parseInt(v.substring(2), 16) : Integer.parseInt(v));
                    }
                    if (!dims.isEmpty() && sizes.isEmpty()) { // `extern Foo X[];`
                        Integer total_bytes = symSizes.get(name);
                        int elem = dt.getLength();
                        if (total_bytes != null && elem > 0 && total_bytes % elem == 0) {
                            sizes.add(total_bytes / elem);
                        } else {
                            unsizedArray++;
                            bad = true;
                        }
                    }
                    if (bad) continue;
                    for (int i = sizes.size() - 1; i >= 0; i--) {
                        dt = new ArrayDataType(dt, sizes.get(i), dt.getLength(), dtm);
                    }
                    try {
                        DataUtilities.createData(currentProgram, addr, dt, -1,
                                ClearDataMode.CLEAR_ALL_CONFLICT_DATA);
                        applied++;
                    } catch (Exception e) {
                        failed++;
                        if (failed <= 10) println("FAIL " + name + " @ " + addr + " as " + dt.getName() + ": " + e.getMessage());
                    }
                }
            }
        }
        println("APPLY total=" + total + " applied=" + applied + " noSymbol=" + noSymbol + " noType=" + noType
                + " skippedCode=" + isCode + " unsizedArray=" + unsizedArray + " failed=" + failed);
    }

    private DataType resolveType(DataTypeManager dtm, String typeName) {
        java.util.List<DataType> found = new java.util.ArrayList<>();
        String bare = typeName.replaceAll("^struct\\s+", "").trim();
        dtm.findDataTypes(bare, found);
        if (!found.isEmpty()) return found.get(0);
        // C builtins the headers spell out.
        switch (bare.replaceAll("\\s+", " ")) {
            case "char": return dtm.getDataType("/char");
            case "unsigned char": return dtm.getDataType("/uchar");
            case "short": return dtm.getDataType("/short");
            case "unsigned short": return dtm.getDataType("/ushort");
            case "int": return dtm.getDataType("/int");
            case "unsigned int": return dtm.getDataType("/uint");
            case "long": return dtm.getDataType("/long");
            case "unsigned long": return dtm.getDataType("/ulong");
            case "void": return dtm.getDataType("/void");
            default: return null;
        }
    }
}
