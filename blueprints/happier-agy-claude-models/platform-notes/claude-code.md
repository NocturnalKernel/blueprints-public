# Platform Notes: Claude Code (`claude-code`)

- **Tool Mapping:**
  - `run-script` $\rightarrow$ `Bash`
  - `files-rw` $\rightarrow$ `Read`, `Write`, `Edit`
- **Skill Installation (Optional):**
  - If installing as a persistent Claude Code skill (`~/.claude/skills/happier-agy-claude-models/SKILL.md`), copy `assets/patch_agy_acp_models.py` and `assets/test_patch_agy_acp_models.py` into `~/.claude/skills/happier-agy-claude-models/scripts/` so the user can re-apply the patch after future `agy-acp-server` updates with `/happier-agy-claude-models`.
