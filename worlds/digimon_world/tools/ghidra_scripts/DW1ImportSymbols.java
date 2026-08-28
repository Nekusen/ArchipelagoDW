import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

// Imports dw_decomp's symbol map (config/symbols*.txt, lines like
//     name = 0x800A4240; // type:func size:0x11c
// ) into the DW1 Ghidra project.
//
// Policy -- the project already carries SydMontague's names and PsyQ signatures, and our own
// notes reference Ghidra's FUN_/DAT_ defaults, so nothing existing is destroyed:
//   * function at the address named FUN_*      -> renamed to the dw_decomp name; the old FUN_ name
//                                                 is kept as a secondary label so old references
//                                                 still resolve in searches
//   * function with a real (non-default) name  -> dw_decomp name added as a SECONDARY label
//   * no function at a `type:func` address     -> function created with the dw_decomp name
//   * data address with only a default symbol  -> dw_decomp name becomes the primary label
//   * data address with a real name            -> dw_decomp name added as a secondary label
// Addresses outside the program's memory map (overlays, which are not loaded in this project)
// are counted and skipped.
//
// Headless usage (NOT read-only -- this writes to the project; serialize with other Ghidra runs):
//   powershell -File worlds\digimon_world\tools\dw1_ghidra.ps1 -Script DW1ImportSymbols.java
//       references\dw_decomp\config\symbols.txt [more files...]
public class DW1ImportSymbols extends GhidraScript {
    private static final Pattern LINE = Pattern.compile(
            "^\\s*(\\w+)\\s*=\\s*0x([0-9A-Fa-f]+)\\s*;(?:\\s*//\\s*(.*))?");

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("ERROR: need one or more symbols.txt paths");
            return;
        }
        SymbolTable st = currentProgram.getSymbolTable();
        int renamed = 0, created = 0, secondary = 0, dataPrimary = 0, skippedOutside = 0,
                unchanged = 0, failed = 0, total = 0;

        for (String path : args) {
            try (BufferedReader r = new BufferedReader(new FileReader(new File(path)))) {
                String line;
                while ((line = r.readLine()) != null) {
                    Matcher m = LINE.matcher(line);
                    if (!m.matches()) continue;
                    total++;
                    String name = m.group(1);
                    long value = Long.parseLong(m.group(2), 16);
                    String attrs = m.group(3) == null ? "" : m.group(3);

                    Address addr = currentProgram.getAddressFactory().getDefaultAddressSpace()
                            .getAddress(value);
                    if (!currentProgram.getMemory().contains(addr)) {
                        skippedOutside++;
                        continue;
                    }
                    // dw_decomp's files carry `type:func` on almost nothing (3 of ~6600 lines),
                    // so treat any address Ghidra already knows as a function entry as a
                    // function. (The first import, 2026-08-28, predates this line: function
                    // names went in through the label path, which also renames the function
                    // but does not leave the old FUN_ alias behind.)
                    boolean isFunc = attrs.contains("type:func") || getFunctionAt(addr) != null;
                    try {
                        if (isFunc) {
                            Function f = getFunctionAt(addr);
                            if (f == null) {
                                f = createFunction(addr, name);
                                if (f == null) {
                                    // Not disassembled here (or mid-instruction): fall back to a label.
                                    st.createLabel(addr, name, SourceType.IMPORTED);
                                    secondary++;
                                } else {
                                    created++;
                                }
                            } else if (f.getName().equals(name)) {
                                unchanged++;
                            } else if (f.getSymbol().getSource() == SourceType.DEFAULT) {
                                String old = f.getName();
                                f.setName(name, SourceType.IMPORTED);
                                st.createLabel(addr, old, SourceType.IMPORTED); // keep FUN_ as alias
                                renamed++;
                            } else {
                                st.createLabel(addr, name, SourceType.IMPORTED); // secondary
                                secondary++;
                            }
                        } else {
                            Symbol primary = st.getPrimarySymbol(addr);
                            if (primary == null || primary.getSource() == SourceType.DEFAULT) {
                                Symbol s = st.createLabel(addr, name, SourceType.IMPORTED);
                                if (s != null && !s.isPrimary()) s.setPrimary();
                                dataPrimary++;
                            } else if (primary.getName().equals(name)) {
                                unchanged++;
                            } else {
                                st.createLabel(addr, name, SourceType.IMPORTED);
                                secondary++;
                            }
                        }
                    } catch (Exception e) {
                        failed++;
                        if (failed <= 10) println("FAIL " + name + " @ " + addr + ": " + e.getMessage());
                    }
                }
            }
        }
        println("IMPORT total=" + total + " funcRenamed=" + renamed + " funcCreated=" + created
                + " secondaryLabels=" + secondary + " dataPrimary=" + dataPrimary
                + " unchanged=" + unchanged + " skippedOutsideMemory=" + skippedOutside
                + " failed=" + failed);
    }
}
