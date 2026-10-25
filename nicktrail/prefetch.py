"""Read several *different* services at once without changing per-service pacing.

Only network reads run in worker threads; every database write stays in the
caller's thread.  The HTTP client serialises requests per host (one request at
a time, configured pause included), so a single service sees exactly the same
traffic as with sequential reading.
"""

from concurrent.futures import ThreadPoolExecutor


class Prefetcher:
    def __init__(self, client, workers, read):
        self.client = client
        self.read = read
        self.workers = workers
        self.pool = (
            ThreadPoolExecutor(max_workers=workers, thread_name_prefix='nicktrail-read')
            if workers > 1
            else None
        )
        self.futures = {}

    def _run(self, key, task):
        local = self.client.local
        local.task, local.count = key, 0
        try:
            return ('ok', self.read(task), local.count)
        except BaseException as error:  # re-raised in the owner thread
            return ('raise', error, local.count)
        finally:
            local.task = None

    def schedule(self, tasks):
        if not self.pool:
            return
        for task in tasks:
            key = (task['platform'], task['term'], task['mode'])
            if key not in self.futures and len(self.futures) < self.workers * 2:
                self.futures[key] = self.pool.submit(self._run, key, task)

    def take(self, key):
        future = self.futures.pop(key, None)
        return future.result() if future else None

    def close(self):
        if self.pool:
            for future in self.futures.values():
                future.cancel()
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.futures.clear()
