import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from app.config import settings


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, queue: Deque[float], now: float) -> None:
        while queue and now - queue[0] >= self.window:
            queue.popleft()

    def _retry_after(self, queue: Deque[float], now: float) -> int:
        return int(self.window - (now - queue[0])) + 1

    def allow(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            queue = self._events[key]
            self._trim(queue, now)
            if len(queue) >= self.max_events:
                return False, self._retry_after(queue, now)
            queue.append(now)
            return True, 0

    def is_limited(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            queue = self._events[key]
            self._trim(queue, now)
            if len(queue) >= self.max_events:
                return True, self._retry_after(queue, now)
            return False, 0

    def record(self, key: str) -> None:
        with self._lock:
            self._events[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


chat_limiter = SlidingWindowLimiter(settings.chat_rate_per_minute, 60)
login_limiter = SlidingWindowLimiter(settings.login_max_failures, settings.login_window_seconds)
