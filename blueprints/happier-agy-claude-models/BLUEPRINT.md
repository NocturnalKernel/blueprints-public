---
name: happier-agy-claude-models
version: 1.0.0
status: stable
summary: Enable third-party models (Claude Opus 5.5, Claude Sonnet 5.5, GPT-OSS 120B) in Happier's managed Google Antigravity ACP server (agy_acp_server.par) with path-agnostic and Python-version-independent patching.
requires: [run-script, files-rw]
profile_keys: []
related: []
---

# Blueprint: happier-agy-claude-models (v1.0.0)

> **Want simple standalone instructions instead of a full Blueprint install?**
> Read [QUICKSTART.md](QUICKSTART.md) — you or your AI agent can apply the patch directly in 3 commands without installing the Blueprint framework.

## 1. Purpose
Enables third-party models (`claude-opus-5-5-{low,medium,high}`, `claude-sonnet-5-5-{low,medium,high}`, and `gpt-oss-120b-medium`) in Happier when using the Google Antigravity (`agy`) backend on a Google AI Pro or Google AI Ultra subscription.

By default, Google's managed ACP server (`agy_acp_server.par`) gates non-Gemini models behind `supports_third_party_models(client)` in `model_selection.py`, which only returns `True` for `jetbrains`, `zed`, or `xcode` clients. Because Happier connects as `clientInfo.name = "happier-cli"` (or `"happier-cli-capabilities"`), Claude and GPT-OSS models are stripped from the model catalog and rejected during model selection. This blueprint patches both the `.py` source and `.pyc` bytecode inside `agy_acp_server.par`, updates the ZIP CRC32 headers and PEP 552 `source_hash`, and synchronizes Happier's `install-state.json` manifest.

## 2. Triggers
- Activated when the user asks to enable, check, repair, or revert Claude / third-party models in Happier's Antigravity (`agy`) provider.
- Activated after a Happier or `agy-acp-server` update when Claude models disappear from the `agy` model picker.

## 3. Capabilities required
- `run-script` — run the stdlib Python patcher, unit test suite, daemon restart, and live ACP verification probe.
- `files-rw` — inspect configuration and write optional skill/customization records.

## 4. Flow
1. **Locate Installation (`discover_happier_home`):**
   - Resolve `$HAPPIER_HOME_DIR` from environment, `systemctl --user cat happier-daemon*.service`, or `~/.happier`.
   - Confirm `<happier_home>/tools/agy-acp-server/current/agy_acp_server.par` and `<happier_home>/tools/agy-acp-server/install-state.json` exist.
2. **Run Self-Test:**
   - Execute `python3 assets/test_patch_agy_acp_models.py -v` to verify check/apply/backup/idempotency/revert on a synthetic `.par` archive.
3. **Check Current State:**
   - Execute `python3 assets/patch_agy_acp_models.py --check`. If already `"state": "patched"` with valid CRCs and matching `install-state.json`, skip to Step 5.
4. **Back Up & Apply Patch:**
   - Execute `python3 assets/patch_agy_acp_models.py --apply --backup-dir ~/.backups/happier-agy-claude-models`.
   - Re-run `python3 assets/patch_agy_acp_models.py --check` and confirm exit code `0`.
5. **Flush Happier Model Probe Cache:**
   - Restart the Happier daemon (`systemctl --user restart happier-daemon.default.service` or equivalent daemon restart) to clear its 24-hour in-memory model catalog cache.
6. **Verify Live ACP Catalog:**
   - Spawn `<happier_home>/tools/agy-acp-server/current/agy_acp_server.par --uid=` with the Connected Service `antigravity` environment, send `initialize` (`clientInfo: { name: "happier-cli", version: "0.2.20" }`) and `session/new`, confirm `claude-opus-5-5-*` and `claude-sonnet-5-5-*` are present in `availableModels`, and clean up the temporary probe session files.

## 5. Rules
- **R1:** MUST run `test_patch_agy_acp_models.py` before applying the patch to a live binary.
- **R2:** MUST preserve an unpatched backup (`--backup-dir`) with `0700`/`0600` permissions and a SHA-256 manifest before modifying `agy_acp_server.par`.
- **R3:** MUST patch both `model_selection.py` and `__pycache__/model_selection.cpython-314.pyc` (including the 8-byte PEP 552 `source_hash` computed with the `.pyc` header's magic number) so Python 3.14's `zipimport` loads the patched bytecode cleanly regardless of the host Python version.
- **R4:** MUST atomically replace `agy_acp_server.par` via staging + `os.replace` so running `agy` sessions do not fail with `ETXTBSY` (`Text file busy`).
- **R5:** MUST synchronize `executableSha256`, `executableSize`, and `executableMtimeMs` in `install-state.json` so Happier's `verifyExistingAgyAcpManagedBinPath()` check succeeds.
- **R6:** MUST clean up any temporary session `.db`, `.pb`, and `brain/` artifacts created during live ACP verification probes.

## 6. Loop and stop logic
- Single-pass execution: once `--check` reports `"state": "patched"` (`exit 0`), the daemon is restarted, and the ACP probe confirms the third-party models are returned, stop and report the verification summary.

## 7. Outputs
- Patched `<happier_home>/tools/agy-acp-server/current/agy_acp_server.par` and synchronized `<happier_home>/tools/agy-acp-server/install-state.json`.
- Pre-change backup and `sha256sums.txt` in `~/.backups/happier-agy-claude-models/`.
- JSON status output from `patch_agy_acp_models.py --check`.

## 8. Pitfalls
- **P1 (`only-.py-patched`):** Patching only `model_selection.py` without patching `__pycache__/model_selection.cpython-314.pyc` (or without updating the PEP 552 `source_hash`) fails because `zipimport` executes the cached `.pyc` when its hash matches or raises `ImportError` when the hash mismatches.
- **P2 (`host-python-magic-mismatch`):** Calling `_imp.source_hash(_imp.pyc_magic_number_token, ...)` directly uses the *host* Python's magic number instead of the `.pyc` file's Python 3.14 magic number (`0x0a0d0e2b`). Always unpack the magic number from `pyc_data[:4]`.
- **P3 (`etextbsy-in-place-open`):** Opening `agy_acp_server.par` with `"r+b"` while an Antigravity session is active raises `OSError: [Errno 26] Text file busy` on Linux. Always stage to a temporary file and `os.replace()`.
- **P4 (`linux-nobody-group`):** When invoking `agy_acp_server.par` directly for a standalone CLI probe on Debian/Ubuntu (where the unprivileged group is `nogroup` instead of `nobody`), pass `--uid=` so `terminal_sandbox.py` does not fail looking up group `nobody`.

## 9. Test scenarios
- **T1 (`static`):** Run `python3 assets/test_patch_agy_acp_models.py -v` and confirm the synthetic `.par` archive transitions `unpatched -> patched -> patched (idempotent) -> unpatched` with byte-for-byte SHA-256 restoration.
- **T2 (`live`):** Run `python3 assets/patch_agy_acp_models.py --check` against the live Happier installation and confirm exit status `0` with `"crc_valid": true` and `"install_state_matches": true`.
- **T3 (`live`):** Run an ACP `initialize` + `session/new` probe with `clientInfo.name = "happier-cli"` and verify `claude-opus-5-5-low`, `claude-opus-5-5-medium`, `claude-opus-5-5-high`, `claude-sonnet-5-5-low`, `claude-sonnet-5-5-medium`, `claude-sonnet-5-5-high`, and `gpt-oss-120b-medium` are returned in `availableModels`.

## 10. Personalisation points
- None required (`profile_keys: []`). All paths are discovered dynamically via `$HAPPIER_HOME_DIR`, `systemctl --user`, or `~/.happier` (and overridable via `--par-path` / `--state-path`).

## 11. Changelog
- **1.0.0 (2026-11-09):** Initial public release supporting `agy-acp-server` v1.3.0 / Happier v0.2.20+ with path-agnostic discovery, cross-Python PEP 552 hashing, atomic replacement, and standalone `QUICKSTART.md`.
