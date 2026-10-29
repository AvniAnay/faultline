"""TemplateMiner interface over Drain3. One global miner; identity = (service, cluster id)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from drain3 import TemplateMiner as _Drain3Miner
from drain3.masking import MaskingInstruction
from drain3.persistence_handler import PersistenceHandler
from drain3.template_miner_config import TemplateMinerConfig

from app.redaction.engine import RedactedText, require_redacted

# Order matters: most specific first. Redaction placeholders (<IP>, <HOST>...) are left as-is
# so Drain3 treats them as fixed tokens.
MASKS = [
    ("UUID", r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    ("HEX", r"0x[0-9a-fA-F]+"),
    ("DURATION", r"\d+(?:\.\d+)?(?:ms|s|m|h)"),
    ("PATH", r"(?:/[\w.@-]+){2,}"),
    ("NUM", r"[-+]?\d+(?:\.\d+)?"),
]


@dataclass(frozen=True)
class MinedLine:
    cluster_id: int
    is_new_cluster: bool


class TemplateMiner(ABC):
    @abstractmethod
    def add(self, text: RedactedText) -> MinedLine:
        """Learn from a line (ingestion only)."""

    @abstractmethod
    def match(self, text: RedactedText) -> int | None:
        """Lookup only: cluster id of a known template, or None."""

    @abstractmethod
    def template(self, cluster_id: int) -> RedactedText:
        """Current template text of a cluster."""

    @abstractmethod
    def save(self) -> None:
        """Persist state."""


class _Drain3(_Drain3Miner):
    def get_snapshot_reason(self, change_type, cluster_id):  # type: ignore[override]
        return None  # we save explicitly once per run


class Drain3Miner(TemplateMiner):
    def __init__(self, persistence: PersistenceHandler | None = None) -> None:
        cfg = TemplateMinerConfig()
        cfg.drain_sim_th = 0.4
        cfg.drain_depth = 4
        cfg.drain_max_children = 100
        cfg.masking_instructions = [MaskingInstruction(p, name) for name, p in MASKS]
        self._miner = _Drain3(persistence, cfg)
        self._parents: dict[int, RedactedText] = {}  # a redacted line per cluster, for derive()

    def add(self, text: RedactedText) -> MinedLine:
        result = self._miner.add_log_message(require_redacted(text))
        self._parents[result["cluster_id"]] = text
        return MinedLine(result["cluster_id"], result["change_type"] == "cluster_created")

    def match(self, text: RedactedText) -> int | None:
        cluster = self._miner.match(require_redacted(text))
        return cluster.cluster_id if cluster else None

    def template(self, cluster_id: int) -> RedactedText:
        cluster = self._miner.drain.id_to_cluster[cluster_id]
        # Templates are built solely from redacted lines, so they are safe to wrap.
        return RedactedText.derive(self._parents[cluster_id], cluster.get_template())

    def save(self) -> None:
        self._miner.save_state("run complete")

