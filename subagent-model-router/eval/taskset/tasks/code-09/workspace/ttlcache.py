"""A least-recently-used cache whose entries also expire."""

import time


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
        raise NotImplementedError

    def put(self, key, value):
        """Store ``value`` under ``key`` (replacing any earlier value), written now and used now."""
        raise NotImplementedError

    def get(self, key, default=None):
        """Return the value of the live entry for ``key`` and mark it used; ``default`` if there is none."""
        raise NotImplementedError

    def __contains__(self, key):
        """Whether ``key`` has a live entry. Does not count as a use."""
        raise NotImplementedError

    def __len__(self):
        """The number of live entries."""
        raise NotImplementedError

    def keys(self):
        """A list of the keys of all live entries, from least recently used to most recently used."""
        raise NotImplementedError
