"""In-memory sliding-window rate limiting — Production (v0.8).

No new dependency (no slowapi, no Redis — budget $0, local-first).
Rules, per key (IP + email — see auth.py for the exact keys):
  - login:  5 FAILED attempts / 60 s per (IP, email). Only failures
    count, and a successful login clears the key. A real user who
    mistypes 5 times waits a minute; a brute-force script hits 429.
  - register: 3 attempts / 60 s per (IP, email), all attempts count.

429 responses carry a Retry-After header (seconds until the oldest
attempt in the window expires).

Honest limit: this is IN-MEMORY and PER-PROCESS. The production
server runs a single uvicorn worker (see scripts/production_start.*),
so one process sees all traffic and the limit holds. With multiple
workers it would not — do not run --workers > 1 without a shared
store (Redis). The limiter is keyed per (IP, email), not per IP
alone, so the automated test suite (many logins from one test IP
with different emails) is unaffected.
"""
import time

# key -> list of monotonic timestamps (seconds) of counted attempts.
_attempts: dict[str, list[float]] = {}

LOGIN_LIMIT = 5
REGISTER_LIMIT = 3
WINDOW_SECONDS = 60


def _prune(key: str, now: float) -> list[float]:
    stamps = [t for t in _attempts.get(key, []) if now - t < WINDOW_SECONDS]
    if stamps:
        _attempts[key] = stamps
    else:
        _attempts.pop(key, None)
    return stamps


def check_allowed(key: str, limit: int, window_seconds: int = WINDOW_SECONDS) -> tuple[bool, int]:
    """True + 0 if another attempt is allowed now; False + retry-after
    (seconds) if the limit is already reached. Does NOT record."""
    now = time.monotonic()
    stamps = _prune(key, now)
    if len(stamps) < limit:
        return True, 0
    retry_after = int(window_seconds - (now - stamps[0])) + 1
    return False, max(retry_after, 1)


def record(key: str) -> None:
    """Record one counted attempt (call only after check_allowed)."""
    _attempts.setdefault(key, []).append(time.monotonic())


def clear(key: str) -> None:
    """Forget all attempts for a key (e.g. after a successful login)."""
    _attempts.pop(key, None)


def reset_all() -> None:
    """Test helper: empty the whole limiter."""
    _attempts.clear()
