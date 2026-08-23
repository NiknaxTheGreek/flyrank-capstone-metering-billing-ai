from dataclasses import FrozenInstanceError

import pytest

from app.services.pricing import (
    API_CALL_VARIABLE_COST_CENTS,
    TokenUsage,
    price_gemini_25_flash_lite_standard,
)


def test_prices_each_token_category_and_retains_all_counts() -> None:
    result = price_gemini_25_flash_lite_standard(
        TokenUsage(
            api_calls=9,
            input_tokens=1_000_000,
            cached_input_tokens=2_000_000,
            output_tokens=3_000_000,
            reasoning_tokens=4_000_000,
        )
    )

    assert API_CALL_VARIABLE_COST_CENTS == 0
    assert result.api_calls == 9
    assert result.input_tokens == 1_000_000
    assert result.cached_input_tokens == 2_000_000
    assert result.output_tokens == 3_000_000
    assert result.reasoning_tokens == 4_000_000
    assert result.total_cents == 292


def test_rounds_once_after_combining_categories_not_per_category() -> None:
    result = price_gemini_25_flash_lite_standard(
        TokenUsage(
            input_tokens=50_000,
            cached_input_tokens=500_000,
        )
    )

    # Input is 0.5 cents and cached input is 0.5 cents. One final rounding
    # produces 1 cent; separately rounding categories would incorrectly produce 2.
    assert result.total_cents == 1


def test_half_cent_rounds_up_and_just_below_half_rounds_down() -> None:
    exact_half = price_gemini_25_flash_lite_standard(TokenUsage(input_tokens=50_000))
    below_half = price_gemini_25_flash_lite_standard(TokenUsage(input_tokens=49_999))

    assert exact_half.total_cents == 1
    assert below_half.total_cents == 0


def test_large_integer_totals_remain_exact() -> None:
    result = price_gemini_25_flash_lite_standard(
        TokenUsage(
            input_tokens=10_000_000_000_000,
            cached_input_tokens=20_000_000_000_000,
            output_tokens=30_000_000_000_000,
            reasoning_tokens=40_000_000_000_000,
        )
    )

    assert result.total_cents == 2_920_000_000


@pytest.mark.parametrize(
    "field_name",
    [
        "api_calls",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ],
)
@pytest.mark.parametrize("invalid_value", [True, 1.0, "1"])
def test_token_usage_rejects_non_integer_counts(
    field_name: str, invalid_value: object
) -> None:
    with pytest.raises(TypeError, match=field_name):
        TokenUsage(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "field_name",
    [
        "api_calls",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ],
)
def test_token_usage_rejects_negative_counts(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        TokenUsage(**{field_name: -1})


def test_pricing_result_is_immutable_and_repeatable() -> None:
    usage = TokenUsage(input_tokens=1_234_567, output_tokens=765_432)
    first = price_gemini_25_flash_lite_standard(usage)
    second = price_gemini_25_flash_lite_standard(usage)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.total_cents = 0  # type: ignore[misc]