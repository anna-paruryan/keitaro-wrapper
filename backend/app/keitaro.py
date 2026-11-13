"""Тонкий клиент Keitaro Admin API (v1).

Адрес:  {KEITARO_URL}/admin_api/v1/...
Ключ:   заголовок `Api-Key`.

Всё, что знает про формат Keitaro, живёт в этом файле и в `services.py`: если на вашей
версии трекера какое-то поле называется иначе, править нужно в этих двух местах.
"""

import logging
import re
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


class KeitaroError(Exception):
    """Любая ошибка общения с Keitaro (сеть, 4xx/5xx, неожиданный ответ)."""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


def normalize_base_url(url: str) -> str:
    """`tlgk.host/admin` -> `https://tlgk.host`."""
    url = url.strip().rstrip("/")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    for suffix in ("/admin_api/v1", "/admin"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:300].strip() or resp.reason_phrase
    if isinstance(data, dict):
        for key in ("error", "message", "detail", "errors"):
            if data.get(key):
                return str(data[key])[:500]
    return str(data)[:500]


def as_list(data: Any) -> list:
    """Списочные ответы бывают голым массивом или обёрнутыми в {rows|data|items}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("rows", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


class KeitaroClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.root = normalize_base_url(base_url)
        self._http = httpx.Client(
            base_url=f"{self.root}/admin_api/v1/",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    # ------------------------------------------------------------------ transport
    def _request(self, method: str, path: str, *, params: Optional[dict] = None, json: Any = None) -> Any:
        try:
            resp = self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise KeitaroError(f"Could not reach Keitaro ({self.root}): {exc}") from exc

        if resp.status_code >= 400:
            hint = " Check KEITARO_API_KEY." if resp.status_code in (401, 403) else ""
            raise KeitaroError(
                f"Keitaro responded {resp.status_code} to {method} {path}: {_error_text(resp).rstrip('.')}.{hint}",
                status=resp.status_code,
                body=resp.text[:2000],
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise KeitaroError(
                "Keitaro did not return JSON. Check KEITARO_URL: it must be the tracker address, not the login page.",
                status=resp.status_code,
            ) from exc

    # ------------------------------------------------------------------ справочники
    def list_offers(self) -> list[dict]:
        return as_list(self._request("GET", "offers"))

    def get_offer(self, offer_id: int) -> dict:
        return self._request("GET", f"offers/{offer_id}")

    def list_domains(self) -> list[dict]:
        return as_list(self._request("GET", "domains"))

    def list_groups(self, group_type: str = "campaigns") -> list[dict]:
        # Keitaro требует параметр type: campaigns | offers | landings
        return as_list(self._request("GET", "groups", params={"type": group_type}))

    def list_traffic_sources(self) -> list[dict]:
        return as_list(self._request("GET", "traffic_sources"))

    def list_stream_filters(self) -> Any:
        return self._request("GET", "stream_filters")

    # ------------------------------------------------------------------ кампании
    def list_campaigns(self) -> list[dict]:
        return as_list(self._request("GET", "campaigns"))

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "campaigns", json=payload)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"campaigns/{campaign_id}")

    # ------------------------------------------------------------------ потоки
    def list_campaign_streams(self, campaign_id: int) -> list[dict]:
        try:
            data = self._request("GET", f"campaigns/{campaign_id}/streams")
        except KeitaroError as exc:
            if exc.status not in (404, 405):
                raise
            data = self._request("GET", "streams", params={"campaign_id": campaign_id})
        return as_list(data)

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> Any:
        return self._request("PUT", f"streams/{stream_id}", json=payload)

    # ------------------------------------------------------------------ отчёты
    def build_report(self, body: dict) -> Any:
        return self._request("POST", "report/build", json=body)

    def close(self) -> None:
        self._http.close()