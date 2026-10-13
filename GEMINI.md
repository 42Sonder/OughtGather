# Ought Gather — Developer Guide (GEMINI.md)

This guide provides compact developer instructions, architecture decisions, and strict compliance guidelines for working on the Ought Gather codebase.

## Common Commands

- **Install**: `pip install -r requirements.txt`
- **Run**: `python3.11 src/main.py [--config path/to/config.json]`
- **Test**: `python3.11 -m pytest tests/` (runs tests with coverage reporting enabled automatically; use `-v` for detail, `--tb=short` for brief failures)

## Tooling & Automation

- **Config Editor**: Open `config-editor.html` in browser for a visual configuration builder.
- **GitHub Actions**: Runs daily at UTC 00:00 (08:00 Beijing time). Explicitly sets `TZ=Asia/Shanghai`. Automatically uploads logs and EPUB artifacts.

## Architecture & Core Rules

- **Flow**: `config.json` → `Fetchers` → `Processors` → `Dedup` → `EPUB Generator` → optional `SMTP Sender` & `WebDAV Uploader`
- **Timezone**: All timestamping and datetime calculations must use Beijing Time (UTC+8) via `src/utils/helpers.py:get_now()`.
- **Fetchers (`src/fetchers/`)**:
  - `MailFetcher`: Uses testmail.app API. `src` supports `"namespace"` or `"namespace.tag"` (dot-split). `metadata` enables tags, limits, and date range filters.
  - `RSSFetcher`: feedparser. Supports `metadata.full_text=Y/N` for full article retrieval via trafilatura.
  - `WebFetcher`: Trafilatura with BeautifulSoup fallback.
  - `TrendingFetcher`: LLM generation via OpenRouter API.
  - **Plugin Architecture Mandate (插件化规范)**:
    - **Pluggable Registration**: All fetchers must be implemented as plugs under `src/fetchers/` and inherit from `BaseFetcher`. They register automatically via `__init_subclass__` and are resolved dynamically via `get_fetcher_class(source.type)`.
    - **No Hardcoded References**: Do not add specialized, hardcoded, or conditional code for specific fetchers outside of the `src/fetchers/` directory (e.g., inside `src/config.py`, `src/epub/toc.py`, or `src/epub/generator.py`).
    - **Decoupled Settings**: Keep fetcher-specific config validation and defaults inside the fetcher class or use generic hooks. Do not add fetcher-specific top-level properties to `ContentSource`. Use `metadata` for any extra parameters.
    - **Decoupled Formatting/Styling**: Any specific title formatting, custom CSS classes (e.g., `.weather-item`), or custom layout requirements must be abstracted/encapsulated within the fetcher or handled via generic extensible hooks.
- **Processors (`src/processors/`)**:
  - `content_processor`: Applies `keep_link`, `exclude`, and `delete` rules.
  - `image_processor`: Downloads/compresses images (≤250KB, max 640×960, JPEG Q75). Filters out small decorative assets (< 120×120).
- **Dedup Tracker (`src/dedup/tracker.py`)**: File-based tracker (`data/fetched_urls.txt`) storing URL/title hashes. Automatically prunes old records when exceeding `MAX_RECORDS = 50000`. GitHub Actions CI automatically persists this file using `actions/cache` to avoid committing logs to the repository history.
- EPUB Generator (`src/epub/`):
  - Cover: Custom (`title.img`) or Bing Daily wallpaper with text/date overlays.
  - TOC: Flat layout (source → articles).
  - Emoji Support: Automatically identifies emojis, renders them as black-and-white PNG images using `NotoEmoji-Medium.ttf`, and embeds them into the EPUB to ensure consistent display on Kindle without font dependency.
  - Compliance: Standard `FOLDER_NAME='EPUB'` must be used (avoids OCF RSC-026). OPF version must be `3.0`. EPUB 3.0 requires both EpubNcx and EpubNav items (avoids RSC-005). XHTML covers must not be empty. Escape f-string CSS curly braces as `{{}}`. EPUBCheck validates against EPUB 3.3 rules (`java -jar epubcheck.jar <file.epub>`).

- **Uploader (`src/uploader/`)**:
  - `WebDavUploader`: Uploads generated EPUBs to WebDAV endpoints if configured (`WEBDAV_ENABLED`=true).

## Configuration

Required credentials for the GitHub Actions WebDAV flow (environment or GitHub Secrets): `WEBDAV_USERNAME`, `WEBDAV_PASSWORD`.
The default workflow targets CSTCloud at `https://data.cstcloud.cn/dav/RSS` and sends `User-Agent: Mozilla/5.0 (compatible; Zotero/8.0) AList`.
Optional variables: `CONFIG_JSON` (overrides file), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `KINDLE_EMAIL`, `TESTMAIL_APP_API_KEY`, `OPENROUTER_API_KEY`, `OPENROUTER_API_ENDPOINT`, `WEBDAV_ENABLED`, `WEBDAV_URL`, `WEBDAV_USER_AGENT`, `WEBDAV_REMOTE_PATH`.

### config.json Schema
```json
{
  "title": {
    "text": "{Daily News {time}}", // supports {time} and </br> placeholders
    "img": "" // Custom cover image URL, fallback to Bing daily image if empty
  },
  "load_images": "Y|N", // Global image toggle
  "body": [
    {
      "type": "rss|mail|web|trending|raindropio",
      "src": "URL, namespace[.tag], or keyword query",
      "priority": 10, // Higher priority items appear earlier in book (stable sorted)
      "load_images": "Y|N", // Per-source image toggle
      "keep_link": "Y|N",
      "metadata": {} // Fetcher-specific options (e.g. metadata.full_text for RSS)
      "exclude": [{"type": "start|end|exact", "value": "keyword"}],
      "delete": "keyword1,keyword2",
      "metadata": {} // Fetcher-specific options
    }
  ]
}
```
