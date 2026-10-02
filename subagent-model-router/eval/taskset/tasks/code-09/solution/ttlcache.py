"""A least-recently-used cache whose entries also expire."""

import time
from collections import OrderedDict


class TTLCache:
    """A bounded mapping with least-recently-used eviction and per-entry expiry.

    ``TTLCache(capacity, ttl, clock=time.monotonic)``: ``capacity`` is an ``int`` of at least 1 and ``ttl`` a
    number greater than 0; anything else raises ``ValueError``. ``clock`` is a function of no arguments that
    returns the current time as a number; the cache calls it whenever it needs the time, as often as it likes.

    Expiry: an entry written by ``put`` at time ``t`` is *live* while ``clock() < t + ttl`` and *expired* from
    the moment ``clock() >= t + ttl``. Only ``put`` sets ``t``; reading an entry never extends its life. An
    expired entry behaves exactly as if it were not in the cache, for every method below.

    Recency: an entry is *used* when it is written by ``put`` or read by a successful ``get``. The least recently
    used live entry is the one whose last use is the oldest.

    Capacity: after ``put`` stores its entry, if the number of live entries is greater than ``capacity``, the
    least recently used live entry is removed. Expired entries never count towards the capacity, and nothing is
    removed while the live entries fit.
    """

    def __init__(self, capacity, ttl, clock=time.monotonic):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError(f"capacity must be a positive int, not {capacity!r}")
        try:
            positive = ttl > 0
        except TypeError:  # not a number at all
            positive = False
        if not positive:
            raise ValueError(f"ttl must be positive, not {ttl!r}")
        self._capacity = capacity
        self._ttl = ttl
        self._clock = clock
        self._entries = OrderedDict()  # key -> (value, written_at), least recently used first

    def put(self, key, value):
        """Store ``value`` under ``key`` (replacing any earlier value), written now and used now."""
        now = self._purge()
        self._entries[key] = (value, now)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def get(self, key, default=None):
        """Return the value of the live entry for ``key`` and mark it used; ``default`` if there is none."""
        self._purge()
        if key not in self._entries:
            return default
        self._entries.move_to_end(key)
        return self._entries[key][0]

    def __contains__(self, key):
        """Whether ``key`` has a live entry. Does not count as a use."""
        self._purge()
        return key in self._entries

    def __len__(self):
        """The number of live entries."""
        self._purge()
        return len(self._entries)

    def keys(self):
        """A list of the keys of all live entries, from least recently used to most recently used."""
        self._purge()
        return list(self._entries)

    def _purge(self):
        """Drop every expired entry and return the current time."""
        now = self._clock()
        for key in [key for key, (_, written) in self._entries.items() if now >= written + self._ttl]:
            del self._entries[key]
        return now
