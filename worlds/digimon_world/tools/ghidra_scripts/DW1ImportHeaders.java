import java.io.File;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.app.util.cparser.C.CParserUtils;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FileDataTypeManager;
import ghidra.util.task.TaskMonitor;

// Parses dw_decomp's game headers (include/dw/*.h) into the DW1 program's data-type manager,
// so the decompiler can show `PARTNER_ENTITY.learnedMoves[1]` instead of `*(int *)0x80155804`.
//
// The headers reference PsyQ library types (POLY_FT4, DVECTOR, GsOT, ...). Those are resolved
// from the ghidra_psx_ldr extension's PsyQ data-type archive, opened read-only and passed to the
// parser as an extra type source -- the PsyQ headers themselves are NOT parsed (their inline-asm
// macros defeat Ghidra's C parser). Any header that still fails to parse is reported and skipped;
// the ones that succeed are applied.
//
// Headless usage (writes the project; serialize with other Ghidra runs):
//   powershell -File worlds\digimon_world\tools\dw1_ghidra.ps1 -Script DW1ImportHeaders.java
//       references\dw_decomp\include  C:\opt\tools\ghidra\...\ghidra_psx_ldr\data\psyq340.gdt
public class DW1ImportHeaders extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("ERROR: need <include dir> [psyq .gdt archive]");
            return;
        }
        File includeDir = new File(args[0]);
        File dwDir = new File(includeDir, "dw");
        if (!dwDir.isDirectory()) {
            println("ERROR: no dw/ under " + includeDir);
            return;
        }

        List<DataTypeManager> extra = new ArrayList<>();
        FileDataTypeManager psyq = null;
        if (args.length >= 2) {
            psyq = FileDataTypeManager.openFileArchive(new File(args[1]), false);
            extra.add(psyq);
            println("PSYQ archive: " + psyq.getName() + " (" + psyq.getDataTypeCount(true) + " types)");
        }

        DataTypeManager dtm = currentProgram.getDataTypeManager();
        int before = dtm.getDataTypeCount(true);

        // types.h first (everything includes it), then the rest alphabetically. Each header is
        // parsed on its own so one failure does not sink the batch; the parser is handed the
        // include root so `#include <dw/...>` resolves.
        File[] headers = dwDir.listFiles((d, n) -> n.endsWith(".h"));
        java.util.Arrays.sort(headers, (a, b) -> {
            if (a.getName().equals("types.h")) return -1;
            if (b.getName().equals("types.h")) return 1;
            return a.getName().compareTo(b.getName());
        });
        // Include roots: dw_decomp's own, then any extra dirs from the command line. The extra
        // dir is expected to hold EMPTY libgte.h / libgs.h / libgpu.h / libcd.h / setjmp.h stubs:
        // the `#include <libgte.h>` lines then resolve to nothing and the PsyQ types come from
        // the .gdt archive instead of a parse of the real PsyQ headers (which Ghidra cannot do).
        List<String> inc = new ArrayList<>();
        inc.add(includeDir.getAbsolutePath());
        for (int i = 2; i < args.length; i++) inc.add(new File(args[i]).getAbsolutePath());
        String[] includePaths = inc.toArray(new String[0]);
        String[] parserArgs = { "-D__GHIDRA__", "-D_LANGUAGE_C" };

        int ok = 0, failed = 0;
        for (File h : headers) {
            try {
                CParserUtils.parseHeaderFiles(extra.toArray(new DataTypeManager[0]),
                        new String[] { h.getAbsolutePath() }, includePaths, parserArgs, dtm,
                        TaskMonitor.DUMMY);
                ok++;
            } catch (Exception e) {
                failed++;
                String msg = e.getMessage() == null ? e.toString() : e.getMessage();
                println("PARSE FAIL " + h.getName() + ": " + msg.replace("\n", " | ").substring(0, Math.min(300, msg.length())));
            }
        }
        int after = dtm.getDataTypeCount(true);
        println("HEADERS ok=" + ok + " failed=" + failed + " dataTypes " + before + " -> " + after);

        // Spot-check the types this project leans on most.
        for (String name : new String[] { "PartnerEntity", "Entity", "ScriptState", "Item",
                "TextBoxData", "EvoRequirements", "MapEntry" }) {
            List<DataType> found = new ArrayList<>();
            dtm.findDataTypes(name, found);
            println("  " + name + ": " + (found.isEmpty() ? "MISSING" : found.get(0).getLength() + " bytes"));
        }
        if (psyq != null) psyq.close();
    }
}
