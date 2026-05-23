"""Tests for deterministic engagement ('hot') scoring."""

import math

import pytest

from ghr.analysis.rank import DEFAULT_WEIGHTS, hot_score, recency_factor


def test_default_weights_are_pinned() -> None:
    assert DEFAULT_WEIGHTS == {"reactions": 1.0, "comments": 0.7, "recency": 1.5}


def test_recency_factor_decays_by_half_life() -> None:
    assert recency_factor(0.0, half_life_days=30) == 1.0
    assert recency_factor(30.0, half_life_days=30) == pytest.approx(0.5)
    assert recency_factor(60.0, half_life_days=30) == pytest.approx(0.25)


def test_hot_score_combines_weighted_log_terms_and_recency() -> None:
    # spec: w_react*log1p(pos) + w_comments*log1p(comments) + w_recency*recency
    expected = round(1.0 * math.log1p(9) + 0.7 * math.log1p(3) + 1.5 * 0.5, 4)
    assert hot_score(positive_reactions=9, comments=3, recency=0.5) == expected


def test_hot_score_rounds_to_four_decimals() -> None:
    assert hot_score(positive_reactions=1, comments=1, recency=0.123456) == round(
        math.log1p(1) + 0.7 * math.log1p(1) + 1.5 * 0.123456, 4
    )


def test_hot_score_respects_weight_override() -> None:
    weights = {"reactions": 2.0, "comments": 0.0, "recency": 0.0}
    assert hot_score(positive_reactions=9, comments=999, recency=1.0, weights=weights) == round(
        2.0 * math.log1p(9), 4
    )
