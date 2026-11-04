#!/usr/bin/env python3
"""
Plot context ladder experiment results from Postgres (same env as context_ladder_optuna) or --demo.

Produces per-trial charts (success vs num_ctx, throughput, latency), one combined
**line chart** comparing all models on the same axes (`all_models_gen_tokens_per_s_vs_ctx_line.png`),
a small `preview_all_models_line.html` to open in a browser, plus an aggregated
"best successful num_ctx" bar chart derived from those trials.

Examples:
  uv run --with matplotlib --with pandas python stacks/llms/context_ladder_plot.py --demo
  uv run --with matplotlib --with pandas python stacks/llms/context_ladder_plot.py --pg --run-id RUN123
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

_BAR_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def _read_postgres(run_id: Optional[str], schema: str) -> pd.DataFrame:
    from sqlalchemy import create_engine, text

    host = os.environ.get("RESULTS_PG_HOST")
    user = os.environ.get("RESULTS_PG_USER")
    pw = os.environ.get("RESULTS_PG_PASSWORD")
    if not pw:
        pw_file = os.environ.get("RESULTS_PG_PASSWORD_FILE", "").strip()
        if pw_file:
            pw = Path(pw_file).read_text(encoding="utf-8").strip()
    db = os.environ.get("RESULTS_PG_DATABASE")
    port = int(os.environ.get("RESULTS_PG_PORT", "5432"))
    if not host or not user or not pw or not db:
        raise SystemExit("Missing RESULTS_PG_* for --pg")
    url = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"
    engine = create_engine(url, pool_pre_ping=True)
    q = f'SELECT * FROM "{schema}"."context_ladder_trials"'
    params: dict[str, Any] = {}
    if run_id:
        q += " WHERE run_id = :rid"
        params["rid"] = run_id
    with engine.connect() as conn:
        return pd.read_sql(text(q), conn, params=params or None)


def _normalize_trials_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "success" in out.columns:
        out["success"] = out["success"].apply(
            lambda x: x
            if isinstance(x, bool)
            else str(x).lower() in {"1", "true", "yes", "t"}
        )
    for col in (
        "num_ctx",
        "elapsed_ms",
        "prompt_eval_count",
        "eval_count",
        "prompt_tokens_per_s",
        "gen_tokens_per_s",
        "load_duration_ns",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _plot_trials(df: pd.DataFrame, outdir: Path, title_prefix: str) -> None:
    """Per-model trial charts: outcome, throughput, wall time, optional load time."""
    outdir.mkdir(parents=True, exist_ok=True)
    if "num_ctx" not in df.columns or "success" not in df.columns:
        raise SystemExit("Data must include num_ctx and success")

    df = _normalize_trials_df(df)

    models = df["model"].dropna().unique() if "model" in df.columns else ["model"]
    for model in models:
        sub = df[df["model"] == model] if "model" in df.columns else df
        safe = str(model).replace(":", "_").replace("/", "_")

        # --- Success vs num_ctx ---
        fig, ax = plt.subplots(figsize=(10, 5))
        ok = sub[sub["success"] == True]  # noqa: E712
        bad = sub[sub["success"] == False]  # noqa: E712
        if not ok.empty:
            ax.scatter(ok["num_ctx"], [1] * len(ok), c="#2ca02c", s=60, label="success", zorder=3)
        if not bad.empty:
            ax.scatter(bad["num_ctx"], [0] * len(bad), c="#d62728", s=60, label="fail", zorder=3)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["fail", "success"])
        ax.set_xlabel("num_ctx")
        ax.set_title(f"{title_prefix}{model} — trial outcome")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        fig.savefig(outdir / f"success_vs_ctx_{safe}.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

        # --- elapsed_ms vs num_ctx (all trials) ---
        if "elapsed_ms" in sub.columns and sub["elapsed_ms"].notna().any():
            fig_e, ax_e = plt.subplots(figsize=(10, 5))
            if not ok.empty:
                ax_e.scatter(
                    ok["num_ctx"],
                    ok["elapsed_ms"],
                    c="#2ca02c",
                    s=50,
                    alpha=0.85,
                    label="success",
                )
            if not bad.empty:
                ax_e.scatter(
                    bad["num_ctx"],
                    bad["elapsed_ms"],
                    c="#d62728",
                    s=50,
                    alpha=0.85,
                    label="fail",
                )
            ax_e.set_xlabel("num_ctx")
            ax_e.set_ylabel("elapsed_ms (wall time)")
            ax_e.set_title(f"{title_prefix}{model} — request duration")
            ax_e.legend()
            ax_e.grid(True, alpha=0.3)
            fig_e.savefig(outdir / f"elapsed_ms_vs_ctx_{safe}.png", dpi=150, bbox_inches="tight")
            plt.close(fig_e)

        # --- gen / prompt tok/s vs num_ctx (successful trials) ---
        s_ok = sub[sub["success"] == True]  # noqa: E712
        for col, fname, ylabel in (
            ("gen_tokens_per_s", "gen_tps_vs_ctx", "gen_tokens_per_s (eval)"),
            ("prompt_tokens_per_s", "prompt_tps_vs_ctx", "prompt_tokens_per_s (prompt eval)"),
        ):
            if col not in sub.columns or not s_ok[col].notna().any():
                continue
            fig2, ax2 = plt.subplots(figsize=(10, 5))
            ax2.scatter(s_ok["num_ctx"], s_ok[col], c="#1f77b4", s=55, alpha=0.88)
            ax2.set_xlabel("num_ctx")
            ax2.set_ylabel(ylabel)
            ax2.set_title(f"{title_prefix}{model} — {ylabel.split()[0]} vs context")
            ax2.grid(True, alpha=0.3)
            fig2.savefig(outdir / f"{fname}_{safe}.png", dpi=150, bbox_inches="tight")
            plt.close(fig2)

        # --- load_duration (ms) vs num_ctx ---
        if "load_duration_ns" in sub.columns and sub["load_duration_ns"].notna().any():
            s2 = sub.copy()
            load_ms = s2["load_duration_ns"] / 1e6
            s2_ok = s2[s2["success"] == True]  # noqa: E712
            if s2_ok["load_duration_ns"].notna().any():
                fig_l, ax_l = plt.subplots(figsize=(10, 5))
                ax_l.scatter(
                    s2_ok["num_ctx"],
                    s2_ok["load_duration_ns"] / 1e6,
                    c="#9467bd",
                    s=50,
                    alpha=0.88,
                )
                ax_l.set_xlabel("num_ctx")
                ax_l.set_ylabel("load_duration (ms, from Ollama)")
                ax_l.set_title(f"{title_prefix}{model} — model load time (successful trials)")
                ax_l.grid(True, alpha=0.3)
                fig_l.savefig(outdir / f"load_ms_vs_ctx_{safe}.png", dpi=150, bbox_inches="tight")
                plt.close(fig_l)


def _plot_all_models_line_compare(
    df: pd.DataFrame,
    outdir: Path,
    title_prefix: str,
    y_metric: str = "gen_tokens_per_s",
) -> Optional[Path]:
    """
    Single axes: one line per model, Y = metric vs num_ctx (successful trials).
    Returns path to PNG if written, else None.
    """
    df = _normalize_trials_df(df)
    if "model" not in df.columns:
        return None
    ok = df[df["success"] == True]  # noqa: E712
    if y_metric not in ok.columns:
        return None
    sub = ok.dropna(subset=[y_metric, "num_ctx"])
    if sub.empty:
        return None

    _linestyles = ("-", "--", "-.", ":")
    fig, ax = plt.subplots(figsize=(12, 7))
    models = sorted(sub["model"].unique())
    for i, model in enumerate(models):
        m = sub[sub["model"] == model]
        agg = m.groupby("num_ctx", as_index=False)[y_metric].mean()
        agg = agg.sort_values("num_ctx")
        ax.plot(
            agg["num_ctx"],
            agg[y_metric],
            marker="o",
            linewidth=2.2,
            markersize=7,
            alpha=0.92,
            color=_BAR_COLORS[i % len(_BAR_COLORS)],
            linestyle=_linestyles[i % len(_linestyles)],
            label=model,
        )

    ylabel = {
        "gen_tokens_per_s": "Generation tokens / s (successful trials, mean if duplicate ctx)",
        "prompt_tokens_per_s": "Prompt tokens / s (successful trials, mean if duplicate ctx)",
        "elapsed_ms": "elapsed_ms (successful trials, mean if duplicate ctx)",
    }.get(y_metric, y_metric)

    ax.set_xlabel("num_ctx")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title_prefix}All models compared — {y_metric} vs context")
    ax.legend(loc="best", fontsize=9, framealpha=0.92)
    ax.grid(True, alpha=0.38)
    ax.set_axisbelow(True)
    fig.tight_layout()
    out_path = outdir / f"all_models_{y_metric}_vs_ctx_line.png"
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _write_compare_preview_html(outdir: Path, image_name: str) -> Path:
    """Small HTML wrapper to review the comparison chart in a browser."""
    html_path = outdir / "preview_all_models_line.html"
    html_path.write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Context ladder — all models (line)</title>
  <style>
    :root {{ --bg: #0f1114; --fg: #e8eaed; --muted: #9aa0a6; --border: #2a2f36; }}
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: var(--bg); color: var(--fg);
           max-width: 1280px; margin: 0 auto; padding: 1.5rem 1rem 3rem; line-height: 1.5; }}
    h1 {{ font-size: 1.15rem; font-weight: 600; margin: 0 0 0.75rem; }}
    p {{ color: var(--muted); font-size: 0.9rem; margin: 0 0 1rem; }}
    figure {{ margin: 0; padding: 0; border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
              background: #16191d; }}
    img {{ display: block; width: 100%; height: auto; vertical-align: middle; }}
  </style>
</head>
<body>
  <h1>All models compared (line chart)</h1>
  <p>Successful trials only. Duplicate num_ctx per model are averaged.</p>
  <figure>
    <img src="{image_name}" alt="All models line comparison"/>
  </figure>
</body>
</html>
""",
        encoding="utf-8",
    )
    return html_path


def _plot_best_ctx_from_trials(df: pd.DataFrame, outdir: Path, title: str) -> None:
    """Bar chart: max successful num_ctx per model (derived from trial rows)."""
    df = _normalize_trials_df(df)
    ok = df[df["success"] == True]  # noqa: E712
    if ok.empty or "model" not in ok.columns:
        return
    best = ok.groupby("model", as_index=False)["num_ctx"].max().sort_values("num_ctx", ascending=False)
    fig, ax = plt.subplots(figsize=(max(8, len(best) * 1.2), 5))
    x = range(len(best))
    ax.bar(
        x,
        best["num_ctx"],
        color=[_BAR_COLORS[i % len(_BAR_COLORS)] for i in range(len(best))],
    )
    ax.set_xticks(x)
    ax.set_xticklabels(best["model"], rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Best successful num_ctx")
    ax.set_title(title)
    for i, v in enumerate(best["num_ctx"]):
        ax.text(i, v, f" {int(v)}", va="bottom", fontsize=9)
    fig.savefig(outdir / "best_successful_ctx_by_model.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _demo_trials_frame() -> pd.DataFrame:
    """Synthetic multi-trial ladder data for smoke tests (no database)."""
    rows: list[dict[str, Any]] = []

    def row(
        model: str,
        num_ctx: int,
        success: bool,
        *,
        gen_tps: float,
        prompt_tps: float,
        elapsed_base: int,
    ) -> None:
        elapsed = elapsed_base + num_ctx // 400
        ld_ns = 300_000_000 if num_ctx <= 8192 else 1_200_000_000
        if not success:
            ld_ns = 0
        rows.append(
            {
                "model": model,
                "num_ctx": num_ctx,
                "success": success,
                "elapsed_ms": elapsed if success else min(elapsed + 5000, 120_000),
                "gen_tokens_per_s": gen_tps if success else float("nan"),
                "prompt_tokens_per_s": prompt_tps if success else float("nan"),
                "load_duration_ns": ld_ns if success else float("nan"),
            }
        )

    for ctx in [1024, 4096, 8192, 16384, 24576, 32768]:
        row(
            "qwen3.5:0.8b",
            ctx,
            True,
            gen_tps=140 - ctx / 2500,
            prompt_tps=2800,
            elapsed_base=40,
        )

    for ctx in [1024, 4096, 8192, 16384, 32768]:
        row(
            "qwen3.5:2b-q4_K_M",
            ctx,
            True,
            gen_tps=95 - ctx / 3500,
            prompt_tps=2200,
            elapsed_base=120,
        )
    row("qwen3.5:2b-q4_K_M", 32768, False, gen_tps=0, prompt_tps=0, elapsed_base=120)

    for ctx in [1024, 4096, 6144, 8192, 9216]:
        row(
            "qwen3.5:4b-q4_K_M",
            ctx,
            True,
            gen_tps=55 - ctx / 8000,
            prompt_tps=1800,
            elapsed_base=200,
        )
    for ctx in [12288, 16384, 24576, 32768]:
        row(
            "qwen3.5:4b-q4_K_M",
            ctx,
            False,
            gen_tps=0,
            prompt_tps=0,
            elapsed_base=200,
        )

    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Plot context ladder trial data from Postgres or synthetic demo"
    )
    ap.add_argument("--pg", action="store_true", help="Load from Postgres (RESULTS_PG_*)")
    ap.add_argument("--run-id", default="", help="Filter Postgres by run_id")
    ap.add_argument(
        "--schema",
        default=os.environ.get("RESULTS_PG_SCHEMA", "infra_experiments"),
        help="Postgres schema for context_ladder_trials",
    )
    ap.add_argument("--outdir", type=Path, default=Path("stacks/llms/context_ladder_plots"))
    ap.add_argument(
        "--demo",
        action="store_true",
        help="Use synthetic trial rows (writes full trial charts + best-ctx aggregate)",
    )
    ap.add_argument(
        "--no-aggregate",
        action="store_true",
        help="Skip best_successful_ctx_by_model.png (per-trial charts only)",
    )
    ap.add_argument(
        "--no-compare-line",
        action="store_true",
        help="Skip all_models_*_vs_ctx_line.png and preview HTML",
    )
    args = ap.parse_args()

    if args.demo:
        df = _demo_trials_frame()
        title_prefix = "[demo] "
        src = "demo"
    else:
        if not args.pg:
            ap.error("Provide --pg or --demo")
        df = _read_postgres(args.run_id or None, args.schema)
        title_prefix = ""
        src = "postgres"

    _plot_trials(df, args.outdir, title_prefix=title_prefix)

    if not args.no_compare_line:
        compare_path = _plot_all_models_line_compare(
            df, args.outdir, title_prefix=title_prefix, y_metric="gen_tokens_per_s"
        )
        if compare_path is None and "prompt_tokens_per_s" in df.columns:
            compare_path = _plot_all_models_line_compare(
                df, args.outdir, title_prefix=title_prefix, y_metric="prompt_tokens_per_s"
            )
        if compare_path is not None:
            _write_compare_preview_html(args.outdir, compare_path.name)

    if not args.no_aggregate:
        agg_title = (
            "Best successful num_ctx by model (from trial data)"
            if src == "postgres"
            else "[demo] Best successful num_ctx by model (synthetic trials)"
        )
        _plot_best_ctx_from_trials(df, args.outdir, title=agg_title)

    print(f"Wrote per-trial charts (and aggregate unless --no-aggregate) to {args.outdir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
