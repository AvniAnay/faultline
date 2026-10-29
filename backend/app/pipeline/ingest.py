"""Ingestion + detection for one run, in a single DB transaction (spec G16)."""

import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from elasticsearch import Elasticsearch
from sqlalchemy.orm import Session

from app.agent.state import ErrorItem
from app.config import Settings
from app.connectors.elasticsearch import fetch_records
from app.db.repos import ingest as repo
from app.db.repos.sources import get_source
from app.pipeline.detection import is_spike, spike_periods
from app.pipeline.fingerprint import TemplateMiner
from app.pipeline.preprocess import preprocess
from app.redaction.engine import RedactionError, redact

logger = logging.getLogger(__name__)

Key = tuple[str, int]  # (service, drain cluster id)


@dataclass
class _Acc:
    level: str
    first_seen: datetime
    last_seen: datetime
    count: int = 0
    minutes: Counter = field(default_factory=Counter)  # minute start -> count
    samples: deque = field(default_factory=lambda: deque(maxlen=repo.MAX_SAMPLES))


@dataclass
class IngestResult:
    window_start: datetime
    window_end: datetime
    stats: dict
    flagged: list[ErrorItem]


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def compute_window(watermark: datetime | None, s: Settings, now: datetime) -> tuple[datetime, datetime]:
    end = now - timedelta(minutes=s.ingest_lag_minutes)
    start = watermark or now - timedelta(hours=s.initial_lookback_hours)
    return start, end


def ingest(
    session: Session, run_id, es: Elasticsearch, miner: TemplateMiner, s: Settings, now: datetime | None = None
) -> IngestResult:
    """Caller commits on success and rolls back on any exception (watermark then stays put)."""
    now = now or datetime.now(UTC)
    source = get_source(session)
    window_start, window_end = compute_window(source.watermark, s, now)

    scanned = dropped = failures = 0
    redaction_counts: Counter = Counter()
    acc: dict[Key, _Acc] = {}
    anchor: datetime | None = None

    for rec in fetch_records(es, s, window_start, window_end):
        scanned += 1
        pre = preprocess(rec.message, s.app_package_prefixes, s.stack_frames_kept, s.max_message_chars)
        if pre is None:
            dropped += 1
            continue
        try:
            result = redact(pre.text)
        except RedactionError:
            failures += 1  # fail closed: drop the line
            logger.error("redaction failed for a line from %s; line dropped", rec.service)
            continue
        redaction_counts.update(result.counts)
        cluster_id = miner.add(result.text).cluster_id
        a = acc.get((rec.service, cluster_id))
        if a is None:
            a = acc[(rec.service, cluster_id)] = _Acc(pre.level, rec.timestamp, rec.timestamp)
        if repo.LEVEL_RANK[pre.level] > repo.LEVEL_RANK[a.level]:
            a.level = pre.level
        a.first_seen = min(a.first_seen, rec.timestamp)
        a.last_seen = max(a.last_seen, rec.timestamp)
        a.count += 1
        a.minutes[_minute(rec.timestamp)] += 1
        a.samples.append((rec.timestamp, result.text))
        anchor = max(anchor, rec.timestamp) if anchor else rec.timestamp

    existing = repo.load_fingerprints(session, set(acc))
    flagged: list[ErrorItem] = []
    for (service, cluster_id), a in acc.items():
        template = miner.template(cluster_id)
        fp, created = repo.upsert_fingerprint(
            session, existing.get((service, cluster_id)), service, cluster_id, template,
            a.level, a.first_seen, a.last_seen, a.count,
        )
        session.flush()
        hours: dict[datetime, tuple[datetime, int]] = {}
        for minute, n in a.minutes.items():
            start = _hour(minute)
            hours[start] = (start + timedelta(hours=1), hours.get(start, (None, 0))[1] + n)
        repo.add_occurrences(session, fp.id, run_id, hours)
        repo.add_samples(session, fp.id, list(a.samples))

        flags = ["new"] if created else []
        assert anchor is not None
        cur_start, base_start, base_end = spike_periods(anchor, s.spike_lookback_hours)
        current = sum(n for m, n in a.minutes.items() if m + timedelta(minutes=1) > cur_start)
        if is_spike(current, repo.baseline_total(session, fp.id, base_start, base_end), s):
            flags.append("spike")
        if flags:
            flagged.append(
                ErrorItem(
                    fingerprint_id=str(fp.id), service=service, level=fp.level,
                    template=template.text,
                    samples=[t.text for _, t in reversed(a.samples)][:2],
                    count=a.count, flags=flags,
                )
            )

    miner.save()
    source.watermark = window_end
    stats = {
        "lines_scanned": scanned,
        "lines_dropped_level": dropped,
        "distinct_errors": len(acc),
        "flagged": len(flagged),
        "redaction_counts": dict(redaction_counts),
        "redaction_failures": failures,
    }
    logger.info("ingestion done: %s", stats)
    return IngestResult(window_start, window_end, stats, flagged)

