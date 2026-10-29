"""classify -> web_research -> build_report -> human_review (interrupt) -> send_email -> persist."""

from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agent.deps import Deps
from app.agent.nodes.build_report import make_build_report
from app.agent.nodes.classify import make_classify
from app.agent.nodes.human_review import make_human_review
from app.agent.nodes.persist import make_persist
from app.agent.nodes.send_email import make_send_email
from app.agent.nodes.web_research import make_web_research
from app.agent.state import RunState
from app.config import get_settings


def build_graph(deps: Deps, checkpointer):
    g = StateGraph(RunState)
    g.add_node("classify", make_classify(deps))
    g.add_node("web_research", make_web_research(deps))
    g.add_node("build_report", make_build_report(deps))
    g.add_node("human_review", make_human_review(deps))
    g.add_node("send_email", make_send_email(deps))
    g.add_node("persist", make_persist(deps))
    g.add_edge(START, "classify")
    g.add_edge("classify", "web_research")
    g.add_edge("web_research", "build_report")
    g.add_edge("build_report", "human_review")
    g.add_edge("human_review", "send_email")
    g.add_edge("send_email", "persist")
    g.add_edge("persist", END)
    return g.compile(checkpointer=checkpointer)


@lru_cache
def _pool() -> ConnectionPool:
    return ConnectionPool(
        get_settings().sync_database_url, min_size=1, max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=True,
    )


@lru_cache
def get_checkpointer() -> PostgresSaver:
    saver = PostgresSaver(_pool())
    saver.setup()
    return saver


@lru_cache
def get_graph():
    from app.agent.deps import default_deps

    return build_graph(default_deps(), get_checkpointer())
