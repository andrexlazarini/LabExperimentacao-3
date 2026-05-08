from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr


STATUS_METRICS = [
    "files_changed",
    "additions",
    "deletions",
    "changed_lines_total",
    "analysis_time_hours",
    "description_length",
    "participants_count",
    "comments_total",
]

REVIEW_METRICS = STATUS_METRICS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analisa o dataset de PRs do GitHub.")
    parser.add_argument("--input", default="data/pull_requests_dataset.csv", help="CSV de entrada.")
    parser.add_argument("--output-dir", default="outputs", help="Diretorio de saida.")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def summarize_by_status(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "files_changed",
        "additions",
        "deletions",
        "changed_lines_total",
        "analysis_time_hours",
        "description_length",
        "participants_count",
        "comments_total",
        "reviews_count",
    ]
    return df.groupby("pull_state")[columns].median(numeric_only=True).round(3)


def summarize_review_buckets(df: pd.DataFrame) -> pd.DataFrame:
    bucketed = df.copy()
    bucketed["reviews_bucket"] = pd.cut(
        bucketed["reviews_count"],
        bins=[0, 1, 2, 1000],
        labels=["1 revisao", "2 revisoes", "3+ revisoes"],
        include_lowest=True,
    )
    columns = [
        "files_changed",
        "additions",
        "deletions",
        "changed_lines_total",
        "analysis_time_hours",
        "description_length",
        "participants_count",
        "comments_total",
    ]
    return bucketed.groupby("reviews_bucket")[columns].median(numeric_only=True).round(3)


def compute_spearman(df: pd.DataFrame, target: str, metrics: list[str]) -> list[dict[str, float | str]]:
    results: list[dict[str, float | str]] = []
    for metric in metrics:
        subset = df[[target, metric]].dropna()
        coefficient, p_value = spearmanr(subset[target], subset[metric])
        results.append(
            {
                "target": target,
                "metric": metric,
                "spearman_correlation": round(float(coefficient), 4),
                "p_value": round(float(p_value), 6),
                "sample_size": int(len(subset)),
            }
        )
    return results


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, df: pd.DataFrame) -> None:
    df.to_csv(path, index=True)


def plot_boxplots(df: pd.DataFrame, output_dir: Path) -> None:
    sns.set_theme(style="whitegrid")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    sns.boxplot(data=df, x="pull_state", y="changed_lines_total", ax=axes[0, 0])
    sns.boxplot(data=df, x="pull_state", y="analysis_time_hours", ax=axes[0, 1])
    sns.boxplot(data=df, x="pull_state", y="description_length", ax=axes[1, 0])
    sns.boxplot(data=df, x="pull_state", y="comments_total", ax=axes[1, 1])
    axes[0, 0].set_title("Tamanho vs status do PR")
    axes[0, 1].set_title("Tempo de analise vs status do PR")
    axes[1, 0].set_title("Descricao vs status do PR")
    axes[1, 1].set_title("Interacoes vs status do PR")
    fig.tight_layout()
    fig.savefig(output_dir / "status_boxplots.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    sns.boxplot(data=df, x="reviews_count", y="changed_lines_total", ax=axes[0, 0])
    sns.boxplot(data=df, x="reviews_count", y="analysis_time_hours", ax=axes[0, 1])
    sns.boxplot(data=df, x="reviews_count", y="description_length", ax=axes[1, 0])
    sns.boxplot(data=df, x="reviews_count", y="comments_total", ax=axes[1, 1])
    axes[0, 0].set_title("Tamanho vs numero de revisoes")
    axes[0, 1].set_title("Tempo de analise vs numero de revisoes")
    axes[1, 0].set_title("Descricao vs numero de revisoes")
    axes[1, 1].set_title("Interacoes vs numero de revisoes")
    fig.tight_layout()
    fig.savefig(output_dir / "review_count_boxplots.png", dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    df = pd.read_csv(input_path)
    df["pull_state_binary"] = df["merged_flag"].astype(int)

    status_summary = summarize_by_status(df)
    review_summary = summarize_review_buckets(df)
    status_correlations = compute_spearman(df, "pull_state_binary", STATUS_METRICS)
    review_correlations = compute_spearman(df, "reviews_count", REVIEW_METRICS)

    save_csv(output_dir / "summary_by_status.csv", status_summary)
    save_csv(output_dir / "summary_by_review_bucket.csv", review_summary)
    save_json(output_dir / "spearman_status.json", status_correlations)
    save_json(output_dir / "spearman_review_count.json", review_correlations)
    plot_boxplots(df, output_dir)

    print(f"Analises salvas em: {output_dir}")


if __name__ == "__main__":
    main()
