"""
Memory Note Schema - A-MEM Zettelkasten-inspired
Roland Fleet Agentic Memory Architecture V1.0
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Content(BaseModel):
    """Raw content and source metadata"""

    raw: str
    source_type: str  # conversation | task_output | ingestion | observation
    source_ref: str  # subagent:task_id or conversation:session_id
    previous_raw: str | None = None  # Original content before evolution (for rollback)


class Semantic(BaseModel):
    """LLM-generated semantic enrichment"""

    context: str  # One-sentence contextual summary
    keywords: list[str] = Field(default_factory=list, max_length=7)
    tags: list[str] = Field(default_factory=list, max_length=5)
    entities: list[str] = Field(default_factory=list)


class Embedding(BaseModel):
    """Embedding vector and metadata"""

    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    vector: list[float] = Field(default_factory=list)
    dimensions: int = 768
    input_hash: str = ""  # SHA256 of concatenated text fields


class Links(BaseModel):
    """Conceptual links to other notes"""

    related: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    supersedes: list[str] = Field(default_factory=list)  # Notes this note supersedes
    causal_chain: list[str] = Field(default_factory=list)


class VulnerabilityMeta(BaseModel):
    """Structured CVE scoring fields — populated during OpenCTI sync, not text extraction.

    Mirrors the subset of OpenCTI's 32 CVSS fields that ZettelForge needs for
    prioritisation workflows: base score, vector string, EPSS exploitation
    probability, and CISA KEV membership.
    """

    cvss_v3_score: float | None = None  # 0.0–10.0; None if not yet scored
    cvss_v3_vector: str | None = None  # e.g. "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    epss_score: float | None = None  # 0.0–1.0, daily exploitation probability
    epss_percentile: float | None = None  # 0.0–1.0, relative to all scored CVEs
    cisa_kev: bool = False  # True if in CISA Known Exploited Vulnerabilities catalog


class Metadata(BaseModel):
    """Note lifecycle and access metadata"""

    access_count: int = 0
    last_accessed: str | None = None
    evolution_count: int = 0
    confidence: float = 1.0  # Decays for inferred/evolved content
    ttl: int | None = None  # Time-to-live in days
    domain: str = "general"  # security_ops | project | personal | research
    persistence_semantics: str = "memory"  # knowledge, memory, wisdom, intelligence
    ttl_anchor: str | None = None  # ISO timestamp for TTL calculation (set on backfill)
    tier: str = "B"  # Epistemic tier: A (authoritative) | B (operational) | C (support)
    importance: int = 5  # 1-10 scale, used by extraction phase for prioritization
    tlp: str = ""  # TLP marking: WHITE, GREEN, AMBER, RED, or empty (unclassified)
    stix_confidence: int = -1  # STIX confidence 0-100, -1 = unset
    vuln: VulnerabilityMeta | None = None  # Populated for CVE notes during OpenCTI sync


class MemoryNote(BaseModel):
    """Complete memory note schema"""

    id: str  # note_YYYYMMDD_HHMMSS_xxxx
    version: int = 1
    created_at: str  # ISO 8601 timestamp
    updated_at: str  # ISO 8601 timestamp
    evolved_from: str | None = None
    evolved_by: list[str] = Field(default_factory=list)

    content: Content
    semantic: Semantic
    embedding: Embedding
    links: Links = Field(default_factory=Links)
    metadata: Metadata = Field(default_factory=Metadata)

    def increment_access(self):
        """Track note access for maintenance decisions"""
        self.metadata.access_count += 1
        self.metadata.last_accessed = datetime.now().isoformat()

    def increment_evolution(self, evolved_by_note_id: str | None = None):
        """Record evolution event"""
        self.metadata.evolution_count += 1
        if evolved_by_note_id:
            self.evolved_by.append(evolved_by_note_id)
        self.updated_at = datetime.now().isoformat()
        # Confidence decay: evolved notes lose confidence
        self.metadata.confidence = min(self.metadata.confidence, 0.95)

    def should_flag_for_review(self) -> bool:
        """Check if note should be flagged for human review"""
        return self.metadata.confidence < 0.5 or self.metadata.evolution_count > 5

    def is_expired(self, ttl_days: dict[str, int] | None = None) -> bool:
        """Check if this note has expired based on its persistence semantics.

        Args:
            ttl_days: Override TTL per type. Defaults:
                knowledge=None (never), memory=30, wisdom=90, intelligence=7
        """
        defaults: dict[str, int | None] = {
            "knowledge": None,
            "memory": 30,
            "wisdom": 90,
            "intelligence": 7,
        }
        ttls: dict[str, int | None] = {**defaults, **(ttl_days or {})}

        ttl = ttls.get(self.metadata.persistence_semantics)
        if ttl is None:
            return False  # knowledge never expires

        anchor = self.metadata.ttl_anchor or self.created_at
        if not anchor:
            return False

        try:
            anchor_dt = datetime.fromisoformat(anchor)
            last_access = datetime.fromisoformat(self.updated_at) if self.updated_at else anchor_dt
            # TTL resets on access
            effective_anchor = max(anchor_dt, last_access)
            age_days = (datetime.now() - effective_anchor).days
            return age_days > ttl
        except (ValueError, TypeError):
            return False

    @staticmethod
    def infer_persistence(source_type: str, domain: str = "") -> str:
        """Infer persistence semantics from source type and domain."""
        if source_type in ("ingestion", "report") and domain == "cti":
            return "knowledge"
        if source_type == "synthesis":
            return "wisdom"
        if source_type == "task_output" and domain != "cti":
            return "intelligence"
        return "memory"  # default for conversation, mcp, unknown
