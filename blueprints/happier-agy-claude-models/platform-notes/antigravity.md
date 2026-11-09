# Platform Notes: Google Antigravity (`agy`)

- **Tool Mapping:**
  - `run-script` $\rightarrow$ `run_command`
  - `files-rw` $\rightarrow$ `client_view_file`, `client_create_file`, `client_edit_file`
- **Important Environment Note when Running Inside a Happier `agy` Session:**
  - Happier runs `agy` sessions with `HOME` set to the isolated Connected Service home (`$HAPPIER_HOME_DIR/servers/.../daemon/connected-services/homes/antigravity/default/agy`).
  - `patch_agy_acp_models.py` automatically checks `systemctl --user cat happier-daemon.default.service` (and `$HAPPIER_HOME_DIR`) to locate the real `~/.happier` root. If `systemctl --user` is unavailable inside your container/environment, pass `--par-path /path/to/.happier/tools/agy-acp-server/current/agy_acp_server.par` explicitly.
  - Because `patch_agy_acp_models.py` uses `os.replace()`, you can safely run `--apply` from *inside* an active `agy` session without hitting `ETXTBSY`.
