"""The night's sleep (product owner, 13 Nov 2026: "we can make system sleep from
12:30 am to 8:00 am"). Inside the window a DI process asks the database nothing
on its own clock; a document sent at night is still read (verigence.di.night_rest)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

import pytest

from verigence.di import night_rest as nr

IST = ZoneInfo("Asia/Kolkata")
NIGHT = (clock_time(0, 30), clock_time(8, 0))
URL = "https://di-api.example/health/night-signal"


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=IST).astimezone(UTC)


class World:
    """A clock, the API's counter and the queues, all in the test's hands."""

    def __init__(self, start: str) -> None:
        self.now = at(start)
        self.signal: nr.Signal | None = ("boot-1", 0)
        self.due_in: float | None = None
        self.looks = 0
        self.fetches = 0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.now.timestamp()

    async def fetch(self, url: str) -> nr.Signal | None:
        assert url == URL
        self.fetches += 1
        return self.signal

    async def work_due_in(self) -> float | None:
        self.looks += 1
        return self.due_in

    def rest(self, signal_url: str = URL) -> nr.NightRest:
        return nr.NightRest(
            signal_url=signal_url, work_due_in=self.work_due_in, fetch=self.fetch,
            clock=self.clock, monotonic=self.monotonic,
        )

    def pass_time(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def _window(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nr, "WINDOW", NIGHT)
    yield
    nr.install(None)


# ── the window ──────────────────────────────────────────────────────────────


@pytest.mark.no_docker
def test_the_window_is_read_like_audit_core_reads_it() -> None:
    assert nr.parse_window("00:30-08:00") == NIGHT
    assert nr.parse_window("off") is None
    assert nr.parse_window("nonsense") == NIGHT  # a typing mistake never changes the window
    assert nr.in_window(at("2026-11-20 00:30")) and nr.in_window(at("2026-11-20 07:59"))
    assert not nr.in_window(at("2026-11-20 08:00")) and not nr.in_window(at("2026-11-20 00:29"))
    assert nr.seconds_until_wake(at("2026-11-20 07:00")) == 3600
    assert nr.seconds_until_wake(at("2026-11-20 12:00")) == 0


# ── the API's counter ───────────────────────────────────────────────────────


@pytest.mark.no_docker
def test_only_a_request_that_can_queue_work_moves_the_counter() -> None:
    assert nr.may_queue_work("POST") and nr.may_queue_work("put") and nr.may_queue_work("DELETE")
    assert not nr.may_queue_work("GET") and not nr.may_queue_work("head")
    before = nr.signal()
    nr.note_request()
    after = nr.signal()
    assert after["boot"] == before["boot"] and after["seq"] == int(before["seq"]) + 1


# ── a worker's night ────────────────────────────────────────────────────────


@pytest.mark.no_docker
async def test_by_day_a_worker_never_rests_and_reads_nothing() -> None:
    world = World("2026-11-20 14:00")
    rest = world.rest()
    for _ in range(5):
        await rest.step()
        world.pass_time(10)
    assert not rest.resting and world.fetches == 0 and world.looks == 0


@pytest.mark.no_docker
async def test_with_nothing_in_hand_a_worker_rests_and_then_never_reads_the_database() -> None:
    world = World("2026-11-20 00:30")
    rest = world.rest()
    await rest.step()
    assert rest.resting and world.looks == 1  # one look, then rest
    for _ in range(300):  # fifty minutes of the night
        world.pass_time(10)
        await rest.step()
    assert rest.resting and world.looks == 1  # the counter was read; the database was not


@pytest.mark.no_docker
async def test_work_still_being_read_at_half_past_midnight_is_finished_first() -> None:
    world = World("2026-11-20 00:30")
    world.due_in = 0.0  # the 9 pm Drive run is still being read
    rest = world.rest()
    for _ in range(12):
        await rest.step()
        world.pass_time(10)
    assert not rest.resting and world.looks == 4  # up, looking every 30 seconds
    world.due_in = None  # the last page is read
    world.pass_time(30)
    await rest.step()
    assert rest.resting


@pytest.mark.no_docker
async def test_a_document_sent_at_night_wakes_the_worker_within_one_read_of_the_counter() -> None:
    world = World("2026-11-20 02:00")
    rest = world.rest()
    await rest.step()
    assert rest.resting
    world.signal = ("boot-1", 1)  # the API took an upload
    world.due_in = 0.0
    world.pass_time(10)
    await rest.step()
    assert not rest.resting
    # Up for two minutes at least, then for as long as work is in hand.
    world.pass_time(nr.LINGER_SECONDS + 1)
    await rest.step()
    assert not rest.resting
    world.due_in = None
    world.pass_time(nr.LOOK_EVERY_SECONDS + 1)
    await rest.step()
    assert rest.resting


@pytest.mark.no_docker
async def test_a_restarted_api_counts_as_a_change() -> None:
    world = World("2026-11-20 02:00")
    rest = world.rest()
    await rest.step()
    world.signal = ("boot-2", 0)  # deployed at night
    world.pass_time(10)
    await rest.step()
    assert not rest.resting


@pytest.mark.no_docker
async def test_a_retry_due_in_the_night_wakes_the_worker_at_its_time() -> None:
    world = World("2026-11-20 01:00")
    world.due_in = 600.0  # a page to be read again in ten minutes
    rest = world.rest()
    await rest.step()
    assert rest.resting
    world.pass_time(590)
    await rest.step()
    assert rest.resting and world.looks == 1
    world.pass_time(20)
    await rest.step()
    assert not rest.resting


@pytest.mark.no_docker
async def test_once_an_hour_a_resting_worker_takes_one_look_and_goes_on_resting() -> None:
    world = World("2026-11-20 01:00")
    rest = world.rest()
    await rest.step()
    world.pass_time(nr.SAFETY_LOOK_SECONDS + 1)
    await rest.step()
    assert rest.resting and world.looks == 2
    world.due_in = 0.0  # work queued by something other than the API
    world.pass_time(nr.SAFETY_LOOK_SECONDS + 1)
    await rest.step()
    assert not rest.resting


@pytest.mark.no_docker
async def test_not_knowing_is_a_reason_to_stay_up() -> None:
    # No address for the counter: the worker polls as it always did.
    world = World("2026-11-20 02:00")
    unset = world.rest(signal_url="")
    await unset.step()
    assert not unset.resting and world.looks == 0

    # The API stops answering: three failed reads and the worker is up.
    rest = world.rest()
    await rest.step()
    assert rest.resting
    world.signal = None
    for _ in range(nr.SIGNAL_FAILURES_BEFORE_UP):
        world.pass_time(10)
        await rest.step()
    assert not rest.resting

    # The queues cannot be read: up, never asleep.
    async def broken() -> float | None:
        raise RuntimeError("database unreachable")

    world.signal = ("boot-1", 0)
    blind = nr.NightRest(
        signal_url=URL, work_due_in=broken, fetch=world.fetch, clock=world.clock, monotonic=world.monotonic,
    )
    await blind.step()
    assert not blind.resting


@pytest.mark.no_docker
async def test_at_eight_the_worker_is_up_again() -> None:
    world = World("2026-11-20 07:59:55")
    rest = world.rest()
    await rest.step()
    assert rest.resting
    world.pass_time(10)
    await rest.step()
    assert not rest.resting


@pytest.mark.no_docker
async def test_a_resting_lane_waits_without_a_timer_and_is_released_when_woken_or_stopped() -> None:
    world = World("2026-11-20 02:00")
    rest = world.rest()
    await rest.step()
    nr.install(rest)
    assert nr.resting()
    stop = asyncio.Event()
    lane = asyncio.create_task(nr.wait_until_awake(stop))
    await asyncio.sleep(0.01)
    assert not lane.done()
    world.signal = ("boot-1", 5)
    world.pass_time(10)
    await rest.step()
    await asyncio.wait_for(lane, timeout=1)

    world.due_in = None
    world.pass_time(nr.LINGER_SECONDS + 1)
    await rest.step()
    assert nr.resting()
    lane = asyncio.create_task(nr.wait_until_awake(stop))
    await asyncio.sleep(0.01)
    stop.set()  # the service is stopping
    await asyncio.wait_for(lane, timeout=1)


@pytest.mark.no_docker
def test_a_process_without_a_watch_never_rests() -> None:
    nr.install(None)
    assert not nr.resting()  # the API: asleep by the clock alone (in_window)


# ── the lanes ───────────────────────────────────────────────────────────────


class _Conn:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


async def _resting_watch(world: World) -> nr.NightRest:
    rest = world.rest()
    await rest.step()
    assert rest.resting
    nr.install(rest)
    return rest


@pytest.mark.no_docker
async def test_a_resting_processing_lane_closes_its_listener_and_listens_again_when_woken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verigence.di.workers.processor import V2ProcessingWorker

    world = World("2026-11-20 02:00")
    rest = await _resting_watch(world)
    lane = V2ProcessingWorker(1)
    first = _Conn()
    lane._notify_conn = first  # noqa: SLF001
    opened: list[str] = []

    async def reopen(url: str) -> bool:
        opened.append(url)
        lane._notify_conn = _Conn()  # noqa: SLF001
        return True

    monkeypatch.setattr(lane, "_open_notify_conn", reopen)
    turn = asyncio.create_task(lane._keep_listening("postgresql://direct", True))  # noqa: SLF001
    await asyncio.sleep(0.01)
    assert not turn.done() and first.closed and opened == []
    world.signal = ("boot-1", 1)
    world.pass_time(10)
    await rest.step()
    assert await asyncio.wait_for(turn, timeout=1) is True
    assert opened == ["postgresql://direct"]


@pytest.mark.no_docker
async def test_by_day_a_lost_listener_is_opened_again_at_most_once_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verigence.di.workers import capture_v2_classifier as classifier
    from verigence.di.workers import processor

    for lane, opener in (
        (processor.V2ProcessingWorker(1), "_open_notify_conn"),
        (classifier.CaptureV2ClassificationWorker(), "_open_notify"),
    ):
        conn = _Conn()
        lane._notify_conn = conn  # noqa: SLF001
        attempts: list[str] = []

        async def refuse(url: str, attempts: list[str] = attempts) -> bool:
            attempts.append(url)
            return False

        monkeypatch.setattr(lane, opener, refuse)
        assert await lane._keep_listening("postgresql://direct", True) is True  # noqa: SLF001
        assert attempts == []  # the connection is open: nothing to do
        conn.closed = True  # the database dropped it
        assert await lane._keep_listening("postgresql://direct", True) is False  # noqa: SLF001
        assert await lane._keep_listening("postgresql://direct", False) is False  # noqa: SLF001
        assert attempts == ["postgresql://direct"]  # one try now, the next a minute later


# ── heartbeats and the scheduler ────────────────────────────────────────────


@pytest.mark.no_docker
async def test_nothing_is_sampled_or_written_while_asleep(monkeypatch: pytest.MonkeyPatch) -> None:
    from verigence.di import platform_heartbeat as hb

    calls: list[str] = []

    class Quiet:
        def __init__(self, engine: object, service: str) -> None:
            del engine, service

        async def boot(self) -> None:
            calls.append("boot")

        def sample(self) -> None:
            calls.append("sample")

        async def beat(self) -> None:
            calls.append("beat")

        async def stop(self) -> None:
            calls.append("stop")

    monkeypatch.setattr(hb, "PlatformHeartbeat", Quiet)
    monkeypatch.setattr(hb, "BEAT_EVERY_SAMPLES", 1)
    stop = asyncio.Event()
    task = asyncio.create_task(hb.run_platform_heartbeat(
        "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none", "di-api", stop,
        sample_seconds=0.005, asleep=lambda: True))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert calls == ["boot", "sample", "stop"]  # the start and the stop; nothing in between


@pytest.mark.no_docker
async def test_a_resting_worker_logs_no_heartbeat_and_is_not_called_stalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verigence.di.workers import heartbeat

    emitted: list[int] = []

    async def emit(**_: object) -> tuple[int, int]:
        emitted.append(1)
        return 3, 0  # work pending, nothing processed: a stall by day

    monkeypatch.setattr(heartbeat, "emit_heartbeat", emit)
    stop = asyncio.Event()
    task = asyncio.create_task(heartbeat.run_heartbeat(
        stop_event=stop, session_factory=None, stats=list, fields={}, interval_seconds=0.005,
        asleep=lambda: True))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert emitted == []


@pytest.mark.no_docker
async def test_the_scheduler_tick_does_nothing_while_the_worker_rests(monkeypatch: pytest.MonkeyPatch) -> None:
    from verigence.di.scheduler import beat

    world = World("2026-11-20 02:00")
    await _resting_watch(world)
    ran: list[datetime] = []

    async def tick(session_factory: object, now_utc: datetime) -> None:
        del session_factory
        ran.append(now_utc)

    monkeypatch.setattr(beat, "_run_scheduler_tick_in_context", tick)
    await beat._run_scheduler_tick(session_factory=None)  # type: ignore[arg-type]  # noqa: SLF001
    assert ran == []
    nr.install(None)
    await beat._run_scheduler_tick(session_factory=None)  # type: ignore[arg-type]  # noqa: SLF001
    assert len(ran) == 1


# ── what a worker has in hand ───────────────────────────────────────────────


@pytest.mark.no_docker
def test_a_worker_rests_only_with_nothing_waiting_or_running() -> None:
    from verigence.di.workers.night_work import due_in

    now = datetime(2026, 11, 19, 21, 0, tzinfo=UTC)
    nothing = {"running": False, "link_pending": False, "next_due_at_utc": None}
    assert due_in(**nothing, include_legacy=False, now=now) is None
    assert due_in(**{**nothing, "running": True}, include_legacy=False, now=now) == 0
    # a job due now, or overdue, is work in hand; one due later is a wait
    assert due_in(**{**nothing, "next_due_at_utc": now - timedelta(seconds=5)}, include_legacy=False, now=now) == 0
    assert due_in(**{**nothing, "next_due_at_utc": now + timedelta(minutes=10)}, include_legacy=False, now=now) == 600
    # the link to Audit Core is the legacy lane's alone
    assert due_in(**{**nothing, "link_pending": True}, include_legacy=False, now=now) is None
    assert due_in(**{**nothing, "link_pending": True}, include_legacy=True, now=now) == 0


# ── against the database ────────────────────────────────────────────────────


async def test_the_queues_are_read_in_one_look(db_url: str) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from verigence.di.workers.night_work import work_due_in

    engine = create_async_engine(db_url, echo=False)
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        for include_legacy in (False, True):
            wait = await work_due_in(factory, include_legacy=include_legacy)
            assert wait is None or wait >= 0
    finally:
        await engine.dispose()


async def test_a_known_actor_is_read_not_rewritten(db_session) -> None:  # type: ignore[no-untyped-def]
    """Every upload came as the same service actor and rewrote its row: uploads
    queued behind each other on that one row lock (7,696 calls waited 4.6 s on
    average, 16-20 Nov 2026). A known, active actor is now only read."""
    import uuid

    from sqlalchemy import text

    from verigence.di.repositories.database import set_tenant_context
    from verigence.di.repositories.tenants import provision_actor, provision_tenant

    tenant_id = f"actor-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)

    async def row() -> tuple[str, str, str, str]:
        found = (await db_session.execute(text(
            "SELECT ctid::text, xmax::text, actor_type, status FROM docintel.actors"
            " WHERE tenant_id = :t AND actor_id = 'audit-core'"), {"t": tenant_id})).one()
        return tuple(found)  # type: ignore[return-value]

    await provision_actor(db_session, tenant_id, "audit-core", "SERVICE")
    first = await row()
    assert first[2:] == ("SERVICE", "ACTIVE")
    for _ in range(3):
        await provision_actor(db_session, tenant_id, "audit-core", "SERVICE")
    assert await row() == first  # same row version, and no lock taken on it (xmax 0)
    assert first[1] == "0"

    # An actor of another type is left as it is, as before.
    await provision_actor(db_session, tenant_id, "audit-core", "USER")
    assert await row() == first

    # An actor switched off is switched on again, as before.
    await db_session.execute(text(
        "UPDATE docintel.actors SET status = 'DISABLED' WHERE tenant_id = :t AND actor_id = 'audit-core'"),
        {"t": tenant_id})
    await provision_actor(db_session, tenant_id, "audit-core", "SERVICE")
    assert (await row())[3] == "ACTIVE"
