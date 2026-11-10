# Tool requests are excluded from the local fallback

A small local model cannot be trusted with tool calls, and a silent downgrade of an agent request to it would change behaviour without notice. The exclusion is enforced twice.

## Structure

No alias that serves tool calls lists the local fallback hop. A test reads the gateway config and fails if one does.

## Runtime

LiteLLM 1.106.6 (the version this was verified on) cannot condition fallbacks on the presence of `tools`. A pre-call hook therefore:

- sets `disable_fallbacks` for requests that carry tools, tool calls or tool results when they arrive on a text-only alias;
- returns HTTP 400 for tools sent straight to the local fallback model.

## Side effect to remember

A tool request on a text-only alias also loses the cloud fallbacks, not only the local one, because fallbacks are disabled for the whole request. Send tool traffic to an alias designed for it.

## Verify

Tool request on a text alias: no fallback. Tool request on a tool alias: no fallback. Tool request on the local model: 400. A plain text request with a failed primary: local answer.

## Related

- [Local text-only fallback design](litellm-local-text-only-fallback-design.md)
- [LiteLLM local text-only fallback ADR](../adr/litellm_local_text_fallback_adr.md)

Entities: [[LiteLLM]]
