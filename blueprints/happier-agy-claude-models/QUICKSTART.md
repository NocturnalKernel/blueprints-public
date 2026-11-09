# Quickstart: Enable Claude 5.5 & Third-Party Models in Happier + Google Antigravity (`agy`)

If you use **Happier** with the **Google Antigravity (`agy`)** backend on a **Google AI Pro or Google AI Ultra** plan, your Google account is entitled to third-party models (`claude-opus-5-5-{low,medium,high}`, `claude-sonnet-5-5-{low,medium,high}`, and `gpt-oss-120b-medium`), but they do not appear in Happier's model picker by default.

You can either **hand this file to your AI agent** (Claude Code, Antigravity, Hermes, Cursor, etc.) and ask it to apply the fix for you, or run the commands below yourself.

---

## Option A: One-Line Prompt for Your AI Agent

Paste this into Claude Code (or any agent with terminal access on your VM/machine):

> Read `QUICKSTART.md` and `assets/patch_agy_acp_models.py` in `blueprints/happier-agy-claude-models/`, verify my Happier `agy-acp-server` installation, run the unit test, apply the patch with a backup, restart the Happier daemon, and verify that the Claude 5.5 models appear in a live ACP probe.

---

## Option B: Step-by-Step Manual / Agent Walkthrough

### Why Claude Models Are Hidden by Default
Happier runs Google's managed Antigravity ACP server binary (`agy_acp_server.par`, located under `$HAPPIER_HOME_DIR/tools/agy-acp-server/current/agy_acp_server.par`, defaulting to `~/.happier/...`).

Inside `agy_acp_server.par`, `google3/cloud/developer_experience/antigravity_extensions/acp_server/model_selection.py` defines an allowlist check:
```python
def supports_third_party_models(client: client_info_lib.ClientInfo) -> bool:
  return client.is_jetbrains or client.is_zed or client.is_xcode
```
Because Happier connects over ACP with `clientInfo.name = "happier-cli"` (or `"happier-cli-capabilities"` when probing models), `supports_third_party_models(client)` returns `False`. That causes `agy_acp_server.par` to:
1. Strip all non-Gemini models (`claude-*`, `gpt-oss-*`) from the `session/new` model list, and
2. Reject `session/set_config_option` calls when selecting a `claude-*` model ID.

Furthermore, because `agy_acp_server.par` is a Python 3.14 `autopar` archive that loads precompiled `.pyc` bytecode from `__pycache__/model_selection.cpython-314.pyc` (and validates its PEP 552 `source_hash` against `model_selection.py`), **both** the `.py` source member and the `.pyc` bytecode member inside the uncompressed ZIP archive must be patched together, along with their ZIP Local/Central Directory CRC32 checksums and Happier's `install-state.json` SHA-256 manifest.

---

### Prerequisites
1. **Happier** is installed and the `agy` provider (`agy-acp-server`) has been installed (`happier install provider agy`).
2. Your Google AI Pro/Ultra account is connected to Happier's `antigravity` Connected Service (`happier connect agy --paste`) and selected as your auth profile (`cs:default` or Connected Service in the Web UI).
3. **Python 3.9+** is installed on the host (`python3 --version`). No third-party Python packages are required (stdlib only).

---

### Step 1: Run the Self-Contained Unit Test
Verify the patcher logic against a temporary synthetic `.par` archive before touching your installation:

```bash
python3 assets/test_patch_agy_acp_models.py -v
```

### Step 2: Check Your Current `agy_acp_server.par` Status (Read-Only)
`patch_agy_acp_models.py` automatically discovers `$HAPPIER_HOME_DIR` (from the environment, your `happier-daemon` systemd user service, or `~/.happier`). You can also pass `--par-path` and `--state-path` explicitly if your installation lives in a custom directory.

```bash
python3 assets/patch_agy_acp_models.py --check
```
- If unpatched, it will print `"state": "unpatched"` and exit with status `1`.

### Step 3: Apply the Patch (with Automatic Backup)
Run `--apply` with `--backup-dir` to save a read-only backup of the original `agy_acp_server.par` and `install-state.json` (plus a `sha256sums.txt` manifest), atomically patch both `.py` and `.pyc` members via `os.replace` (safe even if a session is currently running), and synchronize `install-state.json`:

```bash
python3 assets/patch_agy_acp_models.py --apply --backup-dir ~/.backups/happier-agy-claude-models
```

Verify the post-patch state:
```bash
python3 assets/patch_agy_acp_models.py --check
```
It should output `"state": "patched"`, `"crc_valid": true`, `"source_hash_matches_py": true`, `"install_state_matches": true`, and exit `0`.

### Step 4: Restart the Happier Daemon
Happier caches model probe results in memory for 24 hours. Restart the daemon so the Web UI and CLI immediately pick up the newly exposed models:

```bash
# If running via systemd user service (standard on Linux):
systemctl --user restart happier-daemon.default.service

# Check status:
happier status
```

### Step 5: Verify in Happier (or via CLI Probe)
Open a new Antigravity session in the Happier Web UI (making sure your Connected Service account is selected, not native auth) and open the model picker. You will now see all 13 models:
- `claude-opus-5-5-low`, `claude-opus-5-5-medium`, `claude-opus-5-5-high`
- `claude-sonnet-5-5-low`, `claude-sonnet-5-5-medium`, `claude-sonnet-5-5-high`
- `gpt-oss-120b-medium`
- `gemini-4-argon-medium`, `gemini-4-argon-high`, `gemini-4-argon-low`
- `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`

*(Note: Any session that was already running prior to Step 3 keeps its old process in memory until that session runner restarts or you start a new session.)*

---

## Rollback / Reverting to Stock
To revert `agy_acp_server.par` back to the exact upstream bytes and re-sync `install-state.json`:

```bash
python3 assets/patch_agy_acp_models.py --revert
systemctl --user restart happier-daemon.default.service
```

---

## Re-Applying After Happier Updates `agy-acp-server`
Whenever Happier downloads a new version of `agy-acp-server`, it overwrites `agy_acp_server.par`. Simply re-run:

```bash
python3 assets/patch_agy_acp_models.py --apply
systemctl --user restart happier-daemon.default.service
```
