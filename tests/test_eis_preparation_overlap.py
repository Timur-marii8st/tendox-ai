"""Bounded local overlap experiment; no source/production calls."""

import asyncio
from datetime import date
from itertools import pairwise
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from procurement.sources.eis_223_sync import fetch_notice223_day
from procurement.sources.eis_feed_sync import (
    EisPreparationOverlap,
    EisSyncError,
    _request,
    sync_eis_hour,
)
from procurement.storage.eis_notice_index import EisIngestReport
from test_eis_223_sync import Transport
from test_eis_feed_sync import SELECTION, TOKEN, FakeTransport


class Clock:
    def __init__(self):
        self.now = 0.0
        self.pending = []

    async def sleep(self, seconds):
        if seconds == 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self.pending.append((self.now + seconds, future))
        await future

    async def drive(self, coroutine):
        task = asyncio.create_task(coroutine)
        for _ in range(100000):
            # Drain runnable tasks before advancing virtual monotonic time.
            for _ in range(20):
                await asyncio.sleep(0)
            if task.done():
                return await task
            self.pending = [(at, f) for at, f in self.pending if not f.done()]
            if not self.pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise AssertionError("cooperative transport deadlock")
            self.now = min(at for at, _ in self.pending)
            for at, future in self.pending:
                if at <= self.now and not future.done():
                    future.set_result(None)
        raise AssertionError("virtual run exceeded bound")


class PacedPayloads:
    """One shared paced channel and identical SOAP/XML fixture bytes per run."""

    def __init__(self, clock, duration=0, expiry=None):
        self.clock, self.duration, self.expiry = clock, duration, expiry
        self.t44, self.t223 = FakeTransport(), Transport()
        self.active = self.max_active = 0
        self.calls = []
        self.uid_law = {}
        self.cached44 = None
        self.cached223 = None

    async def invoke(self, law, method, *args):
        await self.clock.sleep(2)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        row = {"law": law, "method": method, "start": self.clock.now}
        self.calls.append(row)
        try:
            await self.clock.sleep(self.duration)
            if (
                self.expiry is not None
                and law == "223"
                and method == "download"
                and self.clock.now > self.expiry
            ):
                return 410, b"expired synthetic prepared result"
            target = self.t44 if law == "44" else self.t223
            result = await getattr(target, method)(*args)
            if method == "download":
                attr = "cached44" if law == "44" else "cached223"
                if getattr(self, attr) is None:
                    setattr(self, attr, result)
                result = getattr(self, attr)
            return result
        finally:
            row["end"] = self.clock.now
            self.active -= 1

    async def post(self, xml):
        root = ET.fromstring(xml)
        payload = next(iter(root.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")))
        if payload.tag.endswith("getDocsByOrgRegionRequest"):
            law = "223" if payload.findtext("selectionParams/subsystemType") == "RI223" else "44"
            self.uid_law[payload.findtext("index/id")] = law
        else:
            law = self.uid_law[payload.findtext("docRequestUid")]
        return await self.invoke(law, "post", xml)

    async def download(self, url, token):
        return await self.invoke("223" if "int44." in url else "44", "download", url, token)


def test_same_payload_overlap_finishes_ready223_before_more44(monkeypatch):
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", "")

    async def exercise(enabled):
        clock = Clock()
        channel = PacedPayloads(clock)
        completed = []
        ingested = []

        async def one44(transport):
            if len(completed) == 2:
                return False
            result = await sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport)
            completed.append(result.status)
            return True

        owner = EisPreparationOverlap(
            channel, one44, sleep=clock.sleep, monotonic=lambda: clock.now
        )

        async def run():
            observation = await fetch_notice223_day(
                "tenant-a",
                date(2026, 10, 1),
                TOKEN,
                owner.primary if enabled else channel,
                prepared_wait=owner.wait if enabled else clock.sleep,
            )
            if enabled:
                await owner.finish()
            while len(completed) < 2:
                await one44(channel)
            return observation

        with (
            patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
            patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
        ):

            def intake(storage, company, window, **kwargs):
                assert company == "tenant-a"
                ingested.append(window.archives)
                return EisIngestReport(SELECTION.window_key, 1, 1, 1, False)

            ingest.side_effect = intake
            observed = await clock.drive(run())
        return clock.now, observed, ingested, channel, owner

    old = asyncio.run(exercise(False))
    new = asyncio.run(exercise(True))
    assert old[0] == 28 and new[0] == 18  # 10s of real useful work, not timeout reduction.
    assert old[1].status == new[1].status == "SYNCED"
    assert old[1].window.archives == new[1].window.archives
    assert old[2] == new[2]
    assert new[3].max_active == 1 and len(old[3].calls) == len(new[3].calls) == 9
    calls = new[3].calls
    assert all(b["start"] - a["end"] >= 2 for a, b in pairwise(calls))
    poll = next(i for i, c in enumerate(calls[1:], 1) if c["law"] == "223")
    assert calls[poll + 1]["law"] == "223" and calls[poll + 1]["method"] == "download"
    assert new[4].poll_lateness_seconds == 0


def test_atomic44_request_can_delay_poll_but_no_new44_call_precedes_ready_get():
    async def exercise():
        clock = Clock()
        channel = PacedPayloads(clock, duration=4)

        async def one44(transport):
            await transport.post(_request(TOKEN, "44", selection=SELECTION))
            return True

        owner = EisPreparationOverlap(
            channel, one44, sleep=clock.sleep, monotonic=lambda: clock.now
        )

        async def run():
            await fetch_notice223_day(
                "tenant-a", date(2026, 10, 1), TOKEN, owner.primary, prepared_wait=owner.wait
            )
            await owner.finish()

        await clock.drive(run())
        return owner, channel

    owner, channel = asyncio.run(exercise())
    assert owner.poll_lateness_seconds == 2
    assert channel.max_active == 1
    assert [c["law"] for c in channel.calls] == ["223", "44", "44", "223", "223"]


def test_expired_prepared_result_is_rejected_not_checkpointed():
    async def exercise():
        clock = Clock()
        channel = PacedPayloads(clock, expiry=15)  # model TTL, not official source TTL.

        async def idle(_):
            return False

        owner = EisPreparationOverlap(channel, idle, sleep=clock.sleep, monotonic=lambda: clock.now)

        async def run():
            try:
                with pytest.raises(EisSyncError, match="ARCHIVE_CONTENT_REJECTED"):
                    await fetch_notice223_day(
                        "tenant-a",
                        date(2026, 10, 1),
                        TOKEN,
                        owner.primary,
                        prepared_wait=owner.wait,
                    )
            finally:
                await owner.abort()

        await clock.drive(run())
        assert channel.max_active == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
def test_timeout_or_restart_poison_session_and_preserve_unfinished_job(failure):
    async def exercise():
        calls = 0
        pending = ["44-uncommitted", "223-uncommitted"]

        class Uncertain:
            async def post(self, xml):
                nonlocal calls
                calls += 1
                raise failure()

            async def download(self, url, token):
                raise AssertionError("must not reuse uncertain session")

        async def idle(_):
            return False

        owner = EisPreparationOverlap(Uncertain(), idle)
        with pytest.raises(failure):
            await owner.primary.post(b"one")
        with pytest.raises(EisSyncError, match="OVERLAP_TRANSPORT_CLOSED"):
            await owner.primary.post(b"two")
        await owner.abort()
        assert calls == 1 and pending == ["44-uncommitted", "223-uncommitted"]
        assert owner.borrowed_completed == 0

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "family",
    [
        "purchaseNoticeAESMBO",
        "purchaseNotice",
        "purchaseNoticeZKESMBO",
        "purchaseRejection",
        "purchaseLotCancellation",
    ],
)
def test_prepared_poll_interval_remains_per_uid_and_bounded(family):
    from procurement.sources.eis_223_event_sync import fetch_purchase_rejection_day
    from procurement.sources.eis_223_lot_event_sync import fetch_purchase_lot_cancellation_day
    from test_eis_223_event_sync import Transport as RejectionTransport
    from test_eis_223_lot_event_sync import Transport as LotTransport

    async def exercise():
        clock = Clock()
        channel = PacedPayloads(clock)
        fetcher = fetch_notice223_day
        kwargs = {"document_type": family}
        if family == "purchaseRejection":
            channel.t223 = RejectionTransport("PREPARING")
            fetcher, kwargs = fetch_purchase_rejection_day, {}
        elif family == "purchaseLotCancellation":
            channel.t223 = LotTransport("PREPARING")
            fetcher, kwargs = fetch_purchase_lot_cancellation_day, {}
        else:
            channel.t223 = Transport("PREPARING", family=family)

        async def idle(_):
            return False

        owner = EisPreparationOverlap(channel, idle, sleep=clock.sleep, monotonic=lambda: clock.now)

        async def run():
            result = await fetcher(
                "tenant-a",
                date(2026, 10, 1),
                TOKEN,
                owner.primary,
                prepared_wait=owner.wait,
                **kwargs,
            )
            await owner.finish()
            return result

        result = await clock.drive(run())
        assert result.status == "PREPARING" and result.window is None
        assert len(channel.calls) == 5 and channel.max_active == 1
        assert all(b["start"] - a["end"] >= 12 for a, b in pairwise(channel.calls))
        assert channel.t223.downloads == 0

    asyncio.run(exercise())


def test_restart_during_borrow_does_not_ingest_partial44_then_retries_whole_window():
    async def exercise():
        clock = Clock()
        channel = PacedPayloads(clock)

        async def one44(transport):
            await sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, transport)
            return True

        owner = EisPreparationOverlap(
            channel, one44, sleep=clock.sleep, monotonic=lambda: clock.now
        )

        async def interrupt():
            waiting = asyncio.create_task(owner.wait(10))
            await clock.sleep(3)  # after initial44 POST, before complete archive set
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            with pytest.raises(EisSyncError, match="OVERLAP_TRANSPORT_CLOSED"):
                await owner.primary.post(b"must not reuse")

        with (
            patch("procurement.sources.eis_feed_sync.has_ingested_window", return_value=False),
            patch("procurement.sources.eis_feed_sync.ingest_ready_window") as ingest,
        ):
            await clock.drive(interrupt())
            ingest.assert_not_called()
            new_channel = PacedPayloads(clock)  # old browser session must close in real caller
            ingest.return_value = EisIngestReport(SELECTION.window_key, 1, 1, 1, False)
            result = await clock.drive(
                sync_eis_hour(None, "tenant-a", "worker", SELECTION, TOKEN, new_channel)
            )
            assert result.status == "SYNCED"
            ingest.assert_called_once()
        assert channel.t44.original_request_id != new_channel.t44.original_request_id
        assert channel.active == 0 and new_channel.max_active == 1

    asyncio.run(exercise())


def test_existing_budget_rejects_nested_window_so_transport_prototype_is_not_release_ready(
    tmp_path,
):
    from procurement.eis_joint_budget import JointStartBudget

    with JointStartBudget(tmp_path, "tenant-a") as budget:
        budget.begin_window("223")
        with pytest.raises(ValueError, match="JOINT_WINDOW_ALREADY_ACTIVE"):
            budget.begin_window("44")
        budget.end_window()
