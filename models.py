"""Data models for Grok GTM Agent."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Product(BaseModel):
    description: str
    name: Optional[str] = None
    category: Optional[str] = None


class ICP(BaseModel):
    """Ideal Customer Profile.

    Legacy fields (industry/markets/target_team/summary) remain for demo JSON
    compatibility. Richer live fields are optional and backfill legacy when set.
    """

    # Legacy / shared
    industry: str = ""
    company_size: str = ""
    markets: list[str] = Field(default_factory=list)
    target_team: str = ""
    pain_points: list[str] = Field(default_factory=list)
    buying_triggers: list[str] = Field(default_factory=list)
    summary: str = ""

    # Live / richer schema (optional)
    product_summary: Optional[str] = None
    problem_solved: Optional[str] = None
    target_industries: list[str] = Field(default_factory=list)
    target_markets: list[str] = Field(default_factory=list)
    target_departments: list[str] = Field(default_factory=list)
    buyer_roles: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_legacy(self) -> "ICP":
        if not self.industry and self.target_industries:
            self.industry = self.target_industries[0]
        if not self.markets and self.target_markets:
            self.markets = list(self.target_markets)
        if not self.target_markets and self.markets:
            self.target_markets = list(self.markets)
        if not self.target_industries and self.industry:
            self.target_industries = [self.industry]
        if not self.target_team and self.target_departments:
            self.target_team = self.target_departments[0]
        if not self.target_departments and self.target_team:
            self.target_departments = [self.target_team]
        if not self.buying_triggers and self.positive_signals:
            self.buying_triggers = list(self.positive_signals)
        if not self.positive_signals and self.buying_triggers:
            self.positive_signals = list(self.buying_triggers)
        if not self.summary:
            bits = [
                self.product_summary or "",
                self.problem_solved or "",
                f"Target: {self.industry} {self.company_size}".strip(),
                f"Team: {self.target_team}" if self.target_team else "",
            ]
            self.summary = " ".join(b for b in bits if b).strip()
        if not self.product_summary and self.summary:
            self.product_summary = self.summary
        return self


class Signal(BaseModel):
    type: str
    description: str
    title: Optional[str] = None
    freshness_days: Optional[int] = None
    freshness_band: Optional[str] = None  # e.g. "0-30", "31-90", "91-180", ">180"
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    published_date: Optional[str] = None
    confidence: Optional[str] = None  # HIGH / MEDIUM / LOW
    relevance_to_product: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _norm_confidence(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        s = str(v).strip().upper()
        if s in {"HIGH", "MEDIUM", "LOW", "MED"}:
            return "MEDIUM" if s == "MED" else s
        return s

    @model_validator(mode="after")
    def _derive_freshness_band(self) -> "Signal":
        if self.freshness_band:
            return self
        d = self.freshness_days
        if d is None:
            return self
        if d <= 30:
            self.freshness_band = "0-30"
        elif d <= 90:
            self.freshness_band = "31-90"
        elif d <= 180:
            self.freshness_band = "91-180"
        else:
            self.freshness_band = ">180"
        return self


class Company(BaseModel):
    name: str
    website: Optional[str] = None
    description: str = ""
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    signals: list[Signal] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    raw_notes: Optional[str] = None


class Opportunity(BaseModel):
    company: str
    website: Optional[str] = None
    description: str = ""
    signals: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    icp_fit: float = 0.0
    signal_score: float = 0.0
    timing_score: float = 0.0
    gtm_score: float = 0.0
    why_now: str = ""
    best_contact_role: str = ""
    outreach_angle: str = ""
    outreach_message: str = ""
    # Extra explainability (exported in run files + leads when present)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)

    def to_export_dict(self, include_breakdown: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "company": self.company,
            "website": self.website,
            "description": self.description,
            "signals": self.signals,
            "sources": self.sources,
            "icp_fit": self.icp_fit,
            "signal_score": self.signal_score,
            "timing_score": self.timing_score,
            "gtm_score": self.gtm_score,
            "why_now": self.why_now,
            "best_contact_role": self.best_contact_role,
            "outreach_angle": self.outreach_angle,
            "outreach_message": self.outreach_message,
        }
        if include_breakdown and self.score_breakdown:
            payload["score_breakdown"] = self.score_breakdown
        return payload


class GTMResult(BaseModel):
    product: Product
    icp: ICP
    opportunities: list[Opportunity] = Field(default_factory=list)
    mode: str = "demo"
