import threading

class StatsManager:
    def __init__(self, num_workers):
        self.num_workers = num_workers
        self._active_workers = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._active_workers = min(self.num_workers, self._active_workers + 1)

    def decrement(self):
        with self._lock:
            self._active_workers = max(0, self._active_workers - 1)

    @property
    def active_workers(self):
        with self._lock:
            return self._active_workers