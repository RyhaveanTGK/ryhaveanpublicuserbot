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

    @staticmethod
    def _clean_text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _walk_path(cls, payload: Any, path: tuple[str, ...]) -> Any:
        current = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _find_prefixed_strings(cls, payload: Any, prefixes: tuple[str, ...]) -> list[str]:
        found: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
                return
            if isinstance(value, (list, tuple, set)):
                for nested in value:
                    visit(nested)
                return
            if isinstance(value, str):
                text = value.strip()
                if text.startswith(prefixes):
                    found.append(text)

        visit(payload)
        return found

    @classmethod
    def _pick_prefixed_value(
        cls,
        payload: Any,
        prefixes: tuple[str, ...],
        *candidate_paths: tuple[str, ...],
    ) -> str:
        for path in candidate_paths:
            value = cls._walk_path(payload, path)
            if isinstance(value, str):
                text = value.strip()
                if text.startswith(prefixes):
                    return text
        recursive_hits = cls._find_prefixed_strings(payload, prefixes)
        return recursive_hits[0] if recursive_hits else ""

    @classmethod
    def _normalize_owner_record(cls, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = cls._pick_prefixed_value(
            payload,
            ("tea-",),
            ("id",),
            ("ownerId",),
            ("workspaceId",),
            ("workspace", "id"),
            ("owner", "id"),
            ("team", "id"),
            ("defaultWorkspace", "id"),
            ("defaultOwner", "id"),
        )
        user_id = cls._pick_prefixed_value(
            payload,
            ("own-",),
            ("id",),
            ("ownerId",),
            ("userId",),
            ("user", "id"),
            ("owner", "id"),
            ("workspaceOwner", "id"),
        )

        name = (
            cls._clean_text(payload.get("name"))
            or cls._clean_text(cls._walk_path(payload, ("workspace", "name")))
            or cls._clean_text(cls._walk_path(payload, ("owner", "name")))
            or cls._clean_text(cls._walk_path(payload, ("team", "name")))
        )
        email = (
            cls._clean_text(payload.get("email"))
            or cls._clean_text(payload.get("ownerEmail"))
            or cls._clean_text(cls._walk_path(payload, ("owner", "email")))
            or cls._clean_text(cls._walk_path(payload, ("workspace", "ownerEmail")))
        )
        owner_type = (
            cls._clean_text(payload.get("type"))
            or cls._clean_text(payload.get("ownerType"))
            or cls._clean_text(cls._walk_path(payload, ("workspace", "type")))
            or cls._clean_text(cls._walk_path(payload, ("owner", "type")))
        ).lower()

        return {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "name": name,
            "email": email,
            "type": owner_type,
            "raw": payload,
        }

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
            items = data.get("items") or data.get("data") or data.get("owners") or data.get("results") or []
            return [item for item in items if isinstance(item, dict)]
        return []

    async def get_owner(self, owner_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/owners/{owner_id}")

    async def _resolve_workspace_from_hint(self, owner_hint: str) -> str:
        hint = (owner_hint or "").strip()
        if not hint:
            return ""
        if hint.startswith("tea-"):
            return hint
        if not hint.startswith("own-"):
            return ""

        owner_payload = await self.get_owner(hint)
        if isinstance(owner_payload, dict):
            normalized = self._normalize_owner_record(owner_payload)
            if normalized["workspace_id"]:
                return normalized["workspace_id"]

        nested_workspace_ids = self._find_prefixed_strings(owner_payload, ("tea-",))
        return nested_workspace_ids[0] if nested_workspace_ids else ""

    async def resolve_owner_id(self, cached_owner_id: str | None = None) -> str:
        fallback_owner_id = (cached_owner_id or self._get_cached_owner_id()).strip()
        if fallback_owner_id.startswith("tea-"):
            fallback_workspace_id = fallback_owner_id
        else:
            fallback_workspace_id = ""
            if fallback_owner_id.startswith("own-"):
                try:
                    fallback_workspace_id = await self._resolve_workspace_from_hint(fallback_owner_id)
                except RenderAPIError:
                    fallback_workspace_id = ""

        try:
            owners = await self.list_owners()
        except RenderAPIError:
            if fallback_workspace_id:
                return self._set_cached_owner_id(fallback_workspace_id)
            if fallback_owner_id.startswith("tea-"):
                return self._set_cached_owner_id(fallback_owner_id)
            raise

        normalized_owners = [self._normalize_owner_record(owner) for owner in owners]

        if fallback_owner_id:
            for owner in normalized_owners:
                if fallback_owner_id in {
                    owner["workspace_id"],
                    owner["user_id"],
                }:
                    resolved = owner["workspace_id"] or fallback_workspace_id
                    if resolved:
                        return self._set_cached_owner_id(resolved)

        scored_owners: list[tuple[int, str]] = []
        for owner in normalized_owners:
            workspace_id = owner["workspace_id"]
            if not workspace_id:
                continue

            score = 10
            owner_type = owner["type"]
            if owner_type in {"workspace", "team", "organization"}:
                score += 4
            if owner_type in {"user", "personal", "owner"}:
                score += 3
            if owner["email"]:
                score += 2
            if owner["name"]:
                score += 1
            scored_owners.append((score, workspace_id))

        if scored_owners:
            scored_owners.sort(key=lambda item: item[0], reverse=True)
            return self._set_cached_owner_id(scored_owners[0][1])

        for owner in normalized_owners:
            user_id = owner["user_id"]
            if not user_id:
                continue
            try:
                workspace_id = await self._resolve_workspace_from_hint(user_id)
            except RenderAPIError:
                continue
            if workspace_id:
                return self._set_cached_owner_id(workspace_id)

        if fallback_workspace_id:
            return self._set_cached_owner_id(fallback_workspace_id)

        raise RenderAPIError("Render workspace ID tapılmadı")

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

    @staticmethod
    def _sanitize_env_vars(env_vars: list[dict[str, str]] | None) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in env_vars or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "") or "").strip()
            value = item.get("value")
            text = value.strip() if isinstance(value, str) else str(value).strip() if value is not None else ""
            if not key or not text or text.lower() == "none" or key in seen:
                continue
            cleaned.append({"key": key, "value": text})
            seen.add(key)
        return cleaned

    async def replace_env_vars(self, service_id: str, env_vars: list[dict[str, str]]) -> dict[str, Any]:
        return await self._request("PUT", f"/services/{service_id}/env-vars", json=self._sanitize_env_vars(env_vars))

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
                "envVars": self._sanitize_env_vars(env_vars),
            },
        }
        return await self._request("POST", "/services", json=payload, timeout=90.0)



def slugify_service_name(text: str, fallback: str) -> str:
    value = (text or "").strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:58] or fallback
