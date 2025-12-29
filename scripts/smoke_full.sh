#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/tmp/nexus_full}"
API_KEY="${OPENROUTER_API_KEY:-}"

rm -rf "$ROOT"

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
"$ROOT/.venv/bin/python" -m pip install -e .[dev] >/dev/null
NEXUS="$ROOT/.venv/bin/nexus"

"$NEXUS" init --root "$ROOT"

# Configure calendar + enrichment
python3 - <<PY
from pathlib import Path
import yaml

cfg_path = Path("$ROOT") / ".assistant" / "config.yaml"
data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
data.setdefault("llm", {})
data["llm"]["provider"] = "openrouter"
data["llm"]["model"] = "xiaomi/mimo-v2-flash:free"
data["llm"]["weak_model"] = "xiaomi/mimo-v2-flash:free"
data.setdefault("calendar", {})
data["calendar"]["ics_paths"] = [str(Path("$ROOT") / "calendar.ics")]
data.setdefault("integrations", {})
data["integrations"]["mode"] = "read_only"
cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY

if [[ -z "$API_KEY" ]]; then
  echo "NOTE: OPENROUTER_API_KEY not set; AI enrichment + chat actions will be skipped."
  python3 - <<PY
from pathlib import Path
import yaml

cfg_path = Path("$ROOT") / ".assistant" / "config.yaml"
data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
data.setdefault("llm", {})
data["llm"].setdefault("enrich", {})
data["llm"]["enrich"]["enabled"] = False
cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
PY
fi

# Create a simple PDF with text (minimal PDF generator).
python3 - <<'PY'
from pathlib import Path

def make_pdf(path: Path, text: str):
    objects = []

    def add_obj(s: bytes):
        objects.append(s)

    add_obj(b"<< /Type /Catalog /Pages 2 0 R >>")
    add_obj(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add_obj(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("utf-8")
    add_obj(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    xref_offsets = []
    out = b"%PDF-1.4\n"
    for i, obj in enumerate(objects, start=1):
        xref_offsets.append(len(out))
        out += f"{i} 0 obj\n".encode()
        out += obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in xref_offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {len(objects)+1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_pos}\n".encode()
    out += b"%%EOF\n"
    path.write_bytes(out)

root = Path("/tmp/nexus_full")
pdf_path = root / "0_Inbox" / "sample.pdf"
make_pdf(pdf_path, "Nexus PDF says: roof repair receipt")
PY

echo "Home maintenance note." > "$ROOT/0_Inbox/home.txt"

"$NEXUS" --root "$ROOT" ingest

mkdir -p "$ROOT/Knowledge/2_Areas/Home"
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
EOF

"$NEXUS" --root "$ROOT" sync

# Calendar sync + planning
cat > "$ROOT/calendar.ics" <<'EOF'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Nexus//EN
BEGIN:VEVENT
UID:event-1@example.com
DTSTAMP:20251229T120000Z
DTSTART:20251229T160000Z
DTEND:20251229T170000Z
SUMMARY:Nexus Demo Event
END:VEVENT
END:VCALENDAR
EOF

"$NEXUS" --root "$ROOT" calendar sync
"$NEXUS" --root "$ROOT" today
"$NEXUS" --root "$ROOT" week

# Outbox
mkdir -p "$ROOT/Outbox/drafts"
echo "Draft email body" > "$ROOT/Outbox/drafts/email.md"
"$NEXUS" --root "$ROOT" outbox list
printf "y\n" | "$NEXUS" --root "$ROOT" outbox approve drafts/email.md >/dev/null || true
"$NEXUS" --root "$ROOT" outbox list

# Chat retrieval (LLM or fallback excerpts)
echo "Chat retrieval:"
"$NEXUS" --root "$ROOT" chat "roof repair receipt" || true

# Chat-driven ingestion (requires LLM + approval)
if [[ -n "$API_KEY" ]]; then
  printf "y\n" | "$NEXUS" --root "$ROOT" chat "Add that I need to clean the gutters by next month." || true
  "$NEXUS" --root "$ROOT" tasks
else
  echo "Skipping chat-driven edits (no OPENROUTER_API_KEY)."
fi

"$NEXUS" --root "$ROOT" doctor

echo "Full smoke OK: $ROOT"
