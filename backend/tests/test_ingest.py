"""Ingestion + detection against a throwaway DB, with the ES fetch replaced by canned records."""

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import support
from sqlalchemy import func, select

NOW = datetime(2026, 9, 23, 16, 0, tzinfo=UTC)
JAVA = "2026-09-23 {t},000 [main] ERROR c.e.payment.PaymentClient - "


def rec(ts, msg, service="payment-svc"):
    from app.connectors.elasticsearch import LogRecord

    return LogRecord(ts, service, "h", msg, str(uuid.uuid4()), "logs-x")


def lines(n, start, template, service="payment-svc", step_seconds=30):
    out = []
    for i in range(n):
        ts = start + timedelta(seconds=i * step_seconds)
        out.append(rec(ts, JAVA.format(t=ts.strftime("%H:%M:%S")) + template.format(i=i), service))
    return out


class IngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.setup_db()
        from app.config import get_settings
        from app.db.repos.sources import ensure_source
        from app.db.session import new_session

        with new_session() as s:
            ensure_source(s, get_settings())
            s.commit()

    def run_ingest(self, records, now=NOW):
        from app.config import get_settings
        from app.db.models import Run
        from app.db.session import new_session
        from app.pipeline.drain_persistence import PostgresPersistence
        from app.pipeline.fingerprint import Drain3Miner
        from app.pipeline.ingest import ingest

        with new_session() as s:
            run = Run(id=uuid.uuid4(), status="running")
            s.add(run)
            s.commit()
            miner = Drain3Miner(PostgresPersistence(s))
            with mock.patch("app.pipeline.ingest.fetch_records", return_value=iter(records)):
                result = ingest(s, run.id, object(), miner, get_settings(), now=now)
            s.commit()
            return run.id, result

    def test_new_spike_watermark_and_no_double_count(self):
        from app.db.models import Fingerprint, Occurrence, Sample, Source
        from app.db.session import new_session

        base = NOW - timedelta(hours=3)
        recs = lines(3, base, "Rare failure code {i}", "auth-svc", 3600)  # spread: hourly buckets
        recs += lines(40, NOW - timedelta(minutes=45), "Timeout after {i}ms calling bank for order ORD-{i}")
        recs.append(rec(NOW - timedelta(minutes=1), "2026-09-23 15:59:00,000 [main] INFO  c.e.X - Exception logged as info"))
        run_id, res = self.run_ingest(sorted(recs, key=lambda r: r.timestamp))
        self.assertEqual(res.stats["lines_scanned"], 44)
        self.assertEqual(res.stats["lines_dropped_level"], 1)
        self.assertEqual(res.stats["distinct_errors"], 2)
        by_service = {i.service: i for i in res.flagged}
        self.assertEqual(by_service["payment-svc"].flags, ["new", "spike"])
        self.assertEqual(by_service["auth-svc"].flags, ["new"])
        with new_session() as s:
            self.assertEqual(s.scalar(select(Source.watermark)), NOW - timedelta(minutes=2))
            fp = s.scalar(select(Fingerprint).where(Fingerprint.service == "payment-svc"))
            self.assertEqual(fp.total_count, 40)
            hours = s.scalars(select(Occurrence).where(Occurrence.fingerprint_id == fp.id)).all()
            self.assertEqual(sum(o.count for o in hours), 40)
            for o in hours:
                self.assertEqual(o.window_end - o.window_start, timedelta(hours=1))
            self.assertLessEqual(s.scalar(select(func.count()).select_from(Sample).where(Sample.fingerprint_id == fp.id)), 5)

        # Second run over the next window: same errors, new lines only -> same fingerprints, not new
        later = NOW + timedelta(hours=1)
        more = lines(4, NOW + timedelta(minutes=10), "Timeout after {i}ms calling bank for order ORD-{i}")
        _, res2 = self.run_ingest(more, now=later)
        self.assertEqual(res2.window_start, NOW - timedelta(minutes=2))
        self.assertEqual(res2.flagged, [])
        with new_session() as s:
            fps = s.scalars(select(Fingerprint).where(Fingerprint.service == "payment-svc")).all()
            self.assertEqual(len(fps), 1)
            self.assertEqual(fps[0].total_count, 44)

    def test_failure_rolls_back_everything_including_watermark(self):
        from app.db.models import Fingerprint, Source
        from app.db.session import new_session

        with new_session() as s:
            before_wm = s.scalar(select(Source.watermark))
            before_fp = s.scalar(select(func.count()).select_from(Fingerprint))

        def exploding():
            yield from lines(5, NOW, "Unique boom {i}", "boom-svc")
            raise RuntimeError("es died")

        from app.config import get_settings
        from app.db.models import Run
        from app.pipeline.drain_persistence import PostgresPersistence
        from app.pipeline.fingerprint import Drain3Miner
        from app.pipeline.ingest import ingest

        with new_session() as s:
            run = Run(id=uuid.uuid4(), status="running")
            s.add(run)
            s.commit()
            with mock.patch("app.pipeline.ingest.fetch_records", return_value=exploding()):
                with self.assertRaises(RuntimeError):
                    ingest(s, run.id, object(), Drain3Miner(PostgresPersistence(s)), get_settings(), now=NOW + timedelta(days=1))
            s.rollback()
        with new_session() as s:
            self.assertEqual(s.scalar(select(Source.watermark)), before_wm)
            self.assertEqual(s.scalar(select(func.count()).select_from(Fingerprint)), before_fp)

    def test_redaction_failure_drops_line_and_counts(self):
        from app.redaction.engine import RedactionError

        recs = lines(2, NOW - timedelta(hours=5), "fail me {i}", "rf-svc")
        with mock.patch("app.pipeline.ingest.redact", side_effect=RedactionError("x")):
            _, res = self.run_ingest(recs, now=NOW + timedelta(days=2))
        self.assertEqual(res.stats["redaction_failures"], 2)
        self.assertEqual(res.stats["distinct_errors"], 0)


class ConnectorTests(unittest.TestCase):
    def test_pit_search_after_no_from_paging_and_pit_closed(self):
        from app.config import get_settings
        from app.connectors.elasticsearch import fetch_records

        pages = [
            {"pit_id": "p2", "hits": {"hits": [
                {"_id": "1", "_index": "i", "sort": [1, 1], "_source": {"@timestamp": "2026-09-23T10:00:00Z", "message": "m", "kubernetes": {"container": {"name": "svc"}}}}]}},
            {"pit_id": "p3", "hits": {"hits": []}},
        ]
        es = mock.Mock()
        es.open_point_in_time.return_value = {"id": "p1"}
        es.search.side_effect = pages
        out = list(fetch_records(es, get_settings(), NOW - timedelta(hours=1), NOW))
        self.assertEqual([r.service for r in out], ["svc"])
        for call in es.search.call_args_list:
            self.assertNotIn("from_", call.kwargs)
            self.assertIn("pit", call.kwargs)
        self.assertEqual(es.search.call_args_list[1].kwargs["search_after"], [1, 1])
        es.close_point_in_time.assert_called_once_with(id="p3")

    def test_pit_closed_on_error(self):
        from app.config import get_settings
        from app.connectors.elasticsearch import fetch_records

        es = mock.Mock()
        es.open_point_in_time.return_value = {"id": "p1"}
        es.search.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            list(fetch_records(es, get_settings(), NOW - timedelta(hours=1), NOW))
        es.close_point_in_time.assert_called_once()


if __name__ == "__main__":
    unittest.main()
