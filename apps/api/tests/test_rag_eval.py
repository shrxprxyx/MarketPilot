"""
Golden question set and hit-rate script (FR-RAG-06). The eval runs the real embeddings and
hybrid retrieval, so it also guards retrieval quality against regressions.
"""
import asyncio

import pytest
from sqlalchemy import text

import app.db.engine as db_engine
from rag_eval.run import evaluate, hit_rate, load_corpus, load_questions, main

# Measured baseline is 83% at k=1 and 100% at k>=3; thresholds leave headroom for noise.
MIN_HIT_AT_3 = 0.9


def test_hit_rate_counts_expected_title_within_top_k() -> None:
    ranked = [["a", "b", "c"], ["b", "a", "c"], ["x", "y", "z"]]
    expected = ["a", "a", "a"]
    assert hit_rate(ranked, expected, 1) == pytest.approx(1 / 3)
    assert hit_rate(ranked, expected, 2) == pytest.approx(2 / 3)
    assert hit_rate(ranked, expected, 3) == pytest.approx(2 / 3)  # third question never hits


def test_hit_rate_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        hit_rate([["a"]], ["a", "b"], 1)
    with pytest.raises(ValueError):
        hit_rate([], [], 1)


def test_golden_set_is_well_formed() -> None:
    corpus, questions = load_corpus(), load_questions()
    assert len(corpus) >= 5 and len(questions) >= 10
    assert all(q["question"].strip() and q["expected"] in corpus for q in questions)
    assert len({q["question"] for q in questions}) == len(questions)  # no duplicates
    assert {q["expected"] for q in questions} <= set(corpus)


def test_retrieval_meets_golden_hit_rate_and_cleans_up() -> None:
    result = asyncio.run(evaluate([1, 3, 5]))
    assert result["questions"] == len(load_questions())
    assert result["hit_rate"][1] <= result["hit_rate"][3] <= result["hit_rate"][5]  # monotonic
    assert result["hit_rate"][3] >= MIN_HIT_AT_3, result["misses"][3]

    async def _leftovers() -> int:
        async with db_engine.AsyncSessionLocal() as session:
            return int(
                await session.scalar(
                    text("SELECT count(*) FROM tenants WHERE slug LIKE 'rag-eval-%'")
                )
                or 0
            )

    assert asyncio.run(_leftovers()) == 0  # the throwaway tenant is removed


def test_cli_exit_code_reflects_threshold(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--k", "5", "--min", "0.5"]) == 0
    assert "hit@5" in capsys.readouterr().out
    assert main(["--k", "5", "--min", "1.01"]) == 1  # unreachable threshold fails
