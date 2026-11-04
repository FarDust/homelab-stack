# Cluster STT for Chilean Spanish and English

Status: v0.1.0 GPU Whisper passed real LiteLLM and client WS speed-stress gates; authorized transition to permanent cluster serving. Qwen remains staged and unvalidated; CPU stopped.

## Permanent serving decision (2026-11-03 01:28 SCL, UTC-03:00)

The client owner independently verified the accelerated16.862125s fixture through both LiteLLM (200/0.992853s) and actual OpenChamber WS (0.694755s total,0.351363s after finish). Both transcripts retained Spanish and English, where the prior local baseline omitted English twice. No language hint, correction or settings changes were used in that acceptance; audio chunks were sent without real-time pacing. This is fixture-specific preservation evidence, not natural Chilean accuracy. Exact client receipt is retained locally at D:/stt-qwen-runtime/client-gpu-speed135.json.

The user authorized permanent cluster serving after this gate. Canonical GPU replicas now default1; CPU and Qwen remain0. The sole model entry stays behind LiteLLM config754; no direct public API or new client endpoint is introduced. The experimental GPU stop timer is stopped before client activation. Current runtime already has1 replica, so applying the default should preserve the existing task; verify the task ID and health after canonical deployment. Preserve original Qwen staging and both downloaded model candidates.

Rollback: the client owner restores its saved prior speech settings/Parakeet selection first. Set STT_GPU_REPLICAS=0 and use reports/cluster-cpu-stage.sh with STT_VARIANT=gpu to stop only this service; verify zero desired/running replicas. Restore the canonical default to0 if retiring it, validate compose and redeploy the same service. Keep CPU/Qwen0. The alias may remain as a stopped candidate, or remove only its model entry with a separate LiteLLM config bump; no inference fallback or credential expansion is permitted. The shared model-scoped credential stays in existing custody unless deliberately revoked by its owner.

Availability follows the existing high-end ephemeral-node placement: if the desktop node is shut down under user control, this service is unavailable until that node returns. No automatic desktop/WSL startup or workload eviction is authorized. The first GPU request took50.377s; later warm requests are measured separately, and cold-start performance remains part of the documented operational boundary.

## Superseding CPU experiment (2026-11-03)

The Qwen image is absent. A privileged journal inspection reported the previous WSL boot ending at 2026-11-03 00:44:24 SCL (UTC-03:00) and the current boot beginning00:47:17. The transient pull unit is not-found; default Result=success is not evidence of completion. Last layer completion00:37:29 lacked a final digest. The reboot cause is unknown; no additional pull or WSL restart was initiated.

The bounded alternative uses official whisper.cpp image `ghcr.io/ggml-org/whisper.cpp@sha256:8608a75b23588b920e0617eed2446b118765e2cb7ed49fb24f6c406a435be9fb` and `ggerganov/whisper.cpp` model revision `5359861c739e955e79d9a303bcbc70fb988958b1`, file `ggml-large-v3-turbo-q5_0.bin`, SHA256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`. Both download and checksum succeeded. This tests Whisper, not Qwen.

Canonical source `stacks/llms/speech-cpu.yml` defaults to0 replicas. Existing heavy/non-ephemeral/x86_64/AVX placement selects a heavy x86_64 AVX worker node, verified by the actual Swarm task. It serves through the official whisper-server binary with automatic language detection, no translation option, no GPU,2 threads and the official configurable inference route `/v1/audio/transcriptions`. Model volume `speech_whisper_models` is read-only at runtime. Limits2 CPUs/3GiB RAM, reservation1536MiB; swap avoidance is the intention, but no per-task swap cap is claimed or host policy changed.

The manager timer `stt-cpu-stop-20261103.timer` was armed and verified active before activation, with a20-minute deadline at2026-11-03 01:29:40 SCL (UTC-03:00). It scales only the CPU service to0. Deployment used cluster-utils deploy stack for the new one-service stack; deploy service rejected the nonexistent stack without mutation. Server loaded its model and local GET /health returned200 with status ok.

LiteLLM config753 changes only the STT alias's upstream to `http://llms-speech-cpu_whisper:8080/v1`, model `openai/whisper-large-v3-turbo-q5_0`, owned_by whisper.cpp. The initial deploy monitor reported convergence on the previous task before the actual replacement completed. First real Spanish multipart POST returned404, and public liveliness also returned404 during that transition. The replacement task was subsequently verified healthy and public liveliness200 before a new probe. No transcript success is implied by readiness alone.

Scoped client key issuance/reuse is verified independently by the parent with models200 exactly [openchamber-stt]. Client uses transient WS options and private captured pipes; values stay in process memory. Client activation and natural Chilean code-switching quality remain separate gates.

The parent added `test-es-en-speed135.wav` (atempo1.35 from the mixed fixture,16.862125s) as a reproducible speed-stress gate. Parakeetv3 actual WS dropped the entire English portion twice, while its22.73125s original control preserved Spanish and English. Candidate acceptance requires both portions through LiteLLM and actual WS, beyond200/nonempty text. This artificial fixture does not establish natural Chilean quality.

Actual CPU backend probe returned200 for Spanish99.568s, English78.138s and mixed78.255s, with language omitted and response_format=json. Mixed output retained both Spanish and English, including sentido/music anchors. Unauthenticated multipart returned401. Exact receipts live at `reports/backend-cpu-receipts.json`. These are single observations and client acceptance overlapped the probe window; they are not an isolated latency benchmark. The observed CPU latency does not meet fast interactive dictation expectations. Client selection remains unchanged pending its own acceptance.

Parent actual acceptance failed with ReadTimeout before reaching WS. Server logs showed serialized work and a client-disconnected cancellation, so the120s timeout is not isolated inference latency. After requests drained to an observed0.07%CPU, the canonical CPU stack was deployed at0 and docker ps verified no live CPU speech container. The standalone stop timer remains an idempotent backstop.

## GPU continuation

Next experiment retains the same model and official API using main-cuda digest `sha256:eb5f21530421cefcb1c5bf18a276dc5082110e66dd4962eb403e578679562126`. Its14 layers total2,260,321,245compressed bytes, versus the9.74GB vLLM candidate. OCI config is CUDA13.0.0; parent inspected current upstream build architectures75/80/86/90, with no explicit120. Runtime compatibility with5090 is a test gate, not an assumption; no custom rebuild is authorized.

`stacks/llms/speech-gpu.yml` defaults0 replicas, uses the existing high-end GPU label group and explicit official whisper-server entrypoint, and mounts the same checksum-verified model fromD: read-only. Rootful Docker already reports default runtime nvidia; no daemon changes are made. Limits2 CPUs/3GiB resident memory; no per-service swap or VRAM cap is claimed. Capture fresh free VRAM, verify actual CUDA backend allocation, arm an independent manager stop timer before activation, then run one finite Spanish request before handing the client owner a non-overlapping test window. Keep Qwen staging and every other workload intact.

GPU image pull completed179.809s/exit0; image ID745bdf2095fe005faf3cbbe39d21e9856ac8261ab7da66eb05f6037a075a9f91 verified independently. Manager timer `stt-gpu-stop-20261103.timer` was verified active before activation, deadline2026-11-03 01:38:25 SCL (UTC-03:00). Actual task on the high-end node detected RTX5090 capability12.0 and loaded573.45MB ontoCUDA0 with flash attention enabled; health200. Shared GPU free memory was7860MiB before activation and6835MiB after allocation. LiteLLM config754 mounted upstream llms-speech-gpu_whisper:8080/v1 and public liveliness200 were checked on the replacement task before the first Spanish POST. Actual inference and client gates remain pending at this checkpoint.

First GPU inference then completed200/50.377s for the7.68s Spanish fixture, with correct Spanish text and unauthenticated401. Receipt `reports/backend-gpu-first-receipt.json` distinguishes actual CUDA compatibility from performance acceptance. The first request alone does not identify JIT or cold-start contribution. Remaining test window was ceded exclusively to the client owner for mixed and accelerated fixtures through LiteLLM and actual WS; no concurrent backend probe is authorized by that handoff.

## Context

OpenChamber sends multipart file/model/response_format=json to an OpenAI-compatible transcription endpoint and expects text. Dictation must preserve mixed spoken languages and use no translation or downstream rewriting. Permanent serving belongs to Swarm behind LiteLLM. Representative Chilean code-switching samples are not available.

## Decision

Use upstream vLLM v0.33.0, pinned by manifest digest, with Qwen/Qwen3-ASR-1.7B revision 7278e1e70fe206f11671096ffdd38061171dd6e5. Reuse downloaded model bytes read-only from D: through the high-end GPU label group. Runtime YAML uses immutable speech_qwen3_config-v0.1.0. The stack source is stacks/llms/speech.yml. The serving endpoint has no published port or Traefik route; LiteLLM reaches it on the existing internal cluster overlay.

Add alias openchamber-stt with audio_transcription mode. Omit language and prompt. Keep the existing client selection until an actual multipart request through LiteLLM passes. Issue a model-scoped client credential through the existing Trust Agent provisioning route and OpenBao custody, never in chat. This ADR grants no broader permissions.

## Alternatives

NVIDIA Nemotron 3.5 Transcribe NVFP4 is promising and its October 28 model card lists RTX5090 and Spanish code-switching. Inspected NeMo Speech vLLM plugin implements multimodal chat, not SupportsTranscription; its CTC middleware intercepts chat completions. SGLang-Omni's documented multipart path is BF16/FP8, not NVFP4. No verified official NVFP4 multipart deployment is available in this evaluation; a custom API shim would violate the requested scope. This is a compatibility decision, not a comparative Chilean accuracy result.

Voxtral3's official announcement offers self-deployment through contacting Mistral. The observed official Hugging Face catalog lists earlier Voxtral checkpoints, not Voxtral3. No private commercial access is established here.

## Consequences

The high-end GPU worker is ephemeral. Dictation availability depends on it; do not silently fall back to a paid cloud API. The bind mount is node-local data, not configuration. A future second high-end node requires model provisioning before scheduling there. Preserve downloaded weights on rollback.

Resident memory limit 10GiB, reservation 2GiB; GPU fraction 0.30, two sequences, 4096-token limit, eager execution. Swap intention is to avoid dependence on swapping; Swarm exposes no per-task swap cap here, so this does not claim a zero-swap guarantee. Host policies remain authoritative. Cache writes land on the durable Docker filesystem. Initial replicas=0 is staging; Gabriel subsequently authorized a brief bounded GPU test while the desktop is active, without changing other workloads. That authorization does not cover an unrestricted background GPU workload.

Trust Agent's cache-reuse path needs read access before key creation. Its existing services namespace grants create/update, with separate exact-path read exceptions. The reviewed STT repair adds create/update/read only at `secret/data/services/openchamber-stt/litellm`, preserving every existing stanza. Applying uses the existing Trust Agent OpenBao adapter and short-lived JWT; the root-token-only CLI is not used. This is a concrete service-cache exception, not a namespace-wide read grant.

## Verification

Compose validation passed. Swarm service with replicas=0 was created through cluster-utils; its monitor returned partial/ambiguous_state for expected zero replicas, so it is not a readiness receipt. Inspect confirms Replicated.Replicas=0. No server, latency or transcription quality is established by staging.

LiteLLM config750 converged1/1 and exposes the alias. Both model shards independently match their pinned upstream SHA256. Two attached image pulls were cancelled without registering the image; a bounded systemd unit now owns the image pull independently of the client session.

After the exact-path policy repair, JWT-authenticated STT cache GET returned404 (absent), while a separate ungranted service path returned403. Provisioning then exposed an alias-versus-ID mismatch: the existing personal-stack team uses UUID `8ba755a2-ebaf-4552-8fab-7119d02222aa`. Supplying that ID issued the model-scoped key and persisted its cache. No new team was created. The finite client at `reports/stt_probe.py` retains credentials in memory; its transcript schema rejects missing, null, empty and whitespace-only output. Credential issuance alone does not establish successful audio inference.

Acceptance requires actual multipart POST via LiteLLM, a validated text response, English and Spanish fixtures with provenance and measured elapsed time, credential rejection, preserved autodetection, and parent-owned OpenChamber integration. Public monolingual fixtures establish functionality only. Chilean code-switching remains unmeasured until representative audio is supplied.

## Rollback

Remove only the openchamber-stt model entry and deploy only LiteLLM with a new config version. Keep qwen3-asr replicas=0 and deploy only that service. OpenChamber prior settings belong to the parent and retain Parakeet rollback. Preserve unrelated repository edits and service updates.

For policy rollback, remove only the added exact STT stanza and apply the preserved canonical policy through the same Trust Agent adapter. The pre-repair policy is recorded at `reports/stt-policy-before-20261103.hcl`; compare current content before restoring so subsequent unrelated policy edits survive. Retain or revoke the scoped credential deliberately through its owning service; do not print it or replace it with a master key.

## Primary sources

- https://raw.githubusercontent.com/vllm-project/vllm/v0.33.0/vllm/model_executor/models/qwen3_asr.py
- https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4
- https://github.com/NVIDIA-NeMo/Speech/tree/main/nemo/collections/speechlm2/vllm/salm
- https://mistral.ai/news/voxtral-3
- https://huggingface.co/mistralai
