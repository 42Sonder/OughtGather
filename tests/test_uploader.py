from unittest.mock import MagicMock, patch

from src.config import WebDavConfig
from src.uploader.webdav_uploader import WebDavUploader


@patch("src.uploader.webdav_uploader.get_webdav_config")
@patch("src.uploader.webdav_uploader.httpx.request")
def test_webdav_uploader_cstcloud_upload(mock_request, mock_get_config, tmp_path):
    mock_get_config.return_value = WebDavConfig(
        enabled=True,
        url="https://data.cstcloud.cn/dav",
        username="user",
        password="password",
        remote_path="RSS",
    )
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    epub_path = tmp_path / "每日新闻.epub"
    epub_path.write_bytes(b"epub-content")

    uploader = WebDavUploader()
    assert uploader.upload_epub(str(epub_path)) is True

    assert mock_request.call_count == 3
    mkcol_call, put_call, move_call = mock_request.call_args_list

    assert mkcol_call.args[0] == "MKCOL"
    assert mkcol_call.args[1] == "https://data.cstcloud.cn/dav/RSS"
    assert mkcol_call.kwargs["headers"]["User-Agent"] == (
        "Mozilla/5.0 (compatible; Zotero/8.0) AList"
    )

    assert put_call.args[0] == "PUT"
    assert put_call.args[1].startswith(
        "https://data.cstcloud.cn/dav/RSS/."
    )
    assert put_call.args[1].endswith(".upload.zip")
    assert put_call.kwargs["content"] == b"epub-content"
    assert put_call.kwargs["headers"]["User-Agent"] == (
        "Mozilla/5.0 (compatible; Zotero/8.0) AList"
    )

    assert move_call.args[0] == "MOVE"
    assert move_call.kwargs["headers"]["User-Agent"] == (
        "Mozilla/5.0 (compatible; Zotero/8.0) AList"
    )
    assert move_call.kwargs["headers"]["Overwrite"] == "T"
    assert move_call.kwargs["headers"]["Destination"].endswith(
        "/RSS/%E6%AF%8F%E6%97%A5%E6%96%B0%E9%97%BB.epub"
    )


@patch("src.uploader.webdav_uploader.get_webdav_config")
def test_webdav_uploader_disabled(mock_get_config):
    mock_get_config.return_value = WebDavConfig(enabled=False)
    uploader = WebDavUploader()
    uploader.logger = MagicMock()
    result = uploader.upload_epub("test.epub")
    assert result is False
    uploader.logger.info.assert_called_once_with("WebDAV is not enabled, skip pushing.")
