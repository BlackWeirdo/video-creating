"""Apify HTTP client: actor runs, monthly usage, and the spend check before every run."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("videocreator.trends.apify")

APIFY_API = "https://api.apify.com/v2"


# clockworks/tiktok-scraper refuses runs capped below $0.50 (seen 2026-11-14); actual cost is far lower.
RUN_CHARGE_CAP_USD = 0.50


RUN_WAIT_S = 300
TRANSIENT_RETRIES = 2
RETRY_BACKOFF_S = 5


class ApifyError(RuntimeError):
    """Errors whose text contains 'giới hạn' stop the source for the rest of a scan (`scan.py`)."""


class ApifyClient:
    def __init__(self, token: str, *, http_client: httpx.Client | None = None) -> None:
        self._token = token
        self._http = http_client

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        """One API call; retries Apify's transient gateway errors (a real 502 was seen 2026-11-14)."""
        own = self._http is None
        client = self._http or httpx.Client(timeout=RUN_WAIT_S + 60)
        try:
            for attempt in range(TRANSIENT_RETRIES + 1):
                try:
                    resp = client.request(
                        method, f"{APIFY_API}{path}", headers={"Authorization": f"Bearer {self._token}"}, **kw
                    )
                except httpx.TransportError as exc:
                    if attempt == TRANSIENT_RETRIES:
                        raise ApifyError(f"Không kết nối được Apify: {exc.__class__.__name__}") from exc
                    time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                    continue
                if resp.status_code in (500, 502, 503, 504) and attempt < TRANSIENT_RETRIES:
                    logger.info("Apify HTTP %s on %s %s, retrying", resp.status_code, method, path)
                    time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                    continue
                break
        finally:
            if own:
                client.close()
        if resp.status_code == 401:
            raise ApifyError("Apify từ chối token (401): kiểm tra APIFY_API_TOKEN trong Cài đặt.")
        if resp.status_code == 402 or resp.status_code == 429:
            raise ApifyError(f"Apify báo hết hạn mức hoặc quá giới hạn gọi (HTTP {resp.status_code}).")
        if resp.status_code >= 400:
            raise ApifyError(f"Apify lỗi HTTP {resp.status_code} khi gọi {path.split('?')[0]}")
        return resp.json()

    def monthly_usage(self) -> tuple[float, float]:
        """Returns `(used_usd, account_limit_usd)` for the current billing cycle."""
        data = self._request("GET", "/users/me/limits").get("data") or {}
        used = float((data.get("current") or {}).get("monthlyUsageUsd") or 0.0)
        limit = float((data.get("limits") or {}).get("maxMonthlyUsageUsd") or 0.0)
        return used, limit

    def run_actor(self, actor: str, run_input: dict[str, Any], *, max_items: int) -> tuple[list[dict[str, Any]], float]:
        """Runs an actor, waits for it, and returns `(dataset_items, run_cost_usd)`."""
        run = self._request(
            "POST",
            f"/acts/{actor}/runs",
            params={"waitForFinish": 60, "maxTotalChargeUsd": RUN_CHARGE_CAP_USD, "maxItems": max_items},
            json=run_input,
        )["data"]
        deadline = time.monotonic() + RUN_WAIT_S
        while run.get("status") in ("READY", "RUNNING") and time.monotonic() < deadline:
            run = self._request("GET", f"/actor-runs/{run['id']}", params={"waitForFinish": 60})["data"]
        if run.get("status") != "SUCCEEDED":
            raise ApifyError(f"Apify run {actor} kết thúc với trạng thái {run.get('status')}.")
        items = self._request(
            "GET", f"/datasets/{run['defaultDatasetId']}/items", params={"clean": "true", "limit": max_items}
        )
        return [i for i in items if isinstance(i, dict)], float(run.get("usageTotalUsd") or 0.0)


def check_budget(used_usd: float, account_limit_usd: float, monthly_budget_usd: float) -> str | None:
    """Returns a stop reason when one more capped run could exceed the owner's or the account's limit."""
    ceiling = min(monthly_budget_usd, account_limit_usd) if account_limit_usd > 0 else monthly_budget_usd
    if used_usd + RUN_CHARGE_CAP_USD > ceiling:
        return f"Apify: đã dùng ${used_usd:.2f}/${ceiling:.2f} trong tháng (giới hạn ngân sách); dừng tới chu kỳ sau."
    return None
