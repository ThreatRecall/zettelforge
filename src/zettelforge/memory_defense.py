"""Write-time memory poisoning defenses.

Implements the first SEC-011 / MemSAD-inspired control: score a candidate
memory before it is persisted, using recent trusted memories as calibration.
Default mode is audit-only; block/quarantine can be enabled by config once a
site has a clean calibration corpus.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zettelforge.config import MemoryDefenseConfig, get_config
from zettelforge.log import get_logger
from zettelforge.memory_store import get_default_data_dir

_logger = get_logger("zettelforge.memory_defense")
_VALID_MODES = {"audit", "block", "quarantine"}


class MemoryAnomalyError(RuntimeError):
    """Raised when memory defense blocks or quarantines a write."""

    def __init__(self, message: str, decision: MemoryAnomalyDecision) -> None:
        super().__init__(message)
        self.decision = decision


@dataclass
class MemoryAnomalyDecision:
    """Decision metadata for a single memory-write anomaly evaluation."""

    enabled: bool
    mode: str
    action: str
    flagged: bool
    reason: str
    content_hash: str
    score: float | None = None
    threshold: float | None = None
    memsad_score: float | None = None
    lexical_jsd: float | None = None
    max_similarity: float | None = None
    mean_similarity: float | None = None
    calibration_mean: float | None = None
    calibration_std: float | None = None
    reference_count: int = 0

    @property
    def should_stop_write(self) -> bool:
        return self.flagged and self.mode in {"block", "quarantine"}

    def as_event_fields(self) -> dict[str, Any]:
        return asdict(self)


class MemoryAnomalyGate:
    """MemSAD-style write-time anomaly scorer.

    The embedding score mirrors the MemSAD shape:

    ``0.5 * max_similarity(candidate, refs) + 0.5 * mean_similarity(candidate, refs)``

    A character n-gram Jensen-Shannon divergence term is added to reduce the
    synonym/paraphrase loophole called out in SEC-011. Calibration uses the
    same composite score in leave-one-out form over the reference notes.
    """

    def __init__(self, config: MemoryDefenseConfig | None = None) -> None:
        self._config = config

    def evaluate(
        self,
        note: Any,
        reference_notes: list[Any],
        *,
        domain: str = "",
        source_type: str = "",
        source_ref: str = "",
        request_id: str = "",
    ) -> MemoryAnomalyDecision:
        cfg = self._config or get_config().governance.memory_defense
        mode = (cfg.mode or "audit").lower()
        if mode not in _VALID_MODES:
            mode = "audit"

        raw_content = _note_text(note)
        content_hash = _content_hash(raw_content)
        if not cfg.enabled:
            return MemoryAnomalyDecision(
                enabled=False,
                mode=mode,
                action="allow",
                flagged=False,
                reason="disabled",
                content_hash=content_hash,
            )

        if cfg.monitored_domains and domain not in cfg.monitored_domains:
            return MemoryAnomalyDecision(
                enabled=True,
                mode=mode,
                action="allow",
                flagged=False,
                reason="domain_not_monitored",
                content_hash=content_hash,
            )

        candidate_vector = _note_vector(note)
        if not _valid_vector(candidate_vector):
            decision = MemoryAnomalyDecision(
                enabled=True,
                mode=mode,
                action="audit",
                flagged=False,
                reason="candidate_embedding_unavailable",
                content_hash=content_hash,
            )
            self._log_decision(decision, domain, source_type, source_ref, request_id)
            return decision

        refs = _select_reference_notes(note, reference_notes, cfg.max_reference_notes)
        if len(refs) < cfg.min_calibration_notes:
            decision = MemoryAnomalyDecision(
                enabled=True,
                mode=mode,
                action="audit",
                flagged=False,
                reason="calibration_insufficient",
                content_hash=content_hash,
                reference_count=len(refs),
            )
            self._log_decision(decision, domain, source_type, source_ref, request_id)
            return decision

        calibration_scores = _calibration_scores(refs, cfg)
        if not calibration_scores:
            decision = MemoryAnomalyDecision(
                enabled=True,
                mode=mode,
                action="audit",
                flagged=False,
                reason="calibration_unscorable",
                content_hash=content_hash,
                reference_count=len(refs),
            )
            self._log_decision(decision, domain, source_type, source_ref, request_id)
            return decision

        memsad_score, max_similarity, mean_similarity = _memsad_score(candidate_vector, refs)
        lexical_jsd = _lexical_jsd(raw_content, [_note_text(ref) for ref in refs], cfg.ngram_size)
        score = memsad_score + (cfg.lexical_weight * lexical_jsd)

        calibration_mean = sum(calibration_scores) / len(calibration_scores)
        calibration_std = _stddev(calibration_scores, calibration_mean)
        threshold = calibration_mean + (float(cfg.kappa) * calibration_std)
        flagged = score > threshold
        action = mode if flagged and mode in {"block", "quarantine"} else "audit"

        decision = MemoryAnomalyDecision(
            enabled=True,
            mode=mode,
            action=action,
            flagged=flagged,
            reason="score_above_threshold" if flagged else "score_within_threshold",
            content_hash=content_hash,
            score=score,
            threshold=threshold,
            memsad_score=memsad_score,
            lexical_jsd=lexical_jsd,
            max_similarity=max_similarity,
            mean_similarity=mean_similarity,
            calibration_mean=calibration_mean,
            calibration_std=calibration_std,
            reference_count=len(refs),
        )
        self._log_decision(decision, domain, source_type, source_ref, request_id)
        return decision

    def enforce(
        self,
        note: Any,
        reference_notes: list[Any],
        *,
        domain: str = "",
        source_type: str = "",
        source_ref: str = "",
        request_id: str = "",
    ) -> MemoryAnomalyDecision:
        decision = self.evaluate(
            note,
            reference_notes,
            domain=domain,
            source_type=source_type,
            source_ref=source_ref,
            request_id=request_id,
        )
        if decision.should_stop_write:
            if decision.mode == "quarantine":
                self._write_quarantine(note, decision, domain, source_type, source_ref, request_id)
            raise MemoryAnomalyError(
                f"memory write {decision.action}ed by anomaly defense: "
                f"score={decision.score:.4f} threshold={decision.threshold:.4f}",
                decision,
            )
        return decision

    def _write_quarantine(
        self,
        note: Any,
        decision: MemoryAnomalyDecision,
        domain: str,
        source_type: str,
        source_ref: str,
        request_id: str,
    ) -> None:
        cfg = self._config or get_config().governance.memory_defense
        path = Path(os.path.expanduser(cfg.quarantine_path)) if cfg.quarantine_path else None
        if path is None:
            path = get_default_data_dir() / "quarantine" / "memory_anomalies.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "domain": domain,
            "source_type": source_type,
            "source_ref": source_ref,
            "note_id": getattr(note, "id", ""),
            "decision": decision.as_event_fields(),
        }
        if cfg.quarantine_raw_content:
            record["raw_content"] = _note_text(note)

        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(record, default=str) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)

    def _log_decision(
        self,
        decision: MemoryAnomalyDecision,
        domain: str,
        source_type: str,
        source_ref: str,
        request_id: str,
    ) -> None:
        fields = decision.as_event_fields()
        fields.update(
            {
                "domain": domain,
                "source_type": source_type,
                "source_ref": source_ref,
                "request_id": request_id,
            }
        )
        if decision.flagged:
            _logger.warning("memory_anomaly_detected", **fields)
        elif decision.enabled:
            _logger.debug("memory_anomaly_evaluated", **fields)


def _select_reference_notes(candidate: Any, notes: list[Any], limit: int) -> list[Any]:
    candidate_id = getattr(candidate, "id", "")
    refs = [
        note
        for note in notes
        if getattr(note, "id", "") != candidate_id and _valid_vector(_note_vector(note))
    ]
    refs.sort(key=lambda n: getattr(n, "created_at", "") or "", reverse=True)
    return refs[: max(0, int(limit))]


def _calibration_scores(notes: list[Any], cfg: MemoryDefenseConfig) -> list[float]:
    scores: list[float] = []
    for i, note in enumerate(notes):
        refs = notes[:i] + notes[i + 1 :]
        if not refs:
            continue
        memsad_score, _, _ = _memsad_score(_note_vector(note), refs)
        lexical_jsd = _lexical_jsd(
            _note_text(note), [_note_text(ref) for ref in refs], cfg.ngram_size
        )
        scores.append(memsad_score + (cfg.lexical_weight * lexical_jsd))
    return scores


def _memsad_score(candidate_vector: list[float], refs: list[Any]) -> tuple[float, float, float]:
    similarities = [_cosine(candidate_vector, _note_vector(ref)) for ref in refs]
    if not similarities:
        return 0.0, 0.0, 0.0
    max_similarity = max(similarities)
    mean_similarity = sum(similarities) / len(similarities)
    return 0.5 * max_similarity + 0.5 * mean_similarity, max_similarity, mean_similarity


def _cosine(a: list[float], b: list[float]) -> float:
    if not _valid_vector(a) or not _valid_vector(b) or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _stddev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _lexical_jsd(text: str, reference_texts: list[str], ngram_size: int) -> float:
    candidate = _ngram_counts(text, ngram_size)
    reference = Counter()
    for ref_text in reference_texts:
        reference.update(_ngram_counts(ref_text, ngram_size))
    return _jensen_shannon(candidate, reference)


def _ngram_counts(text: str, ngram_size: int) -> Counter[str]:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return Counter()
    n = max(1, int(ngram_size))
    if len(normalized) <= n:
        return Counter([normalized])
    return Counter(normalized[i : i + n] for i in range(0, len(normalized) - n + 1))


def _jensen_shannon(left: Counter[str], right: Counter[str]) -> float:
    if not left and not right:
        return 0.0
    if not left or not right:
        return 1.0
    left_total = sum(left.values())
    right_total = sum(right.values())
    keys = set(left) | set(right)
    divergence = 0.0
    for key in keys:
        p = left[key] / left_total
        q = right[key] / right_total
        m = 0.5 * (p + q)
        if p:
            divergence += 0.5 * p * math.log2(p / m)
        if q:
            divergence += 0.5 * q * math.log2(q / m)
    return min(1.0, max(0.0, divergence))


def _note_vector(note: Any) -> list[float]:
    embedding = getattr(note, "embedding", None)
    vector = getattr(embedding, "vector", None)
    return vector if isinstance(vector, list) else []


def _note_text(note: Any) -> str:
    content = getattr(note, "content", None)
    raw = getattr(content, "raw", "")
    return raw if isinstance(raw, str) else str(raw)


def _valid_vector(vector: list[float] | None) -> bool:
    if not isinstance(vector, list) or not vector:
        return False
    try:
        return any(float(v) != 0.0 for v in vector)
    except (TypeError, ValueError):
        return False


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
