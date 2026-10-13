"""Print the Groq model ids your GROQ_API_KEY can use (the key itself is never printed).
    python list_groq_models.py
"""
import os
import sys
# Windows consoles and redirected output (| tee, > file) may not be UTF-8;
# never crash on a symbol an LLM wrote, print a '?' instead.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
key = os.environ.get("GROQ_API_KEY", "").strip()
if not key:
    sys.exit("GROQ_API_KEY is empty in .env")
r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
if r.status_code != 200:
    sys.exit(f"Groq returned {r.status_code}: {r.text[:200]}")
ids = sorted(m["id"] for m in r.json().get("data", []) if m.get("active", True))
skip = ("whisper", "guard", "orpheus", "tts", "playai")
print("Chat models your key can use:")
for i in ids:
    if not any(s in i for s in skip):
        print("  ", i)
