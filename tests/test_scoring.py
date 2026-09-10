"""Scoring component + freshness weighting tests."""

from models import Company, ICP, Product, Signal
from scoring import WEIGHTS, compute_gtm_score, opportunity_from_company, score_confidence, score_signal_freshness, _freshness_band_score


def _icp() -> ICP:
    return ICP(industry="B2B SaaS", company_size="50-500", markets=["US", "Europe"], target_team="Customer Support", pain_points=["ticket research time"], buying_triggers=["hiring support"], summary="Mid-market B2B SaaS support teams")


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_freshness_bands_ordering():
    assert _freshness_band_score(10, "0-30") > _freshness_band_score(45, "31-90")
    assert _freshness_band_score(45, "31-90") > _freshness_band_score(120, "91-180")
    assert _freshness_band_score(120, "91-180") > _freshness_band_score(400, ">180")
    assert _freshness_band_score(400, ">180") < 25


def test_freshness_ranking_prefers_recent():
    fresh = [Signal(type="hiring", description="role open", freshness_days=7, strength=0.8)]
    stale = [Signal(type="hiring", description="role open", freshness_days=400, strength=0.8)]
    f_score, _ = score_signal_freshness(fresh)
    s_score, _ = score_signal_freshness(stale)
    assert f_score > s_score


def test_confidence_high_medium_low():
    high = Company(name="A", signals=[Signal(type="funding", description="Series B", confidence="HIGH", strength=0.9, source_url="https://techcrunch.com/example")], sources=["https://techcrunch.com/example"])
    low = Company(name="B", signals=[Signal(type="rumor", description="maybe", confidence="LOW", strength=0.3)], sources=[])
    h, _ = score_confidence(high)
    l, _ = score_confidence(low)
    assert h > l


def test_compute_gtm_score_components():
    co = Company(name="Acme", website="https://acme.test", description="B2B SaaS customer support platform", industry="B2B SaaS", size="100-200", location="San Francisco, US", signals=[Signal(type="hiring", description="Hiring support engineers", freshness_days=12, confidence="HIGH", strength=0.85, source_url="https://boards.greenhouse.io/acme")], sources=["https://boards.greenhouse.io/acme"])
    co.website = "https://www.acme.io"
    product = Product(description="AI support research automation")
    bd = compute_gtm_score(co, product, _icp())
    assert "components" in bd
    comps = bd["components"]
    for key in ("icp_fit","signal_strength","signal_freshness","problem_relevance","timing","confidence"):
        assert key in comps
        assert 0 <= comps[key] <= 100
    assert 0 <= bd["gtm_score"] <= 100


def test_opportunity_ranking():
    product = Product(description="AI support research for B2B SaaS")
    icp = _icp()
    strong = Company(name="StrongCo", website="https://strongco.io", description="B2B SaaS with support team scaling", industry="B2B SaaS", size="100-200", location="US", signals=[Signal(type="funding", description="Series B", freshness_days=10, confidence="HIGH", strength=0.9, source_url="https://news.example.org/x"), Signal(type="hiring", description="Support hiring", freshness_days=5, confidence="HIGH", strength=0.85, source_url="https://jobs.ashbyhq.com/strongco")], sources=["https://jobs.ashbyhq.com/strongco"])
    weak = Company(name="WeakCo", description="misc", industry="Retail", signals=[Signal(type="other", description="old note", freshness_days=500, confidence="LOW", strength=0.2)], sources=[])
    s = opportunity_from_company(strong, product, icp)
    w = opportunity_from_company(weak, product, icp)
    assert s.gtm_score > w.gtm_score
