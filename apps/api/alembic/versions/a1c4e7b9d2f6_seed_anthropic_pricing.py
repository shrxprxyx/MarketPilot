"""seed anthropic model pricing

Revision ID: a1c4e7b9d2f6
Revises: f6b9d3e8a2c4
Create Date: 2026-11-23 09:00:00.000000

Without prices, Anthropic calls were recorded with cost NULL: they never counted toward the
monthly budget, so a hard stop could not trigger for them (FR-BYOM-04, FR-BYOM-05).
Prices are USD per million tokens at Anthropic's published first-party rates. Claude Haiku
5.5 is listed at its up-to-100K-token-prompt rate, which covers this app's prompts.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b9d2f6'
down_revision: str | Sequence[str] | None = 'f6b9d3e8a2c4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICES = [
    ("claude-fable-5-2", "8.00", "40.00"),
    ("claude-fable-5-1", "10.00", "50.00"),
    ("claude-fable-5", "10.00", "50.00"),
    ("claude-opus-5-5", "4.00", "20.00"),
    ("claude-opus-5", "5.00", "25.00"),
    ("claude-opus-4-8", "5.00", "25.00"),
    ("claude-opus-4-7", "5.00", "25.00"),
    ("claude-opus-4-6", "5.00", "25.00"),
    ("claude-sonnet-5-5", "2.00", "10.00"),
    ("claude-sonnet-5", "2.00", "10.00"),
    ("claude-sonnet-4-6", "3.00", "15.00"),
    ("claude-haiku-5-5", "0.10", "0.50"),
    ("claude-haiku-4-5", "1.00", "5.00"),
]


def upgrade() -> None:
    values = ", ".join(
        f"(gen_random_uuid(), 'anthropic', '{model}', {inp}, {out})" for model, inp, out in PRICES
    )
    op.execute(
        "INSERT INTO model_pricing (id, provider, model, input_per_mtok, output_per_mtok) "
        f"VALUES {values} ON CONFLICT ON CONSTRAINT uq_pricing_provider_model DO NOTHING"
    )


def downgrade() -> None:
    models = ", ".join(f"'{model}'" for model, _, _ in PRICES)
    op.execute(f"DELETE FROM model_pricing WHERE provider = 'anthropic' AND model IN ({models})")
