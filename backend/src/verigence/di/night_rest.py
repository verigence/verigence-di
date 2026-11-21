"""night_rest.py -- Document Intelligence in the night's sleep.

Product owner, 13 Nov 2026: "we can make system sleep from 12:30 am to 8:00 am".
The database (Neon) is billed for every hour it runs and stops by itself only
after five minutes in which nobody asked it anything. Audit Core, its worker and
Security have slept since then; DI had no part in it. Its worker lanes asked for
work every six seconds each and every DI service wrote a heartbeat a minute, day
and night: in the 450 minutes of the window on 19-20 Nov, DI wrote to the
database in all 450, and the database never stopped (20 Nov 2026).

What sleeping means here. Inside the window (India time,
``VERIGENCE_SLEEP_WINDOW_IST``, "off" to disable -- the same setting Audit Core
and Security read) a DI process asks the database nothing on its own clock:

* the API writes no heartbeat; a request is served as always (the database
  starts by itself in under a second);
* a worker finishes what is in hand first -- a Drive run still being read at
  12:30 keeps it up -- and only then rests: no polling, no heartbeat, no
  scheduler tick, no LISTEN connection (the database drops it when it stops);
* a resting worker is woken, without the database, by the API: every request
  that can queue work moves a counter the API keeps in memory
  (``GET /health/night-signal``), and the worker reads that counter every ten
  seconds. A document sent at night is therefore read as by day;
* a retry whose time falls in the night wakes the worker at that time, and once
  an hour the worker takes one look at the queues anyway (the safety net for
  work queued by anything other than the API);
* at the end of the window everything carries on as by day, and each lane
  opens its LISTEN connection again.

Not knowing is a reason to stay up, never to sleep: with no signal address set,
or the API not answering, a worker polls as it always did.

The shutdown switch (product owner, 21 Nov 2026: "lets have a tab in the
verigence to have a full shutdown of DB"). The window was a setting of each
service. It is now state held by Verigence Security, changed by a Super Admin or
Executive from the System shutdown tab: the daily hours, a "Shut down now" (shut
to the next daily opening) and a "Start now". Each DI process asks Security for
it once a minute (``start_following``; Security answers from memory, no
database) and ``follow`` takes the answer. From then on "the window" here is
that state: a shutdown by hand in the evening is rested through exactly as the
night is, work in hand first, and a Start at night ends the rest within the
minute. The answer carries the schedule, so a process keeps time by itself
between answers and while Security cannot be reached; before the first answer
the setting above stands.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_WINDOW = "00:30-08:00"

Window = tuple[clock_time, clock_time]


def parse_window(value: str | None) -> Window | None:
    """``"00:30-08:00"`` as two times of day (IST); None for "off". Anything
    unreadable is the default window: a typing mistake must neither keep the
    database up all night nor put DI to sleep by day."""
    raw = (value or "").strip().lower()
    if raw in {"off", "none", "never", "false", "0"}:
        return None
    for candidate in (raw, DEFAULT_WINDOW):
        start_text, _, end_text = candidate.partition("-")
        try:
            start = clock_time.fromisoformat(start_text.strip())
            end = clock_time.fromisoformat(end_text.strip())
        except ValueError:
            continue
        if start != end:
            return start, end
    return None


WINDOW: Window | None = parse_window(os.environ.get("VERIGENCE_SLEEP_WINDOW_IST", DEFAULT_WINDOW))


SHUT = "SHUT"
OPEN = "OPEN"


@dataclass(frozen=True)
class Followed:
    """Security's shutdown switch as last heard: the daily hours (None: no daily
    shutdown) and a Shut down or Start by hand, in force until ``until``."""

    hours: Window | None
    manual: str | None = None
    until: datetime | None = None


_followed: Followed | None = None
_followed_lock = threading.Lock()


def _when(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC) if value else None
    except ValueError:
        return None


def follow(status: object) -> bool:
    """Take Security's answer (GET /security/v1/system/status) as the state to go
    by. False, and nothing changes, for an answer that is not one."""
    global _followed  # noqa: PLW0603 - one state per process is the design
    if not isinstance(status, dict) or "resting" not in status:
        return False
    hours: Window | None = None
    start_text, end_text = status.get("hoursFromIst"), status.get("hoursToIst")
    if start_text or end_text:
        try:
            start, end = clock_time.fromisoformat(str(start_text)), clock_time.fromisoformat(str(end_text))
        except ValueError:
            return False
        if start == end:
            return False
        hours = (start, end)
    manual = status.get("manual")
    until = _when(status.get("manualUntilUtc"))
    if manual not in {SHUT, OPEN} or until is None:
        manual, until = None, None
    with _followed_lock:
        _followed = Followed(hours=hours, manual=manual, until=until)
    return True


def unfollow() -> None:
    """Back to the setting alone (tests)."""
    global _followed  # noqa: PLW0603
    with _followed_lock:
        _followed = None


def followed() -> Followed | None:
    with _followed_lock:
        return _followed


def _hours() -> Window | None:
    state = followed()
    return state.hours if state is not None else WINDOW


def _manual(moment: datetime) -> Followed | None:
    state = followed()
    if state is None or state.manual is None or state.until is None:
        return None
    return state if moment < state.until else None


def _in_hours(moment: datetime) -> bool:
    hours = _hours()
    if hours is None:
        return False
    start, end = hours
    local = moment.astimezone(IST).time()
    return start <= local < end if start < end else (local >= start or local < end)


def _next_opening(moment: datetime) -> datetime | None:
    hours = _hours()
    if hours is None:
        return None
    local = moment.astimezone(IST)
    wake = local.replace(hour=hours[1].hour, minute=hours[1].minute, second=0, microsecond=0)
    if wake <= local:
        wake += timedelta(days=1)
    return wake


def in_window(now: datetime | None = None) -> bool:
    """Whether Verigence is shut at this moment: a Shut down or Start by hand
    while it lasts, else the daily hours."""
    moment = now or datetime.now(UTC)
    manual = _manual(moment)
    return manual.manual == SHUT if manual is not None else _in_hours(moment)


def seconds_until_wake(now: datetime | None = None) -> float:
    """Seconds left of the shutdown; 0 outside one."""
    moment = now or datetime.now(UTC)
    if not in_window(moment):
        return 0.0
    manual = _manual(moment)
    wake = manual.until if manual is not None else _next_opening(moment)
    if manual is not None and wake is not None and _in_hours(wake):
        # A shutdown by hand that runs out inside the daily hours goes on to that day's opening.
        wake = _next_opening(wake)
    return max(0.0, (wake - moment).total_seconds()) if wake is not None else 0.0


# ── Asking Security ────────────────────────────────────────────────────────
FOLLOW_EVERY_SECONDS = 60.0
_follower: threading.Thread | None = None
_follower_lock = threading.Lock()


def status_url(security_jwks_url: str) -> str:
    """Where Security says whether Verigence is shut: VERIGENCE_SHUTDOWN_STATUS_URL
    if set, else the same host DI already checks tokens against."""
    explicit = os.environ.get("VERIGENCE_SHUTDOWN_STATUS_URL", "").strip()
    if explicit:
        return explicit
    from urllib.parse import urlsplit  # noqa: PLC0415

    parts = urlsplit(security_jwks_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc or "mock" in parts.netloc.lower():
        return ""
    return f"{parts.scheme}://{parts.netloc}/security/v1/system/status"


def ask(url: str, *, timeout: float = 5.0) -> bool:
    """One question. True when Security's answer was taken; False otherwise, with
    the state left as it was: a failure is never a reason to sleep or to wake."""
    import httpx  # noqa: PLC0415

    try:
        response = httpx.get(url, timeout=timeout)
        if response.status_code != 200:
            return False
        return follow(response.json())
    except Exception:  # noqa: BLE001 - any failure is "not known"
        return False


def start_following(url: str, stop: threading.Event | None = None) -> threading.Thread | None:
    """Ask once a minute, in a thread of its own, once per process. None when
    there is nowhere to ask, when VERIGENCE_SHUTDOWN_SWITCH=off, or when this
    process was told never to sleep (VERIGENCE_SLEEP_WINDOW_IST=off)."""
    global _follower  # noqa: PLW0603
    off = os.environ.get("VERIGENCE_SHUTDOWN_SWITCH", "on").strip().lower() in {"off", "false", "0", "no"}
    if off or not url or WINDOW is None:
        return None
    halt = stop or threading.Event()

    def run() -> None:
        heard: bool | None = None
        was_shut: bool | None = None
        while True:
            answered = ask(url)
            if answered != heard:
                heard = answered
                logger.info("di_shutdown_switch_heard" if answered else "di_shutdown_switch_not_heard")
            shut = in_window()
            if shut != was_shut:
                was_shut = shut
                state = followed()
                logger.info("di_shutdown_switch_state", shut=shut, by_hand=state.manual if state else None,
                            wakes_in_seconds=round(seconds_until_wake()))
            if halt.wait(FOLLOW_EVERY_SECONDS):
                return

    with _follower_lock:
        if _follower is None or not _follower.is_alive():
            _follower = threading.Thread(target=run, name="shutdown-switch", daemon=True)
            _follower.start()
        return _follower


# ── The API's side: the signal ─────────────────────────────────────────────
# Kept in memory, never in the database. A new API process (a deploy, a
# restart) has a new boot id, which a worker reads as a change too.

_BOOT_ID = uuid.uuid4().hex
_requests = 0

_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def may_queue_work(method: str) -> bool:
    """Whether a request of this method can queue work for a worker."""
    return method.upper() not in _READ_ONLY_METHODS


def note_request() -> None:
    """A request that can queue work arrived, or has just been answered."""
    global _requests  # noqa: PLW0603 - one counter per API process is the design
    _requests += 1


def signal() -> dict[str, str | int]:
    return {"boot": _BOOT_ID, "seq": _requests}


# ── A worker process's side ────────────────────────────────────────────────

Signal = tuple[str, int]
SIGNAL_EVERY_SECONDS = 10.0  # how often a worker reads the API's counter (no database)
LINGER_SECONDS = 120.0  # up for this long after the counter moved, before looking to rest again
LOOK_EVERY_SECONDS = 30.0  # while up at night with work in hand: look again this often
SAFETY_LOOK_SECONDS = 3600.0  # resting: one look at the queues this often, whatever the counter says
SIGNAL_FAILURES_BEFORE_UP = 3  # the API not answering this many times running: up, as by day


async def fetch_signal(url: str, *, timeout: float = 5.0) -> Signal | None:
    """The API's counter; None when it cannot be read."""
    import httpx  # noqa: PLC0415 - only a resting worker needs it

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        response.raise_for_status()
        body = response.json()
        return str(body["boot"]), int(body["seq"])
    except Exception:  # noqa: BLE001 - any failure is "not known"
        return None


class NightRest:
    """One per worker process: decides whether its lanes rest, and wakes them.

    ``work_due_in`` reads the queues: 0 when work is waiting or running, the
    seconds until the earliest retry or scheduled run otherwise, None when
    there is nothing at all. It is called only while the worker is up, and for
    the hourly safety look.
    """

    def __init__(
        self,
        *,
        signal_url: str,
        work_due_in: Callable[[], Awaitable[float | None]],
        fetch: Callable[[str], Awaitable[Signal | None]] = fetch_signal,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        name: str = "di-worker",
    ) -> None:
        self._signal_url = signal_url.strip()
        self._work_due_in = work_due_in
        self._fetch = fetch
        self._clock = clock
        self._monotonic = monotonic
        self._name = name
        self._awake = asyncio.Event()
        self._awake.set()
        self._seen: Signal | None = None
        self._failures = 0
        self._up_until = 0.0
        self._next_look = 0.0
        self._wake_at: float | None = None
        self._safety_look_at = 0.0

    @property
    def resting(self) -> bool:
        return not self._awake.is_set()

    async def wait_until_awake(self, stop: asyncio.Event) -> None:
        """Returns when the worker is up again, or is stopping."""
        if self._awake.is_set() or stop.is_set():
            return
        up = asyncio.create_task(self._awake.wait())
        stopping = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({up, stopping}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (up, stopping):
                task.cancel()
            await asyncio.gather(up, stopping, return_exceptions=True)

    def _get_up(self, reason: str, *, linger: bool = True) -> None:
        if linger:
            self._up_until = self._monotonic() + LINGER_SECONDS
        self._wake_at = None
        if not self._awake.is_set():
            logger.info("di_night_up", worker=self._name, reason=reason)
            self._awake.set()

    def _rest(self, due_in: float | None) -> None:
        now = self._monotonic()
        self._wake_at = None if due_in is None else now + max(due_in, 1.0)
        self._safety_look_at = now + SAFETY_LOOK_SECONDS
        if self._awake.is_set():
            logger.info(
                "di_night_resting",
                worker=self._name,
                next_retry_in_seconds=None if due_in is None else round(due_in),
                window_ends_in_seconds=round(seconds_until_wake(self._clock())),
            )
            self._awake.clear()

    async def _look(self) -> tuple[bool, float | None]:
        """(known, due_in). Not known is a reason to stay up."""
        try:
            return True, await self._work_due_in()
        except Exception as exc:  # noqa: BLE001
            logger.warning("di_night_look_failed", worker=self._name, error=type(exc).__name__)
            return False, None

    async def step(self) -> None:
        """One turn of the watch. Reads the database only while the worker is
        up, and for the hourly safety look."""
        if not self._signal_url or not in_window(self._clock()):
            if self.resting:
                self._get_up("window_over", linger=False)
            self._seen = None
            self._failures = 0
            self._up_until = 0.0
            return
        now = self._monotonic()
        current = await self._fetch(self._signal_url)
        if current is None:
            self._failures += 1
            if self._failures >= SIGNAL_FAILURES_BEFORE_UP:
                self._get_up("signal_unreachable")
            return
        self._failures = 0
        if self._seen is not None and current != self._seen:
            self._get_up("request")
        self._seen = current

        if self.resting:
            if self._wake_at is not None and now >= self._wake_at:
                self._get_up("retry_due")
            elif now >= self._safety_look_at:
                known, due_in = await self._look()
                if not known or (due_in is not None and due_in <= 0):
                    self._get_up("work_found")
                else:
                    self._rest(due_in)
            return

        if now < self._up_until or now < self._next_look:
            return
        known, due_in = await self._look()
        if not known or (due_in is not None and due_in <= 0):
            self._next_look = now + LOOK_EVERY_SECONDS
            return
        self._rest(due_in)

    async def run(self, stop: asyncio.Event) -> None:
        """Until ``stop`` is set. A failing turn never stops the watch, and
        leaves the worker up."""
        while not stop.is_set():
            try:
                await self.step()
            except Exception as exc:  # noqa: BLE001
                logger.warning("di_night_watch_failed", worker=self._name, error=type(exc).__name__)
                self._get_up("watch_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=SIGNAL_EVERY_SECONDS)
        self._awake.set()


_installed: NightRest | None = None


def install(rest: NightRest | None) -> None:
    """The worker process's own watch; None in the API and in tests."""
    global _installed  # noqa: PLW0603
    _installed = rest


def resting() -> bool:
    """Whether this process's worker is resting. Never true in a process
    without a watch (the API): it sleeps by the clock alone (``in_window``)."""
    return _installed is not None and _installed.resting


async def wait_until_awake(stop: asyncio.Event) -> None:
    if _installed is not None:
        await _installed.wait_until_awake(stop)
