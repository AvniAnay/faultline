import unittest

import support
from drain3.persistence_handler import PersistenceHandler

from app.pipeline.drain_persistence import PostgresPersistence
from app.pipeline.fingerprint import Drain3Miner
from app.redaction.engine import redact

LINES = [
    "Timeout after 3303ms calling bank-gateway for order ORD-476149",
    "Timeout after 120ms calling bank-gateway for order ORD-111",
    "Connection reset by peer: 10.0.0.1:8443",
    "Kafka producer send failed: topic=order-events partition=11 error=NOT_LEADER_OR_FOLLOWER",
]


def red(text):
    return redact(text).text


class MemoryPersistence(PersistenceHandler):
    def __init__(self):
        self.state = None

    def save_state(self, state):
        self.state = state

    def load_state(self):
        return self.state


class FingerprintStability(unittest.TestCase):
    def test_same_line_same_cluster_after_reload_in_memory(self):
        store = MemoryPersistence()
        first = Drain3Miner(store)
        ids = [first.add(red(t)).cluster_id for t in LINES]
        first.save()
        second = Drain3Miner(store)  # simulates a restart
        again = [second.add(red(t)).cluster_id for t in LINES]
        self.assertEqual(ids, again)
        self.assertEqual(ids[0], ids[1])  # variables masked: one fingerprint
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual([second.match(red(t)) for t in LINES], ids)

    def test_same_line_same_cluster_after_reload_in_postgres(self):
        support.setup_db()
        from app.db.session import new_session

        with new_session() as s1:
            m1 = Drain3Miner(PostgresPersistence(s1, key="test-a"))
            ids = [m1.add(red(t)).cluster_id for t in LINES]
            m1.save()
            s1.commit()
        with new_session() as s2:
            m2 = Drain3Miner(PostgresPersistence(s2, key="test-a"))
            self.assertEqual([m2.add(red(t)).cluster_id for t in LINES], ids)


if __name__ == "__main__":
    unittest.main()
