import sqlite3
import threading
import hashlib
from datetime import datetime


class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)        
        self.conn.isolation_level = None  # Enable autocommit mode        
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-65536")  # 64MB
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self._create_tables_if_not_exist()
        self.recover_stale_urls()
        self._fix_fts5_table_if_needed()

    def _create_tables_if_not_exist(self):
        # Check if urls table exists
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='urls'")
        if not cursor.fetchone():
            # Create all tables
            self.conn.executescript("""
CREATE TABLE urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    url_hash TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    depth INTEGER DEFAULT 0,
    parent_url_id INTEGER,
    http_status INTEGER,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    last_heartbeat TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    content_hash TEXT,
    FOREIGN KEY (parent_url_id) REFERENCES urls(id)
);
CREATE INDEX idx_status ON urls(status);
CREATE INDEX idx_url_hash ON urls(url_hash);
CREATE INDEX idx_last_heartbeat ON urls(last_heartbeat);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id INTEGER NOT NULL UNIQUE,
    title TEXT,
    content TEXT NOT NULL,
    http_status INTEGER,
    crawled_at TIMESTAMP NOT NULL,
    parse_method TEXT DEFAULT 'html.parser',
    parse_errors TEXT,
    FOREIGN KEY (url_id) REFERENCES urls(id) ON DELETE CASCADE
);
CREATE INDEX idx_crawled_at ON documents(crawled_at);

CREATE VIRTUAL TABLE documents_fts USING fts5(
    title,
    content,
    url_id UNINDEXED,
    content=documents,
    content_rowid=id
);

CREATE TABLE frontier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL UNIQUE,
    enqueued_at TIMESTAMP NOT NULL,
    source_url_id INTEGER,
    FOREIGN KEY (source_url_id) REFERENCES urls(id)
);
CREATE INDEX idx_url_hash_frontier ON frontier(url_hash);

CREATE TABLE recovery_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    last_recovery_at TIMESTAMP,
    last_recovery_duration_ms INTEGER,
    urls_recovered INTEGER,
    documents_pending_index INTEGER,
    frontier_size INTEGER,
    notes TEXT
);

CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
  INSERT INTO documents_fts(rowid, title, content, url_id)
  VALUES (new.id, new.title, new.content, new.url_id);
END;

CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, content, url_id)
  VALUES('delete', old.id, old.title, old.content, old.url_id);
  INSERT INTO documents_fts(rowid, title, content, url_id)
  VALUES (new.id, new.title, new.content, new.url_id);
END;

CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, content, url_id)
  VALUES('delete', old.id, old.title, old.content, old.url_id);
END;
""")


    def recover_stale_urls(self):
        """Recover stale URLs from previous crashes by resetting in_progress to pending"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE urls SET status = 'pending', last_heartbeat = NULL, started_at = NULL WHERE status = 'in_progress'")
            recovered = cursor.rowcount
            if recovered > 0:
                print(f"Recovered {recovered} stale in_progress URLs to pending")

    def _fix_fts5_table_if_needed(self):
        """Fix FTS5 table if it was created with UNINDEXED columns (prevents search)"""
        with self._lock:
            try:
                # Try to get FTS5 table info
                cursor = self.conn.cursor()
                cursor.execute("PRAGMA table_info(documents_fts)")
                cols = cursor.fetchall()
                
                # Check if content column is indexed  
                # If the table exists and has the old schema, we need to rebuild it
                # This is a workaround: drop and recreate the FTS5 table with correct schema
                has_docs = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                
                if has_docs > 0:
                    # Rebuild FTS5 index from scratch
                    try:
                        print("Rebuilding FTS5 index...")
                        self.conn.execute("DROP TABLE IF EXISTS documents_fts")
                        
                        # Recreate with correct schema (title and content are INDEXED by default)
                        self.conn.execute("""
CREATE VIRTUAL TABLE documents_fts USING fts5(
    title,
    content,
    url_id UNINDEXED,
    content=documents,
    content_rowid=id
)""")
                        
                        # Re-populate FTS5 from documents table
                        self.conn.execute("""
INSERT INTO documents_fts(rowid, title, content, url_id)
SELECT id, title, content, url_id FROM documents""")
                        
                        print(f"FTS5 index rebuilt with {has_docs} documents")
                    except Exception as e:
                        print(f"Warning: Could not rebuild FTS5 index: {e}")
            except Exception as e:
                print(f"FTS5 diagnostic check: {e}")

    def upsert_frontier(self, urls_data):
        """urls_data: list of {'url': str, 'source_url_id': int}"""
        with self._lock:
            now = datetime.now().isoformat()
            data = []
            for item in urls_data:
                url = item['url']
                url_hash = hashlib.sha256(url.encode()).hexdigest()
                data.append((url, url_hash, now, item['source_url_id']))
            self.conn.executemany(
                "INSERT OR IGNORE INTO frontier (url, url_hash, enqueued_at, source_url_id) VALUES (?, ?, ?, ?)",
                data
            )

    def get_crawl_batch(self, limit):
        """Return list of (url_id, url) for pending URLs, mark them in_progress"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, url FROM urls WHERE status='pending' LIMIT ?",
                (limit,)
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                now = datetime.now().isoformat()
                placeholders = ','.join('?' * len(ids))
                self.conn.execute(
                    f"UPDATE urls SET status='in_progress', last_heartbeat=? WHERE id IN ({placeholders})",
                    [now] + ids
                )
            return rows

    def complete_crawl(self, url_id, title, content, status_code):
        """Insert document and update URL status to 'fetched'"""
        with self._lock:
            now = datetime.now().isoformat()
            self.conn.execute(
                "INSERT INTO documents (url_id, title, content, http_status, crawled_at) VALUES (?, ?, ?, ?, ?)",
                (url_id, title, content, status_code, now)
            )
            self.conn.execute(
                "UPDATE urls SET status='fetched', completed_at=?, http_status=? WHERE id=?",
                (now, status_code, url_id)
            )

    def get_stats(self):
        """Return dict with counts"""
        with self._lock:
            stats = {}
            stats['pending'] = self.conn.execute("SELECT COUNT(*) FROM urls WHERE status='pending'").fetchone()[0]
            stats['in_progress'] = self.conn.execute("SELECT COUNT(*) FROM urls WHERE status='in_progress'").fetchone()[0]
            stats['fetched'] = self.conn.execute("SELECT COUNT(*) FROM urls WHERE status='fetched'").fetchone()[0]
            stats['failed'] = self.conn.execute("SELECT COUNT(*) FROM urls WHERE status='failed'").fetchone()[0]
            stats['frontier'] = self.conn.execute("SELECT COUNT(*) FROM frontier").fetchone()[0]
            return stats

    def get_index_diagnostics(self):
        """Return diagnostic info about indexing status"""
        with self._lock:
            docs_total = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            docs_fts = self.conn.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
            docs_fetched = self.conn.execute(
                "SELECT COUNT(*) FROM documents d JOIN urls u ON d.url_id = u.id WHERE u.status='fetched'"
            ).fetchone()[0]
            return {
                'total_documents': docs_total,
                'fts5_indexed': docs_fts,
                'fetched_urls': docs_fetched
            }

    def add_url(self, url, parent_url_id=None, depth=0):
        """Add a URL to the database and frontier if it doesn't exist"""
        with self._lock:
            url_hash = hashlib.sha256(url.encode()).hexdigest()
            # Check if URL already exists
            existing = self.conn.execute(
                "SELECT id FROM urls WHERE url_hash = ?",
                (url_hash,)
            ).fetchone()

            if existing:
                return existing[0]  # Return existing ID

            # Insert new URL
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO urls (url, url_hash, depth, parent_url_id) VALUES (?, ?, ?, ?)",
                (url, url_hash, depth, parent_url_id)
            )
            url_id = cursor.lastrowid

            # Add to frontier
            now = datetime.now().isoformat()
            self.conn.execute(
                "INSERT OR IGNORE INTO frontier (url, url_hash, enqueued_at, source_url_id) VALUES (?, ?, ?, ?)",
                (url, url_hash, now, parent_url_id)
            )

            return url_id

    def process_frontier_batch(self, limit=10):
        """Move URLs from frontier to urls table for crawling"""
        with self._lock:
            # Get URLs from frontier that aren't already in urls
            rows = self.conn.execute("""
                SELECT f.url, f.source_url_id
                FROM frontier f
                LEFT JOIN urls u ON f.url_hash = u.url_hash
                WHERE u.id IS NULL
                LIMIT ?
            """, (limit,)).fetchall()

            if not rows:
                return 0

            # Insert into urls table
            for url, source_url_id in rows:
                url_hash = hashlib.sha256(url.encode()).hexdigest()
                # Get depth from parent if exists
                depth = 0
                if source_url_id:
                    parent_depth = self.conn.execute(
                        "SELECT depth FROM urls WHERE id = ?",
                        (source_url_id,)
                    ).fetchone()
                    if parent_depth:
                        depth = parent_depth[0] + 1

                self.conn.execute(
                    "INSERT OR IGNORE INTO urls (url, url_hash, depth, parent_url_id) VALUES (?, ?, ?, ?)",
                    (url, url_hash, depth, source_url_id)
                )

            # Remove processed URLs from frontier
            url_hashes = [hashlib.sha256(url.encode()).hexdigest() for url, _ in rows]
            placeholders = ','.join('?' * len(url_hashes))
            self.conn.execute(
                f"DELETE FROM frontier WHERE url_hash IN ({placeholders})",
                url_hashes
            )

            return len(rows)
