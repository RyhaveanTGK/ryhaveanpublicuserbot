from __future__ import annotations

import asyncio
import hashlib
import random
import re
from typing import Any

import httpx

from config import settings


class RenderAPIError(RuntimeError):
    pass


class RenderClient:
    _owner_id_cache: dict[str, str] = {}

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = settings.render_api_base
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RyhaveanDeployPanel/2.0",
        }

    def _cache_key(self) -> str:
        return hashlib.sha1(self.api_key.encode("utf-8")).hexdigest()

    def _get_cached_owner_id(self) -> str:
        return self._owner_id_cache.get(self._cache_key(), "")

    def _set_cached_owner_id(self, owner_id: str) -> str:
        owner_id = (owner_id or "").strip()
        if owner_id:
            self._owner_id_cache[self._cache_key()] = owner_id
        return owner_id

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", 45.0)
        retry_statuses = {408, 409, 423, 425, 429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
                    response = await client.request(method, url, **kwargs)

                if response.status_code in retry_statuses and attempt < 3:
                    await asyncio.sleep((0.6 * attempt) + random.uniform(0.1, 0.4))
                    continue

                if response.status_code >= 400:
                    raise RenderAPIError(f"Render API xətası ({response.status_code}): {response.text[:300]}")

                if not response.text.strip():
                    return {}
                return response.json()
            except RenderAPIError as exc:
                last_error = exc
                if attempt < 3 and any(code in str(exc) for code in ("408", "409", "423", "425", "429", "500", "502", "503", "504")):
                    await asyncio.sleep((0.6 * attempt) + random.uniform(0.1, 0.4))
                    continue
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < 3:
                    await asyncio.sleep((0.6 * attempt) + random.uniform(0.1, 0.4))
                    continue
                raise RenderAPIError(f"Render API bağlantı xətası: {exc}") from exc

        raise RenderAPIError(f"Render API sorğusu tamamlanmadı: {last_error}")

    async def list_owners(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/owners")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items") or data.get("data") or data.get("owners") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    async def resolve_owner_id(self, cached_owner_id: str | None = None) -> str:
        fallback_owner_id = (cached_owner_id or self._get_cached_owner_id()).strip()
        try:
            owners = await self.list_owners()
        except RenderAPIError:
            if fallback_owner_id:
                return self._set_cached_owner_id(fallback_owner_id)
            raise

        if not owners:
            if fallback_owner_id:
                return self._set_cached_owner_id(fallback_owner_id)
            raise RenderAPIError("Render owner ID tapılmadı")

        if fallback_owner_id:
            for owner in owners:
                if str(owner.get("id", "")).strip() == fallback_owner_id:
                    return self._set_cached_owner_id(fallback_owner_id)

        scored_owners: list[tuple[int, str]] = []
        for owner in owners:
            owner_id = str(owner.get("id", "")).strip()
            if not owner_id:
                continue
            score = 0
            owner_type = str(owner.get("type") or owner.get("ownerType") or "").lower()
            if owner_type in {"user", "personal", "owner"}:
                score += 4
            if owner.get("email") or owner.get("ownerEmail"):
                score += 2
            if owner.get("name"):
                score += 1
            scored_owners.append((score, owner_id))

        if not scored_owners:
            if fallback_owner_id:
                return self._set_cached_owner_id(fallback_owner_id)
            raise RenderAPIError("Render owner ID tapılmadı")

        scored_owners.sort(key=lambda item: item[0], reverse=True)
        return self._set_cached_owner_id(scored_owners[0][1])

    async def list_services(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if owner_id:
            params["ownerId"] = owner_id
        data = await self._request("GET", "/services", params=params)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items") or data.get("data") or data.get("services") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    async def get_service(self, service_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/services/{service_id}")

    async def list_deploys(self, service_id: str, limit: int = 5) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/services/{service_id}/deploys", params={"limit": limit})
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items") or data.get("data") or data.get("deploys") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    async def trigger_deploy(self, service_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/services/{service_id}/deploys")

    async def replace_env_vars(self, service_id: str, env_vars: list[dict[str, str]]) -> dict[str, Any]:
        return await self._request("PUT", f"/services/{service_id}/env-vars", json=env_vars)

    async def create_service(
        self,
        *,
        owner_id: str,
        service_name: str,
        env_vars: list[dict[str, str]],
    ) -> dict[str, Any]:
        payload = {
            "type": "web_service",
            "name": service_name,
            "ownerId": owner_id,
            "repo": settings.render_template_repo,
            "branch": settings.render_template_branch,
            "rootDir": settings.render_template_root_dir,
            "serviceDetails": {
                "env": "docker",
                "plan": settings.render_default_plan,
                "region": settings.render_default_region,
                "pullRequestPreviewsEnabled": "no",
                "envVars": env_vars,
            },
        }
        return await self._request("POST", "/services", json=payload, timeout=90.0)



def slugify_service_name(text: str, fallback: str) -> str:
    value = (text or "").strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:58] or fallback
