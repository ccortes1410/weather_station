import time
from typing import Any, Dict, List, Optional, Tuple


class TTLCache:
    """Lightweight in-memory TTL cache to minimize TiDB query load."""

    def __init__(self, max_entries: int = 64) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = time.time()
        if len(self._store) >= self._max_entries:
            expired: List[str] = [k for k, v in self._store.items() if now >= v[0]]
            for k in expired:
                self._store.pop(k, None)
            if len(self._store) >= self._max_entries:
                oldest_key: Optional[str] = None
                oldest_exp: Optional[float] = None
                for k, v in self._store.items():
                    if oldest_exp is None or v[0] < oldest_exp:
                        oldest_exp = v[0]
                        oldest_key = k
                if oldest_key is not None:
                    self._store.pop(oldest_key, None)
        self._store[key] = (now + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
