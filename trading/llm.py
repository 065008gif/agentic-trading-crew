"""
LLM factory with an ordered fallback chain. Only free providers are used.

LLM_CHAIN in .env decides the order, e.g.  groq,groq_backup,openrouter
  groq          Groq free tier, GROQ_MODEL (default openai/gpt-oss-120b)
  groq_backup   Groq free tier, second model with its own daily quota
  openrouter    OpenRouter ":free" model, OPENROUTER_MODEL
  ollama_cloud  Ollama Cloud free tier (OLLAMA_API_KEY), OLLAMA_CLOUD_MODEL
  ollama        Local Ollama on this computer, OLLAMA_MODEL

If one provider fails (rate limit, outage, bad key) the crew is re-run on the
next one. If every provider fails, the system still trades on the pure
rule-based Alpha Score plan, so a run never ends without a decision.
"""

from __future__ import annotations

import os
import warnings

from crewai import LLM

# harmless CrewAI notice about callbacks and checkpoints; hide it from the run output
warnings.filterwarnings("ignore", message="function callbacks cannot be serialized")


def _env(k: str, d: str = "") -> str:
    return (os.environ.get(k) or d).strip()


def describe(name: str) -> str:
    return {
        "groq": f"groq:{_env('GROQ_MODEL', 'openai/gpt-oss-120b')}",
        "groq_backup": f"groq:{_env('GROQ_BACKUP_MODEL', 'openai/gpt-oss-20b')}",
        "openrouter": f"openrouter:{_env('OPENROUTER_MODEL', 'openai/gpt-oss-20b:free')}",
        "ollama_cloud": f"ollama-cloud:{_env('OLLAMA_CLOUD_MODEL', 'gpt-oss:120b')}",
        "ollama": f"ollama-local:{_env('OLLAMA_MODEL', 'qwen3:8b')}",
    }.get(name, name)


def make_llm(name: str) -> LLM | None:
    """Build one provider's LLM, or None if its key is not configured."""
    common = {"temperature": 0.2, "max_retries": 6}
    if name in ("groq", "groq_backup"):
        key = _env("GROQ_API_KEY")
        if not key:
            return None
        model = _env("GROQ_MODEL", "openai/gpt-oss-120b") if name == "groq" \
            else _env("GROQ_BACKUP_MODEL", "openai/gpt-oss-20b")
        # CrewAI strips one leading "openai/" when routing; add it back so Groq
        # receives its exact model id (e.g. "openai/gpt-oss-120b").
        return LLM(model=f"openai/{model}", custom_openai=True,
                   base_url=_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"), api_key=key, **common)
    if name == "openrouter":
        key = _env("OPENROUTER_API_KEY")
        if not key:
            return None
        return LLM(model=f"openrouter/{_env('OPENROUTER_MODEL', 'openai/gpt-oss-20b:free')}",
                   api_key=key, **common)
    if name == "ollama_cloud":
        key = _env("OLLAMA_API_KEY")
        if not key:
            return None
        return LLM(model=f"ollama/{_env('OLLAMA_CLOUD_MODEL', 'gpt-oss:120b')}",
                   base_url="https://ollama.com", api_key=key, **common)
    if name == "ollama":
        if _env("OLLAMA_ENABLED", "0") != "1":
            return None
        return LLM(model=f"ollama/{_env('OLLAMA_MODEL', 'qwen3:8b')}",
                   base_url=_env("OLLAMA_LOCAL_URL", "http://localhost:11434"), **common)
    return None


def chain() -> list[tuple[str, LLM]]:
    """Configured providers in fallback order (skips any without a key)."""
    names = [n.strip() for n in _env("LLM_CHAIN", "groq,groq_backup,openrouter,ollama_cloud").split(",") if n.strip()]
    out = []
    for n in names:
        llm = make_llm(n)
        if llm is not None:
            out.append((n, llm))
    return out


def pause_seconds(name: str) -> float:
    """Pause between tasks so Groq's free tokens-per-minute limit is never hit."""
    if name.startswith("groq"):
        return float(_env("LLM_PAUSE_SECONDS", "12"))
    return float(_env("LLM_PAUSE_SECONDS_OTHER", "0"))
