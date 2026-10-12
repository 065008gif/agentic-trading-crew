"""
Zip this computer's run records (agent .md files, plans, trade journal,
equity log) to send to the teammate writing the report:
    python export_reports.py      ->  reports_<ACCOUNT>_<date>.zip
"""

import os
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
src = ROOT / "run_reports"
if not src.exists():
    raise SystemExit("No run_reports folder yet - run the crew first.")
label = os.environ.get("ACCOUNT_LABEL", "")
out = ROOT / f"reports_{label or 'all'}_{datetime.now():%d%m%Y-%H%M}.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in src.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(ROOT))
print(f"Created {out.name} ({out.stat().st_size // 1024} KB). Send this file to Akshit.")
