"""Company discovery + signal detection. LIVE vs DEMO cleanly separated.

LIVE research uses xAI built-in web_search and x_search via the Responses API
(see xai_client.research_with_tools). Never silently falls back to demo data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from models import Company, ICP, Product, Signal
from prompts import (
    COMPANY_DISCOVERY_SYSTEM,
    COMPANY_DISCOVERY_USER,
    ICP_SYSTEM,
    ICP_USER,
    SIGNAL_RESEARCH_SYSTEM,
    SIGNAL_RESEARCH_USER,
)
from url_utils import dedupe_urls, validate_url
from xai_client import (
    AuthError,
    InvalidResponseError,
    RateLimitError,
    ResearchError,
    TimeoutError as XAITimeoutError,
    XAIClient,
)

ProgressFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# DEMO
# ---------------------------------------------------------------------------

def load_demo_icp(demo_dir: Path, product: Product) -> ICP:
    path = demo_dir / "icp.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return ICP(**data)


def load_demo_companies(demo_dir: Path) -> list[Company]:
    path = demo_dir / "companies.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    companies: list[Company] = []
    for item in raw:
        signals = [Signal(**s) for s in item.get("signals", [])]
        companies.append(
            Company(
                name=item["name"],
                website=item.get("website"),
                description=item.get("description", ""),
                industry=item.get("industry"),
                size=item.get("size"),
                location=item.get("location"),
                signals=signals,
                sources=item.get("sources", []),
                raw_notes=item.get("raw_notes"),
            )
        )
    return companies


def demo_research(
    product: Product,
    demo_dir: Path,
    progress: ProgressFn | None = None,
) -> tuple[ICP, list[Company]]:
    progress = progress or _noop
    progress("Loading deterministic ICP from demo dataset...")
    icp = load_demo_icp(demo_dir, product)
    progress("Loading candidate companies + signals from demo dataset...")
    companies = load_demo_companies(demo_dir)
    return icp, companies


# ---------------------------------------------------------------------------
# LIVE helpers
# ---------------------------------------------------------------------------

def _icp_from_dict(data: dict) -> ICP:
    """Validate ICP JSON with Pydantic; map rich + legacy fields."""
    if not data.get("target_industries") and data.get("industry"):
        data = {**data, "target_industries": [data["industry"]]}
    if not data.get("target_markets") and data.get("markets"):
        data = {**data, "target_markets": list(data["markets"])}
    if not data.get("markets") and data.get("target_markets"):
        data = {**data, "markets": list(data["target_markets"])}
    if not data.get("target_departments") and data.get("target_team"):
        data = {**data, "target_departments": [data["target_team"]]}
    if not data.get("positive_signals") and data.get("buying_triggers"):
        data = {**data, "positive_signals": list(data["buying_triggers"])}
    if not data.get("buying_triggers") and data.get("positive_signals"):
        data = {**data, "buying_triggers": list(data["positive_signals"])}
    if not data.get("industry") and data.get("target_industries"):
        data = {**data, "industry": data["target_industries"][0]}
    if not data.get("target_team") and data.get("target_departments"):
        data = {**data, "target_team": data["target_departments"][0]}
    return ICP.model_validate(data)


def _parse_signals_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def _signal_from_dict(s: dict, allowed_urls: set[str]) -> Signal | None:
    url = s.get("source_url")
    if url:
        url = str(url).strip()
        if url not in allowed_urls and not validate_url(url):
            url = None
        elif url not in allowed_urls:
            url = None
        elif not validate_url(url):
            url = None

    conf = s.get("confidence")
    strength = float(s.get("strength", 0.5) or 0.5)
    strength = max(0.0, min(1.0, strength))
    rel = s.get("relevance_to_product")
    try:
        rel_f = float(rel) if rel is not None else None
        if rel_f is not None:
            rel_f = max(0.0, min(1.0, rel_f))
    except (TypeError, ValueError):
        rel_f = None

    desc = (s.get("description") or "").strip()
    if not desc and not s.get("title"):
        return None

    return Signal(
        type=(s.get("type") or "unknown").strip() or "unknown",
        title=(s.get("title") or None),
        description=desc or (s.get("title") or ""),
        freshness_days=s.get("freshness_days"),
        freshness_band=s.get("freshness_band"),
        source_url=url,
        source_name=s.get("source_name"),
        published_date=s.get("published_date"),
        confidence=conf,
        relevance_to_product=rel_f,
        strength=strength,
    )


def has_meaningful_evidence(company: Company) -> bool:
    """True if company has usable non-LOW signals and/or verified sources."""
    usable = [
        s
        for s in company.signals
        if (s.confidence or "MEDIUM").upper() != "LOW"
        or (s.source_url and validate_url(s.source_url))
        or (s.strength >= 0.55 and s.description)
    ]
    urls = [u for u in company.sources if validate_url(u)]
    urls += [s.source_url for s in company.signals if s.source_url and validate_url(s.source_url)]
    if not usable:
        return False
    if urls:
        return True
    medium_plus = [
        s for s in usable if (s.confidence or "").upper() in {"HIGH", "MEDIUM"} or s.strength >= 0.6
    ]
    return len(medium_plus) >= 2


# ---------------------------------------------------------------------------
# LIVE pipeline
# ---------------------------------------------------------------------------

def live_build_icp(
    product: Product,
    client: XAIClient,
    progress: ProgressFn | None = None,
) -> ICP:
    progress = progress or _noop
    progress("Building ICP...")
    try:
        data = client.chat_json(
            ICP_SYSTEM,
            ICP_USER.format(product_description=product.description),
            retry_on_malformed=True,
        )
        icp = _icp_from_dict(data)
    except InvalidResponseError:
        raise ResearchError("ICP generation returned malformed JSON after retry.")
    return icp


def live_discover_companies(
    product: Product,
    icp: ICP,
    client: XAIClient,
    *,
    limit: int = 15,
    progress: ProgressFn | None = None,
) -> list[Company]:
    progress = progress or _noop
    progress("Discovering companies...")
    ask_n = max(10, min(20, max(int(limit), 10)))
    data = client.chat_json(
        COMPANY_DISCOVERY_SYSTEM,
        COMPANY_DISCOVERY_USER.format(
            product_description=product.description,
            industry=icp.industry,
            company_size=icp.company_size,
            markets=", ".join(icp.markets or icp.target_markets),
            target_team=icp.target_team,
            target_departments=", ".join(icp.target_departments or [icp.target_team]),
            buyer_roles=", ".join(icp.buyer_roles or []),
            pain_points=", ".join(icp.pain_points),
            buying_triggers=", ".join(icp.buying_triggers or icp.positive_signals),
            negative_signals=", ".join(icp.negative_signals or []),
            icp_summary=icp.summary,
            limit=ask_n,
        ),
        retry_on_malformed=True,
    )
    companies: list[Company] = []
    for item in data.get("companies") or []:
        website = item.get("website")
        if website and not validate_url(str(website)):
            website = None
        companies.append(
            Company(
                name=item.get("name", "Unknown"),
                website=website,
                description=item.get("description", ""),
                industry=item.get("industry"),
                size=item.get("size"),
                location=item.get("location"),
                signals=[],
                sources=[],
                raw_notes=item.get("research_notes"),
            )
        )
    progress(f"Found {len(companies)} candidates")
    return companies


def live_research_company_signals(
    product: Product,
    icp: ICP,
    company: Company,
    client: XAIClient,
    progress: ProgressFn | None = None,
) -> Company:
    """Tool-augmented research for one company; attach only verified citation URLs."""
    progress = progress or _noop
    progress(f"Researching {company.name}...")

    research_prompt = (
        f"Research buying signals for company '{company.name}' "
        f"(website: {company.website or 'unknown'}) related to this product:\n"
        f"{product.description}\n\n"
        f"ICP: {icp.summary}\n"
        f"Look for: funding, hiring (esp. {icp.target_team}), leadership hires, "
        f"product launches, expansion, support/CX pain, complaints, migrations.\n"
        f"Prefer evidence from the last 180 days. Cite real URLs.\n"
        f"Also search X/Twitter for recent posts about {company.name} and support/CX issues."
    )

    try:
        result = client.research_with_tools(
            research_prompt,
            system=(
                "You are a B2B researcher. Use web_search and x_search to find "
                "recent, verifiable buying signals. Always cite sources with real URLs."
            ),
        )
    except (AuthError, RateLimitError, XAITimeoutError):
        raise
    except ResearchError as exc:
        progress(f"Research failed for {company.name}: {exc}")
        return company.model_copy(update={"signals": [], "sources": list(company.sources)})

    citation_set = set(result.citations)
    if company.website and validate_url(company.website):
        citation_set.add(company.website)

    try:
        structured = client.chat_json(
            SIGNAL_RESEARCH_SYSTEM,
            SIGNAL_RESEARCH_USER.format(
                product_description=product.description,
                icp_summary=icp.summary,
                target_team=icp.target_team,
                pain_points=", ".join(icp.pain_points),
                positive_signals=", ".join(icp.positive_signals or icp.buying_triggers),
                company_name=company.name,
                website=company.website or "",
                company_description=company.description,
                citation_urls="\n".join(sorted(citation_set)) or "(none)",
                research_text=result.text[:12000],
            ),
            retry_on_malformed=True,
        )
    except Exception:
        try:
            structured = _parse_signals_json(result.text)
        except Exception as exc:
            progress(f"Signal parse failed for {company.name}: {exc}")
            structured = {"signals": [], "notes": result.text[:500]}

    signals: list[Signal] = []
    sources = list(company.sources)
    for raw in structured.get("signals") or []:
        if not isinstance(raw, dict):
            continue
        sig = _signal_from_dict(raw, citation_set)
        if not sig:
            continue
        signals.append(sig)
        if sig.source_url and sig.source_url not in sources:
            sources.append(sig.source_url)

    for c in result.citations:
        if validate_url(c) and c not in sources:
            sources.append(c)
    sources = dedupe_urls(sources)

    note = structured.get("notes") or ""
    raw_notes = (company.raw_notes or "")
    if note:
        raw_notes = (raw_notes + "\n" + str(note)).strip()
    raw_notes = (raw_notes + "\n--- research excerpt ---\n" + result.text[:2000]).strip()

    verified = sum(1 for s in signals if s.source_url)
    progress(f"{verified} signals verified" if signals else "0 signals verified")

    return company.model_copy(
        update={"signals": signals, "sources": sources, "raw_notes": raw_notes}
    )


def live_research(
    product: Product,
    api_key: str,
    model: str,
    base_url: str,
    progress: ProgressFn | None = None,
    *,
    limit: int = 15,
) -> tuple[ICP, list[Company]]:
    """Full LIVE pipeline with tool-augmented per-company research.

    Raises AuthError/RateLimitError/ResearchError on failure — never returns demo data.
    """
    progress = progress or _noop
    with XAIClient(api_key=api_key, base_url=base_url, model=model) as client:
        icp = live_build_icp(product, client, progress)
        candidates = live_discover_companies(
            product, icp, client, limit=limit, progress=progress
        )
        if not candidates:
            raise ResearchError("Company discovery returned no candidates.")

        to_research = candidates[: max(1, min(limit, len(candidates)))]
        qualified: list[Company] = []
        for co in to_research:
            enriched = live_research_company_signals(product, icp, co, client, progress)
            if has_meaningful_evidence(enriched):
                qualified.append(enriched)
            else:
                progress(f"Discarded {co.name}: insufficient evidence")

        progress(f"Scoring {len(qualified)} qualified companies...")
        return icp, qualified
