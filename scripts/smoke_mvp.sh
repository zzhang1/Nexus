#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/tmp/nexus_demo}"

rm -rf "$ROOT"

python3 -m venv "$ROOT/.venv"
source "$ROOT/.venv/bin/activate"

pip install -e .

nexus init --root "$ROOT"

# Disable ingestion enrichment during smoke (keeps it deterministic and avoids requiring API keys).
python3 - <<PY
from pathlib import Path
import yaml

cfg_path = Path("$ROOT") / ".assistant" / "config.yaml"
data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
llm = data.get("llm", {}) or {}
enrich = llm.get("enrich", {}) or {}
enrich["enabled"] = False
llm["enrich"] = enrich
data["llm"] = llm
cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY

echo "Meet with Alice about taxes." > "$ROOT/0_Inbox/meeting.txt"
nexus --root "$ROOT" ingest

mkdir -p "$ROOT/Knowledge/2_Areas/Home"
TOMORROW="$(date -I -d '+1 day')"
cat > "$ROOT/Knowledge/2_Areas/Home/Home.md" <<EOF
---
type: note
title: Home
created: 2025-12-28T00:00:00+00:00
updated: 2025-12-28T00:00:00+00:00
status: active
tags: [home]
---

- [ ] Repaint door p:P2 effort:2h
- [ ] Clean gutters due:${TOMORROW} p:P1
EOF

nexus --root "$ROOT" sync

nexus --root "$ROOT" tasks
nexus --root "$ROOT" today
nexus --root "$ROOT" week

echo "Smoke OK: $ROOT"
