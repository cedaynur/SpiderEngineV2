### Product Requirements Document (PRD) for SpiderEngine V2

#### 1. Overview
SpiderEngine V2 is a concurrent web crawler and search engine built entirely with Python's standard library. It crawls websites, builds a searchable inverted index, and supports real-time queries during indexing. The system must handle "Very Large" scales (e.g., millions of pages) without crashing, prioritizing resumability and concurrency.

**Technical Justification**: Standard library ensures zero dependencies, reducing deployment complexity. Concurrency via threading maximizes CPU utilization on multi-core systems, while SQLite provides ACID-compliant persistence.

#### 2. Functional Requirements
- **Crawling**: Start from seed URLs, follow links up to a configurable depth, respect robots.txt (via `urllib.robotparser`), and handle rate limits (via `time.sleep`). Use defensive HTML parsing with fallback heuristics for malformed content.
- **Indexing**: Extract text and links from HTML using `html.parser` with regex-based fallbacks for malformed structures. Normalize terms (lowercase, remove punctuation), and build inverted index via SQLite FTS5 virtual table for optimized full-text search.
- **Searching**: Support keyword queries, phrase searches, and fuzzy matching via FTS5; ranking via BM25 (built into FTS5); pagination via LIMIT/OFFSET.
- **Resumability**: Persist crawl state with atomicity guarantees. Implement recovery pass at startup to reclaim in-flight work using state flags and heartbeat logic.
- **Concurrency**: Index and search simultaneously; no blocking between operations.

**Technical Justification**: Defensive parsing (`html.parser` + regex fallbacks) handles real-world malformed HTML better than `html.parser` alone, without external dependencies. SQLite FTS5 is part of the standard library (`sqlite3` module) and provides BM25 ranking and fast full-text search without the storage/latency penalty of storing individual term positions. FTS5 virtual tables avoid the exploding `index_positions` table problem. Recovery pass ensures no work is lost on crashes—key for "Very Large" scales where re-crawling lost URLs is expensive.

#### 3. Non-Functional Requirements
- **Performance**: Handle 1000+ pages/minute on modern hardware; search latency <100ms for FTS5 queries.
- **Scalability**: Bounded queues prevent memory growth; support 10M+ documents via SQLite FTS5 indexing; batch database writes to reduce lock contention.
- **Reliability**: Retry failed crawls with exponential backoff; graceful shutdown on signals (`signal` module). Recovery pass on startup ensures no in-flight work is lost.
- **Security**: No arbitrary code execution; validate URLs (`urllib.parse`); sanitize HTML parsing against malformed input.
- **Usability**: CLI interface for start/stop/search; log progress (`logging` module).

**Technical Justification**: FTS5 provides sub-100ms query latency on large corpora due to inverted index and prefix trees built into SQLite. Batched writes (e.g., 100-1000 rows per transaction) amortize lock overhead, reducing lock contention and improving write throughput from ~500 rows/sec (single write) to ~5000+ rows/sec (batched). WAL mode allows concurrent reads during batched writes. Recovery pass adds <1s overhead on startup but saves hours of re-crawling on crash recovery.

#### 4. Architecture
- **Components**:
  - **Crawler**: Threads fetching URLs, parsing HTML, enqueuing data.
  - **Indexer**: Threads updating SQLite index.
  - **Searcher**: Threads querying index.
  - **Queue Manager**: Bounded queue for data flow.
  - **Database**: SQLite for persistence.
- **Data Flow**: URLs → Crawl → Queue → Index → Search.
- **Concurrency Model**: Producer-consumer with locks for shared state.

**Technical Justification**: Threading allows parallelism without processes (simpler than `multiprocessing`). Queue decouples components, enabling back-pressure.

#### 5. Data Model
As detailed in the Data Schema section above. Justifications include normalization for integrity and inverted index for fast searches.

#### 6. Concurrency Model
As detailed in the Concurrency & Back-Pressure section. Justifications focus on thread safety and crash prevention via limits.

#### 7. Implementation Guidelines
- Use `sqlite3` with WAL mode for concurrency.
- Threads: 4 crawlers, 2 indexers, 1 searcher (configurable).
- Error Handling: Log to stderr; re-queue on failure.
- Testing: Unit tests for parsing/indexing; integration for full crawl.

**Technical Justification**: WAL allows reads during writes. Configurable threads adapt to hardware; logging uses stdlib for simplicity.

#### 8. Risks & Mitigations

**Risk 1: HTML Parsing Failures on Malformed Content**
- **Problem**: `html.parser` alone is fragile on real-world HTML with broken tags, encoding issues, or malformed nesting.
- **Mitigation**: 
  - Primary: Use `html.parser` for well-formed HTML; catches most valid cases.
  - Fallback 1: Regex-based extraction of links (`href=["']?(?P<url>[^"'\s>]+)`) when parser fails or produces empty results.
  - Fallback 2: Substring search for common patterns (e.g., `<a `, `<title>`) if regex misses content.
  - Logging: Log parse failures and which fallback was used for debugging; track success rates.
- **Technical Justification**: Layered approach ensures robustness without external dependencies. Regex and substring methods handle edge cases ("fuzzing" tests). Logging identifies systematic issues (e.g., specific site HTML patterns).

**Risk 2: Database Write Throughput Bottleneck**
- **Problem**: Single SQLite writer at high scales (10M+ URLs) becomes the bottleneck; naive writes (commit per insert) incur lock contention overhead (~500 rows/sec).
- **Mitigation**:
  - Batch writes: Accumulate 100–1000 documents in memory, then insert in a single transaction (reduces commits by 100–1000x).
  - WAL mode: Enable WAL (Write-Ahead Logging) to allow concurrent reads during writes; readers do not block writers.
  - Connection pooling: Maintain a write-lock monitor to queue pending writes and serialize them efficiently.
  - Profiles: Measure write latency; if still bottlenecked, switch to disk-based queue (SQLite journal) or pre-index in batch mode.
  - Backpressure: If queue fills faster than indexer can flush writes, crawler threads block on `queue.put()`, naturally throttling crawlers.
- **Technical Justification**: Batching reduces commit overhead from O(1000) to O(1) per 1000 rows, enabling 5000+ rows/sec on modern SQLite. WAL is designed for high concurrency; it separates reads from writes. Profiling data guides further optimization (e.g., sharding if needed).

**Risk 3: Search Index Latency (index_positions Explosion)**
- **Problem**: Storing every term position in a relational table causes storage explosion and slow phrase/ranking queries (e.g., millions of rows per term).
- **Mitigation**:
  - Use SQLite FTS5 (Full-Text Search module, built into `sqlite3`): FTS5 compresses posting lists and manages term positions internally, avoiding the relational storage penalty.
  - FTS5 table: `CREATE VIRTUAL TABLE documents_fts USING fts5(title, content, url_id)` replaces `index_terms` and `index_positions`.
  - Query: `SELECT * FROM documents_fts WHERE documents_fts MATCH 'exact "phrase"' ORDER BY rank`.
  - BM25 ranking: FTS5 supports BM25 algorithm for relevance without manual TF-IDF calculation (faster and more accurate).
  - Storage: FTS5 stores compressed inverted index; 10M documents = ~1-2GB (vs. 10-50GB with naive term position table).
- **Technical Justification**: FTS5 is purpose-built for full-text search; it is orders of magnitude faster than querying a huge positions table. Compression reduces I/O. BM25 is superior to TF-IDF for ranking without recomputing on each query. All built into `sqlite3`, no externals.

**Risk 4: Incomplete Resumability (Single Status Flag Insufficient)**
- **Problem**: A single `status` flag does not capture in-flight state; on crash, in-progress URLs may be lost, partial commits may corrupt consistency, and recovery is ambiguous.
- **Mitigation**:
  - Extended state model: Use state flags `pending`, `in_progress`, `fetched`, `indexed`, `failed`. Record timestamps for each transition.
  - Heartbeat logic: Crawlers update a `last_heartbeat` timestamp on each URL periodically (e.g., every 5 seconds). On startup, any `in_progress` URL with stale heartbeat is reverted to `pending`.
  - Transactional recovery: On startup, run recovery pass:
    1. SELECT all `in_progress` URLs; check heartbeats.
    2. Reset stale ones to `pending`.
    3. SELECT all `fetched` documents not yet indexed; re-queue for indexing.
    4. Verify SQLite database integrity via `PRAGMA integrity_check` (no overhead if WAL is healthy).
  - Frontier persistence: Store crawl frontier (URLs discovered but not yet crawled) in a `frontier` table, not just in memory; ensures no lost discoveries.
  - Atomic transitions: Each state change is wrapped in a transaction; crashes roll back partial writes via WAL.
- **Technical Justification**: Extended state model captures all possible work in-flight. Heartbeats handle stale `in_progress` without data corruption. Transactional semantics ensure no work is lost; WAL guarantees crash safety. Recovery pass is fast (seconds, not hours) because it's a simple scan; re-crawling would take days. Frontier table prevents redundant discovery crawls.

**Risk 5: High Memory on Very Large Crawls**
- **Problem**: Bounded queue is good, but if crawl frontier (all discovered URLs) is kept in memory, it can grow unbounded (10M URLs = ~500MB+ in memory).
- **Mitigation**: 
  - Frontier in DB: Store frontier in `urls` table with `status='pending'`; query frontier lazily (e.g., batch of 1000 URLs at a time).
  - Visited set optimization: Use hash of URL (SHA256) to check duplicates, not full URL string, reducing memory footprint.
  - Bloom filter optional: For additional speedup, maintain in-memory Bloom filter (~1-2MB for 10M URLs at 1% false positive rate) as a cache; always verify against DB.
- **Technical Justification**: Lazy frontier loading ensures memory scales with queue size, not total URL count. Hashing reduces memory; Bloom filter provides O(1) lookups without storing full URLs in memory. Database remains source of truth; Bloom filter is a performance cache, not critical path.

