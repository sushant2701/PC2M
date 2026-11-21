import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window limiter keyed by string."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._hits = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
