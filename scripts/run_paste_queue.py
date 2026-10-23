#!/usr/bin/env python3
"""
run_paste_queue.py — Drains the admin manual-paste queue in Supabase.

The admin panel (frontend) inserts pasted bulletins into
public.manual_ingest_queue; this script — run by the manual-ingest
GitHub Action (every 15 min or on demand) — claims pending rows and
runs each paste through scripts.run_manual_paste (region auto-detected
from the text, falling back to the admin's selection), then marks the
row done/failed so the panel can show the outcome.

Runs with the SUPABASE_KEY service secret (bypasses RLS) — only the
Action ever holds it; the frontend never does.
"""
import os
import sys
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from shared.sync_engine import get_supabase_client
from scripts.run_manual_paste import main as run_manual_paste, detect_navarea, REGIONS

QUEUE_TABLE = "manual_ingest_queue"
MAX_ROWS_PER_RUN = 20


def _set_status(client, row_id, status, detected=None, result=None):
    patch = {"status": status, "processed_at": os.environ.get("NOW") or None}
    # processed_at handled below via .update with now() unavailable; use ISO from time
    import datetime
    patch["processed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if detected is not None:
        patch["detected_navarea"] = detected
    if result is not None:
        patch["result"] = result[:2000]
    client.table(QUEUE_TABLE).update(patch).eq("id", row_id).execute()


def main() -> bool:
    client = get_supabase_client()
    res = (
        client.table(QUEUE_TABLE)
        .select("id, navarea, raw_text")
        .eq("status", "pending")
        .order("created_at")
        .limit(MAX_ROWS_PER_RUN)
        .execute()
    )
    rows = res.data or []
    if not rows:
        print("Paste queue empty — nothing to ingest.")
        return True

    print(f"Draining paste queue: {len(rows)} row(s).")
    all_ok = True
    for row in rows:
        row_id = row["id"]
        raw_text = row.get("raw_text") or ""
        detected = detect_navarea(raw_text)
        effective = detected or row.get("navarea")
        if not effective or effective not in REGIONS:
            _set_status(client, row_id, "failed", detected,
                        "Could not determine NAVAREA region (no header in text "
                        "and no selection) — not ingested.")
            all_ok = False
            continue
        if detected and row.get("navarea") and detected != row.get("navarea"):
            print(f"  Row {row_id}: selection '{row['navarea']}' overridden by "
                  f"text header '{detected}'.")

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(raw_text)
            tmp_path = f.name
        try:
            ok = run_manual_paste(["--navarea", effective, "--input", tmp_path])
        except Exception as e:
            print(f"  Row {row_id}: ingest raised {e}")
            ok = False
        finally:
            os.unlink(tmp_path)

        _set_status(client, row_id, "done" if ok else "failed", detected,
                    f"ingested via region '{effective}'"
                    + ("" if ok else " — see Action log for details"))
        all_ok = all_ok and ok
        print(f"  Row {row_id}: {'OK' if ok else 'FAILED'} (region {effective})")

    return all_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
