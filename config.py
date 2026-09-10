"""Configuration loader for Grok GTM Agent."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = "grok-4-1-fast-reasoning"


@dataclass
class Config:
    mode: str  # demo | live
    xai_api_key: str | None
    model: str
    output_path: Path
    demo_dir: Path
    api_base_url: str = "https://api.x.ai/v1"
    research_limit: int = 15
    verbose: bool = False


def load_config(
    mode_override: str | None = None,
    *,
    output_override: str | Path | None = None,
    limit: int | None = None,
    verbose: bool = False,
    model_override: str | None = None,
) -> Config:
    mode = (mode_override or os.getenv("MODE", "demo")).strip().lower()
    if mode not in {"demo", "live"}:
        print(f"Invalid MODE '{mode}'. Use 'demo' or 'live'.", file=sys.stderr)
        sys.exit(1)

    api_key = os.getenv("XAI_API_KEY") or None
    if api_key:
        api_key = api_key.strip() or None

    model = (
        (model_override or os.getenv("MODEL", DEFAULT_MODEL) or DEFAULT_MODEL)
        .strip()
        or DEFAULT_MODEL
    )

    if mode == "live" and not api_key:
        print(
            "Live mode requires XAI_API_KEY. Set it in .env or the environment,\n"
            "or run with --mode demo.",
            file=sys.stderr,
        )
        sys.exit(1)

    out = Path(output_override) if output_override else (ROOT / "output" / "leads.json")
    if not out.is_absolute():
        out = ROOT / out

    research_limit = int(limit) if limit is not None else int(os.getenv("RESEARCH_LIMIT", "15"))
    research_limit = max(1, min(50, research_limit))

    return Config(
        mode=mode,
        xai_api_key=api_key,
        model=model,
        output_path=out,
        demo_dir=ROOT / "demo",
        research_limit=research_limit,
        verbose=verbose,
    )
