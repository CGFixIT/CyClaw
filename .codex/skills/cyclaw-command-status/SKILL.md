---
name: cyclaw-command-status
description: >-
  Codex-native CyClaw status workflow. Use when working in CGFixIT/CyClaw and the user asks for environment status, server status, prerequisite checks, config validation, index/soul readiness, telemetry-kill verification, or local health diagnostics.
---

# CyClaw Command Status

Use this skill for a read-only status pass over the local CyClaw environment and
server. Report missing prerequisites and risky defaults without changing files.

Run commands only when the user asks to execute the status check.

## Workflow

1. Read `AGENTS.md`.
2. Check Python version and core dependency presence.
3. Check required files and directories.
4. Parse `config.yaml` and flag risky defaults.
5. Report relevant environment variables.
6. Probe live server health if `127.0.0.1:8787` is running.
7. Verify telemetry-kill environment variables are unset or disabled.

## Commands

Python and packages:

```bash
python --version
python -c "import fastapi, uvicorn, chromadb, langchain_core; print('core imports OK')"
```

Required files:

```bash
for f in data/personality/soul.md index/chroma_db index/bm25.json config.yaml requirements.txt; do
  test -e "$f" && echo "OK: $f" || echo "MISSING: $f"
done
```

Configuration:

```bash
python -c "import yaml; cfg=yaml.safe_load(open('config.yaml')); print('mode:', cfg['app']['mode']); print('host:', cfg['api']['host']); print('port:', cfg['api']['port']); print('top_k:', cfg['retrieval']['top_k']); print('min_score:', cfg['retrieval']['min_score']); print('grok_enabled:', cfg['models']['grok'].get('enabled', False))"
```

Environment:

```bash
python -c "import os; print('GROK_API_KEY:', 'SET' if os.environ.get('GROK_API_KEY') else 'MISSING'); print('CYCLAW_MODE:', os.environ.get('CYCLAW_MODE', 'not set'))"
```

Live health:

```bash
curl -s --connect-timeout 2 http://127.0.0.1:8787/health | python -m json.tool
```

Telemetry kill:

```bash
python -c "import os; vars=['LANGCHAIN_TRACING_V2','LANGCHAIN_API_KEY','CHROMA_TELEMETRY','ANONYMIZED_TELEMETRY','OTEL_EXPORTER_OTLP_ENDPOINT']; [print(f'{v}: {os.environ.get(v, \"not set\")}') for v in vars]"
```

## Flag Conditions

- Python is not 3.12.x.
- Core imports fail.
- `data/personality/soul.md`, `index/chroma_db`, or `index/bm25.json` is
  missing when runtime checks are requested.
- `api.host` is not `127.0.0.1`.
- Grok is unexpectedly enabled.
- Telemetry/tracing variables are enabled.
- Live health reports graph or index not ready.

## Output Shape

```text
=== CyClaw Environment Status ===
Python:        3.12.x / mismatch / unavailable
Soul file:     EXISTS / MISSING
ChromaDB:      EXISTS / MISSING
BM25 index:    EXISTS / MISSING
Config mode:   offline / hybrid / other
Server:        RUNNING / NOT RUNNING
Health status: healthy / degraded / unavailable
```

Include remediation steps for failures and list checks that were skipped because
dependencies, network, or server state were unavailable.
