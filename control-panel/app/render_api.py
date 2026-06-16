from __future__ import annotations

import re
from typing import Any

import httpx

from config import settings


class RenderAPIError(RuntimeError):
    pass


class RenderClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = settings.render_api_base
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RyhaveanDeployPanel/1.0",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", 45.0)
        async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
            response = await client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise RenderAPIError(f"Render API xətası ({response.status_code}): {response.text[:300]}")
        if not response.text.strip():
            return {}
        return response.json()

    async def list_workspaces(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/owners")
        if isinstance(data, list):
            return data
        return data.get("items", []) if isinstance(data, dict) else []

    async def resolve_workspace(self) -> dict[str, Any]:
        workspaces = await self.list_workspaces()
        if not workspaces:
            raise RenderAPIError("Bu API key üçün workspace tapılmadı")

        if settings.render_workspace_hint:
            needle = settings.render_workspace_hint.lower()
            for workspace in workspaces:
                hay = " ".join(
                    str(workspace.get(key, "")) for key in ("name", "id", "ownerEmail", "email")
                ).lower()
                if needle in hay:
                    return workspace

        return workspaces[0]

    async def list_services(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if owner_id:
            params["ownerId"] = owner_id
        data = await self._request("GET", "/services", params=params)
        if isinstance(data, list):
            return data
        return data.get("items", []) if isinstance(data, dict) else []

    async def get_service(self, service_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/services/{service_id}")

    async def list_deploys(self, service_id: str, limit: int = 5) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/services/{service_id}/deploys", params={"limit": limit})
        if isinstance(data, list):
            return data
        return data.get("items", []) if isinstance(data, dict) else []

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
