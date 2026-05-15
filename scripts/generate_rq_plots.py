from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from csv_utils import read_csv_with_optional_header


DATASET_COLUMNS = [
    "repository_full_name",
    "repository_stars",
    "repository_language",
    "pull_number",
    "pull_state",
    "merged_flag",
    "created_at",
    "closed_or_merged_at",
    "analysis_time_hours",
    "analysis_time_days",
    "files_changed",
    "additions",
    "deletions",
    "changed_lines_total",
    "description_length",
    "participants_count",
    "issue_comments_count",
    "review_comments_count",
    "comments_total",
    "reviews_count",
    "review_approvals",
    "review_change_requests",
    "review_comments_only",
    "author_login",
    "url",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera graficos por questao de pesquisa.")
    parser.add_argument("--input", default="data/pull_requests_dataset.csv")
    parser.add_argument("--output-dir", default="outputs")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def setup_theme() -> None:
    sns.set_theme(style="whitegrid")


def save_barplot(
    labels: list[str],
    values: list[float],
    title: str,
    ylabel: str,
    output_path: Path,
    color: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=color, edgecolor="black")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")

    for bar, value in zip(bars, values):
        label = f"{value:.3f}" if abs(value - round(value)) > 1e-9 else f"{int(value)}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            label,
            ha="center",
            va="bottom",
            fontsize=10,
        )
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)
    setup_theme()

    df = read_csv_with_optional_header(Path(args.input), DATASET_COLUMNS)
    review_bucket = pd.cut(
        df["reviews_count"],
        bins=[0, 1, 2, 1000],
        labels=["1 revisao", "2 revisoes", "3+ revisoes"],
        include_lowest=True,
    )
    df = df.assign(reviews_bucket=review_bucket)

    by_status = df.groupby("pull_state")[
        ["files_changed", "analysis_time_hours", "description_length", "comments_total"]
    ].median(numeric_only=True)
    by_reviews = df.groupby("reviews_bucket")[
        ["files_changed", "analysis_time_hours", "description_length", "comments_total"]
    ].median(numeric_only=True)

    save_barplot(
        ["merged", "closed"],
        [
            float(by_status.loc["merged", "files_changed"]),
            float(by_status.loc["closed", "files_changed"]),
        ],
        "RQ01 - Tamanho do PR vs status final",
        "Mediana de arquivos alterados",
        output_dir / "rq01_tamanho_vs_status.png",
        "#2a9d8f",
    )
    save_barplot(
        ["merged", "closed"],
        [
            float(by_status.loc["merged", "analysis_time_hours"]),
            float(by_status.loc["closed", "analysis_time_hours"]),
        ],
        "RQ02 - Tempo de analise vs status final",
        "Mediana de horas",
        output_dir / "rq02_tempo_vs_status.png",
        "#f4a261",
    )
    save_barplot(
        ["merged", "closed"],
        [
            float(by_status.loc["merged", "description_length"]),
            float(by_status.loc["closed", "description_length"]),
        ],
        "RQ03 - Descricao do PR vs status final",
        "Mediana de caracteres",
        output_dir / "rq03_descricao_vs_status.png",
        "#7b2cbf",
    )
    save_barplot(
        ["merged", "closed"],
        [
            float(by_status.loc["merged", "comments_total"]),
            float(by_status.loc["closed", "comments_total"]),
        ],
        "RQ04 - Interacoes vs status final",
        "Mediana de comentarios",
        output_dir / "rq04_interacoes_vs_status.png",
        "#e76f51",
    )

    review_labels = ["1 revisao", "2 revisoes", "3+ revisoes"]
    save_barplot(
        review_labels,
        [float(by_reviews.loc[label, "files_changed"]) for label in review_labels],
        "RQ05 - Tamanho do PR vs numero de revisoes",
        "Mediana de arquivos alterados",
        output_dir / "rq05_tamanho_vs_revisoes.png",
        "#219ebc",
    )
    save_barplot(
        review_labels,
        [float(by_reviews.loc[label, "analysis_time_hours"]) for label in review_labels],
        "RQ06 - Tempo de analise vs numero de revisoes",
        "Mediana de horas",
        output_dir / "rq06_tempo_vs_revisoes.png",
        "#ffb703",
    )
    save_barplot(
        review_labels,
        [float(by_reviews.loc[label, "description_length"]) for label in review_labels],
        "RQ07 - Descricao do PR vs numero de revisoes",
        "Mediana de caracteres",
        output_dir / "rq07_descricao_vs_revisoes.png",
        "#9d4edd",
    )
    save_barplot(
        review_labels,
        [float(by_reviews.loc[label, "comments_total"]) for label in review_labels],
        "RQ08 - Interacoes vs numero de revisoes",
        "Mediana de comentarios",
        output_dir / "rq08_interacoes_vs_revisoes.png",
        "#d62828",
    )

    print(f"Graficos por RQ salvos em: {output_dir}")


if __name__ == "__main__":
    main()
