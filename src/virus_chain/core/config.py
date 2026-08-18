"""Model specs and context limit configuration."""

# Known model specs: (total_context_window, max_output_tokens)
MODEL_SPECS = {
    "claude-opus-4-20250514": (200000, 32000),
    "claude-opus-4-5-20251101": (200000, 32000),
    "claude-sonnet-4-5-20250929": (200000, 64000),
    "claude-sonnet-4-20250514": (200000, 64000),
    "claude-sonnet-4-6": (200000, 64000),
    "claude-haiku-4-5-20250926": (200000, 64000),
    "claude-haiku-4-5-20251001": (200000, 64000),
    "claude-3-5-sonnet-20241022": (200000, 8192),
    "google/gemini-3-pro-preview": (1000000, 65536),
    "google/gemini-3-flash-preview": (1000000, 65536),
    "gpt-5-2025-08-07": (1000000, 32768),
    "qwen/qwen3-32b": (128000, 8192),
}

_SAFETY_MARGIN = 3000


def get_model_context_limit(model: str) -> int | None:
    """Get the usable input token limit for a model.

    Returns total_context - max_output_tokens - safety_margin.
    """
    spec = MODEL_SPECS.get(model)
    if spec is None:
        return None
    total_context, max_output = spec
    return total_context - max_output - _SAFETY_MARGIN
