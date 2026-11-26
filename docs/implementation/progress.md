# SDD ledger — plan: docs/superpowers/plans/2026-11-26-basketball-detect.md

Execution: inline, in existing baketball_detect worktree.
Pre-flight: Task 1 DetectConfig feeds Task 2 analyze and Task 4 CLI; Task 2 AnalysisResult feeds Task 3 render; consistent.
Ruling: Use native PowerShell bookkeeping instead of Bash-only skill helpers on Windows; keep persistent progress in this file.
Ruling: Source-direct scanning avoids proxy rescaling; slightly slower decoding in exchange for one coordinate/time system.
Task 1: complete — configuration 7 tests passed; CLI help works without loading a model.
Ruling: Keep vendor/src/basketball_highlight layout to preserve unmodified upstream imports.
Ruling: pytest temp directory ACLs fail under the Windows sandbox; verification runs use approved execution with explicit worktree-local basetemp.
Task 2: complete — 20 tests passed across configuration, candidate fallback, conservative evidence agreement, empty candidates, auto-ROI failure and missing checks.
Ruling: Model/ROI failures are errors; an empty candidate list after a valid hoop is a successful zero-event analysis.
Task 3: complete — whole suite 28 passed, including real FFmpeg export with/without audio, odd dimensions, 29.97fps and output protection.
Ruling: Put status banner at the bottom to reduce overlap with the rim; corrected the visual-content test to inspect the bottom region.
Runtime: external bball_model.pt loaded successfully and inferred a blank 640x640 frame; classes ball/hoop. torch 2.9.0+cpu; ultralytics 8.3.225; no CUDA.
