"""LiteLLM model wrapper — replaces inspect_ai.model.get_model() + model.generate()."""

from dataclasses import dataclass, field

import litellm

litellm.suppress_debug_info = True


@dataclass
class ToolCall:
    id: str
    function_name: str
    arguments: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ModelResponse:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None


async def generate(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: int = 300,
    reasoning_effort: str | None = None,
    extra_litellm_kwargs: dict | None = None,
) -> tuple[ModelResponse, dict]:
    """Returns (ModelResponse, raw_assistant_msg_dict).

    The raw_assistant_msg_dict is the litellm message serialized via
    .model_dump() — use it for conversation history so provider-specific
    fields (e.g. Gemini thought_signatures) are preserved across turns.
    Never write it to disk.
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort is not None and reasoning_effort != "none":
        kwargs["reasoning_effort"] = reasoning_effort
    elif reasoning_effort == "none" and (model.startswith("openai/") or model.startswith("gemini/gemini-")):
        kwargs["reasoning_effort"] = "none"
    kwargs["max_tokens"] = max_tokens or 32000
    if extra_litellm_kwargs:
        kwargs.update(extra_litellm_kwargs)

    resp = await litellm.acompletion(**kwargs)
    choice = resp.choices[0]
    msg = choice.message

    raw_msg = msg.model_dump(exclude_none=True)
    raw_msg.setdefault("role", "assistant")
    raw_msg.setdefault("content", "")
    raw_msg.pop("thinking", None)

    tool_calls = None
    if msg.tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.id,
                function_name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in msg.tool_calls
        ]

    usage = Usage()
    if resp.usage:
        usage = Usage(
            input_tokens=resp.usage.prompt_tokens or 0,
            output_tokens=resp.usage.completion_tokens or 0,
        )

    parsed = ModelResponse(
        content=msg.content,
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=choice.finish_reason,
    )
    return parsed, raw_msg
