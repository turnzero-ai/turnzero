"""Generic mtime-based cache for file-backed loaders.

Both retrieval_svc (block index) and index_repo (incremental builds) use the
same invalidation pattern: compare the file's mtime to a stored value; reload
only when it changes. CachedLoader centralises that pattern.
"""

from __future__ import annotations

from collections.abc import Callable


class CachedLoader[T]:
    """Cache the result of loader_fn, invalidating when get_mtime_fn returns a new value.

    Example:
        loader = CachedLoader(
            loader_fn=lambda: load_index(path),
            get_mtime_fn=lambda: path.stat().st_mtime,
        )
        entries = loader.get()  # loads on first call, cached thereafter
    """

    def __init__(
        self,
        loader_fn: Callable[[], T],
        get_mtime_fn: Callable[[], float],
    ) -> None:
        self._loader = loader_fn
        self._get_mtime = get_mtime_fn
        self._cached_mtime: float | None = None
        self._cached_value: T | None = None

    def get(self) -> T:
        """Return cached value if mtime unchanged; otherwise reload."""
        try:
            mtime = self._get_mtime()
        except (FileNotFoundError, OSError):
            mtime = 0.0

        if self._cached_mtime is None or mtime != self._cached_mtime:
            self._cached_value = self._loader()
            self._cached_mtime = mtime

        return self._cached_value  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Force a reload on the next get() call."""
        self._cached_mtime = None
        self._cached_value = None
