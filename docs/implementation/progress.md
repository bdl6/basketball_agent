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
Task 4: complete — 32 tests passed; CLI writes events/run reports and independently named full annotated videos; failure report tested.
Runtime smoke: upstream model successfully loaded on CPU. Actual auto-ROI on a gray video failed with the intended no-hoop message; actual scan, refine and rim-check scripts ran successfully on generated media. No real-video accuracy claim.
Visual QA: inspected runs/runtime-smoke/overlay-preview.png extracted from a real encoded MP4; Chinese made label and cumulative count legible.
Ruling: Accept ultralytics >=8.3.225 rather than force an unneeded upgrade to >=8.4; the installed 8.3.225 has loaded and run all inference stages with this model.
Ruling: Reject rotated metadata and obviously variable-frame-rate input in MVP rather than silently drift source coordinates/timestamps; README gives a normalization command. Full VFR support remains out of scope.
