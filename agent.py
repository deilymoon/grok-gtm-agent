"""Orchestrate PRODUCT → ICP → COMPANIES → SIGNALS → SCORE → WHY NOW → CONTACT → OUTREACH."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from config import Config
from models import GTMResult, Opportunity, Product
from prompts import SCORING_RATIONALE_SYSTEM, SCORING_RATIONALE_USER
from research import demo_research, has_meaningful_evidence, live_research
from scoring import compute_gtm_score, opportunity_from_company
from url_utils import dedupe_urls, validate_url
from xai_client import XAIClient

ProgressFn = Callable[[str], None]


def _user_tz():
    for key in ("Europe/Kyiv", "Europe/Kiev"):
        try:
            return ZoneInfo(key)
        except Exception:
            continue
    return timezone(timedelta(hours=3))  # UTC+3 fallback


USER_TZ = _user_tz()


def _noop(_: str) -> None:
    pass


def _strip_unsourced_claims(why_now: str, sources: list[str], signals: list[str]) -> str:
    """Best-effort: if why_now invents URL-like claims not in sources, drop those sentences."""
    if not why_now:
        return why_now
    urls_in_text = re.findall(r"https?://[^\s\]\"'<>]+", why_now)
    allowed = {u.rstrip(").,;]").lower() for u in sources}
    bad = [u for u in urls_in_text if u.rstrip(").,;]").lower() not in allowed]
    if not bad:
        return why_now
    parts = re.split(r"(?<=[.!?])\s+", why_now)
    kept = []
    for p in parts:
        if any(b in p for b in bad):
            continue
        kept.append(p)
    return " ".join(kept).strip() or why_now


def _enrich_with_grok(
    product: Product,
    opportunities: list[Opportunity],
    icp_summary: str,
    target_team: str,
    cfg: Config,
    progress: ProgressFn,
) -> list[Opportunity]:
    """Live rationale pass for top opportunities — references actual signals/sources."""
    if cfg.mode != "live" or not cfg.xai_api_key:
        return opportunities

    enriched: list[Opportunity] = []
    with XAIClient(
        api_key=cfg.xai_api_key,
        base_url=cfg.api_base_url,
        model=cfg.model,
    ) as client:
        for opp in opportunities:
            progress(f"Writing outreach for {opp.company}...")
            bd = opp.score_breakdown or {}
            comps = bd.get("components", {})
            try:
                user = SCORING_RATIONALE_USER.format(
                    product_description=product.description,
                    company_name=opp.company,
                    company_description=opp.description,
                    signals="; ".join(opp.signals) or "none",
                    sources="; ".join(opp.sources) or "none",
                    icp_fit=comps.get("icp_fit", opp.icp_fit),
                    signal_strength=comps.get("signal_strength", opp.signal_score),
                    signal_freshness=comps.get("signal_freshness", 0),
                    problem_relevance=comps.get("problem_relevance", 0),
                    timing=comps.get("timing", opp.timing_score),
                    confidence=comps.get("confidence", 0),
                    gtm_score=int(opp.gtm_score),
                    icp_summary=icp_summary,
                    target_team=target_team,
                )
                data = client.chat_json(
                    SCORING_RATIONALE_SYSTEM,
                    user,
                    temperature=0.4,
                    retry_on_malformed=True,
                )
                why = data.get("why_now") or opp.why_now
                why = _strip_unsourced_claims(why, opp.sources, opp.signals)
                enriched.append(
                    opp.model_copy(
                        update={
                            "why_now": why,
                            "best_contact_role": data.get("best_contact_role")
                            or opp.best_contact_role,
                            "outreach_angle": data.get("outreach_angle") or opp.outreach_angle,
                            "outreach_message": data.get("outreach_message")
                            or opp.outreach_message,
                        }
                    )
                )
            except Exception as exc:
                progress(f"Outreach enrichment failed for {opp.company}: {exc}")
                enriched.append(opp)
    return enriched


def _sanitize_opportunity_urls(opp: Opportunity) -> Opportunity | None:
    """Drop malformed/duplicate URLs; require at least some evidence for live."""
    sources = dedupe_urls(list(opp.sources or []))
    website = opp.website if validate_url(opp.website) else None
    if website and website not in sources:
        pass
    why = _strip_unsourced_claims(opp.why_now, sources, opp.signals)
    return opp.model_copy(update={"sources": sources, "website": website, "why_now": why})


def _weak_evidence(opp: Opportunity) -> bool:
    """Filter weak opportunities before top-5 finalization."""
    if not opp.signals:
        return True
    if not opp.sources:
        return opp.gtm_score < 55
    return opp.gtm_score < 40


def run_pipeline(
    product_description: str,
    cfg: Config,
    progress: Optional[ProgressFn] = None,
    top_n: int = 5,
) -> GTMResult:
    progress = progress or _noop
    product = Product(description=product_description.strip())

    if cfg.mode == "demo":
        icp, companies = demo_research(product, cfg.demo_dir, progress)
    else:
        if not cfg.xai_api_key:
            raise RuntimeError("Live mode requires XAI_API_KEY.")
        icp, companies = live_research(
            product,
            cfg.xai_api_key,
            cfg.model,
            cfg.api_base_url,
            progress,
            limit=cfg.research_limit,
        )

    progress(f"Scoring {len(companies)} companies...")
    scored: list[Opportunity] = []
    for co in companies:
        if cfg.mode == "live" and not has_meaningful_evidence(co):
            continue
        bd = compute_gtm_score(co, product, icp)
        opp = opportunity_from_company(co, product, icp)
        opp.gtm_score = float(bd["gtm_score"])
        scored.append(opp)

    scored.sort(key=lambda o: o.gtm_score, reverse=True)

    filtered = [o for o in scored if not _weak_evidence(o)]
    if cfg.mode == "live":
        pool = filtered if filtered else [o for o in scored if o.signals]
    else:
        pool = filtered if filtered else scored

    top = pool[:top_n]
    sanitized: list[Opportunity] = []
    for opp in top:
        clean = _sanitize_opportunity_urls(opp)
        if clean is None:
            continue
        sanitized.append(clean)
    top = sanitized[:top_n]

    if cfg.mode == "live":
        top = _enrich_with_grok(product, top, icp.summary, icp.target_team, cfg, progress)
        top = [c for o in top if (c := _sanitize_opportunity_urls(o)) is not None]

    if cfg.mode == "live" and len(top) < top_n:
        progress(
            f"Warning: only {len(top)} opportunities with verified evidence "
            f"(requested {top_n})."
        )

    progress("Top 5 ready." if len(top) >= 5 else f"Top {len(top)} ready.")
    return GTMResult(product=product, icp=icp, opportunities=top, mode=cfg.mode)


def save_leads(result: GTMResult, path: Path) -> Path:
    """Write leads.json (array of opportunities with score_breakdown + sources)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [opp.to_export_dict(include_breakdown=True) for opp in result.opportunities]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def save_run(result: GTMResult, runs_dir: Path | None = None) -> Path:
    """Write timestamped run file under output/runs/YYYY-MM-DD_HHMMSS.json (local user TZ)."""
    root = Path(__file__).resolve().parent
    runs_dir = runs_dir or (root / "output" / "runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    now_local = datetime.now(USER_TZ)
    stamp = now_local.strftime("%Y-%m-%d_%H%M%S")
    path = runs_dir / f"{stamp}.json"
    payload = {
        "timestamp": now_local.isoformat(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": result.mode,
        "product": result.product.model_dump(),
        "icp": result.icp.model_dump(),
        "opportunities": [
            opp.to_export_dict(include_breakdown=True) for opp in result.opportunities
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def save_outputs(result: GTMResult, leads_path: Path) -> tuple[Path, Path]:
    leads = save_leads(result, leads_path)
    run = save_run(result)
    return leads, run
