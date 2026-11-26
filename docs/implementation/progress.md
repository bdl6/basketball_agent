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
Final review: independent reviewer reviewed 8b94be1..3dc8f1a read-only; completed review, no re-review requested.
Final: fixed lost contradictory hypotheses — test_producer_deduplication_preserves_conflicting_hypotheses RED→GREEN.
Final: fixed duplicate occlusion calibration — test_overlapping_windows_do_not_inflate_occlusion_calibration RED→GREEN.
Final: fixed missing net-motion evidence promoted to made — test_thin_net_calibration_without_motion_measurements_stays_uncertain RED→GREEN.
Final: fixed swallowed neighboring coarse seed — test_neighboring_goal_does_not_swallow_unrefined_seed RED→GREEN.
Final: fixed millisecond sampling frame loss and wrong source timestamps — test_native_rate_sampling_does_not_skip_every_third_frame and actual video scanner/refiner test RED→GREEN.
Final: fixed detection boxes on unobserved frames — test_detection_box_is_not_projected_onto_adjacent_frames RED→GREEN.
Final: fixed unreachable witnessed-miss classification — actual source rebound detections through upstream refiner, fallback and dense check tested RED→GREEN; resumed descent with positive/negative conflict correctly remains uncertain.
Final: fixed audio/video source-start rebasing — frequency/silence tests for both offset directions RED→GREEN.
Final: fixed invalid fallback rational encoder fps — test_fallback_frame_rate_is_the_rate_given_to_encoder RED→GREEN.
Final suite: .venv/Scripts/python.exe -m pytest -q --basetemp=runs/test-review-final → 45 passed in 9.77s.
Final: Ruling: Accept witnessed dense negative evidence with inconclusive refinement, but never override a conflicting made refinement — otherwise real misses dropped by the positive-oriented refiner cannot be displayed; cost is dependence on dense checker evidence quality, to be measured on user footage.
Final: minor (deferred): explicit null/empty output is not validated early and can cause TypeError; normal/default runs path is supported, README instructs retaining a nonempty directory.
Final: Ruling: Keep branch and managed worktree as requested by the user; do not merge, push, or clean up this working checkout.
