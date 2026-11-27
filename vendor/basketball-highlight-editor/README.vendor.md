# Original engine source snapshot

Copied from E:/basketball-highlight-editor on 2026-11-27 under its MIT license (LICENSE).
Engine and shared Python package are preserved byte-for-byte, together with the nine runtime scripts needed for standard recognition and ROI suggestions. SOURCE_MANIFEST.json records SHA256 of every imported file for auditing.

Layout intentionally preserves engine/python, src and scripts: upstream resolves scripts relative to this root. No upstream algorithm changes were made. Model weights, uploaded media, databases, caches, desktop/mobile UI and release tooling are excluded.

Install requirements.txt using the Python configured for the engine. Model weights remain configured separately with BASKETBALL_MODEL_PATH. Run this application from its source checkout; standalone wheel packaging of vendor is not supported.

Default web recognition uses this snapshot. BASKETBALL_ENGINE_ROOT optionally overrides it for development. To update, import the complete matching runtime and regenerate the manifest; validate full analysis before replacing this snapshot.
