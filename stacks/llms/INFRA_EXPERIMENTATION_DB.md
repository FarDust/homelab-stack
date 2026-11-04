## Infra Experimentation Postgres DB (Notes + Conventions)

This directory contains scripts/experiments that record results into a dedicated Postgres database for infrastructure benchmarking and tuning.

### Default schema
- Schema: `infra_experiments`

### Table naming
- Use `snake_case`.
- Include the experiment “subject” in the table name (for this ladder: `context_ladder_trials`).

### Run/Trial conventions (recommended)
- `run_id` (`TEXT`): groups all trials from one logical experiment run (set by `EXPERIMENT_RUN_ID`).
- `trial_number` (`INT`): monotonically increasing ordinal for the trial inside that run.
- Add experiment-specific parameter columns (for context ladder: `num_ctx`, `num_predict`, etc.).
- Include `success` (`BOOLEAN`) and an `error` (`TEXT`, nullable) to support “break detection” during sweeps.

### `context_ladder_trials` (this script)
Table: `infra_experiments.context_ladder_trials`
- `run_id` (`TEXT`)
- `created_at` (`TIMESTAMPTZ`)
- `trial_number` (`INT`)
- `model` (`TEXT`)
- `num_ctx` (`INT`)
- `num_predict` (`INT`)
- `temperature` (`DOUBLE PRECISION`)
- `top_p` (`DOUBLE PRECISION`)
- `prompt_mode` (`TEXT`)
- `prompt_ctx_fraction` (`DOUBLE PRECISION`)
- `success` (`BOOLEAN`)
- `elapsed_ms` (`INT`)
- `error` (`TEXT`, nullable)
- Token/timing metrics (nullable when missing):
  - `prompt_eval_count` (`INT`)
  - `eval_count` (`INT`)
  - `prompt_eval_duration_ns` (`BIGINT`)
  - `eval_duration_ns` (`BIGINT`)
  - `total_duration_ns` (`BIGINT`)
  - `load_duration_ns` (`BIGINT`)
  - `prompt_tokens_per_s` (`DOUBLE PRECISION`)
  - `gen_tokens_per_s` (`DOUBLE PRECISION`)

### Environment variables used by `context_ladder_optuna.py`
Trial rows are **always** written to Postgres (no CSV or other file export). Required:
- `RESULTS_PG_HOST`, `RESULTS_PG_PORT`, `RESULTS_PG_USER`, `RESULTS_PG_PASSWORD` (or `RESULTS_PG_PASSWORD_FILE`)
- `RESULTS_PG_DATABASE`, `RESULTS_PG_SCHEMA` (defaults to `infra_experiments`)
- `EXPERIMENT_RUN_ID` (optional; defaults to a timestamp)
