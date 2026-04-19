import http.server
import socketserver
import json
import urllib.parse
import threading
from .storage import DatabaseManager
from .search import SearchEngine


class SpiderEngineHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, db_manager=None, search_engine=None, index_callback=None, coordinator=None, **kwargs):
        self.db_manager = db_manager
        self.search_engine = search_engine
        self.index_callback = index_callback
        self.coordinator = coordinator
        super().__init__(*args, **kwargs)

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query = urllib.parse.parse_qs(parsed_path.query)

        if path == '/':
            self.serve_dashboard()
        elif path == '/api/stats':
            self.handle_stats()
        elif path == '/api/search' and 'q' in query:
            self.handle_search(query['q'][0])
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/index':
            self.handle_index()
        else:
            self.send_error(404)

    def serve_dashboard(self):
        html = self.generate_html()
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def handle_stats(self):
        try:
            stats = self.db_manager.get_stats()
            # Ensure all values are integers for JSON serialization
            response = {
                'total_indexed': int(stats.get('fetched', 0)),
                'queue_depth': int(stats.get('pending', 0)) + int(stats.get('frontier', 0)),
                'active_workers': int(self.coordinator.get_active_worker_count()),
                'in_flight': int(stats.get('in_progress', 0))  # In-flight work from DB
            }
            self.send_json_response(response)
        except Exception as e:
            self.send_error(500, str(e))

    def handle_search(self, query):
        try:
            results = self.search_engine.execute_query(query)
            response = []
            for url, origin_url, depth, snippet in results:
                response.append({
                    'url': url,
                    'origin_url': origin_url,
                    'depth': depth,
                    'snippet': snippet
                })
            self.send_json_response(response)
        except Exception as e:
            self.send_error(500, str(e))

    def handle_index(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            url = data.get('url', '').strip()

            if not url:
                self.send_error(400, 'Missing url parameter')
                return

            # URL validation and normalization
            if not url.startswith('http://') and not url.startswith('https://'):
                if url and '.' in url and ' ' not in url:
                    # Looks like a domain, prepend https://
                    url = 'https://' + url
                else:
                    self.send_error(400, 'Invalid URL format. Please provide a valid URL (e.g., example.com or https://example.com)')
                    return

            # Basic URL validation
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                if not parsed.netloc:
                    self.send_error(400, 'Invalid URL format')
                    return
            except Exception:
                self.send_error(400, 'Invalid URL format')
                return

            self.index_callback(url)
            self.send_json_response({'status': 'queued', 'url': url})
        except Exception as e:
            self.send_error(500, str(e))

    def send_json_response(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def generate_html(self):
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SpiderEngine V2 Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #fef7fb 0%, #fce4ec 100%);
            color: #4a4a4a;
            min-height: 100vh;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
        }

        .header h1 {
            color: #e91e63;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 0 2px 4px rgba(233, 30, 99, 0.2);
        }

        .header p {
            color: #7a7a7a;
            font-size: 1.1em;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: linear-gradient(135deg, #ffffff 0%, #fce4ec 100%);
            border: 1px solid #f8bbd9;
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(233, 30, 99, 0.1);
            transition: transform 0.3s ease;
        }

        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(233, 30, 99, 0.15);
        }

        .stat-card h3 {
            color: #e91e63;
            font-size: 0.9em;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .stat-card .value {
            font-size: 2.5em;
            font-weight: bold;
            color: #c2185b;
        }

        .search-section {
            background: linear-gradient(135deg, #ffffff 0%, #fce4ec 100%);
            border: 1px solid #f8bbd9;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(233, 30, 99, 0.1);
        }

        .search-section h2 {
            color: #e91e63;
            margin-bottom: 20px;
            text-align: center;
        }

        .search-form {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .search-input {
            flex: 1;
            padding: 12px;
            border: 2px solid #f8bbd9;
            border-radius: 8px;
            background: #ffffff;
            color: #4a4a4a;
            font-size: 1em;
            transition: border-color 0.3s ease;
        }

        .search-input:focus {
            outline: none;
            border-color: #e91e63;
            box-shadow: 0 0 8px rgba(233, 30, 99, 0.3);
        }

        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: all 0.3s ease;
        }

        .btn-primary {
            background: linear-gradient(135deg, #e91e63 0%, #c2185b 100%);
            color: #ffffff;
            box-shadow: 0 2px 8px rgba(233, 30, 99, 0.3);
        }

        .btn-primary:hover {
            background: linear-gradient(135deg, #c2185b 0%, #ad1457 100%);
            box-shadow: 0 4px 12px rgba(233, 30, 99, 0.4);
            transform: translateY(-1px);
        }

        .index-section {
            background: linear-gradient(135deg, #ffffff 0%, #fce4ec 100%);
            border: 1px solid #f8bbd9;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(233, 30, 99, 0.1);
        }

        .index-section h2 {
            color: #e91e63;
            margin-bottom: 20px;
            text-align: center;
        }

        .index-form {
            display: flex;
            gap: 10px;
        }

        .index-input {
            flex: 1;
            padding: 12px;
            border: 2px solid #f8bbd9;
            border-radius: 8px;
            background: #ffffff;
            color: #4a4a4a;
            font-size: 1em;
            transition: border-color 0.3s ease;
        }

        .index-input:focus {
            outline: none;
            border-color: #e91e63;
            box-shadow: 0 0 8px rgba(233, 30, 99, 0.3);
        }

        .results-section {
            background: linear-gradient(135deg, #ffffff 0%, #fce4ec 100%);
            border: 1px solid #f8bbd9;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 4px 20px rgba(233, 30, 99, 0.1);
        }

        .results-section h2 {
            color: #e91e63;
            margin-bottom: 20px;
            text-align: center;
        }

        .result-item {
            border-bottom: 1px solid #f1f1f1;
            padding: 15px 0;
        }

        .result-item:last-child {
            border-bottom: none;
        }

        .result-title {
            color: #e91e63;
            text-decoration: none;
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 5px;
            display: block;
            transition: color 0.3s ease;
        }

        .result-title:hover {
            color: #c2185b;
            text-decoration: underline;
        }

        .result-meta {
            color: #888;
            font-size: 0.9em;
            margin-bottom: 10px;
        }

        .result-snippet {
            color: #666;
            line-height: 1.5;
        }

        .result-snippet b {
            color: #e91e63;
            font-weight: bold;
            background: #fce4ec;
            padding: 2px 4px;
            border-radius: 3px;
        }

        .loading {
            text-align: center;
            color: #888;
            padding: 20px;
            font-style: italic;
        }

        .error {
            background: linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%);
            color: #c62828;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ef5350;
        }

        .success {
            background: linear-gradient(135deg, #e8f5e8 0%, #c8e6c9 100%);
            color: #2e7d32;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #4caf50;
        }

        .warning {
            background: linear-gradient(135deg, #fff3e0 0%, #ffcc02 100%);
            color: #f57c00;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ff9800;
        }

        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }

            .header h1 {
                font-size: 2em;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }

            .search-form,
            .index-form {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🕷️ SpiderEngine V2</h1>
            <p>Advanced Web Crawling & Search Engine</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Indexed</h3>
                <div class="value" id="total-indexed">-</div>
            </div>
            <div class="stat-card">
                <h3>Queue Depth</h3>
                <div class="value" id="queue-depth">-</div>
            </div>
            <div class="stat-card">
                <h3>Active Workers</h3>
                <div class="value" id="active-workers">-</div>
            </div>
            <div class="stat-card">
                <h3>In-Flight Requests</h3>
                <div class="value" id="in-flight">-</div>
            </div>
        </div>

        <div class="search-section">
            <h2>🔍 Search Engine</h2>
            <form class="search-form" onsubmit="performSearch(event)">
                <input type="text" class="search-input" id="search-query" placeholder="Enter your search query..." required>
                <button type="submit" class="btn btn-primary">Search</button>
            </form>
            <div id="search-results"></div>
        </div>

        <div class="index-section">
            <h2>🚀 Start Crawling</h2>
            <form class="index-form" onsubmit="startIndexing(event)">
                <input type="text" class="index-input" id="index-url" placeholder="https://example.com or example.com" required>
                <button type="submit" class="btn btn-primary">Start Crawl</button>
            </form>
            <div id="index-status"></div>
        </div>

        <div class="results-section">
            <h2>📊 System Status</h2>
            <div id="system-status">Loading system status...</div>
        </div>
    </div>

    <script>
        let statsInterval;

        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                document.getElementById('total-indexed').textContent = stats.total_indexed || 0;
                document.getElementById('queue-depth').textContent = stats.queue_depth || 0;
                document.getElementById('active-workers').textContent = stats.active_workers || 0;
                document.getElementById('in-flight').textContent = stats.in_flight || 0;
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }

        async function performSearch(event) {
            event.preventDefault();
            const query = document.getElementById('search-query').value.trim();
            if (!query) return;

            const resultsDiv = document.getElementById('search-results');
            resultsDiv.innerHTML = '<div class="loading">Searching...</div>';

            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const results = await response.json();

                if (results.length === 0) {
                    resultsDiv.innerHTML = '<div class="loading">No results found.</div>';
                    return;
                }

                let html = '';
                results.forEach(result => {
                    html += `
                        <div class="result-item">
                            <a href="${result.url}" class="result-title" target="_blank">${result.url}</a>
                            <div class="result-meta">
                                ${result.origin_url ? `From: ${result.origin_url} | ` : ''}Depth: ${result.depth}
                            </div>
                            <div class="result-snippet">${result.snippet}</div>
                        </div>
                    `;
                });
                resultsDiv.innerHTML = html;
            } catch (error) {
                resultsDiv.innerHTML = '<div class="error">Search failed. Please try again.</div>';
                console.error('Search error:', error);
            }
        }

        async function startIndexing(event) {
            event.preventDefault();
            let url = document.getElementById('index-url').value.trim();
            if (!url) return;

            // URL validation and normalization
            if (!url.startsWith('http://') && !url.startsWith('https://')) {
                if (url.includes('.') && !url.includes(' ')) {
                    // Looks like a domain, prepend https://
                    url = 'https://' + url;
                } else {
                    const statusDiv = document.getElementById('index-status');
                    statusDiv.innerHTML = '<div class="warning">Please enter a valid URL (e.g., example.com or https://example.com)</div>';
                    return;
                }
            }

            // Basic URL validation
            try {
                new URL(url);
            } catch (e) {
                const statusDiv = document.getElementById('index-status');
                statusDiv.innerHTML = '<div class="warning">Please enter a valid URL format</div>';
                return;
            }

            const statusDiv = document.getElementById('index-status');
            statusDiv.innerHTML = '<div class="loading">Starting crawl...</div>';

            try {
                const response = await fetch('/api/index', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });
                const result = await response.json();

                if (response.ok) {
                    statusDiv.innerHTML = `<div class="success">Crawl started for: ${result.url}</div>`;
                    document.getElementById('index-url').value = '';
                    loadStats(); // Refresh stats
                } else {
                    statusDiv.innerHTML = `<div class="error">${result.error || 'Failed to start crawl'}</div>`;
                }
            } catch (error) {
                statusDiv.innerHTML = '<div class="error">Failed to start crawl. Please try again.</div>';
                console.error('Index error:', error);
            }
        }

        // Load initial stats and set up auto-refresh
        loadStats();
        statsInterval = setInterval(loadStats, 5000); // Refresh every 5 seconds

        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (statsInterval) {
                clearInterval(statsInterval);
            }
        });
    </script>
</body>
</html>"""


class WebServer:
    def __init__(self, db_manager, search_engine, index_callback, coordinator, port=8080):
        self.db_manager = db_manager
        self.search_engine = search_engine
        self.index_callback = index_callback
        self.coordinator = coordinator
        self.port = port
        self.server = None

    def create_handler(self):
        def handler_class(*args, **kwargs):
            return SpiderEngineHandler(*args, db_manager=self.db_manager,
                                     search_engine=self.search_engine,
                                     index_callback=self.index_callback,
                                     coordinator=self.coordinator, **kwargs)
        return handler_class

    def start(self):
        handler_class = self.create_handler()
        with socketserver.TCPServer(("", self.port), handler_class) as httpd:
            self.server = httpd
            print(f"Web server started on port {self.port}")
            httpd.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()
            print("Web server stopped")