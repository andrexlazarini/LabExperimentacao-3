from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests


GITHUB_API_URL = "https://api.github.com"
DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubApiError(RuntimeError):
    """Erro levantado quando a API do GitHub retorna uma resposta invalida."""


@dataclass
class GitHubClient:
    token: str | None = None
    per_page: int = 100
    sleep_on_rate_limit: bool = True

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

        resolved_token = self.token or os.getenv("GITHUB_TOKEN")
        if resolved_token:
            self.session.headers["Authorization"] = f"Bearer {resolved_token}"
        self.token = resolved_token

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = path if path.startswith("http") else f"{GITHUB_API_URL}{path}"
        response = self.session.request(method=method, url=url, timeout=60, **kwargs)

        if response.status_code == 403 and self.sleep_on_rate_limit:
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset:
                wait_seconds = max(int(reset) - int(time.time()) + 1, 1)
                print(f"Limite de taxa atingido. Aguardando {wait_seconds} segundos...")
                time.sleep(wait_seconds)
                response = self.session.request(method=method, url=url, timeout=60, **kwargs)

        if response.status_code >= 400:
            try:
                details = response.json()
            except Exception:
                details = response.text
            raise GitHubApiError(f"Erro {response.status_code} em {url}: {details}")

        return response

    def paginated_get(self, path: str, params: dict[str, Any] | None = None) -> Iterator[Any]:
        next_url: str | None = path
        current_params = dict(params or {})
        current_params.setdefault("per_page", self.per_page)

        while next_url:
            response = self.request("GET", next_url, params=current_params)
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubApiError(f"Resposta paginada inesperada em {next_url}")
            for item in payload:
                yield item

            next_url = response.links.get("next", {}).get("url")
            current_params = {}
