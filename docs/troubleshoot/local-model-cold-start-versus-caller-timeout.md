# Local model cold start versus caller timeout

A model that Ollama unloads after idling takes up to about a minute to answer the first request again (weights loaded from disk into GPU memory). Callers with short timeouts give up first.

## Observed

- Cold first call after about 30 minutes idle: 34 seconds in one test, up to roughly a minute in another; warm calls: about 2.5 seconds.
- A caller timeout of 8 seconds (and a bridge timeout of 20 seconds) drops every cold fallback answer, and the caller falls back to its static text.

## Choices

- Keep the model warm with `keep_alive` set longer than the idle gaps of the fallback traffic, accepting the GPU memory it holds.
- Raise the intermediate timeout (a value around 45 seconds covers a cold load) and keep the caller's static text as the last resort.
- Do not count a cold answer as a failure of the fallback; measure cold and warm separately.

## Related

- [Local text-only fallback design](litellm-local-text-only-fallback-design.md)

Entities: [[Ollama]], [[LiteLLM]]
