# LiteLLM local text-only fallback: design

Text-only callers (flavour text, short replies) should keep working when cloud upstreams fail or their quota runs out. The gateway ends their fallback chain on a small local model; tool-using callers never reach it.

Decision record and tests: [LiteLLM local text-only fallback ADR](../adr/litellm_local_text_fallback_adr.md).

## Shape

- A dedicated alias for text-only callers and the existing cheap alias end on a `local-fallback` model served by a small Ollama deployment. Aliases used for tool calls or for agents never list that hop.
- The local model is chosen by response quality on the callers' own prompts and by licence, not by size alone: the smallest model tested was fastest but wrote weak persona text; a mid-size Gemma model stayed in character at usable speed.
- Placement: a stable GPU node chosen by labels. The ephemeral desktop node is avoided because its owner uses it and it comes and goes; a manager without the required CPU features cannot run the model.
- Weights live on node-local disk, not on the bucket-backed model store (see [cost of testing models](litellm-fallback-testing-egress-cost.md)).

## Verification that counts

- Primary path answers 200.
- With the primary made to fail, the local model answers (cold and warm timings recorded).
- A tool request on a text alias does not fall back ([tool requests](litellm-tool-requests-excluded-from-local-fallback.md)).
- The gateway restart leaves the service intact and the config version has a rollback reference ([rollback](litellm-config-version-rollback.md)).

## Related

- [Cold start versus caller timeout](local-model-cold-start-versus-caller-timeout.md)

Entities: [[LiteLLM]], [[Ollama]]
