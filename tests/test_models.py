"""Model validation + JSON serialization tests."""

import json

from models import ICP, Opportunity, Signal


def test_icp_legacy_demo_fields():
    icp = ICP(industry="B2B SaaS", company_size="20–500", markets=["US", "Europe"], target_team="Customer Support", pain_points=["slow research"], buying_triggers=["funding"], summary="Mid-market support teams")
    assert icp.target_industries == ["B2B SaaS"]
    assert icp.target_markets == ["US", "Europe"]
    assert icp.positive_signals == ["funding"]


def test_icp_rich_fields_derive_legacy():
    icp = ICP(product_summary="AI support research", problem_solved="ticket context switching", target_industries=["B2B SaaS", "Fintech"], company_size="50-500", target_markets=["US"], target_departments=["CX", "Support"], buyer_roles=["VP Support"], pain_points=["fragmented KB"], positive_signals=["new VP hire"], negative_signals=["no support org"])
    assert icp.industry == "B2B SaaS"
    assert icp.target_team == "CX"
    assert "funding" not in icp.buying_triggers or icp.buying_triggers == ["new VP hire"]
    assert icp.buying_triggers == ["new VP hire"]
    assert icp.summary


def test_signal_confidence_and_band():
    s = Signal(type="hiring", description="Support roles", freshness_days=20, confidence="med", strength=0.7)
    assert s.confidence == "MEDIUM"
    assert s.freshness_band == "0-30"


def test_opportunity_json_export_includes_breakdown():
    opp = Opportunity(company="Acme", website="https://acme.io", description="SaaS", signals=["hiring: roles"], sources=["https://acme.io/careers"], icp_fit=80, signal_score=70, timing_score=75, gtm_score=78, why_now="Hiring now", best_contact_role="VP Support", outreach_angle="Lead with hiring", outreach_message="Hi...", score_breakdown={"components":{"icp_fit":80,"confidence":70},"gtm_score":78})
    payload = opp.to_export_dict()
    raw = json.dumps(payload)
    assert "score_breakdown" in payload
    assert "sources" in payload
    assert "Acme" in raw
    loaded = json.loads(raw)
    assert loaded["gtm_score"] == 78
