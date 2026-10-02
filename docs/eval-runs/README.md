# Eval runs

Every full run of `python -m eval.run`, with its JSON report and terminal output, written by the
runner and never edited. `reports/eval.json` is a copy of `final/run2.json`: both final runs pass
every gate, and run 2 sits closer to a threshold (T-ORDER-CORRECT 0.9167 against 0.90), so it is
the one reported (SPEC §16: report both runs, use the lower one).

| Round | Commit | Run | Exit | Rows below target or items failed | What changed next |
|---|---|---|---|---|---|
| 1-first | `d940749` | 1 | 2 | T-ACTION-LOGGED 0.875 (A03 asked for an order number); M10 ask blocked by the Guardrail | Guardrail v3, product-name lookup rule (`5b9ccf5`) |
| 1-first | `d940749` | 2 | 0 | M10 ask blocked by the Guardrail (T-MEM-RECALL 0.9) | (same) |
| 2-second | `5b9ccf5` | 1 | 2 | T-ACTION-LOGGED 0.875 (A06 asked to confirm); O08 answered without a tool call | Agent temperature 0, self-hosted Mem0 (`1d3d392`) |
| 2-second | `5b9ccf5` | 2 | crashed | Mem0 cloud free-tier quota (1 000 searches) ran out during the memory pairs | (same) |
| final | `1d3d392` | 1 | 0 | M02 not recalled (score 0.152, below the 0.20 cutoff); T-MEM-RECALL 0.9 | none |
| final | `1d3d392` | 2 | 0 | O08 answered without a tool call; T-ORDER-CORRECT 0.9167 | none |
