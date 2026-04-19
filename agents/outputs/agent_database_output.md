Read [](file:///Users/ceydanurakalin/Desktop/spiderEngineV2/docs/DATA_SCHEMA_V2.md#1-1), lines 1 to 200

Created [](file:///Users/ceydanurakalin/Desktop/spiderEngineV2/crawler/storage.py)

✅ Implemented storage.py with `DatabaseManager` singleton class.

- **Singleton Pattern**: Ensures one shared instance across threads using `__new__` and class variable.
- **Initialization**: Checks for existing DB; if not, creates all tables (`urls`, `documents`, `documents_fts`, `frontier`, `recovery_state`) and FTS5 triggers exactly per DATA_SCHEMA_V2.md.
- **Thread-Safety**: Uses `threading.Lock` for all DB operations to prevent race conditions.
- **upsert_frontier(urls_data)**: Batch inserts discovered URLs into `frontier` with SHA256 `url_hash`, `enqueued_at`, and `source_url_id`; uses `INSERT OR IGNORE` for deduplication.
- **get_crawl_batch(limit)**: Atomically selects up to `limit` pending URLs, updates them to `'in_progress'` with `last_heartbeat`, and returns `(url_id, url)` tuples.
- **complete_crawl(url_id, title, content, status_code)**: Inserts into `documents` and updates `urls` to `'fetched'` with `completed_at`; FTS5 index auto-updates via triggers.
- **get_stats()**: Returns dict with counts for `pending`, `in_progress`, `fetched`, `failed`, and `frontier` sizes.

Made changes.