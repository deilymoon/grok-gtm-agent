"""Explainable GTM scoring: component scores + weighted final score."""

from __future__ import annotations

from typing import Any

from models import Company, ICP, Opportunity, Product, Signal

WEIGHTS = {
    "icp_fit": 0.25,
    "signal_strength": 0.20,
    "signal_freshness": 0.15,
    "problem_relevance": 0.15,
    "timing": 0.15,
    "confidence": 0.10,
}

HIGH_TIMING_TYPES = {
    "funding",
    "hiring",
    "department_hire",
    "leadership_hire",
    "product_launch",
    "enterprise_expansion",
    "market_expansion",
    "migration",
    "competitor",
    "complaints",
    "bottleneck",
    "growth",
    "problem_discussion",
}


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _avg(vals: list[float], default: float = 50.0) -> float:
    return sum(vals) / len(vals) if vals else default


def score_icp_fit(company: Company, icp: ICP) -> tuple[float, str]:
    score = 55.0
    reasons: list[str] = []

    if company.industry and icp.industry:
        ind_c = company.industry.lower()
        ind_i = icp.industry.lower()
        if ind_i in ind_c or any(tok in ind_c for tok in ind_i.replace("/", " ").split() if len(tok) > 2):
            score += 20
            reasons.append("industry match")
        elif "saas" in ind_c and "saas" in ind_i:
            score += 15
            reasons.append("SaaS adjacency")

    if company.size and icp.company_size:
        size_l = company.size.lower()
        if any(k in size_l for k in ("50", "100", "200", "500", "mid", "scale")):
            score += 10
            reasons.append("size in ICP band")
        elif any(k in size_l for k in ("10", "20", "startup", "early")):
            score += 5
            reasons.append("adjacent size")

    if company.location and icp.markets:
        loc = company.location.lower()
        markets = [m.lower() for m in icp.markets]
        if any(m in loc or loc in m for m in markets) or any(
            token in loc for m in markets for token in ("us", "usa", "europe", "uk", "eu") if token in m or m in ("us", "usa", "europe", "uk", "eu")
        ):
            if any(t in loc for t in ("us", "united states", "usa", "new york", "san francisco", "seattle", "austin", "boston")) and any(
                "us" in m or "united" in m for m in markets
            ):
                score += 8
                reasons.append("market overlap (US)")
            elif any(t in loc for t in ("uk", "london", "berlin", "europe", "amsterdam", "paris", "dublin")) and any(
                "europe" in m or "uk" in m or "eu" in m for m in markets
            ):
                score += 8
                reasons.append("market overlap (Europe)")
            elif any(m[:2] in loc for m in markets if len(m) >= 2):
                score += 5
                reasons.append("partial market overlap")

    if company.signals:
        score += min(10, 3 * len(company.signals))
        reasons.append(f"{len(company.signals)} signals present")

    if score > 96:
        score = 96
    score = _clamp(score)
    explanation = "; ".join(reasons) if reasons else "baseline ICP proximity"
    return score, explanation


def score_signal_strength(signals: list[Signal]) -> tuple[float, str]:
    if not signals:
        return 25.0, "no signals detected"
    strengths = [s.strength for s in signals]
    base = _avg(strengths) * 100
    strong = sum(1 for s in strengths if s >= 0.7)
    base += min(15, strong * 5)
    base += min(10, (len(signals) - 1) * 3)
    return _clamp(base), f"{len(signals)} signals, {strong} strong"


def _freshness_band_score(days: int | None, band: str | None = None) -> float:
    b = (band or "").strip()
    if not b and days is not None:
        if days <= 30:
            b = "0-30"
        elif days <= 90:
            b = "31-90"
        elif days <= 180:
            b = "91-180"
        else:
            b = ">180"
    if b == "0-30" or (days is not None and days <= 30):
        if days is not None and days <= 14:
            return 95.0
        return 85.0
    if b == "31-90" or (days is not None and days <= 90):
        if days is not None and days <= 60:
            return 70.0
        return 55.0
    if b == "91-180" or (days is not None and days <= 180):
        return 40.0
    if b == ">180" or (days is not None and days > 180):
        return 18.0
    return 50.0


def score_signal_freshness(signals: list[Signal]) -> tuple[float, str]:
    if not signals:
        return 40.0, "no freshness data"
    scores: list[float] = []
    for s in signals:
        scores.append(_freshness_band_score(s.freshness_days, s.freshness_band))
    avg = _avg(scores)
    freshest = min((s.freshness_days for s in signals if s.freshness_days is not None), default=None)
    note = f"freshest ~{freshest}d" if freshest is not None else "mixed / unknown freshness"
    return _clamp(avg), note


def score_problem_relevance(company: Company, product: Product, icp: ICP) -> tuple[float, str]:
    text_blob = " ".join(
        [
            company.description.lower(),
            (company.raw_notes or "").lower(),
            " ".join(s.description.lower() + " " + s.type.lower() for s in company.signals),
            " ".join(icp.pain_points).lower(),
            product.description.lower(),
        ]
    )
    keywords = [
        "support",
        "customer service",
        "helpdesk",
        "ticket",
        "research",
        "automation",
        "ai",
        "cx",
        "ops",
        "scale",
        "bottleneck",
        "complaint",
        "agent",
        "knowledge",
        "onboarding",
        "churn",
        "nps",
    ]
    hits = [k for k in keywords if k in text_blob]
    score = 40 + min(45, len(hits) * 5)
    for s in company.signals:
        t = s.type.lower()
        if any(x in t for x in ("complaint", "bottleneck", "hiring", "department", "migration")):
            score += 5
    return _clamp(score), f"keyword hits: {', '.join(hits[:6]) or 'few'}"


def score_timing(signals: list[Signal]) -> tuple[float, str]:
    if not signals:
        return 30.0, "no timing signals"
    score = 35.0
    reasons: list[str] = []
    for s in signals:
        t = s.type.lower().replace(" ", "_").replace("-", "_")
        strength_boost = s.strength * 25
        matched = False
        for key in HIGH_TIMING_TYPES:
            if key in t or t in key:
                score += 8 + strength_boost * 0.3
                reasons.append(s.type)
                matched = True
                break
        if not matched and s.strength >= 0.6:
            score += 4
            reasons.append(s.type)
        if s.freshness_days is not None and s.freshness_days <= 45:
            score += 4
    return _clamp(score), ("timing drivers: " + ", ".join(reasons[:4])) if reasons else "weak timing"


_CONF_MAP = {"HIGH": 95.0, "MEDIUM": 65.0, "LOW": 30.0}


def score_confidence(company: Company) -> tuple[float, str]:
    conf_scores = [
        _CONF_MAP.get((s.confidence or "").upper())
        for s in company.signals
        if (s.confidence or "").upper() in _CONF_MAP
    ]
    if conf_scores:
        base = _avg(conf_scores)
    else:
        base = 45.0

    url_sources = [u for u in company.sources if u and u.startswith("http")]
    signal_urls = [
        s.source_url for s in company.signals if s.source_url and s.source_url.startswith("http")
    ]
    n_urls = len(set(url_sources + [u for u in signal_urls if u]))
    if n_urls:
        base = min(100.0, base + min(20, n_urls * 5))
    else:
        base = max(25.0, base - 15)

    if company.website:
        base += 5
    if company.signals:
        base += min(8, len(company.signals) * 2)

    highs = sum(1 for s in company.signals if (s.confidence or "").upper() == "HIGH")
    note = f"{n_urls} evidence URLs, {len(company.signals)} signals, {highs} HIGH"
    return _clamp(base), note


def compute_gtm_score(
    company: Company,
    product: Product,
    icp: ICP,
) -> dict[str, Any]:
    icp_fit, icp_why = score_icp_fit(company, icp)
    sig_str, sig_why = score_signal_strength(company.signals)
    fresh, fresh_why = score_signal_freshness(company.signals)
    prob, prob_why = score_problem_relevance(company, product, icp)
    timing, timing_why = score_timing(company.signals)
    conf, conf_why = score_confidence(company)

    components = {
        "icp_fit": icp_fit,
        "signal_strength": sig_str,
        "signal_freshness": fresh,
        "problem_relevance": prob,
        "timing": timing,
        "confidence": conf,
    }
    explanations = {
        "icp_fit": icp_why,
        "signal_strength": sig_why,
        "signal_freshness": fresh_why,
        "problem_relevance": prob_why,
        "timing": timing_why,
        "confidence": conf_why,
    }

    weighted = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    gtm = int(round(_clamp(weighted)))

    return {
        "components": components,
        "explanations": explanations,
        "weights": dict(WEIGHTS),
        "gtm_score": gtm,
        "icp_fit": round(icp_fit, 1),
        "signal_score": round(sig_str, 1),
        "timing_score": round(timing, 1),
    }


def opportunity_from_company(
    company: Company,
    product: Product,
    icp: ICP,
    why_now: str = "",
    best_contact_role: str = "",
    outreach_angle: str = "",
    outreach_message: str = "",
) -> Opportunity:
    breakdown = compute_gtm_score(company, product, icp)
    signal_labels = [f"{s.type}: {s.description}" for s in company.signals]
    sources = list(company.sources)
    for s in company.signals:
        if s.source_url and s.source_url not in sources:
            sources.append(s.source_url)

    if not why_now:
        why_now = _default_why_now(company, breakdown)
    if not best_contact_role:
        team = (icp.target_team or "Customer Support").strip()
        if team.lower().startswith(("head ", "vp ", "director ", "chief ")):
            best_contact_role = team
        else:
            best_contact_role = f"Head of {team}"
    if not outreach_angle:
        outreach_angle = _default_angle(company, product)
    if not outreach_message:
        outreach_message = _default_outreach(company, product, best_contact_role, why_now)

    return Opportunity(
        company=company.name,
        website=company.website,
        description=company.description,
        signals=signal_labels,
        sources=sources,
        icp_fit=breakdown["icp_fit"],
        signal_score=breakdown["signal_score"],
        timing_score=breakdown["timing_score"],
        gtm_score=float(breakdown["gtm_score"]),
        why_now=why_now,
        best_contact_role=best_contact_role,
        outreach_angle=outreach_angle,
        outreach_message=outreach_message,
        score_breakdown=breakdown,
    )


def _default_why_now(company: Company, breakdown: dict[str, Any]) -> str:
    parts = []
    if company.signals:
        top = sorted(company.signals, key=lambda s: s.strength, reverse=True)[:2]
        parts.append(
            f"{company.name} shows {len(company.signals)} buying signal(s), notably "
            + "; ".join(f"{s.type.lower()} ({s.description})" for s in top)
            + "."
        )
    else:
        parts.append(f"{company.name} matches the ICP but lacks strong recent signals.")
    parts.append(
        f"Combined timing ({breakdown['timing_score']:.0f}) and signal strength "
        f"({breakdown['signal_score']:.0f}) suggest elevated near-term need."
    )
    return " ".join(parts)


def _default_angle(company: Company, product: Product) -> str:
    if company.signals:
        s = max(company.signals, key=lambda x: x.strength)
        return f"Lead with their {s.type.lower()} and how it creates urgency for {product.description.split('.')[0].strip().lower()}."
    return f"Lead with ICP fit and a concrete workflow win for {company.name}."


def _default_outreach(company: Company, product: Product, role: str, why_now: str) -> str:
    desc = product.description.strip().rstrip(".")
    if desc.lower().startswith(("an ", "a ", "our ", "the ")):
        product_phrase = desc
    else:
        article = "an" if desc[:1].lower() in "aeiou" else "a"
        product_phrase = f"{article} {desc}"
    sig = company.signals[0].type.lower().replace("_", " ") if company.signals else "growth"
    return (
        f"Hi — noticed {company.name}'s recent momentum ({sig}). "
        f"We built {product_phrase}. "
        f"Teams in your stage usually hit research/ticket bottlenecks right after "
        f"hiring or expansion. Open to a 15-min walkthrough with your {role} "
        f"on cutting research time this quarter?"
    )
