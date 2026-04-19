import threading
import queue
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import time
import ssl
from datetime import datetime
from .parser import DefensiveParser


class CrawlWorker(threading.Thread):
    def __init__(self, task_queue, db_path, timeout=10):
        super().__init__(daemon=True)
        self.task_queue = task_queue
        self.db_path = db_path
        self.timeout = timeout
        self.parser = DefensiveParser()

    def run(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-65536")  # 64MB
        conn.execute("PRAGMA temp_store=MEMORY")

        while True:
            try:
                item = self.task_queue.get(timeout=1)
                if item is None:  # Sentinel to stop
                    break
                url_id, url = item
                self.process_url(conn, url_id, url)
                self.task_queue.task_done()
            except queue.Empty:
                continue
        conn.close()

    def process_url(self, conn, url_id, url):
        # Mark as in_progress and set heartbeat
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE urls SET status='in_progress', last_heartbeat=?, started_at=? WHERE id=?",
            (now, now, url_id)
        )
        conn.commit()

        try:
            # Create SSL context that doesn't verify certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(url, headers={'User-Agent': 'SpiderEngine/2.0'})
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context) as response:
                content = response.read().decode('utf-8', errors='ignore')
                http_status = response.getcode()

                # Parse and extract links
                links = self.parser.extract_urls(content)
                absolute_links = [urllib.parse.urljoin(url, link) for link in links]

                # Insert new links into frontier
                for link in absolute_links:
                    url_hash = hashlib.sha256(link.encode()).hexdigest()
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO frontier (url, url_hash, enqueued_at, source_url_id) VALUES (?, ?, ?, ?)",
                            (link, url_hash, now, url_id)
                        )
                    except sqlite3.IntegrityError:
                        pass  # Already exists

                # Insert document
                title = self._extract_title(content)
                conn.execute(
                    "INSERT INTO documents (url_id, title, content, http_status, crawled_at, parse_method) VALUES (?, ?, ?, ?, ?, ?)",
                    (url_id, title, content, http_status, now, 'html.parser')  # Assuming parser succeeded
                )

                # Mark as fetched
                conn.execute(
                    "UPDATE urls SET status='fetched', completed_at=?, http_status=? WHERE id=?",
                    (now, http_status, url_id)
                )
                conn.commit()

        except urllib.error.HTTPError as e:
            self._handle_error(conn, url_id, f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            self._handle_error(conn, url_id, f"URL Error: {e.reason}")
        except Exception as e:
            self._handle_error(conn, url_id, f"Unexpected error: {str(e)}")

    def _handle_error(self, conn, url_id, error_msg):
        now = datetime.now().isoformat()
        # For simplicity, mark as failed; in full impl, check retry_count
        conn.execute(
            "UPDATE urls SET status='failed', error_message=?, completed_at=? WHERE id=?",
            (error_msg, now, url_id)
        )
        conn.commit()

    @staticmethod
    def _extract_title(content):
        # Simple title extraction; could be improved
        import re
        match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
        return match.group(1).strip() if match else ''
