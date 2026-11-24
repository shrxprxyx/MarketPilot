"""Grounding post-check (SRS §10.4): figures in the plan's claims must exist in the input."""
from app.strategy.grounding import ungrounded_figures, warnings_for
from app.strategy.schemas import Channel, Kpi, Objective, Risk, StrategyPlan

INPUT = (
    "Client: Acme\nIndustry: SaaS\nGoals: reach 5,000 subscribers; lift conversion to 3.5%\n"
    "Strategy month: 2026-12\nSource: Email open rate was 41% last quarter at $2,400 spend."
)


def _plan(summary: str = "ok", **kw: str) -> StrategyPlan:
    return StrategyPlan(
        summary=summary,
        objectives=[
            Objective(title=kw.get("objective", "Grow"), kpis=[Kpi(name="Subs", target="9,999")])
        ],
        channels=[Channel(name="Email", rationale=kw.get("rationale", "Retention."))],
        risks=[Risk(risk=kw.get("risk", "Delay"), mitigation=kw.get("mitigation", "Buffer"))],
    )


def test_figures_present_in_the_input_are_fine() -> None:
    plan = _plan("Open rate of 41% and $2,400 spend support reaching 5,000 subscribers.")
    assert ungrounded_figures(plan, INPUT) == []


def test_invented_figures_are_flagged_once_each() -> None:
    plan = _plan(
        "Traffic grew 47% to 120,000 visits.", rationale="That 47% lift came from search."
    )
    assert ungrounded_figures(plan, INPUT) == ["47%", "120,000"]


def test_comma_and_formatting_do_not_cause_false_flags() -> None:
    assert ungrounded_figures(_plan("Hit 5000 subscribers at 3.50% conversion."), INPUT) == []


def test_currency_and_percent_matter_for_small_numbers() -> None:
    plan = _plan("Plan 3 channels over 2 phases, expecting 8% more and $9 per lead.")
    assert ungrounded_figures(plan, INPUT) == ["8%", "$9"]


def test_kpi_targets_are_proposals_and_not_scanned() -> None:
    assert ungrounded_figures(_plan("Fine."), INPUT) == []  # target "9,999" is not in INPUT


def test_risks_and_objectives_are_scanned() -> None:
    plan = _plan(objective="Reach 77,000 followers", risk="A 63% drop in reach")
    assert ungrounded_figures(plan, INPUT) == ["77,000", "63%"]


def test_dates_and_identifiers_are_not_mistaken_for_figures() -> None:
    plan = _plan("Launch in 2026-12 using plan A1 and v2.")
    assert ungrounded_figures(plan, INPUT) == []


def test_warning_text_names_the_figure() -> None:
    warns = warnings_for(_plan("Revenue up 31%."), INPUT)
    assert len(warns) == 1 and "31%" in warns[0]
