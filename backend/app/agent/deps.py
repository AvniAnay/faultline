from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agent.llm import GroqLLM, StructuredLLM
from app.agent.search import TavilyWebSearch, WebSearch
from app.config import Settings, get_settings
from app.db.session import new_session
from app.notify.email_sender import EmailSender, LogEmailSender


@dataclass
class Deps:
    settings: Settings
    llm: StructuredLLM
    search: WebSearch
    session_factory: Callable[[], Session]
    email: EmailSender


def default_deps() -> Deps:
    s = get_settings()
    return Deps(s, GroqLLM(s), TavilyWebSearch(s), new_session, LogEmailSender())
