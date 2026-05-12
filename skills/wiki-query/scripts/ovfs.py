from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests


class OVFSError(Exception):
    """Base exception for OpenViking filesystem adapter."""


class OVFSHTTPError(OVFSError):
    """Raised when the OpenViking HTTP API returns an error."""


@dataclass
class OVFSConfig:
    url: str
    api_key: Optional[str] = None
    account_id: Optional[str] = None
    user_id: Optional[str] = None
    profile: Optional[str] = None
    system_name: Optional[str] = None
    timeout: float = 30.0

    @classmethod
    def load(
        cls,
        config_path: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> "OVFSConfig":
        from common import load_config

        config = load_config(config_path=config_path, profile=profile)
        url = str(config.get("openviking_url", "http://localhost:1933"))
        api_key = config.get("openviking_api_key") or None
        account_id = config.get("openviking_account_id") or None
        user_id = config.get("openviking_user_id") or None
        profile_name = config.get("profile") or None
        system_name = config.get("system_name") or None

        try:
            timeout_value = float(config.get("openviking_timeout", 30.0))
        except (TypeError, ValueError) as exc:
            raise OVFSError(
                f"Invalid timeout value: {config.get('openviking_timeout')}"
            ) from exc

        return cls(
            url=url.rstrip("/"),
            api_key=api_key,
            account_id=account_id,
            user_id=user_id,
            profile=profile_name,
            system_name=system_name,
            timeout=timeout_value,
        )


class OVFSClient:
    """
    Thin HTTP adapter for OpenViking filesystem/content APIs.

    Strategy:
    - read/list/stat/tree/mkdir use HTTP fs/content APIs
    - file creation/update uses a compatibility fallback chain
    """

    def __init__(self, config: Optional[OVFSConfig] = None):
        self.config = config or OVFSConfig.load()
        self.session = requests.Session()
        # 本地 OpenViking 常见场景会设置系统代理，
        # 为避免 127.0.0.1/localhost 请求被错误转发，这里对本地地址禁用环境代理。
        if self.config.url.startswith("http://127.0.0.1") or self.config.url.startswith("http://localhost"):
            self.session.trust_env = False
        self.session.headers.update({"Accept": "application/json"})
        if self.config.api_key:
            self.session.headers["X-API-Key"] = self.config.api_key
        if self.config.account_id:
            self.session.headers["X-OpenViking-Account"] = self.config.account_id
        if self.config.user_id:
            self.session.headers["X-OpenViking-User"] = self.config.user_id

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "OVFSClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ----------------------------
    # low-level HTTP helpers
    # ----------------------------
    def _url(self, path: str) -> str:
        return f"{self.config.url}{path}"

    def _handle_response(self, response: requests.Response) -> Any:
        try:
            payload = response.json()
        except Exception as exc:
            text = response.text[:500]
            raise OVFSHTTPError(
                f"Invalid JSON response [{response.status_code}]: {text}"
            ) from exc

        if response.status_code >= 400:
            raise OVFSHTTPError(
                f"HTTP {response.status_code}: {json.dumps(payload, ensure_ascii=False)}"
            )

        status = payload.get("status")
        if status not in (None, "ok"):
            raise OVFSHTTPError(
                f"OpenViking API returned non-ok status: "
                f"{json.dumps(payload, ensure_ascii=False)}"
            )

        return payload.get("result")

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = self.session.get(
            self._url(path),
            params=params,
            timeout=self.config.timeout,
        )
        return self._handle_response(response)

    def _post(self, path: str, body: Dict[str, Any]) -> Any:
        response = self.session.post(
            self._url(path),
            json=body,
            timeout=self.config.timeout,
        )
        return self._handle_response(response)

    def _post_multipart(
        self,
        path: str,
        files: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        response = self.session.post(
            self._url(path),
            files=files,
            data=data,
            timeout=self.config.timeout,
        )
        return self._handle_response(response)

    def _content_write_mode(
        self,
        uri: str,
        content: str,
        mode: str,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "uri": uri,
            "content": content,
            "mode": mode,
            "wait": wait,
        }
        if timeout is not None:
            body["timeout"] = timeout
        return self._post("/api/v1/content/write", body)

    # ----------------------------
    # WebDAV helpers
    # ----------------------------
    def _webdav_url(self, uri: str) -> str:
        """
        Convert a Viking resource URI to the WebDAV endpoint path.

        Example:
        viking://resources/my-kb/wiki/index.md
        -> {base}/webdav/resources/my-kb/wiki/index.md
        """
        prefix = "viking://resources/"
        if not uri.startswith(prefix):
            raise OVFSError(f"WebDAV currently supports resources only: {uri}")

        rel = uri[len(prefix):]
        rel_escaped = "/".join(quote(part) for part in rel.split("/"))
        return f"{self.config.url}/webdav/resources/{rel_escaped}"

    def webdav_mkcol(self, uri: str) -> Dict[str, Any]:
        if not uri.endswith("/"):
            raise ValueError(f"Directory URI must end with '/': {uri}")

        response = self.session.request(
            "MKCOL",
            self._webdav_url(uri),
            timeout=self.config.timeout,
        )

        if response.status_code in (200, 201, 204, 405):
            return {"uri": uri}

        raise OVFSHTTPError(
            f"WebDAV MKCOL failed [{response.status_code}]: {response.text[:500]}"
        )

    def webdav_put_text(self, uri: str, content: str) -> Dict[str, Any]:
        response = self.session.put(
            self._webdav_url(uri),
            data=content.encode("utf-8"),
            headers={"Content-Type": "text/markdown; charset=utf-8"},
            timeout=self.config.timeout,
        )

        if response.status_code in (200, 201, 204):
            return {"uri": uri, "written_bytes": len(content.encode("utf-8"))}

        raise OVFSHTTPError(
            f"WebDAV PUT failed [{response.status_code}]: {response.text[:500]}"
        )

    # ----------------------------
    # public API
    # ----------------------------
    def health(self) -> Dict[str, Any]:
        response = self.session.get(
            self._url("/health"),
            timeout=self.config.timeout,
        )
        try:
            payload = response.json()
        except Exception as exc:
            raise OVFSHTTPError(
                f"Invalid health response [{response.status_code}]: {response.text[:300]}"
            ) from exc

        if response.status_code >= 400:
            raise OVFSHTTPError(
                f"Health check failed [{response.status_code}]: "
                f"{json.dumps(payload, ensure_ascii=False)}"
            )
        return payload

    def stat(self, uri: str) -> Dict[str, Any]:
        return self._get("/api/v1/fs/stat", params={"uri": uri})

    def exists(self, uri: str) -> bool:
        try:
            self.stat(uri)
            return True
        except OVFSHTTPError as exc:
            msg = str(exc).lower()
            if "404" in msg or "not found" in msg:
                return False
            raise

    def ls(
        self,
        uri: str,
        simple: bool = False,
        recursive: bool = False,
    ) -> List[Dict[str, Any]]:
        result = self._get(
            "/api/v1/fs/ls",
            params={
                "uri": uri,
                "simple": str(simple).lower(),
                "recursive": str(recursive).lower(),
            },
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return result["items"]
        raise OVFSError(f"Unexpected ls() result type for {uri}: {type(result)}")

    def tree(
        self,
        uri: str,
        level_limit: int = 3,
    ) -> Any:
        return self._get(
            "/api/v1/fs/tree",
            params={
                "uri": uri,
                "level_limit": level_limit,
            },
        )

    def mkdir(self, uri: str, description: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"uri": uri}
        if description:
            body["description"] = description

        try:
            return self._post("/api/v1/fs/mkdir", body)
        except OVFSHTTPError:
            return self.webdav_mkcol(uri)

    def temp_upload(self, file_path: str) -> str:
        local_file = Path(file_path)
        if not local_file.exists() or not local_file.is_file():
            raise OVFSError(f"Local file not found: {file_path}")

        with local_file.open("rb") as fp:
            result = self._post_multipart(
                "/api/v1/resources/temp_upload",
                files={
                    "file": (
                        local_file.name,
                        fp,
                        "application/octet-stream",
                    )
                },
            )

        if not isinstance(result, dict):
            raise OVFSError(f"Unexpected temp_upload() result type: {type(result)}")

        temp_file_id = result.get("temp_file_id")
        if not isinstance(temp_file_id, str) or not temp_file_id:
            raise OVFSError(f"Missing temp_file_id in temp_upload() result: {result}")

        return temp_file_id

    def add_resource(
        self,
        path: Optional[str] = None,
        temp_file_id: Optional[str] = None,
        to: Optional[str] = None,
        parent: Optional[str] = None,
        reason: str = "",
        instruction: str = "",
        wait: bool = False,
        timeout: Optional[float] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        if bool(path) == bool(temp_file_id):
            raise ValueError("Exactly one of path or temp_file_id must be provided")

        body: Dict[str, Any] = {
            "reason": reason,
            "instruction": instruction,
            "wait": wait,
            "strict": strict,
        }
        if path:
            body["path"] = path
        if temp_file_id:
            body["temp_file_id"] = temp_file_id
        if to:
            body["to"] = to
        if parent:
            body["parent"] = parent
        if timeout is not None:
            body["timeout"] = timeout

        return self._post("/api/v1/resources", body)

    def add_local_resource(
        self,
        file_path: str,
        to: str,
        reason: str = "",
        instruction: str = "",
        wait: bool = False,
        timeout: Optional[float] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        temp_file_id = self.temp_upload(file_path)
        return self.add_resource(
            temp_file_id=temp_file_id,
            to=to,
            reason=reason,
            instruction=instruction,
            wait=wait,
            timeout=timeout,
            strict=strict,
        )

    def read_text(self, uri: str, offset: int = 0, limit: int = -1) -> str:
        result = self._get(
            "/api/v1/content/read",
            params={
                "uri": uri,
                "offset": offset,
                "limit": limit,
            },
        )

        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "content" in result and isinstance(result["content"], str):
                return result["content"]
            if "text" in result and isinstance(result["text"], str):
                return result["text"]

        raise OVFSError(f"Expected text content for {uri}, got: {type(result)}")

    def _create_text_via_resource_api(
        self,
        uri: str,
        content: str,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        basename = PurePosixPath(uri).name or f"unnamed{Path(uri).suffix or '.md'}"
        upload_to = _resolve_upload_target_for_create(uri)
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, basename)
            with open(local_path, "w", encoding="utf-8") as tmp:
                tmp.write(content)
            return self.add_local_resource(
                file_path=local_path,
                to=upload_to,
                wait=False,
                timeout=None,
                strict=True,
            )

    def write_text(
        self,
        uri: str,
        content: str,
        create: bool = False,
        append: bool = False,
        wait: bool = True,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compatibility chain:

        create=True:
          1. content/write mode=create
          2. content/write mode=replace
          3. WebDAV PUT

        append=True:
          1. content/write mode=append

        default replace:
          1. content/write mode=replace
          2. WebDAV PUT
        """
        if create and append:
            raise ValueError("create and append cannot both be True")

        if append:
            return self._content_write_mode(
                uri=uri,
                content=content,
                mode="append",
                wait=wait,
                timeout=timeout,
            )

        errors: List[str] = []

        if create:
            try:
                return self._content_write_mode(
                    uri=uri,
                    content=content,
                    mode="create",
                    wait=wait,
                    timeout=timeout,
                )
            except OVFSHTTPError as exc:
                errors.append(f"create failed: {exc}")

            try:
                return self._content_write_mode(
                    uri=uri,
                    content=content,
                    mode="replace",
                    wait=wait,
                    timeout=timeout,
                )
            except OVFSHTTPError as exc:
                errors.append(f"replace-after-create failed: {exc}")

            try:
                return self._create_text_via_resource_api(
                    uri=uri,
                    content=content,
                    wait=wait,
                    timeout=timeout,
                )
            except OVFSHTTPError as exc:
                errors.append(f"resource-create failed: {exc}")
            except OVFSError as exc:
                errors.append(f"resource-create failed: {exc}")

            try:
                return self.webdav_put_text(uri, content)
            except OVFSHTTPError as exc:
                errors.append(f"webdav-put-after-create failed: {exc}")

            raise OVFSHTTPError(" | ".join(errors))

        try:
            return self._content_write_mode(
                uri=uri,
                content=content,
                mode="replace",
                wait=wait,
                timeout=timeout,
            )
        except OVFSHTTPError as exc:
            errors.append(f"replace failed: {exc}")

        try:
            return self.webdav_put_text(uri, content)
        except OVFSHTTPError as exc:
            errors.append(f"webdav-put-after-replace failed: {exc}")

        raise OVFSHTTPError(" | ".join(errors))


def _resolve_upload_target_for_create(uri: str) -> str:
    basename = PurePosixPath(uri).name
    normalized = uri.rstrip("/")
    parent_uri = normalized.rsplit("/", 1)[0] + "/"
    if PurePosixPath(parent_uri.rstrip("/")).name == basename:
        return parent_uri
    return uri


def ensure_dir(client: OVFSClient, uri: str, description: Optional[str] = None) -> None:
    if not uri.endswith("/"):
        raise ValueError(f"Directory URI must end with '/': {uri}")

    if client.exists(uri):
        return

    client.mkdir(uri, description=description)


def ensure_text_file(
    client: OVFSClient,
    uri: str,
    content: str,
) -> None:
    if client.exists(uri):
        return
    client.write_text(uri, content, create=True, wait=True)


if __name__ == "__main__":
    with OVFSClient() as client:
        print(json.dumps(client.health(), ensure_ascii=False, indent=2))
