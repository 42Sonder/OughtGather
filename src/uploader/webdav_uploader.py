"""WebDAV 上传器模块。"""

from __future__ import annotations

import os
import uuid
from typing import Optional
from urllib.parse import quote

import httpx  # type: ignore[reportMissingImports]

from src.config import get_webdav_config
from src.utils.logger import get_logger


DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Zotero/8.0) AList"


class WebDavUploader:
    """将 EPUB 上传到 WebDAV。

    CSTCloud 的 WebDAV 接口只接受以 ``.zip`` 或 ``.prop`` 结尾的 PUT，
    而 EPUB 本身是 ZIP 容器。因此先以临时 ``.zip`` 文件名上传，再用
    WebDAV MOVE 改回 ``.epub``，文件内容不会被重新压缩。
    """

    MAX_ATTEMPTS = 3
    CONTROL_TIMEOUT_SECONDS = 30.0
    UPLOAD_WRITE_TIMEOUT_SECONDS = 300.0

    def __init__(self):
        self.logger = get_logger()
        self.config = get_webdav_config()

    def _auth(self) -> tuple[str, str]:
        """返回已验证的 WebDAV 凭据。"""
        if not self.config or not self.config.username or not self.config.password:
            raise ValueError("WebDAV credentials are not configured")
        return self.config.username, self.config.password

    def _remote_url(self, filename: str) -> str:
        """构造经过 URL 编码的远端文件 URL。"""
        if not self.config or not self.config.url:
            raise ValueError("WebDAV URL is not configured")

        base_url = self.config.url.rstrip("/")
        remote_path = (self.config.remote_path or "").strip("/")
        encoded_filename = quote(filename, safe="")
        if remote_path:
            return f"{base_url}/{quote(remote_path, safe='/')}/{encoded_filename}"
        return f"{base_url}/{encoded_filename}"

    def _remote_directory_url(self) -> Optional[str]:
        """返回远程目录 URL；根目录上传时返回 None。"""
        if not self.config or not self.config.url:
            raise ValueError("WebDAV URL is not configured")
        remote_path = (self.config.remote_path or "").strip("/")
        if not remote_path:
            return None
        return f"{self.config.url.rstrip('/')}/{quote(remote_path, safe='/')}"

    def _ensure_remote_directory(self, user_agent: str) -> None:
        """确保目标目录存在；目录已存在时 WebDAV 通常返回 405。"""
        directory_url = self._remote_directory_url()
        if not directory_url:
            return

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = httpx.request(
                    "MKCOL",
                    directory_url,
                    auth=self._auth(),
                    headers={"User-Agent": user_agent},
                    timeout=30.0,
                )
                if response.status_code in (201, 405):
                    return
                response.raise_for_status()
                return
            except (httpx.HTTPError, OSError) as error:
                if attempt == self.MAX_ATTEMPTS:
                    raise
                self.logger.warning(
                    f"WebDAV MKCOL 请求失败，将重试 ({attempt}/{self.MAX_ATTEMPTS}): {error}"
                )

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: Optional[bytes] = None,
    ) -> httpx.Response:
        """发送 WebDAV 请求并在网络错误/HTTP 错误时有限重试。"""
        if not self.config:
            raise ValueError("WebDAV configuration is unavailable")

        last_error: Optional[Exception] = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                is_upload = method.upper() == "PUT"
                timeout = httpx.Timeout(
                    self.UPLOAD_WRITE_TIMEOUT_SECONDS
                    if is_upload
                    else self.CONTROL_TIMEOUT_SECONDS,
                    connect=self.CONTROL_TIMEOUT_SECONDS,
                    read=self.CONTROL_TIMEOUT_SECONDS,
                    write=(
                        self.UPLOAD_WRITE_TIMEOUT_SECONDS
                        if is_upload
                        else self.CONTROL_TIMEOUT_SECONDS
                    ),
                    pool=self.CONTROL_TIMEOUT_SECONDS,
                )
                response = httpx.request(
                    method,
                    url,
                    content=content,
                    auth=self._auth(),
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, OSError) as error:
                last_error = error
                if attempt < self.MAX_ATTEMPTS:
                    self.logger.warning(
                        f"WebDAV {method} 请求失败，将重试 ({attempt}/{self.MAX_ATTEMPTS}): {error}"
                    )

        assert last_error is not None
        raise last_error

    def _delete_quietly(self, url: str, user_agent: str) -> None:
        """尽力删除失败上传留下的临时文件。"""
        if not self.config:
            return
        try:
            response = httpx.request(
                "DELETE",
                url,
                auth=self._auth(),
                headers={"User-Agent": user_agent},
                timeout=30.0,
            )
            response.raise_for_status()
        except Exception as error:  # 清理失败不能覆盖原始上传错误
            self.logger.warning(f"清理 WebDAV 临时文件失败: {error}")

    def upload_epub(self, epub_path: str) -> bool:
        """上传 EPUB 文件，成功返回 True。"""
        if not self.config or not self.config.enabled:
            self.logger.info("WebDAV is not enabled, skip pushing.")
            return False

        if not os.path.exists(epub_path):
            self.logger.error(f"EPUB file not found: {epub_path}")
            return False

        filename = os.path.basename(epub_path)
        destination_url = self._remote_url(filename)
        temporary_name = f".{filename}.{uuid.uuid4().hex}.upload.zip"
        temporary_url = self._remote_url(temporary_name)
        user_agent = self.config.user_agent or DEFAULT_USER_AGENT
        headers = {"User-Agent": user_agent}

        try:
            with open(epub_path, "rb") as file:
                content = file.read()

            self.logger.info(f"Uploading EPUB to {destination_url}...")
            self._ensure_remote_directory(user_agent)
            self._request_with_retry(
                "PUT",
                temporary_url,
                headers=headers,
                content=content,
            )
            self._request_with_retry(
                "MOVE",
                temporary_url,
                headers={
                    "User-Agent": user_agent,
                    "Destination": destination_url,
                    "Overwrite": "T",
                },
            )
            self.logger.info("EPUB uploaded successfully to WebDAV")
            return True
        except Exception as error:
            self.logger.error(f"Failed to upload EPUB to WebDAV: {error}")
            self._delete_quietly(temporary_url, user_agent)
            return False
