"""SRS §10.1: the `strategy` task's StrategyPlan output schema."""
from pydantic import BaseModel


class Kpi(BaseModel):
    name: str
    target: str


class Objective(BaseModel):
    title: str
    kpis: list[Kpi]


class Channel(BaseModel):
    name: str
    rationale: str


class Risk(BaseModel):
    risk: str
    mitigation: str


class StrategyPlan(BaseModel):
    summary: str
    objectives: list[Objective]
    channels: list[Channel]
    risks: list[Risk]
