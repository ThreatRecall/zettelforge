"""
ZettelForge Configuration Loader

Resolution order (highest priority first):
  1. Environment variables (ZETTELFORGE_*, TYPEDB_*, AMEM_*)
  2. config.yaml in working directory
  3. config.yaml in project root
  4. config.default.yaml in project root
  5. Hardcoded defaults in this module

Usage:
    from zettelforge.config import get_config
    cfg = get_config()
    cfg.typedb.host       # "localhost"
    cfg.embedding.url     # "http://127.0.0.1:11434"
    cfg.retrieval.default_k  # 10
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from zettelforge.log import get_logger


@dataclass
class StorageConfig:
    data_dir: str = "~/.amem"


@dataclass
class TypeDBConfig:
    host: str = "localhost"
    port: int = 1729
    database: str = "zettelforge"
    username: str = "admin"
    password: str = "password"


@dataclass
class EmbeddingConfig:
    provider: str = "fastembed"  # "fastembed" (in-process ONNX) or "ollama" (HTTP server)
    url: str = "http://127.0.0.1:11434"  # only used when provider=ollama
    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    dimensions: int = 768


@dataclass
class LLMConfig:
    provider: str = "ollama"  # "local" (llama-cpp-python, in-process) or "ollama" (HTTP server)
    model: str = "qwen3.5:9b"  # Ollama model name, or HuggingFace repo for local provider
    url: str = "http://localhost:11434"  # only used when provider=ollama
    temperature: float = 0.1


@dataclass
class ExtractionConfig:
    max_facts: int = 5
    min_importance: int = 3


@dataclass
class RetrievalConfig:
    default_k: int = 10
    similarity_threshold: float = 0.25
    entity_boost: float = 2.5
    max_graph_depth: int = 2


@dataclass
class SynthesisConfig:
    max_context_tokens: int = 3000
    default_format: str = "direct_answer"
    tier_filter: List[str] = field(default_factory=lambda: ["A", "B"])


@dataclass
class GovernanceConfig:
    enabled: bool = True
    min_content_length: int = 1


@dataclass
class CacheConfig:
    ttl_seconds: int = 300
    max_entries: int = 1024


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_intents: bool = True
    log_causal: bool = True
    log_file: str = ""  # Default set at runtime from data_dir
    audit_log_file: str = ""  # Default set at runtime from data_dir
    log_to_stdout: bool = True
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 9
    audit_backup_count: int = 52  # ~1 year at 10MB per file


# ── RFC-008: Memory Salience & Spacing Effect ───────────────────────────────────



@dataclass
class SalienceConfig:
    """Von Restorff Effect: distinctive memories are remembered better.

    Salience boosts high-signal CTI entities (APT groups, malware) in retrieval
    independent of reinforcement. Computed from distinctiveness, signal weight,
    and cluster isolation.
    """

    enabled: bool = True  # Cognitive Science Purist default
    distinctiveness_weight: float = 0.4
    signal_weight: float = 0.4
    isolation_weight: float = 0.2
    recompute_interval_days: int = 7  # Weekly batch recompute
    recompute_batch_size: int = 500  # Avoid memory spikes



@dataclass
class SpacingConfig:
    """Spacing Effect: distributed reinforcement strengthens memory over time.

    Each confirmed retrieval bumps the reinforcement counter, which increases
    effective memory strength via a diminishing-returns curve (Ebbinghaus).
    """
    enabled: bool = True  # Cognitive Science Purist default
    half_life_days: int = 30  # Memory half-life
    reinforcement_factor: float = 0.1  # 0.1 bonus per confirmation (diminishing via sqrt)
    decay_rate: float = 0.02  # e^(-decay_rate × age_days); 50% at ~35 days
    implicit_confirm_window_hours: int = 24  # No edit within 24h = implicit confirm
    reinforcement_threshold: int = 3  # Min confirmations before note is "hot"
    max_strength: float = 1.0  # Cap at 1.0


@dataclass
class DecayConfig:
    """Tiered Decay: hot memories stay fast, cold ones archive.

    Manages storage cost and retrieval performance by routing notes into
    hot/warm/cold/frozen tiers based on reinforcement count and access recency.
    """
    enabled: bool = True  # Cognitive Science Purist default
    hot_threshold: int = 3  # Min reinforcements for HOT
    hot_max_age_days: int = 7  # HOT → WARM after 7 days regardless
    warm_threshold_days: int = 30  # WARM → COLD after 30 days
    frozen_threshold_days: int = 90  # COLD → FROZEN after 90 days
    relevance_freeze_threshold: float = 0.1  # Frozen if salience < 0.1
    tier_update_batch_size: int = 500

    tier_update_schedule: str = "0 3 * * *"  # Daily 3am


@dataclass
class RetrievalWeightsConfig:
    """Retrieval weight configuration for RFC-008.

    Controls how salience scores and memory tiers affect blended retrieval
    ranking. HOT notes get full weight; frozen notes are excluded.
    """
    salience_weight: float = 0.5  # How much salience boosts retrieval
    tier_hot_multiplier: float = 1.0
    tier_warm_multiplier: float = 0.5
    tier_cold_multiplier: float = 0.1
    tier_frozen_multiplier: float = 0.0  # FROZEN excluded


@dataclass
class EnterpriseConfig:
    """Enterprise edition settings (ignored in Community)."""

    license_key: str = ""
    blended_retrieval: bool = True
    cross_encoder_reranking: bool = True
    report_ingestion: bool = True
    multi_tenant: bool = False


@dataclass
class OpenCTIConfig:
    """OpenCTI integration settings (Enterprise edition only)."""

    url: str = "http://localhost:8080"
    token: str = ""
    sync_interval: int = 0  # seconds, 0 = disabled


@dataclass
class ZettelForgeConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    typedb: TypeDBConfig = field(default_factory=TypeDBConfig)
    backend: str = "typedb"
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    enterprise: EnterpriseConfig = field(default_factory=EnterpriseConfig)
    opencti: OpenCTIConfig = field(default_factory=OpenCTIConfig)
    salience: SalienceConfig = field(default_factory=SalienceConfig)
    spacing: SpacingConfig = field(default_factory=SpacingConfig)
    decay: DecayConfig = field(default_factory=DecayConfig)
    retrieval_weights: RetrievalWeightsConfig = field(default_factory=RetrievalWeightsConfig)


def _find_config_file() -> Optional[Path]:
    """Find config.yaml in standard locations."""
    candidates = [
        Path("config.yaml"),
        Path("config.yml"),
        Path(__file__).parent.parent.parent / "config.yaml",
        Path(__file__).parent.parent.parent / "config.yml",
        Path(__file__).parent.parent.parent / "config.default.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _load_yaml(path: Path) -> dict:
    """Load YAML file, return empty dict on failure."""
    try:
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fall back to basic parsing if PyYAML not installed
        return _parse_simple_yaml(path)
    except Exception:
        get_logger("zettelforge.config").warning("yaml_config_parse_failed", exc_info=True)
        return {}


def _save_yaml(data: dict, path: Path):
    """Save dict as YAML to path (used by config PUT endpoint)."""
    import yaml

    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)



def _parse_simple_yaml(path: Path) -> dict:
    """Minimal YAML parser for flat key: value pairs (no PyYAML dependency)."""
    result = {}
    current_section = None
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not line.startswith(" ") and stripped.endswith(":"):
                current_section = stripped[:-1]
                result[current_section] = {}
            elif current_section and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                # Parse basic types
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                elif value.startswith("[") or value.startswith("-"):
                    continue  # Skip lists in simple parser
                else:
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                result[current_section][key] = value
            elif ":" in stripped and current_section is None:
                key, _, value = stripped.partition(":")
                result[key.strip()] = value.strip()
    return result


def _apply_yaml(cfg: ZettelForgeConfig, data: dict):
    """Apply YAML dict to config dataclass."""
    if "storage" in data and isinstance(data["storage"], dict):
        for k, v in data["storage"].items():
            if hasattr(cfg.storage, k):
                setattr(cfg.storage, k, v)

    if "typedb" in data and isinstance(data["typedb"], dict):
        for k, v in data["typedb"].items():
            if hasattr(cfg.typedb, k):
                setattr(cfg.typedb, k, v)

    if "backend" in data:
        cfg.backend = str(data["backend"])

    if "embedding" in data and isinstance(data["embedding"], dict):
        for k, v in data["embedding"].items():
            if hasattr(cfg.embedding, k):
                setattr(cfg.embedding, k, v)

    if "llm" in data and isinstance(data["llm"], dict):
        for k, v in data["llm"].items():
            if hasattr(cfg.llm, k):
                setattr(cfg.llm, k, v)

    if "extraction" in data and isinstance(data["extraction"], dict):
        for k, v in data["extraction"].items():
            if hasattr(cfg.extraction, k):
                setattr(cfg.extraction, k, v)

    if "retrieval" in data and isinstance(data["retrieval"], dict):
        for k, v in data["retrieval"].items():
            if hasattr(cfg.retrieval, k):
                setattr(cfg.retrieval, k, v)

    if "synthesis" in data and isinstance(data["synthesis"], dict):
        for k, v in data["synthesis"].items():
            if hasattr(cfg.synthesis, k):
                setattr(cfg.synthesis, k, v)

    if "governance" in data and isinstance(data["governance"], dict):
        for k, v in data["governance"].items():
            if hasattr(cfg.governance, k):
                setattr(cfg.governance, k, v)

    if "cache" in data and isinstance(data["cache"], dict):
        for k, v in data["cache"].items():
            if hasattr(cfg.cache, k):
                setattr(cfg.cache, k, v)

    if "logging" in data and isinstance(data["logging"], dict):
        for k, v in data["logging"].items():
            if hasattr(cfg.logging, k):
                setattr(cfg.logging, k, v)

    if "enterprise" in data and isinstance(data["enterprise"], dict):
        for k, v in data["enterprise"].items():
            if hasattr(cfg.enterprise, k):
                setattr(cfg.enterprise, k, v)

    if "opencti" in data and isinstance(data["opencti"], dict):
        for k, v in data["opencti"].items():
            if hasattr(cfg.opencti, k):
                setattr(cfg.opencti, k, v)

    if "salience" in data and isinstance(data["salience"], dict):
        for k, v in data["salience"].items():
            if hasattr(cfg.salience, k):
                setattr(cfg.salience, k, v)

    if "spacing" in data and isinstance(data["spacing"], dict):
        for k, v in data["spacing"].items():
            if hasattr(cfg.spacing, k):
                setattr(cfg.spacing, k, v)

    if "decay" in data and isinstance(data["decay"], dict):
        for k, v in data["decay"].items():
            if hasattr(cfg.decay, k):
                setattr(cfg.decay, k, v)

    if "retrieval_weights" in data and isinstance(data["retrieval_weights"], dict):
        for k, v in data["retrieval_weights"].items():
            if hasattr(cfg.retrieval_weights, k):
                setattr(cfg.retrieval_weights, k, v)


def _apply_env(cfg: ZettelForgeConfig):
    """Apply environment variable overrides (highest priority)."""
    # Storage
    if v := os.environ.get("AMEM_DATA_DIR"):
        cfg.storage.data_dir = v

    # TypeDB
    if v := os.environ.get("TYPEDB_HOST"):
        cfg.typedb.host = v
    if v := os.environ.get("TYPEDB_PORT"):
        cfg.typedb.port = int(v)
    if v := os.environ.get("TYPEDB_DATABASE"):
        cfg.typedb.database = v
    if v := os.environ.get("TYPEDB_USERNAME"):
        cfg.typedb.username = v
    if v := os.environ.get("TYPEDB_PASSWORD"):
        cfg.typedb.password = v

    # Backend
    if v := os.environ.get("ZETTELFORGE_BACKEND"):
        cfg.backend = v

    # Embedding
    if v := os.environ.get("ZETTELFORGE_EMBEDDING_PROVIDER"):
        cfg.embedding.provider = v
    if v := os.environ.get("AMEM_EMBEDDING_URL"):
        cfg.embedding.url = v
    if v := os.environ.get("AMEM_EMBEDDING_MODEL"):
        cfg.embedding.model = v

    # LLM
    if v := os.environ.get("ZETTELFORGE_LLM_PROVIDER"):
        cfg.llm.provider = v
    if v := os.environ.get("ZETTELFORGE_LLM_MODEL"):
        cfg.llm.model = v
    if v := os.environ.get("ZETTELFORGE_LLM_URL"):
        cfg.llm.url = v

    # Enterprise
    if v := os.environ.get("THREATENGRAM_LICENSE_KEY"):
        cfg.enterprise.license_key = v

    # OpenCTI
    if os.environ.get("OPENCTI_URL"):
        cfg.opencti.url = os.environ["OPENCTI_URL"]
    if os.environ.get("OPENCTI_TOKEN"):
        cfg.opencti.token = os.environ["OPENCTI_TOKEN"]
    if os.environ.get("OPENCTI_SYNC_INTERVAL"):
        cfg.opencti.sync_interval = int(os.environ["OPENCTI_SYNC_INTERVAL"])


# ── Singleton ──────────────────────────────────────────────

_config: Optional[ZettelForgeConfig] = None


def get_config() -> ZettelForgeConfig:
    """Get global configuration. Loads once, caches thereafter."""
    global _config
    if _config is None:
        _config = ZettelForgeConfig()

        # Layer 1: config file
        config_file = _find_config_file()
        if config_file:
            data = _load_yaml(config_file)
            _apply_yaml(_config, data)

        # Layer 2: environment variables (override)
        _apply_env(_config)

    return _config


def reload_config() -> ZettelForgeConfig:
    """Force reload configuration from file + environment."""
    global _config
    _config = None
    return get_config()
