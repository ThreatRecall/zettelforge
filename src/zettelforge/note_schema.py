"""
Memory Note Schema - A-MEM Zettelkasten-inspired
Roland Fleet Agentic Memory Architecture V1.0
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Content(BaseModel):
    """Raw content and source metadata"""

    raw: str
    source_type: str  # conversation | task_output | ingestion | observation
    source_ref: str  # subagent:task_id or conversation:session_id


class Semantic(BaseModel):
    """LLM-generated semantic enrichment"""

    context: str  # One-sentence contextual summary
    keywords: List[str] = Field(default_factory=list, max_length=7)
    tags: List[str] = Field(default_factory=list, max_length=5)
    entities: List[str] = Field(default_factory=list)


class Embedding(BaseModel):
    """Embedding vector and metadata"""

    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    vector: List[float] = Field(default_factory=list)
    dimensions: int = 768
    input_hash: str = ""  # SHA256 of concatenated text fields


class Links(BaseModel):
    """Conceptual links to other notes"""

    related: List[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    supersedes: List[str] = Field(default_factory=list)  # Notes this note supersedes
    causal_chain: List[str] = Field(default_factory=list)


class VulnerabilityMeta(BaseModel):
    """Structured CVE scoring fields — populated during OpenCTI sync, not text extraction.

    Mirrors the subset of OpenCTI's 32 CVSS fields that ZettelForge needs for
    prioritisation workflows: base score, vector string, EPSS exploitation
    probability, and CISA KEV membership.
    """

    cvss_v3_score: Optional[float] = None  # 0.0–10.0; None if not yet scored
    cvss_v3_vector: Optional[str] = None  # e.g. "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    epss_score: Optional[float] = None  # 0.0–1.0, daily exploitation probability
    epss_percentile: Optional[float] = None  # 0.0–1.0, relative to all scored CVEs
    cisa_kev: bool = False  # True if in CISA Known Exploited Vulnerabilities catalog


class Tier(str):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    FROZEN = "frozen"


class Metadata(BaseModel):
    """Note lifecycle and access metadata"""

    access_count: int = 0
    last_accessed: Optional[str] = None
    evolution_count: int = 0
    confidence: float = 1.0  # Decays for inferred/evolved content
    ttl: Optional[int] = None  # Time-to-live in days
    domain: str = "general"  # security_ops | project | personal | research
    tier: str = "B"  # Epistemic tier: A (authoritative) | B (operational) | C (support)
    importance: int = 5  # 1-10 scale, used by extraction phase for prioritization
    tlp: str = ""  # TLP marking: WHITE, GREEN, AMBER, RED, or empty (unclassified)
    stix_confidence: int = -1  # STIX confidence 0-100, -1 = unset
    vuln: Optional[VulnerabilityMeta] = None  # Populated for CVE notes during OpenCTI sync

    # ── RFC-008: Memory Salience & Spacing Effect ──────────────────────────
    # Salience (Von Restorff): how distinctive and high-signal this note is
    salience_score: float = 0.5  # 0.0–1.0, default neutral
    salience_breakdown: dict = Field(default_factory=dict)  # {distinctiveness, signal_weight, isolation}
    last_salience_update: Optional[str] = None  # ISO 8601, recomputed on entity update + weekly batch

    # Spacing (Reinforcement): confirmed retrievals strengthen memory
    reinforcement_counter: int = 0  # Times analyst confirmed retrieval was useful
    memory_tier: str = Tier.WARM  # hot | warm | cold | frozen; drives retrieval priority


class MemoryNote(BaseModel):
    """Complete memory note schema"""

    id: str  # note_YYYYMMDD_HHMMSS_xxxx
    version: int = 1
    created_at: str  # ISO 8601 timestamp
    updated_at: str  # ISO 8601 timestamp
    evolved_from: Optional[str] = None
    evolved_by: List[str] = Field(default_factory=list)

    content: Content
    semantic: Semantic
    embedding: Embedding
    links: Links = Field(default_factory=Links)
    metadata: Metadata = Field(default_factory=Metadata)

    def increment_access(self):
        """Track note access for maintenance decisions"""
        self.metadata.access_count += 1
        self.metadata.last_accessed = datetime.now().isoformat()

    def increment_evolution(self, evolved_by_note_id: str):
        """Record evolution event"""
        self.metadata.evolution_count += 1
        self.evolved_by.append(evolved_by_note_id)
        # Confidence decay: evolved notes lose confidence
        self.metadata.confidence = min(self.metadata.confidence, 0.95)

    def should_flag_for_review(self) -> bool:
        """Check if note should be flagged for human review"""
        return self.metadata.confidence < 0.5 or self.metadata.evolution_count > 5
