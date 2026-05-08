from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.lab03.github_api import GitHubApiError, GitHubClient


MIN_REVIEW_HOURS = 1.0
DEFAULT_TOP_REPOSITORIES = 200
DEFAULT_MIN_PRS = 100
DEFAULT_MAX_PRS_PER_REPO = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta PRs revisados de repositorios populares do GitHub."
    )
    parser.add_argument("--output-dir", default="data", help="Diretorio de saida.")
    parser.add_argument(
        "--top-repositories",
        type=int,
        default=DEFAULT_TOP_REPOSITORIES,
        help="Quantidade de repositorios populares a considerar.",
    )
    parser.add_argument(
        "--min-prs",
        type=int,
        default=DEFAULT_MIN_PRS,
        help="Quantidade minima de PRs fechados+merged por repositorio.",
    )
    parser.add_argument(
        "--max-prs-per-repo",
        type=int,
        default=DEFAULT_MAX_PRS_PER_REPO,
        help="Quantidade maxima de PRs coletados por repositorio. Use 0 para coletar todos.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Filtro opcional de linguagem para a busca de repositorios.",
    )
    return parser.parse_args()


def iso_to_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_popular_repositories(client: GitHubClient, top_n: int, language: str | None) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1

    while len(repositories) < top_n:
        query = "stars:>1 archived:false mirror:false"
        if language:
            query += f" language:{language}"

        response = client.request(
            "GET",
            "/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        items = response.json().get("items", [])
        if not items:
            break

        repositories.extend(items)
        page += 1

    return repositories[:top_n]


def list_pull_requests(client: GitHubClient, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for pr in client.paginated_get(
        f"/repos/{owner}/{repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc"},
    ):
        results.append(pr)
        if limit > 0 and len(results) >= limit:
            break

    return results


def fetch_reviews(client: GitHubClient, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
    return list(client.paginated_get(f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews"))


def fetch_issue_comments(client: GitHubClient, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
    return list(client.paginated_get(f"/repos/{owner}/{repo}/issues/{pull_number}/comments"))


def fetch_review_comments(client: GitHubClient, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
    return list(client.paginated_get(f"/repos/{owner}/{repo}/pulls/{pull_number}/comments"))


def count_files(client: GitHubClient, owner: str, repo: str, pull_number: int) -> int:
    total = 0
    for _ in client.paginated_get(f"/repos/{owner}/{repo}/pulls/{pull_number}/files"):
        total += 1
    return total


def classify_final_status(pr: dict[str, Any]) -> str:
    return "merged" if pr.get("merged_at") else "closed"


def is_bot(login: str | None) -> bool:
    if not login:
        return False
    lowered = login.lower()
    return lowered.endswith("[bot]") or lowered.endswith("-bot") or "[bot]" in lowered


def unique_participants(
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
) -> int:
    participants = set()
    for actor in [pr.get("user")] + [item.get("user") for item in reviews + issue_comments + review_comments]:
        login = (actor or {}).get("login")
        if login:
            participants.add(login)
    return len(participants)


def build_row(
    repository: dict[str, Any],
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    files_changed: int,
) -> dict[str, Any]:
    created_at = iso_to_datetime(pr.get("created_at"))
    finished_at = iso_to_datetime(pr.get("merged_at") or pr.get("closed_at"))
    assert created_at is not None
    assert finished_at is not None

    analysis_seconds = (finished_at - created_at).total_seconds()

    non_bot_reviews = [review for review in reviews if not is_bot((review.get("user") or {}).get("login"))]
    status_counter = Counter(review.get("state", "UNKNOWN").lower() for review in non_bot_reviews)

    return {
        "repository_full_name": repository["full_name"],
        "repository_stars": repository["stargazers_count"],
        "repository_language": repository.get("language"),
        "pull_number": pr["number"],
        "pull_state": classify_final_status(pr),
        "merged_flag": 1 if pr.get("merged_at") else 0,
        "created_at": pr["created_at"],
        "closed_or_merged_at": pr.get("merged_at") or pr.get("closed_at"),
        "analysis_time_hours": round(analysis_seconds / 3600, 4),
        "analysis_time_days": round(analysis_seconds / 86400, 4),
        "files_changed": files_changed,
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_lines_total": pr.get("additions", 0) + pr.get("deletions", 0),
        "description_length": len(pr.get("body") or ""),
        "participants_count": unique_participants(pr, non_bot_reviews, issue_comments, review_comments),
        "issue_comments_count": len(issue_comments),
        "review_comments_count": len(review_comments),
        "comments_total": len(issue_comments) + len(review_comments),
        "reviews_count": len(non_bot_reviews),
        "review_approvals": status_counter.get("approved", 0),
        "review_change_requests": status_counter.get("changes_requested", 0),
        "review_comments_only": status_counter.get("commented", 0),
        "author_login": (pr.get("user") or {}).get("login"),
        "url": pr.get("html_url"),
    }


def repository_has_enough_prs(client: GitHubClient, owner: str, repo: str, min_prs: int) -> bool:
    response = client.request(
        "GET",
        "/search/issues",
        params={"q": f"repo:{owner}/{repo} is:pr is:closed", "per_page": 1},
    )
    total_count = response.json().get("total_count", 0)
    return total_count >= min_prs


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    client = GitHubClient()
    repositories = get_popular_repositories(client, args.top_repositories, args.language)

    repositories_output = output_dir / "selected_repositories.csv"
    dataset_output = output_dir / "pull_requests_dataset.csv"

    selected_repositories: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []

    for repository in repositories:
        owner = repository["owner"]["login"]
        repo = repository["name"]

        try:
            if not repository_has_enough_prs(client, owner, repo, args.min_prs):
                continue

            selected_repositories.append(
                {
                    "full_name": repository["full_name"],
                    "stars": repository["stargazers_count"],
                    "language": repository.get("language"),
                    "html_url": repository.get("html_url"),
                }
            )

            pulls = list_pull_requests(client, owner, repo, args.max_prs_per_repo)
            for pr in pulls:
                reviews = fetch_reviews(client, owner, repo, pr["number"])
                non_bot_reviews = [
                    review for review in reviews if not is_bot((review.get("user") or {}).get("login"))
                ]
                if not non_bot_reviews:
                    continue

                created_at = iso_to_datetime(pr.get("created_at"))
                finished_at = iso_to_datetime(pr.get("merged_at") or pr.get("closed_at"))
                if created_at is None or finished_at is None:
                    continue

                if (finished_at - created_at).total_seconds() < MIN_REVIEW_HOURS * 3600:
                    continue

                issue_comments = fetch_issue_comments(client, owner, repo, pr["number"])
                review_comments = fetch_review_comments(client, owner, repo, pr["number"])
                files_changed = count_files(client, owner, repo, pr["number"])

                dataset_rows.append(
                    build_row(
                        repository=repository,
                        pr=pr,
                        reviews=non_bot_reviews,
                        issue_comments=issue_comments,
                        review_comments=review_comments,
                        files_changed=files_changed,
                    )
                )

            print(
                f"Repositorio processado: {repository['full_name']} | "
                f"PRs validos acumulados: {len(dataset_rows)}"
            )
        except GitHubApiError as exc:
            print(f"Falha ao processar {repository['full_name']}: {exc}")

    if selected_repositories:
        with repositories_output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=selected_repositories[0].keys())
            writer.writeheader()
            writer.writerows(selected_repositories)

    if dataset_rows:
        with dataset_output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=dataset_rows[0].keys())
            writer.writeheader()
            writer.writerows(dataset_rows)

    print(f"Repositorios salvos em: {repositories_output}")
    print(f"Dataset salvo em: {dataset_output}")
    print(f"Total de repositorios selecionados: {len(selected_repositories)}")
    print(f"Total de PRs coletados: {len(dataset_rows)}")


if __name__ == "__main__":
    main()
