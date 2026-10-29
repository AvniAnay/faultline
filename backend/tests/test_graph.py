"""Agent graph interrupt/resume cycle (LLM and Tavily mocked) driven through the real API routes."""

import unittest
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import support
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api_helpers import bearer, patch_auth


class FakeLLM:
    def __init__(self, fail_classify=False):
        self.fail_classify = fail_classify
        self.prompts: list[str] = []

    def structured(self, schema, system, data, tracker):
        from app.agent.llm import LLMError
        from app.agent.nodes.classify import Classified, ClassifyBatch
        from app.agent.nodes.web_research import ResearchSummary

        self.prompts.append(data.text)
        tracker.add(llm_calls=1)
        tracker.add_tokens(10, 5)
        if schema is ClassifyBatch:
            if self.fail_classify:
                raise LLMError("down")
            n = data.text.count("service=")
            return ClassifyBatch(items=[
                Classified(index=i, category="Database", severity="High", category_reason="db", severity_reason="sev", search_query="postgres error fix")
                for i in range(1, n + 1)
            ])
        return ResearchSummary(relevant=True, summary="Fix it", probable_cause="Cause", steps=["a", "b"],
                               source_urls=["https://docs.example.org/x", "https://not-in-results"], confidence="high")


class FakeSearch:
    def __init__(self, fail_on=()):
        self.calls = 0
        self.fail_on = set(fail_on)

    def search(self, query, tracker):
        from app.agent.search import SearchError, SearchHit

        self.calls += 1
        tracker.add(tavily_calls=1)
        if self.calls in self.fail_on:
            raise SearchError("tavily down")
        return [SearchHit("https://docs.example.org/x", "Doc", "content"), SearchHit("https://b.example.org/y", "B", "content")]


class GraphFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.setup_db()

    def setUp(self):
        from app.api.errors_handling import ApiError  # noqa: F401
        from app.db.session import new_session

        with new_session() as s:
            s.execute(text("UPDATE runs SET status='completed' WHERE status IN ('running','requested','awaiting_review')"))
            s.commit()
        patch_auth(self)
        from app.main import create_app

        self.client = TestClient(create_app())
        self.admin, self.viewer = bearer("admin"), bearer("viewer")

    def make_run(self, n_items):
        from app.db.models import Fingerprint
        from app.db.session import new_session
        from app.pipeline.run import start_run

        run = start_run("admin-1")
        items = []
        with new_session() as s:
            for i in range(n_items):
                fp = Fingerprint(
                    service=f"svc-{uuid.uuid4().hex[:4]}", level="ERROR", drain_cluster_id=i + 1000 + len(str(run.id)),
                    template=f"Boom <NUM> {i}", status="new", first_seen=datetime.now(UTC), last_seen=datetime.now(UTC), total_count=5 - i,
                )
                s.add(fp)
                s.flush()
                items.append({"fingerprint_id": str(fp.id), "service": fp.service, "level": "ERROR",
                              "template": fp.template, "samples": ["sample <EMAIL> failed"], "count": 5 - i, "flags": ["new"]})
            s.commit()
        return run, items

    def run_graph(self, run, items, llm=None, search=None):
        from app.agent.deps import Deps
        from app.agent.graph import build_graph, get_checkpointer
        from app.config import get_settings
        from app.db.session import new_session
        from app.notify.email_sender import LogEmailSender

        deps = Deps(get_settings(), llm or FakeLLM(), search or FakeSearch(), new_session, LogEmailSender())
        graph = build_graph(deps, get_checkpointer())
        graph.invoke({"run_id": str(run.id), "items": items, "decisions": {}}, {"configurable": {"thread_id": str(run.id)}})
        return graph, deps

    def get_run(self, run):
        return self.client.get(f"/api/runs/{run.id}", headers=self.viewer).json()

    def test_approve_one_reject_one_then_complete(self):
        from app.db.models import Fingerprint, Resolution
        from app.db.session import new_session

        run, items = self.make_run(2)
        llm, search = FakeLLM(), FakeSearch(fail_on={2})
        graph, _ = self.run_graph(run, items, llm, search)

        body = self.get_run(run)
        self.assertEqual(body["status"], "awaiting_review")
        self.assertEqual(body["pending_review_count"], 2)

        pending = self.client.get("/api/reviews/pending", headers=self.viewer).json()
        entry = next(r for r in pending["runs"] if r["run"]["id"] == str(run.id))
        self.assertEqual(len(entry["items"]), 2)
        by_fp = {i["fingerprint_id"]: i for i in entry["items"]}
        first, second = items[0]["fingerprint_id"], items[1]["fingerprint_id"]
        self.assertEqual(by_fp[first]["proposed"]["resolution"]["origin"], "web")
        self.assertEqual(by_fp[first]["proposed"]["resolution"]["sources"], ["https://docs.example.org/x"])
        self.assertEqual(by_fp[second]["proposed"]["resolution"]["origin"], "llm_only")
        self.assertEqual(by_fp[second]["proposed"]["resolution"]["sources"], [])
        self.assertIn("No sourced resolution found", by_fp[second]["proposed"]["resolution"]["summary"])

        # submit while items are pending -> 422 listing the pending ids
        r = self.client.post(f"/api/runs/{run.id}/review/submit", headers=self.admin)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(len(r.json()["details"]), 2)

        # viewer cannot decide
        self.assertEqual(self.client.put(f"/api/review-items/{by_fp[first]['id']}", json={"decision": "approved"}, headers=self.viewer).status_code, 403)

        r = self.client.put(f"/api/review-items/{by_fp[first]['id']}", json={"decision": "approved", "comment": "ok, mail bob@example.com"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["comment"], "ok, mail <EMAIL>")
        self.assertEqual(r.json()["reviewer"]["id"], "admin-1")
        r = self.client.put(f"/api/review-items/{by_fp[second]['id']}", json={"decision": "rejected"}, headers=self.admin)
        self.assertEqual(r.status_code, 200)

        with self.assertLogs("faultline.email", level="INFO") as logs, mock.patch("app.pipeline.run._graph", return_value=graph):
            r = self.client.post(f"/api/runs/{run.id}/review/submit", headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "completed")
        self.assertEqual(len(logs.records), 1)
        self.assertIn(f"/errors/{first}", logs.output[0])
        stats = r.json()["stats"]
        self.assertEqual((stats["llm_calls"], stats["tavily_calls"], stats["emails_logged"]), (2, 2, 1))
        self.assertEqual(stats["llm_tokens"], {"prompt": 20, "completion": 10, "total": 30})

        with new_session() as s:
            res = s.scalars(select(Resolution).where(Resolution.fingerprint_id.in_([uuid.UUID(first), uuid.UUID(second)]))).all()
            self.assertEqual([str(x.fingerprint_id) for x in res], [first])
            self.assertEqual((res[0].status, res[0].approved_by, res[0].origin), ("approved", "admin-1", "web"))
            self.assertIsNotNone(res[0].approved_at)
            a, b = s.get(Fingerprint, uuid.UUID(first)), s.get(Fingerprint, uuid.UUID(second))
            self.assertEqual((a.status, a.severity, a.category), ("open", "High", "Database"))
            self.assertEqual((b.status, b.severity, b.category), ("open", None, None))

        # A second submit is a conflict
        self.assertEqual(self.client.post(f"/api/runs/{run.id}/review/submit", headers=self.admin).status_code, 409)
        # Decisions can no longer change
        self.assertEqual(self.client.put(f"/api/review-items/{by_fp[first]['id']}", json={"decision": "rejected"}, headers=self.admin).status_code, 409)

        detail = self.client.get(f"/api/errors/{first}", headers=self.viewer).json()
        self.assertEqual(detail["latest_flags"], ["new"])
        self.assertEqual(len(detail["resolutions"]), 1)
        self.assertEqual(detail["resolutions"][0]["approved_by"]["id"], "admin-1")
        self.assertEqual(detail["review_history"][0]["decision"], "approved")
        self.assertIsNone(detail["pending_review_item"])

    def test_edited_decision_applies_edits(self):
        from app.db.models import Resolution
        from app.db.session import new_session

        run, items = self.make_run(1)
        graph, _ = self.run_graph(run, items)
        item = self.client.get("/api/reviews/pending", headers=self.viewer).json()["runs"]
        item = next(r for r in item if r["run"]["id"] == str(run.id))["items"][0]
        self.assertEqual(self.client.put(f"/api/review-items/{item['id']}", json={"decision": "edited"}, headers=self.admin).status_code, 422)
        self.assertEqual(self.client.put(f"/api/review-items/{item['id']}", json={"decision": "edited", "edited": {}}, headers=self.admin).status_code, 422)
        self.assertEqual(self.client.put(f"/api/review-items/{item['id']}", json={"decision": "approved", "edited": {"severity": "Low"}}, headers=self.admin).status_code, 422)
        r = self.client.put(f"/api/review-items/{item['id']}", headers=self.admin, json={
            "decision": "edited", "edited": {"severity": "Low", "resolution": {"summary": "Restart, ping ops@example.com", "steps": ["one"]}}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["edited"]["resolution"]["summary"], "Restart, ping <EMAIL>")
        with mock.patch("app.pipeline.run._graph", return_value=graph):
            self.assertEqual(self.client.post(f"/api/runs/{run.id}/review/submit", headers=self.admin).json()["status"], "completed")
        with new_session() as s:
            res = s.scalars(select(Resolution).where(Resolution.fingerprint_id == uuid.UUID(items[0]["fingerprint_id"]))).one()
            self.assertEqual((res.summary, res.steps, res.probable_cause), ("Restart, ping <EMAIL>", ["one"], "Cause"))

    def test_llm_down_falls_back_and_does_not_fail_run(self):
        run, items = self.make_run(1)
        items[0]["level"] = "FATAL"
        self.run_graph(run, items, FakeLLM(fail_classify=True), FakeSearch(fail_on={1}))
        item = next(r for r in self.client.get("/api/reviews/pending", headers=self.viewer).json()["runs"] if r["run"]["id"] == str(run.id))["items"][0]
        self.assertEqual((item["proposed"]["category"], item["proposed"]["severity"]), ("Unknown", "High"))
        self.assertEqual(item["proposed"]["resolution"]["confidence"], "low")
        self.assertEqual(item["proposed"]["team_name"], "Platform")

    def test_prompts_only_contain_redacted_text(self):
        run, items = self.make_run(1)
        items[0]["samples"] = ["user bob@example.com from 10.1.2.3 password=hunter2"]
        llm = FakeLLM()
        self.run_graph(run, items, llm)
        joined = "\n".join(llm.prompts)
        for secret in ("bob@example.com", "10.1.2.3", "hunter2"):
            self.assertNotIn(secret, joined)

    def test_trigger_conflict_and_restart_cleanup(self):
        from app.db.repos.runs import fail_interrupted
        from app.db.session import new_session
        from app.pipeline.run import start_run

        run = start_run("admin-1")
        self.assertEqual(self.client.post("/api/runs/trigger", headers=self.admin).status_code, 409)
        with new_session() as s:
            self.assertGreaterEqual(fail_interrupted(s), 1)
        body = self.get_run(run)
        self.assertEqual((body["status"], body["stats"]["error"]), ("failed", "interrupted by restart"))


if __name__ == "__main__":
    unittest.main()
