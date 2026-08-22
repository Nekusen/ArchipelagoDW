import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

// Census of every function in the DW1 Ghidra program: address, name, byte size,
// instruction count, caller count, callee count. Used to size the decomp effort
// (denominator for "% decompiled") and to prioritise units.
//
// Headless usage (arg: output TSV path):
//   analyzeHeadless <proj> DW1 -process SLUS_010.32 -noanalysis -readOnly
//       -scriptPath worlds\digimon_world\tools\ghidra_scripts
//       -postScript DW1FunctionStats.java work\dw1_re\function_census.tsv
public class DW1FunctionStats extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args.length > 0 ? args[0] : "function_census.tsv");
        if (out.getParentFile() != null) out.getParentFile().mkdirs();

        int total = 0, named = 0, thunks = 0;
        long totalBytes = 0, namedBytes = 0;

        try (PrintWriter w = new PrintWriter(out, "UTF-8")) {
            w.println("addr\tname\tbytes\tinstrs\tcallers\tcallees\tthunk");
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) {
                Function f = it.next();
                long bytes = f.getBody().getNumAddresses();
                long instrs = currentProgram.getListing()
                        .getInstructions(f.getBody(), true).hasNext() ? 0 : 0;
                // count instructions explicitly
                instrs = 0;
                for (var i = currentProgram.getListing().getInstructions(f.getBody(), true);
                        i.hasNext(); i.next()) instrs++;

                int callers = 0;
                ReferenceIterator ri = currentProgram.getReferenceManager()
                        .getReferencesTo(f.getEntryPoint());
                while (ri.hasNext()) {
                    Reference r = ri.next();
                    if (r.getReferenceType().isCall()) callers++;
                }
                int callees = f.getCalledFunctions(monitor).size();
                boolean isNamed = !f.getName().startsWith("FUN_");

                w.printf("%s\t%s\t%d\t%d\t%d\t%d\t%s%n", f.getEntryPoint(), f.getName(),
                        bytes, instrs, callers, callees, f.isThunk() ? "Y" : "N");

                total++;
                totalBytes += bytes;
                if (f.isThunk()) thunks++;
                if (isNamed) { named++; namedBytes += bytes; }
            }
        }
        println("TOTAL_FUNCTIONS=" + total);
        println("NAMED_FUNCTIONS=" + named);
        println("UNNAMED_FUN_FUNCTIONS=" + (total - named));
        println("THUNKS=" + thunks);
        println("TOTAL_CODE_BYTES=" + totalBytes);
        println("NAMED_CODE_BYTES=" + namedBytes);
        println("CENSUS=" + out.getAbsolutePath());
    }
}
