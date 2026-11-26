# SDD ledger — plan: docs/superpowers/plans/2026-11-26-basketball-detect.md

Execution: inline, in existing baketball_detect worktree.
Pre-flight: Task 1 DetectConfig feeds Task 2 analyze and Task 4 CLI; Task 2 AnalysisResult feeds Task 3 render; consistent.
Ruling: Use native PowerShell bookkeeping instead of Bash-only skill helpers on Windows; keep persistent progress in this file.
Ruling: Source-direct scanning avoids proxy rescaling; slightly slower decoding in exchange for one coordinate/time system.
Task 1: complete — configuration 7 tests passed; CLI help works without loading a model.
Ruling: Keep vendor/src/basketball_highlight layout to preserve unmodified upstream imports.
Ruling: pytest temp directory ACLs fail under the Windows sandbox; verification runs use approved execution with explicit worktree-local basetemp.
