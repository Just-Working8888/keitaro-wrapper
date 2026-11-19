"""Thin client for the Keitaro Admin API v1 (https://admin-api.docs.keitaro.io)."""
from typing import Any, Dict, List, Optional

import httpx


class KeitaroError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0,
                 transport: Optional[httpx.BaseTransport] = None):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            timeout=timeout,
            transport=transport,
            headers={
                "Api-Key": api_key,
                # Cloudflare in front of the tracker rejects default library UAs (error 1010)
                "User-Agent": "keitaro-wrapper/1.0",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, json: Any = None) -> Any:
        try:
            resp = self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise KeitaroError(f"Keitaro недоступен: {exc}") from exc
        try:
            data = resp.json() if resp.content else None
        except ValueError:
            data = None
        if resp.status_code >= 400:
            raise KeitaroError(self._error_text(data, resp), status=resp.status_code if resp.status_code < 500 else 502)
        if data is None and resp.content:
            raise KeitaroError(f"Keitaro вернул не-JSON ответ: {resp.text[:200]}")
        return data

    @staticmethod
    def _error_text(data: Any, resp: httpx.Response) -> str:
        if isinstance(data, dict):
            if "error" in data:
                return str(data["error"])
            # validation errors look like {"alias": ["Alias is required"]}
            parts = []
            for field, msgs in data.items():
                msgs = msgs if isinstance(msgs, list) else [msgs]
                parts.append(f"{field}: {', '.join(map(str, msgs))}")
            if parts:
                return "; ".join(parts)
        return f"HTTP {resp.status_code}: {resp.text[:200]}"

    # --- dictionaries -------------------------------------------------------
    def list_domains(self) -> List[Dict]:
        return self._request("GET", "/domains")

    def list_groups(self, type_: str = "campaigns") -> List[Dict]:
        return self._request("GET", f"/groups?type={type_}")

    def list_traffic_sources(self) -> List[Dict]:
        return self._request("GET", "/traffic_sources")

    def get_traffic_source(self, source_id: int) -> Dict:
        return self._request("GET", f"/traffic_sources/{source_id}")

    def list_offers(self) -> List[Dict]:
        return self._request("GET", "/offers")

    # --- campaigns & streams ------------------------------------------------
    def list_campaigns(self) -> List[Dict]:
        return self._request("GET", "/campaigns")

    def get_campaign(self, campaign_id: int) -> Dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: Dict) -> Dict:
        return self._request("POST", "/campaigns", json=payload)

    def delete_campaign(self, campaign_id: int) -> Any:
        return self._request("DELETE", f"/campaigns/{campaign_id}")

    def list_streams(self, campaign_id: int) -> List[Dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def get_stream(self, stream_id: int) -> Dict:
        return self._request("GET", f"/streams/{stream_id}")

    def create_stream(self, payload: Dict) -> Dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: Dict) -> Dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)

    # --- reports ------------------------------------------------------------
    def build_report(self, payload: Dict) -> Dict:
        return self._request("POST", "/report/build", json=payload)
