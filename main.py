import threading
import time
import queue
from crawler.storage import DatabaseManager
from crawler.search import SearchEngine
from crawler.worker import CrawlWorker
from crawler.web import WebServer


class SpiderEngineCoordinator:
    def __init__(self, db_path='spiderengine.db', num_workers=4, port=8080):
        self.db_path = db_path
        self.num_workers = num_workers
        self.port = port

        # Initialize components
        self.db_manager = DatabaseManager(db_path)
        self.search_engine = SearchEngine(db_path)

        # Create task queue and workers
        self.task_queue = queue.Queue()
        self.workers = []
        self._start_workers()

        # Start frontier processor
        self.frontier_thread = threading.Thread(target=self._process_frontier_loop, daemon=True)
        self.frontier_thread.start()

        # Web server
        self.web_server = WebServer(
            db_manager=self.db_manager,
            search_engine=self.search_engine,
            index_callback=self._index_callback,
            port=port
        )

    def _start_workers(self):
        """Start crawl worker threads"""
        for i in range(self.num_workers):
            worker = CrawlWorker(self.task_queue, self.db_path)
            worker.start()
            self.workers.append(worker)

    def _process_frontier_loop(self):
        """Continuously process frontier and feed URLs to workers"""
        while True:
            try:
                # Process some URLs from frontier to urls table
                processed = self.db_manager.process_frontier_batch(limit=50)
                if processed > 0:
                    print(f"Processed {processed} URLs from frontier")

                # Get batch of pending URLs and add to task queue
                batch = self.db_manager.get_crawl_batch(limit=10)
                for url_id, url in batch:
                    self.task_queue.put((url_id, url))

                # Sleep a bit to avoid busy waiting
                time.sleep(1)
            except Exception as e:
                print(f"Error in frontier processing: {e}")
                time.sleep(5)

    def _index_callback(self, url):
        """Callback for when user submits a URL to index"""
        try:
            url_id = self.db_manager.add_url(url)
            print(f"Added URL to crawl queue: {url} (ID: {url_id})")
        except Exception as e:
            print(f"Error adding URL {url}: {e}")
            raise

    def start(self):
        """Start the web server (blocking)"""
        print("SpiderEngine V2 starting...")
        print(f"Database: {self.db_path}")
        print(f"Workers: {self.num_workers}")
        print(f"Web server port: {self.port}")
        print(f"Open http://localhost:{self.port} in your browser")
        print("Press Ctrl+C to stop")

        try:
            self.web_server.start()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self._shutdown()

    def _shutdown(self):
        """Clean shutdown"""
        # Stop workers
        for _ in self.workers:
            self.task_queue.put(None)  # Sentinel value

        # Wait for workers to finish
        for worker in self.workers:
            worker.join(timeout=5)

        # Close search engine
        self.search_engine.close()

        print("Shutdown complete")


def main():
    coordinator = SpiderEngineCoordinator()
    coordinator.start()


if __name__ == '__main__':
    main()