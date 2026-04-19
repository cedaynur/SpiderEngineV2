# SpiderEngine V2

A concurrent web crawler and search engine built entirely with Python's standard library. SpiderEngine V2 crawls websites, builds a searchable inverted index, and supports real-time queries during indexing. Designed to handle large-scale crawls (millions of pages) with resumability and concurrency.

## Features

- **Concurrent Crawling**: Multi-threaded crawler with configurable worker threads for high-throughput crawling.
- **Full-Text Search**: Powered by SQLite FTS5 for fast, relevant search with BM25 ranking.
- **Resumable Crawls**: Crash-safe with heartbeat logic and recovery passes to prevent data loss.
- **Defensive Parsing**: Layered HTML parsing (html.parser + regex fallbacks) for robust content extraction from malformed web pages.
- **Web Interface**: Built-in web server for real-time monitoring, URL submission, and search queries.
- **Zero Dependencies**: Uses only Python standard library modules (sqlite3, threading, html.parser, etc.).
- **Scalable Storage**: SQLite with WAL mode for concurrent reads/writes and efficient batched operations.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/cedaynur/SpiderEngineV2.git
   cd SpiderEngineV2
   ```

2. Ensure Python 3.6+ is installed (FTS5 is available in sqlite3).

3. Run the application:
   ```bash
   python main.py
   ```

The web interface will be available at `http://localhost:8080`.

## Usage

### Starting the Crawler

Run the main script to start the coordinator, which initializes the database, workers, and web server:

```bash
python main.py
```

### Web Interface

- **Home Page**: Submit URLs to crawl and view crawl statistics.
- **Search Page**: Perform full-text searches on indexed content.
- **Monitoring**: Real-time stats on crawled pages, queue status, and performance metrics.

### Configuration

Modify the `SpiderEngineCoordinator` parameters in `main.py`:

- `db_path`: Path to SQLite database (default: 'spiderengine.db')
- `num_workers`: Number of crawler threads (default: 4)
- `port`: Web server port (default: 8080)

### Adding Seed URLs

Use the web interface to submit initial URLs, or programmatically via the database manager.

## Architecture

SpiderEngine V2 consists of several key components:

- **Coordinator**: Manages workers, queues, and the web server.
- **Crawl Workers**: Multi-threaded fetchers that parse HTML and extract links.
- **Database Manager**: Handles SQLite operations with FTS5 indexing and WAL mode.
- **Search Engine**: Queries the FTS5 index for fast full-text search.
- **Web Server**: Provides a simple HTTP interface for interaction.

### Data Flow

1. URLs are added to the frontier (pending queue).
2. Workers fetch and parse pages, extracting content and new links.
3. Content is indexed into SQLite FTS5 for search.
4. Users can search indexed content via the web interface.

### Concurrency Model

- Producer-consumer pattern with bounded queues.
- Threading for parallelism without external dependencies.
- WAL mode enables concurrent reads during writes.

## Project Structure

- `main.py`: Entry point and coordinator.
- `crawler/`: Core crawling components.
  - `parser.py`: Defensive HTML parsing.
  - `worker.py`: Crawl worker threads.
  - `storage.py`: Database operations.
  - `web.py`: Web server.
  - `search.py`: Search functionality.
- `agents/`: Multi-agent development artifacts.
- `docs/`: Documentation and specifications.
- `DELIVERABLE_INDEX.md`: Project deliverables overview.

## Contributing

This project was developed using a multi-agent workflow. Contributions are welcome:

1. Fork the repository.
2. Create a feature branch.
3. Make changes and test thoroughly.
4. Submit a pull request.

## License

This project is open-source. See individual files for licensing details.

## Acknowledgments

Built as part of an AI-assisted development experiment demonstrating multi-agent collaboration for complex software systems.