"""Grounding post-check (SRS §10.4): "generated numbers must come from supplied facts; a
post-check flags any figure not present in the input."

The prompt tells the model never to invent metrics. This verifies it. It scans the plan's
prose claims (summary, objective titles, channel and risk text) for figures and reports any
that appear nowhere in the material the model was given. KPI targets are deliberately not
scanned: a target such as "10% growth" is a proposal the strategist is asked to make, not a
claim about the client. Plain whole numbers under 100 ("3 channels", "20 posts", "30-day"),
years, and any count of days, weeks, months, years or hours are ignored unless they carry a %
or $ sign, since they describe the shape of the plan, not a metric about the client.
"""
import re

from app.strategy.schemas import StrategyPlan

_NUMBER = re.compile(r"(?<![\w.])([$€£]?)(\d[\d,]*(?:\.\d+)?)(\s?%)?(?![\w])")
PLAIN_INT_MAX = 99
YEARS = range(1900, 2101)
_TIME_UNIT = re.compile(r"[\s-]*(?:day|week|month|year|hour)s?(?![a-z])", re.IGNORECASE)


def _value(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _numbers(text: str) -> set[float]:
    found = set()
    for m in _NUMBER.finditer(text):
        v = _value(m.group(2))
        if v is not None:
            found.add(v)
    return found


def _is_plan_structure(digits: str, value: float, after: str) -> bool:
    """A figure that describes the plan's shape rather than claiming a metric: a small whole
    number, a year, or a number of days, weeks, months, years or hours."""
    if _TIME_UNIT.match(after):
        return True
    if "." in digits or "," in digits:
        return False
    return value <= PLAIN_INT_MAX or int(value) in YEARS


def _claims(plan: StrategyPlan) -> list[str]:
    texts = [plan.summary]
    texts += [o.title for o in plan.objectives]
    texts += [f"{c.name} {c.rationale}" for c in plan.channels]
    texts += [f"{r.risk} {r.mitigation}" for r in plan.risks]
    return texts


def ungrounded_figures(plan: StrategyPlan, input_text: str) -> list[str]:
    """Figures quoted in the plan's claims that do not occur in `input_text`, in first-seen
    order and without duplicates (e.g. ["47%", "$12,000"])."""
    allowed = _numbers(input_text)
    flagged: list[str] = []
    for text in _claims(plan):
        for m in _NUMBER.finditer(text):
            currency, digits, percent = m.group(1), m.group(2), m.group(3)
            value = _value(digits)
            if value is None or value in allowed:
                continue
            if not currency and not percent and _is_plan_structure(digits, value, text[m.end():]):
                continue
            shown = f"{currency}{digits}{'%' if percent else ''}"
            if shown not in flagged:
                flagged.append(shown)
    return flagged


def warnings_for(plan: StrategyPlan, input_text: str) -> list[str]:
    return [
        f"The figure {fig} does not appear in the client details or knowledge sources. "
        "Check it before sharing this strategy."
        for fig in ungrounded_figures(plan, input_text)
    ]
