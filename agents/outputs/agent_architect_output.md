Read [](file:///Users/ceydanurakalin/Desktop/spiderEngineV2/agents/agent_architect.md)

### Confirmation of Role and Constraints

As the Architect agent for the SpiderEngine V2 project, I have reviewed the role definition in `agent_architect.md`. To confirm my understanding:

- **Standard Library Requirement**: All implementation must rely exclusively on Python's standard library (e.g., modules like `sqlite3`, `queue`, `threading`, `urllib`, `http`, etc.). No external dependencies (e.g., third-party libraries like `requests`, `beautifulsoup`, or `scrapy`) are permitted. This constraint ensures portability, minimal installation overhead, and adherence to a self-contained, lightweight design suitable for environments where external packages cannot be installed.

- **Concurrent Search-while-Index Goal**: The system must support concurrent execution of web crawling/indexing operations alongside real-time search queries. Indexing should not block searches, and vice versa, to enable continuous usability. This requires thread-safe data structures and synchronization mechanisms to handle shared state (e.g., the search index) without race conditions or deadlocks.

I understand these constraints fully and will design the system accordingly. No external libraries will be used, and concurrency will prioritize thread safety and performance under load.

### Data Schema

To support 'Crawl Progress' (for resumability) and 'Search Index', we will use SQLite as the database due to its inclusion in Python's standard library (`sqlite3`). The schema is designed for efficiency, normalization to reduce redundancy, and support for concurrent access via SQLite's built-in locking mechanisms.

#### Tables Overview
- **urls**: Tracks crawl progress and metadata for each URL. Enables resumability by storing crawl state, timestamps, and error handling.
- **documents**: Stores crawled page content and metadata. Acts as the primary data source for indexing.
- **index_terms**: Implements an inverted index for search. Maps terms to document IDs for fast lookups.
- **index_positions**: Stores term positions within documents for advanced search features (e.g., phrase queries).

#### Detailed Schema
```sql
-- Table for crawl progress and resumability
CREATE TABLE urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,  -- Full URL
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'crawling', 'completed', 'failed'
    last_crawled TIMESTAMP,  -- Last crawl attempt timestamp
    retry_count INTEGER DEFAULT 0,  -- Number of retries on failure
    http_status INTEGER,  -- HTTP response code (e.g., 200, 404)
    content_hash TEXT,  -- Hash of content to detect changes
    depth INTEGER DEFAULT 0,  -- Crawl depth from seed URL
    parent_url_id INTEGER,  -- Foreign key to parent URL for hierarchy
    FOREIGN KEY (parent_url_id) REFERENCES urls(id)
);

-- Table for crawled documents
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id INTEGER NOT NULL,  -- Links to urls table
    title TEXT,  -- Page title
    content TEXT,  -- Full page text content
    crawled_at TIMESTAMP NOT NULL,  -- When crawled
    FOREIGN KEY (url_id) REFERENCES urls(id) ON DELETE CASCADE
);

-- Inverted index for search terms
CREATE TABLE index_terms (
    term TEXT NOT NULL,  -- Normalized term (e.g., lowercase, stemmed)
    document_id INTEGER NOT NULL,  -- Links to documents table
    frequency INTEGER NOT NULL,  -- Term frequency in document
    PRIMARY KEY (term, document_id),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Positions of terms in documents (for phrase search)
CREATE TABLE index_positions (
    term TEXT NOT NULL,
    document_id INTEGER NOT NULL,
    position INTEGER NOT NULL,  -- Word position in document
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (term, document_id) REFERENCES index_terms(term, document_id) ON DELETE CASCADE
);
```

**Technical Justification**:
- **Normalization**: Separating URLs, documents, and index data prevents data duplication (e.g., storing content only once per URL). Foreign keys ensure referential integrity, reducing errors in concurrent updates.
- **Resumability**: The `urls` table's `status` and `last_crawled` fields allow pausing/resuming crawls by querying incomplete URLs. `retry_count` and `http_status` handle transient failures (e.g., network timeouts) without infinite loops.
- **Search Efficiency**: The inverted index (`index_terms`) enables O(1) term lookups via hashing. `index_positions` supports proximity searches (e.g., "exact phrase") by storing offsets, improving relevance over simple frequency-based ranking.
- **Concurrency Support**: SQLite handles concurrent reads/writes via WAL (Write-Ahead Logging) mode, which we can enable. Reads (e.g., searches) can proceed during writes (e.g., indexing) without blocking, aligning with the concurrent goal.
- **Scalability**: Indexes on `term` and `document_id` ensure fast queries. For "Very Large" scales (e.g., millions of pages), periodic compaction (e.g., merging duplicate terms) can be added later, but the schema remains efficient.

### Concurrency & Back-Pressure

To achieve concurrent search-while-index, we use Python's `threading` module for multi-threading, with a bounded `queue.Queue` for producer-consumer patterns. Crawling threads produce URLs/pages, indexing threads consume and build the index, and search threads query concurrently.

#### Strategy Overview
- **Threading Model**: 
  - Crawler threads: Fetch URLs, parse content, enqueue for indexing.
  - Indexer threads: Dequeue crawled data, update SQLite index.
  - Search threads: Handle queries against the index without blocking crawlers/indexers.
- **Bounded Queue**: Use `queue.Queue(maxsize=N)` (e.g., N=1000) to limit in-memory buffering. Producers (crawlers) block on `put()` when full, applying back-pressure.
- **Synchronization**: `threading.Lock` for SQLite writes (to prevent corruption), but reads can be concurrent. Use `threading.Event` for graceful shutdown.
- **Back-Pressure Mechanism**: When the queue is full, crawlers pause fetching, preventing memory exhaustion. For "Very Large" scales (e.g., 10M+ pages), monitor queue size and dynamically adjust thread counts or add disk-based buffering if needed.
- **Crash Prevention**: Exceptions (e.g., network failures) are caught and logged; failed URLs are re-queued with exponential backoff. Resource limits (e.g., max threads via `threading.Semaphore`) prevent CPU overload. Heartbeat checks ensure threads don't hang.

**Technical Justification**:
- **Bounded Queue**: Limits memory usage to prevent OOM crashes. Back-pressure throttles producers, maintaining system stability under high load (e.g., rapid URL discovery).
- **Thread Safety**: `queue.Queue` is thread-safe; SQLite's locking ensures atomic index updates. Concurrent reads (searches) use read-only connections, avoiding write conflicts.
- **Scalability**: For large crawls, increase `maxsize` or add more indexer threads. Profiling (via `time` module) can identify bottlenecks (e.g., I/O vs. CPU).
- **Standard Library Compliance**: Relies on `threading` and `queue`, no externals needed.

### Product Requirements Document (PRD) for SpiderEngine V2

#### 1. Overview
SpiderEngine V2 is a concurrent web crawler and search engine built entirely with Python's standard library. It crawls websites, builds a searchable inverted index, and supports real-time queries during indexing. The system must handle "Very Large" scales (e.g., millions of pages) without crashing, prioritizing resumability and concurrency.

**Technical Justification**: Standard library ensures zero dependencies, reducing deployment complexity. Concurrency via threading maximizes CPU utilization on multi-core systems, while SQLite provides ACID-compliant persistence.

#### 2. Functional Requirements
- **Crawling**: Start from seed URLs, follow links up to a configurable depth, respect robots.txt (via `urllib.robotparser`), and handle rate limits (via `time.sleep`).
- **Indexing**: Extract text from HTML (using `html.parser`), normalize terms (lowercase, remove punctuation), and build inverted index.
- **Searching**: Support keyword queries with ranking (TF-IDF via `collections.Counter`), phrase searches, and pagination.
- **Resumability**: Persist crawl state; resume on restart.
- **Concurrency**: Index and search simultaneously; no blocking between operations.

**Technical Justification**: `html.parser` is lightweight and stdlib-native. TF-IDF uses built-in math for scoring without externals. Robots.txt compliance avoids legal issues and reduces load.

#### 3. Non-Functional Requirements
- **Performance**: Handle 1000+ pages/minute on modern hardware; search latency <1s.
- **Scalability**: Bounded queues prevent memory growth; support 10M+ documents via efficient indexing.
- **Reliability**: Retry failed crawls; graceful shutdown on signals (`signal` module).
- **Security**: No arbitrary code execution; validate URLs (`urllib.parse`).
- **Usability**: CLI interface for start/stop/search; log progress (`logging` module).

**Technical Justification**: Bounded queues and threading limits ensure stability. SQLite's indexing optimizes queries; retries use exponential backoff to handle transient errors.

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
- **Risk**: High memory on large crawls. **Mitigation**: Bounded queues; disk buffering if needed.
- **Risk**: Race conditions. **Mitigation**: Locks on writes; read-only connections for searches.
- **Risk**: Network failures. **Mitigation**: Retries with backoff; timeout via `urllib.request`.

This PRD provides a complete blueprint for implementation. Other agents can proceed to code based on these specifications.