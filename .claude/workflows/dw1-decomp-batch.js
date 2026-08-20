export const meta = {
  name: 'dw1-decomp-batch',
  description: 'Decompile a batch of DW1 functions: serial prepare (Ghidra + vector capture), then parallel verified reimplementation',
  whenToUse: 'When the user asks to decompile several DW1 functions following the standard process (DECOMP_PROCESS.md). args = [{name, addr, notes?}, ...]',
  phases: [
    { title: 'Prepare', detail: 'one agent: Ghidra exports + shared emulator vector-capture session (serial by design)' },
    { title: 'Implement', detail: 'one agent per unit: C reimplementation + 100% vector replay verification' },
  ],
}

// args: [{name: 'isTriggerSet', addr: '8010643C', notes: 'fires during intro dialogs'}, ...]
if (!Array.isArray(args) || args.length === 0) {
  throw new Error('args must be a non-empty array of {name, addr, notes?}')
}

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    unit: { type: 'string' },
    status: { type: 'string', enum: ['VERIFIED', 'FAILED', 'PARTIAL', 'BLOCKED'] },
    pass: { type: 'number' },
    fail: { type: 'number' },
    skip: { type: 'number' },
    insights: { type: 'array', items: { type: 'string' } },
    files: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['unit', 'status', 'pass', 'fail', 'skip', 'notes'],
}

phase('Prepare')
const list = args.map(u => `- ${u.name} @ 0x${u.addr}${u.notes ? ` (${u.notes})` : ''}`).join('\n')
const prep = await agent(
  `Mode: prepare. Run the prepare stage of DECOMP_PROCESS.md for this batch of DW1 function units:\n${list}\n` +
  `Export each unit's Ghidra bundle serially, then run ONE shared vector-capture session covering all units. ` +
  `Report per unit: bundle path, vector count, tier, and flag any unit with zero vectors.`,
  { agentType: 'dw1-decomp', label: 'prepare-batch', phase: 'Prepare' },
)
log(`prepare done: ${String(prep).slice(0, 200)}`)

phase('Implement')
const results = await parallel(args.map(u => () =>
  agent(
    `Mode: implement. Unit: ${u.name} (entry 0x${u.addr}). The bundle and vectors already exist ` +
    `(prepare stage summary below). Reimplement in C and verify per DECOMP_PROCESS.md steps 5-7. ` +
    `Do not touch Ghidra or the emulator.\n\nPrepare summary:\n${prep}`,
    { agentType: 'dw1-decomp', label: `impl:${u.name}`, phase: 'Implement', schema: REPORT_SCHEMA },
  )
))

const reports = results.filter(Boolean)
const verified = reports.filter(r => r.status === 'VERIFIED')
log(`${verified.length}/${args.length} units VERIFIED`)
return {
  verified: verified.map(r => r.unit),
  reports,
  missing: args.filter(u => !reports.some(r => r.unit === u.name)).map(u => u.name),
}
