import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

// Exports everything a decomp agent needs about one or more functions of the DW1 Ghidra project.
// Headless usage (args: alternating <hexAddr without 0x> <outputDir> pairs):
//   analyzeHeadless <proj> DW1 -process SLUS_010.32 -noanalysis -readOnly
//       -scriptPath worlds\digimon_world\tools\ghidra_scripts
//       -postScript DW1ExportFunc.java 8010643C work\dw1_re\decomp\isTriggerSet
// Several pairs may be passed in one invocation -- preferred for a batch, since a headless
// startup costs far more than an export and the project database is single-writer.
// Writes: decomp.c, listing.asm, refs.txt into each output directory.
public class DW1ExportFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2 || args.length % 2 != 0) {
            println("ERROR: need one or more <hexAddr> <outDir> pairs");
            return;
        }
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        try {
            for (int i = 0; i < args.length; i += 2) {
                exportOne(decomp, args[i], args[i + 1]);
            }
        } finally {
            decomp.dispose();
        }
    }

    private void exportOne(DecompInterface decomp, String hexAddr, String outPath) throws Exception {
        String[] args = { hexAddr, outPath };
        Address addr = currentProgram.getAddressFactory().getDefaultAddressSpace()
                .getAddress(Long.parseLong(args[0], 16));
        File outDir = new File(args[1]);
        outDir.mkdirs();

        Function f = getFunctionContaining(addr);
        if (f == null) {
            println("ERROR: no function at " + addr);
            return;
        }
        println("EXPORT: " + f.getName() + " @ " + f.getEntryPoint() + " -> " + outDir);

        // 1. Decompilation
        DecompileResults res = decomp.decompileFunction(f, 120, monitor);
        try (PrintWriter w = new PrintWriter(new File(outDir, "decomp.c"), "UTF-8")) {
            w.println("// " + f.getName() + " @ " + f.getEntryPoint()
                    + "  (DW1 SLUS-01032, Ghidra " + getGhidraVersion() + ")");
            String plate = currentProgram.getListing().getCodeUnitAt(f.getEntryPoint())
                    .getComment(CodeUnit.PLATE_COMMENT);
            if (plate != null) w.println("// " + plate.replace("\n", "\n// "));
            w.println(res.decompileCompleted() ? res.getDecompiledFunction().getC()
                    : "// DECOMP FAILED: " + res.getErrorMessage());
        }

        // 2. Disassembly listing
        try (PrintWriter w = new PrintWriter(new File(outDir, "listing.asm"), "UTF-8")) {
            for (Instruction ins = getInstructionAt(f.getEntryPoint());
                    ins != null && f.getBody().contains(ins.getAddress());
                    ins = ins.getNext()) {
                w.printf("%s: %-40s", ins.getAddress(), ins.toString());
                for (Reference r : ins.getReferencesFrom()) {
                    if (!r.getReferenceType().isFlow() || r.getReferenceType().isCall()) {
                        w.print("  ; -> " + r.getToAddress());
                    }
                }
                w.println();
            }
        }

        // 3. Callers, callees, data references
        try (PrintWriter w = new PrintWriter(new File(outDir, "refs.txt"), "UTF-8")) {
            w.println("== CALLERS ==");
            ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
            while (it.hasNext()) {
                Reference r = it.next();
                Function caller = getFunctionContaining(r.getFromAddress());
                w.println(r.getFromAddress() + "  " + (caller == null ? "?" : caller.getName()));
            }
            w.println("== CALLEES ==");
            for (Function callee : f.getCalledFunctions(monitor)) {
                w.println(callee.getEntryPoint() + "  " + callee.getName());
            }
            w.println("== DATA REFS (addr, type) ==");
            for (Instruction ins = getInstructionAt(f.getEntryPoint());
                    ins != null && f.getBody().contains(ins.getAddress());
                    ins = ins.getNext()) {
                for (Reference r : ins.getReferencesFrom()) {
                    if (r.getReferenceType().isData()) {
                        w.println(r.getToAddress() + "  " + r.getReferenceType()
                                + "  from " + ins.getAddress());
                    }
                }
            }
        }
        println("EXPORT DONE: " + f.getName());
    }
}
