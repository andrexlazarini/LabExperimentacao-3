from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from csv_utils import read_csv_with_optional_header


RQ_MAP = {
    "RQ01": ("changed_lines_total", "tamanho do PR", "feedback final"),
    "RQ02": ("analysis_time_hours", "tempo de analise", "feedback final"),
    "RQ03": ("description_length", "descricao do PR", "feedback final"),
    "RQ04": ("comments_total", "interacoes nos PRs", "feedback final"),
    "RQ05": ("changed_lines_total", "tamanho do PR", "numero de revisoes"),
    "RQ06": ("analysis_time_hours", "tempo de analise", "numero de revisoes"),
    "RQ07": ("description_length", "descricao do PR", "numero de revisoes"),
    "RQ08": ("comments_total", "interacoes nos PRs", "numero de revisoes"),
}

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
    parser = argparse.ArgumentParser(description="Gera um relatorio markdown a partir das analises.")
    parser.add_argument("--dataset", default="data/pull_requests_dataset.csv")
    parser.add_argument("--analysis-dir", default="outputs")
    parser.add_argument("--output", default="report/relatorio_preenchido.md")
    return parser.parse_args()


def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def correlation_text(value: float, p_value: float) -> str:
    strength = "muito fraca"
    abs_value = abs(value)
    if abs_value >= 0.7:
        strength = "forte"
    elif abs_value >= 0.4:
        strength = "moderada"
    elif abs_value >= 0.2:
        strength = "fraca"

    direction = "positiva" if value > 0 else "negativa"
    if value == 0:
        direction = "nula"

    significance = "estatisticamente significativa" if p_value < 0.05 else "nao estatisticamente significativa"
    return f"correlacao {strength} {direction}, {significance}"


def safe_lookup(frame: pd.DataFrame, index: str, column: str) -> float:
    if index not in frame.index:
        return float("nan")
    value = frame.loc[index, column]
    return float(value) if pd.notna(value) else float("nan")


def main() -> None:
    args = parse_args()
    dataset = read_csv_with_optional_header(Path(args.dataset), DATASET_COLUMNS)
    analysis_dir = Path(args.analysis_dir)
    output_path = Path(args.output)

    summary_by_status = pd.read_csv(analysis_dir / "summary_by_status.csv", index_col=0)
    summary_by_review_bucket = pd.read_csv(analysis_dir / "summary_by_review_bucket.csv", index_col=0)
    status_correlations = {item["metric"]: item for item in load_json(analysis_dir / "spearman_status.json")}
    review_correlations = {item["metric"]: item for item in load_json(analysis_dir / "spearman_review_count.json")}

    merged_count = int((dataset["pull_state"] == "merged").sum())
    closed_count = int((dataset["pull_state"] == "closed").sum())
    total_count = int(len(dataset))
    repositories = int(dataset["repository_full_name"].nunique())

    report = []
    report.append("# Relatorio Preenchido\n")
    report.append("## Visao geral\n")
    report.append(
        f"O dataset final contem {total_count} PRs distribuidos em {repositories} repositorios. "
        f"Desses, {merged_count} terminaram com merge e {closed_count} foram fechados sem merge.\n"
    )

    for rq, (metric, dimension, outcome) in RQ_MAP.items():
        report.append(f"## {rq}\n")
        if rq in {"RQ01", "RQ02", "RQ03", "RQ04"}:
            merged_median = safe_lookup(summary_by_status, "merged", metric)
            closed_median = safe_lookup(summary_by_status, "closed", metric)
            corr = status_correlations[metric]
            report.append(
                f"Analisando {dimension} em relacao ao {outcome}, a mediana foi {merged_median:.3f} "
                f"para PRs com merge e {closed_median:.3f} para PRs fechados sem merge. "
                f"O coeficiente de Spearman foi {corr['spearman_correlation']:.4f} "
                f"(p = {corr['p_value']:.6f}), indicando {correlation_text(corr['spearman_correlation'], corr['p_value'])}.\n"
            )
        else:
            one_review = safe_lookup(summary_by_review_bucket, "1 revisao", metric)
            two_reviews = safe_lookup(summary_by_review_bucket, "2 revisoes", metric)
            three_plus = safe_lookup(summary_by_review_bucket, "3+ revisoes", metric)
            corr = review_correlations[metric]
            report.append(
                f"Analisando {dimension} em relacao ao {outcome}, a mediana foi {one_review:.3f} "
                f"para PRs com 1 revisao, {two_reviews:.3f} para 2 revisoes e {three_plus:.3f} para 3 ou mais revisoes. "
                f"O coeficiente de Spearman foi {corr['spearman_correlation']:.4f} "
                f"(p = {corr['p_value']:.6f}), indicando {correlation_text(corr['spearman_correlation'], corr['p_value'])}.\n"
            )

    report.append("## Discussao\n")
    report.append(
        "Os resultados devem ser comparados com as hipoteses iniciais do relatorio principal. "
        "Em geral, associacoes positivas com numero de revisoes sugerem aumento de complexidade ou retrabalho; "
        "associacoes negativas com merge podem sugerir maior dificuldade de integracao.\n"
    )

    output_path.write_text("\n".join(report), encoding="utf-8")
    print(f"Relatorio preenchido salvo em: {output_path}")


if __name__ == "__main__":
    main()
