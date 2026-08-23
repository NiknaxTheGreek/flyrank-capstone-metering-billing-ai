"""Pure integer-cent pricing for Gemini 2.5 Flash-Lite Standard tokens."""

from dataclasses import dataclass

TOKENS_PER_MILLION = 1_000_000
API_CALL_VARIABLE_COST_CENTS = 0
GEMINI_25_FLASH_LITE_STANDARD_INPUT_CENTS_PER_MILLION = 10
GEMINI_25_FLASH_LITE_STANDARD_CACHED_INPUT_CENTS_PER_MILLION = 1
GEMINI_25_FLASH_LITE_STANDARD_OUTPUT_CENTS_PER_MILLION = 40
GEMINI_25_FLASH_LITE_STANDARD_REASONING_CENTS_PER_MILLION = 40


@dataclass(frozen=True)
class TokenUsage:
    """Separate non-negative token counts used for one model invocation."""

    api_calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        for field_name, value in (
            ("api_calls", self.api_calls),
            ("input_tokens", self.input_tokens),
            ("cached_input_tokens", self.cached_input_tokens),
            ("output_tokens", self.output_tokens),
            ("reasoning_tokens", self.reasoning_tokens),
        ):
            _require_nonnegative_integer(field_name, value)


@dataclass(frozen=True)
class TokenPrice:
    """The integer-cent price of a token usage, retaining every input category."""

    api_calls: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_cents: int


def price_gemini_25_flash_lite_standard(usage: TokenUsage) -> TokenPrice:
    """Price all categories together and round once, half-up, to integer cents."""
    if not isinstance(usage, TokenUsage):
        raise TypeError("usage must be a TokenUsage instance.")

    numerator = (
        usage.api_calls * API_CALL_VARIABLE_COST_CENTS
        + usage.input_tokens * GEMINI_25_FLASH_LITE_STANDARD_INPUT_CENTS_PER_MILLION
        + usage.cached_input_tokens
        * GEMINI_25_FLASH_LITE_STANDARD_CACHED_INPUT_CENTS_PER_MILLION
        + usage.output_tokens * GEMINI_25_FLASH_LITE_STANDARD_OUTPUT_CENTS_PER_MILLION
        + usage.reasoning_tokens
        * GEMINI_25_FLASH_LITE_STANDARD_REASONING_CENTS_PER_MILLION
    )
    total_cents = (numerator + TOKENS_PER_MILLION // 2) // TOKENS_PER_MILLION
    return TokenPrice(
        api_calls=usage.api_calls,
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        total_cents=total_cents,
    )


def _require_nonnegative_integer(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer.")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")