"""Pydantic schemas shared by the DevForge agent crew.

`TaskPlan` is the structured output of the EngineeringLead agent. Downstream
agents (Backend / Frontend / QA in Day 7+) consume it verbatim.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StepKind(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    QA = "qa"
    MIGRATION = "migration"


class TaskStep(BaseModel):
    id: int = Field(..., description="1-indexed step id")
    kind: StepKind = Field(..., description="Which agent role owns this step")
    description: str = Field(..., description="What the agent should do in plain language")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Each item must be an observable, testable condition",
    )
    files_likely_touched: list[str] = Field(
        default_factory=list,
        description="Best-effort list of repo paths this step will read/write",
    )


class TaskPlan(BaseModel):
    ticket_id: str = Field(..., description="Any human identifier for the ticket")
    analysis: str = Field(
        ...,
        description=(
            "One-paragraph restatement of the problem + the approach. "
            "Should reference retrieved codebase context where relevant."
        ),
    )
    steps: list[TaskStep] = Field(
        ..., description="Ordered list of steps (must have at least 1)"
    )
    estimated_cost_usd: float = Field(
        default=0.0,
        description="Rough cost estimate in USD for running the crew end-to-end (>= 0)",
    )
    requires_human_approval: bool = Field(
        default=False,
        description=(
            "True when any step involves a migration, dependency bump, or infra "
            "change. Set True if unsure."
        ),
    )
