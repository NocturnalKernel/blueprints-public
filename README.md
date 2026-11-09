# Blueprints (Public Library)

Sanitized, platform-neutral AI agent blueprints and standalone customization guides for **Claude Code**, **Google Antigravity (`agy`)**, **Hermes**, and **Happier Client**.

---

## Available Blueprints

| Blueprint | Summary | Standalone Quickstart (No Blueprint Setup Required) | Full Blueprint Spec |
|---|---|---|---|
| **`happier-agy-claude-models`** | Enable **Claude Opus 5.5**, **Claude Sonnet 5.5**, and **GPT-OSS 120B** in Happier's Google Antigravity (`agy`) model picker (`agy_acp_server.par`) | [**QUICKSTART.md**](blueprints/happier-agy-claude-models/QUICKSTART.md) | [**BLUEPRINT.md**](blueprints/happier-agy-claude-models/BLUEPRINT.md) |

---

## How to Use

### 1. Fast Path (Just Run or Hand to Your AI Agent)
If you don't use the full Blueprint framework and simply want your AI agent (Claude Code, Antigravity, Hermes, Cursor, etc.) to apply a capability on your machine, point your agent at the blueprint's **`QUICKSTART.md`**:

```text
Clone https://github.com/NocturnalKernel/blueprints-public (or read blueprints/happier-agy-claude-models/QUICKSTART.md), run the unit test, and follow the steps to enable Claude models in my Happier Antigravity setup.
```

### 2. Full Blueprint Path
If you use the Blueprint workflow (`BLUEPRINT.md` + `platform-notes/`), point your agent at `blueprints/<name>/BLUEPRINT.md` and `blueprints/<name>/platform-notes/<platform>.md` to install, verify, or reconcile the capability natively on your platform.
