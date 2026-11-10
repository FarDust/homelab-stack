"""Keep tool-calling requests off the weak local fallback model.

LiteLLM fallbacks are keyed by model group and cannot be conditioned on the request
body, so the guard (a) switches fallbacks off for any request that carries tools to a
text-only alias and (b) refuses tool requests addressed straight to the local model.
Decision record: docs/adr/litellm_local_text_fallback_adr.md.
"""

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

# Aliases whose fallback chain ends on the local model (config.yaml router_settings.fallbacks).
TEXT_ONLY_ALIASES = frozenset({"zeus-cheap", "zeus-text"})
LOCAL_MODEL = "local-fallback"
TOOL_FIELDS = ("tools", "tool_choice", "functions", "function_call")


def carries_tools(data: dict) -> bool:
    return any(data.get(field) for field in TOOL_FIELDS)


class TextOnlyFallbackGuard(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        model = data.get("model", "")
        if not carries_tools(data):
            return data
        if model == LOCAL_MODEL:
            raise HTTPException(
                status_code=400,
                detail="local-fallback is text-only: tool and function calling are not supported",
            )
        if model in TEXT_ONLY_ALIASES:
            # Per-request switch documented at https://docs.litellm.ai/docs/proxy/reliability
            data["disable_fallbacks"] = True
        return data


proxy_handler_instance = TextOnlyFallbackGuard()
