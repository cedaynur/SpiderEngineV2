import sqlite3

class SearchEngine:
    def __init__(self, db_path):
        # Open database in read-only mode to avoid blocking writers
        self.conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        self.conn.row_factory = sqlite3.Row  # For easier access

    def execute_query(self, query_string, limit=10):
        """
        Perform full-text search on documents_fts table using FTS5 MATCH operator.
        Returns list of tuples: (relevant_url, origin_url, depth, snippet)
        Where origin_url is the parent URL if exists, else None.
        Snippet is highlighted text excerpt with <b> tags around matches.
        """
        cursor = self.conn.cursor()
        query = """
        SELECT u.url as relevant_url,
               p.url as origin_url,
               u.depth,
               snippet(documents_fts, 1, '<b>', '</b>', '...', 10) as snippet
        FROM documents_fts
        JOIN documents d ON documents_fts.rowid = d.id
        JOIN urls u ON d.url_id = u.id
        LEFT JOIN urls p ON u.parent_url_id = p.id
        WHERE documents_fts MATCH ?
        ORDER BY documents_fts.rank
        LIMIT ?
        """
        cursor.execute(query, (query_string, limit))
        results = cursor.fetchall()
        # Convert to list of tuples, handle None for origin_url
        return [(row['relevant_url'], row['origin_url'], row['depth'], row['snippet']) for row in results]

    def close(self):
        if self.conn:
            self.conn.close()