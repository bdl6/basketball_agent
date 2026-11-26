# Upstream
Source: E:/basketball-highlight-editor
Commit: cb8de110e2db5ccbdb9d73ff4f1d2e7fd0d5b472
Selected Python files initially copied from the local working tree; original snapshot hashes are in manifest.json.
License: MIT, see LICENSE. Model weights are external and are not distributed here.
Layout retains src/ so upstream scripts resolve their local imports without modifications.

Local MVP patches (source project remains untouched):
- ranking.py, events.py, refine_dynamic_candidates.py: retain all duplicate track hypotheses so conflicting evidence reaches the final adapter.
- sampling.py, scan_video.py, refine_candidates.py: use full-precision sample grids and actual source-frame timestamps; clamp sampling to native fps.
- rim_check.py: missing net-motion evidence in thin-net calibration remains unsure.
Current vendored file hashes after these patches are recorded in patched-manifest.json.
