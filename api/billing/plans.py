"""Authoritative plan definitions: prices, limits, period length, and display copy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PlanId = Literal["free", "pass", "campus"]


class PlanLimits(BaseModel):
    analyses: int | None
    analyses_label: str
    rewrites: int | None
    rewrites_label: str
    saved_resumes: int | None
    saved_resumes_label: str
    support_label: str


class PlanDefinition(BaseModel):
    id: PlanId
    name: str
    recommended: bool = False
    price_cents: int | None
    price_display: str
    price_suffix: str
    currency: str = "USD"
    period_days: int
    description: str
    limits: PlanLimits
    features: list[str]


PLANS: dict[PlanId, PlanDefinition] = {
    "free": PlanDefinition(
        id="free",
        name="Free",
        recommended=False,
        price_cents=0,
        price_display="$0",
        price_suffix="forever",
        currency="USD",
        period_days=30,
        description="For trying the matcher on your first applications.",
        limits=PlanLimits(
            analyses=3,
            analyses_label="3 per 30 days",
            rewrites=1,
            rewrites_label="1 per 30 days",
            saved_resumes=1,
            saved_resumes_label="1",
            support_label="Community",
        ),
        features=[
            "Requirement-level match report",
            "Non-work evidence mapping",
        ],
    ),
    "pass": PlanDefinition(
        id="pass",
        name="Job Hunt Pass",
        recommended=True,
        price_cents=500,
        price_display="$5",
        price_suffix="per 30 days, one-time",
        currency="USD",
        period_days=30,
        description="For an active job search with many applications.",
        limits=PlanLimits(
            analyses=50,
            analyses_label="50 per pass",
            rewrites=30,
            rewrites_label="30 per pass",
            saved_resumes=10,
            saved_resumes_label="10",
            support_label="Email",
        ),
        features=[
            "Everything in Free",
            "AI rewrite suggestions with fact check",
            "Priority processing (Coming soon)",
        ],
    ),
    "campus": PlanDefinition(
        id="campus",
        name="Campus",
        recommended=False,
        price_cents=None,
        price_display="Custom",
        price_suffix="billed annually",
        currency="USD",
        period_days=365,
        description="For universities and career centres supporting many students.",
        limits=PlanLimits(
            analyses=None,
            analyses_label="Unlimited",
            rewrites=None,
            rewrites_label="Unlimited",
            saved_resumes=None,
            saved_resumes_label="Unlimited",
            support_label="Dedicated",
        ),
        features=[
            "Everything in Pass",
            "Cohort dashboard (Coming soon)",
            "Bulk student onboarding (Coming soon)",
        ],
    ),
}


def list_plans() -> list[PlanDefinition]:
    return [PLANS["free"], PLANS["pass"], PLANS["campus"]]


def get_plan(plan_id: str) -> PlanDefinition | None:
    return PLANS.get(plan_id)  # type: ignore[arg-type]
