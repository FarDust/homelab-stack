import httpx
from litellm.integrations.custom_logger import CustomLogger

OLLAMA_BASE = "http://llms-governance_ollama:11434"
VLLM_MODELS = {"gemma-4-31b-it", "gemma-4-31b-it-nvfp4"}


class OllamaUnloadHook(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        model = data.get("model", "")
        if model not in VLLM_MODELS:
            return data
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/ps")
            if resp.status_code == 200:
                loaded = resp.json().get("models", [])
                for m in loaded:
                    name = m.get("name", "")
                    await client.post(
                        f"{OLLAMA_BASE}/api/generate",
                        json={"model": name, "keep_alive": 0},
                    )
        return data


proxy_handler_instance = OllamaUnloadHook()
