"""Thin client for the Keitaro Admin API (v1)."""

import time
from typing import Any

import httpx

from app.config import Settings, get_settings

OFFERS_TTL = 60.0
_offers_cache: dict[str, Any] = {"data": None, "at": 0.0}


class KeitaroError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f"Keitaro API error {status}: {detail}")


class KeitaroClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=settings.api_base,
            headers={"Api-Key": settings.keitaro_api_key, "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(502, f"Keitaro unreachable: {exc}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text[:500]
            raise KeitaroError(resp.status_code, detail)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- reference data -------------------------------------------------
    def list_offers(self, fresh: bool = False) -> list[dict]:
        """Offers change rarely; cache them for a minute (process-wide)."""
        now = time.monotonic()
        if not fresh and _offers_cache["data"] is not None and now - _offers_cache["at"] < OFFERS_TTL:
            return _offers_cache["data"]
        data = self._request("GET", "/offers")
        _offers_cache.update(data=data, at=now)
        return data

    def get_domain(self, domain_id: int) -> dict:
        return self._request("GET", f"/domains/{domain_id}")

    def list_campaigns(self) -> list[dict]:
        return self._request("GET", "/campaigns")

    # --- campaigns ------------------------------------------------------
    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- streams --------------------------------------------------------
    def list_streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def get_stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}")

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)

    # --- reports --------------------------------------------------------
    def build_report(self, payload: dict) -> dict:
        return self._request("POST", "/report/build", json=payload)


def get_keitaro() -> KeitaroClient:
    return KeitaroClient(get_settings())
