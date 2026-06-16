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

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zettelforge.log import get_logger

# Matches ${VAR_NAME} references used to inject secrets from the
# environment into config values without storing them in YAML.
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_refs(value: str) -> str:
    """Replace ``${VAR}`` references in ``value`` with environment values.

    Unresolved references emit a WARNING log and are replaced with the
    empty string so misconfigured deployments fail fast at auth time
    rather than silently shipping the literal ``${...}`` token.
    """

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            get_logger("zettelforge.config").warning(
                "env_var_not_found",
                var=var_name,
                hint=f"Set {var_name} in your environment",
            )
            return ""
        return env_value

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _env_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _parse_env_int(name: str, value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        get_logger("zettelforge.config").warning(
            "invalid_env_int",
            name=name,
            value=value,
            hint="Must be an int",
        )
        return None


@dataclass
class StorageConfig:
    data_dir: str = "~/.amem"


@dataclass
class TypeDBConfig:
    host: str = "localhost"
    port: int = 1729
    database: str = "zettelforge"
    username: str = ""  # set via TYPEDB_USERNAME env var or ${TYPEDB_USERNAME} in config.yaml
    password: str = ""  # set via TYPEDB_PASSWORD env var or ${TYPEDB_PASSWORD} in config.yaml

    def __repr__(self) -> str:
        password_display = "'***'" if self.password else "''"
        return (
            f"TypeDBConfig(host={self.host!r}, port={self.port}, "
            f"database={self.database!r}, username={self.username!r}, "
            f"password={password_display})"
        )


@dataclass
class EmbeddingConfig:
    provider: str = "fastembed"  # "fastembed" (in-process ONNX) or "ollama" (HTTP server)
    url: str = "http://127.0.0.1:11434"  # only used when provider=ollama
    model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    dimensions: int = 768
    # ONNX intra-op threads for single-query embedding. Oversubscription on
    # many-core hosts hurts small-batch latency (measured 5.9ms -> 4.5ms at
    # 8 threads on a 20-core GB10). 0 = onnxruntime default.
    threads: int = 8


@dataclass
class LLMConfig:
    """LLM provider configuration (RFC-002, extended by RFC-011).

    ``provider`` selects the backend registered in
    :mod:`zettelforge.llm_providers`. ``api_key`` supports ``${VAR}``
    env-reference syntax and is redacted from ``repr()``.

    ``local_backend`` selects the in-process inference engine when
    ``provider`` is ``"local"``. Options: ``"llama-cpp-python"`` (default)
    or ``"onnxruntime-genai"``. Ignored for all other providers.
    """

    provider: str = "ollama"
    model: str = "qwen3.5:9b"
    url: str = "http://localhost:11434"
    api_key: str = ""  # supports ${ENV_VAR} references — never commit raw keys
    temperature: float = 0.1
    timeout: float = 180.0  # v2.5.2: bumped from 60s — reasoning models at higher num_predict (4000 for causal triples) routinely exceed 60s on a 9B at Q4_K_M
    max_retries: int = 2
    fallback: str = ""  # empty preserves implicit local→ollama fallback
    local_backend: str = "llama-cpp-python"  # RFC-011: "llama-cpp-python" or "onnxruntime-genai"
    max_tokens: int = 400
    max_tokens_causal: int = 8000
    max_tokens_synthesis: int = 2500
    max_tokens_extraction: int = 2500
    max_tokens_ner: int = 2500
    max_tokens_evolve: int = 2500
    reasoning_model: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # Keys under ``extra`` that are commonly used for secrets. Matched
    # case-insensitively as substrings so ``openai_api_key``, ``client_secret``,
    # ``auth_token``, ``azure_ad_token``, ``credentials_json`` all redact.
    _SENSITIVE_EXTRA_KEYS = ("key", "token", "secret", "password", "credential", "auth")

    def _redact_extra(self) -> dict[str, Any]:
        """Return ``extra`` with sensitive-looking values replaced by ``'***'``."""
        redacted: dict[str, Any] = {}
        for k, v in self.extra.items():
            k_low = k.lower() if isinstance(k, str) else ""
            if isinstance(v, str) and v and any(s in k_low for s in self._SENSITIVE_EXTRA_KEYS):
                redacted[k] = "***"
            else:
                redacted[k] = v
        return redacted

    def __repr__(self) -> str:
        # Redact api_key plus any sensitive-looking keys inside ``extra`` so
        # secrets resolved via ``${ENV_VAR}`` refs don't leak into structured
        # logs or debug dumps.
        key_display = "'***'" if self.api_key else "''"
        return (
            f"LLMConfig(provider={self.provider!r}, model={self.model!r}, "
            f"url={self.url!r}, api_key={key_display}, "
            f"temperature={self.temperature}, timeout={self.timeout}, "
            f"max_retries={self.max_retries}, fallback={self.fallback!r}, "
            f"local_backend={self.local_backend!r}, "
            f"max_tokens={self.max_tokens}, "
            f"max_tokens_causal={self.max_tokens_causal}, "
            f"max_tokens_synthesis={self.max_tokens_synthesis}, "
            f"max_tokens_extraction={self.max_tokens_extraction}, "
            f"max_tokens_ner={self.max_tokens_ner}, "
            f"max_tokens_evolve={self.max_tokens_evolve}, "
            f"reasoning_model={self.reasoning_model}, "
            f"extra={self._redact_extra()!r})"
        )


@dataclass
class LLMNerConfig:
    enabled: bool = True  # Always-on LLM NER via background enrichment queue


@dataclass
class EnrichmentConfig:
    enabled: bool = True  # Master switch for background enrichment dispatch


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
    # Cross-encoder rerank policy: the reranker is the dominant read-path
    # cost (ONNX on CPU), so its work is bounded. Tuned on the CTI suite
    # (2026-06-09 grid): accuracy holds at 75% from 512c-50n down to
    # 128c-8n while p50 drops 91ms -> 42ms; 256c-8n picked for headroom.
    rerank_enabled: bool = True
    rerank_max_candidates: int = 8
    rerank_doc_chars: int = 256
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Query entities mapped to more than this many notes carry no retrieval
    # signal (conversational speaker names appear in every session); they
    # are skipped by the graph/entity-augmentation stages.
    entity_max_fanout: int = 25
    # ONNX intra-op threads for the cross-encoder. Small rerank batches
    # thrash when onnxruntime grabs every core (measured 23.7ms -> 11.5ms
    # at 8 threads on a 20-core GB10). 0 = onnxruntime default.
    rerank_threads: int = 8


@dataclass
class SynthesisConfig:
    max_context_tokens: int = 3000
    default_format: str = "direct_answer"
    tier_filter: list[str] = field(default_factory=lambda: ["A", "B"])


@dataclass
class PIIConfig:
    """Presidio PII detection settings (RFC-013, optional).

    Disabled by default -- no new core dependencies. Requires
    ``pip install zettelforge[pii]`` to activate.

    ``action`` can be ``"log"`` (warn only, pass through),
    ``"redact"`` (replace PII with placeholders), or
    ``"block"`` (raise exception before storage).
    ``entities``: empty list = detect all supported PII types.
    ``_CTI_ALLOWLIST`` in ``pii_validator.py`` excludes IP_ADDRESS,
    URL, and DOMAIN_NAME from detection since these are legitimate
    CTI indicators.
    """

    enabled: bool = False
    action: str = "log"
    redact_placeholder: str = "[REDACTED]"
    entities: list[str] = field(default_factory=list)
    language: str = "en"
    nlp_model: str = "en_core_web_sm"


@dataclass
class LimitsConfig:
    """Operation limits for DoS mitigation (RFC-014).

    Values of 0 disable the limit (unlimited).
    """

    max_content_length: int = 52428800  # bytes, 50 MB default
    recall_timeout_seconds: float = 30.0


@dataclass
class MemoryDefenseConfig:
    """Write-time memory poisoning defense settings (SEC-011 / MemSAD)."""

    enabled: bool = True
    mode: str = "audit"  # audit | block | quarantine
    min_calibration_notes: int = 50
    max_reference_notes: int = 50
    kappa: float = 2.0
    lexical_weight: float = 0.25
    ngram_size: int = 3
    monitored_domains: list[str] = field(default_factory=list)  # empty = all domains
    quarantine_path: str = ""
    quarantine_raw_content: bool = True


@dataclass
class GovernanceConfig:
    enabled: bool = True
    min_content_length: int = 1
    pii: PIIConfig = field(default_factory=PIIConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    memory_defense: MemoryDefenseConfig = field(default_factory=MemoryDefenseConfig)


@dataclass
class LanceConfig:
    """LanceDB maintenance settings (RFC-009 Phase 1.5)."""

    # Interval between version-cleanup passes per table. 0 disables cleanup.
    cleanup_interval_minutes: int = 60
    # Versions older than this are eligible for pruning. 0 skips a single
    # iteration (operator-disabled without restarting).
    cleanup_older_than_seconds: int = 3600


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


@dataclass
class ExtensionsConfig:
    """Extensions settings (used by zettelforge-enterprise and similar packages)."""

    license_key: str = ""
    blended_retrieval: bool = True
    cross_encoder_reranking: bool = True
    report_ingestion: bool = True
    multi_tenant: bool = False


@dataclass
class TelemetryConfig:
    """RFC-007 Operational Telemetry settings."""

    enabled: bool = True
    data_dir: str = "~/.amem/telemetry"  # Shared fleet-wide telemetry
    debug: bool = False


@dataclass
class OpenCTIConfig:
    """OpenCTI integration settings (Enterprise edition only)."""

    url: str = "http://localhost:8080"
    token: str = ""
    sync_interval: int = 0  # seconds, 0 = disabled


@dataclass
class WebConfig:
    """Web UI configuration (RFC-015: ZettelForge Web Management Interface).

    Controls the SPA management interface served at GET /.
    """

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8088
    ui_dir: str = ""  # defaults to web/ui/ relative to project root at runtime


@dataclass
class ZettelForgeConfig:
    storage: StorageConfig = field(default_factory=StorageConfig)
    typedb: TypeDBConfig = field(default_factory=TypeDBConfig)
    backend: str = "sqlite"
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    llm_ner: LLMNerConfig = field(default_factory=LLMNerConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    lance: LanceConfig = field(default_factory=LanceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    enterprise: ExtensionsConfig = field(default_factory=ExtensionsConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    opencti: OpenCTIConfig = field(default_factory=OpenCTIConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _find_config_file() -> Path | None:
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
                        with contextlib.suppress(ValueError):
                            value = float(value)
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
                if k in {"username", "password"} and isinstance(v, str):
                    v = _resolve_env_refs(v)
                setattr(cfg.typedb, k, v)

    if "backend" in data:
        cfg.backend = str(data["backend"])

    if "embedding" in data and isinstance(data["embedding"], dict):
        for k, v in data["embedding"].items():
            if hasattr(cfg.embedding, k):
                setattr(cfg.embedding, k, v)

    if "llm" in data and isinstance(data["llm"], dict):
        for k, v in data["llm"].items():
            if not hasattr(cfg.llm, k):
                continue
            # Resolve ${ENV_VAR} refs for sensitive string fields.
            if k == "api_key" and isinstance(v, str):
                v = _resolve_env_refs(v)
            elif k == "extra" and isinstance(v, dict):
                v = {
                    ek: _resolve_env_refs(ev) if isinstance(ev, str) else ev for ek, ev in v.items()
                }
            setattr(cfg.llm, k, v)

    if "llm_ner" in data and isinstance(data["llm_ner"], dict):
        for k, v in data["llm_ner"].items():
            if hasattr(cfg.llm_ner, k):
                setattr(cfg.llm_ner, k, v)

    if "enrichment" in data and isinstance(data["enrichment"], dict):
        for k, v in data["enrichment"].items():
            if hasattr(cfg.enrichment, k):
                setattr(cfg.enrichment, k, v)

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
            if not hasattr(cfg.governance, k):
                continue
            # RFC-013: pii is a nested dataclass, not a flat value
            if k == "pii" and isinstance(v, dict):
                for pk, pv in v.items():
                    if hasattr(cfg.governance.pii, pk):
                        setattr(cfg.governance.pii, pk, pv)
            # RFC-014: limits is a nested dataclass (DoS mitigations)
            elif k == "limits" and isinstance(v, dict):
                for lk, lv in v.items():
                    if hasattr(cfg.governance.limits, lk):
                        setattr(cfg.governance.limits, lk, lv)
            elif k == "memory_defense" and isinstance(v, dict):
                for mk, mv in v.items():
                    if hasattr(cfg.governance.memory_defense, mk):
                        setattr(cfg.governance.memory_defense, mk, mv)
            else:
                setattr(cfg.governance, k, v)

    if "lance" in data and isinstance(data["lance"], dict):
        for k, v in data["lance"].items():
            if hasattr(cfg.lance, k):
                setattr(cfg.lance, k, v)

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
                setattr(cfg.enterprise, k, v)  # "enterprise" key kept for config-file compat

    if "opencti" in data and isinstance(data["opencti"], dict):
        for k, v in data["opencti"].items():
            if hasattr(cfg.opencti, k):
                setattr(cfg.opencti, k, v)

    # RFC-015: web UI config
    if "web" in data and isinstance(data["web"], dict):
        for k, v in data["web"].items():
            if hasattr(cfg.web, k):
                setattr(cfg.web, k, v)


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

    # Telemetry (RFC-007)
    if v := os.environ.get("ZETTELFORGE_TELEMETRY_DIR"):
        cfg.telemetry.data_dir = v
    if v := os.environ.get("ZETTELFORGE_TELEMETRY_DEBUG"):
        cfg.telemetry.debug = v.lower() in ("1", "true", "yes")

    # LLM
    if v := os.environ.get("ZETTELFORGE_LLM_PROVIDER"):
        cfg.llm.provider = v
    if v := os.environ.get("ZETTELFORGE_LLM_MODEL"):
        cfg.llm.model = v
    if v := os.environ.get("ZETTELFORGE_LLM_URL"):
        cfg.llm.url = v
    # RFC-002: api_key / timeout / retries / fallback env overrides.
    if v := os.environ.get("ZETTELFORGE_LLM_API_KEY"):
        cfg.llm.api_key = v
    if v := os.environ.get("ZETTELFORGE_LLM_TIMEOUT"):
        try:
            cfg.llm.timeout = float(v)
        except ValueError:
            get_logger("zettelforge.config").warning(
                "invalid_llm_timeout", value=v, hint="Must be a float"
            )
    if v := os.environ.get("ZETTELFORGE_LLM_MAX_RETRIES"):
        try:
            cfg.llm.max_retries = int(v)
        except ValueError:
            get_logger("zettelforge.config").warning(
                "invalid_llm_max_retries", value=v, hint="Must be an int"
            )
    if v := os.environ.get("ZETTELFORGE_LLM_FALLBACK"):
        cfg.llm.fallback = v

    # RFC-011: local backend selection
    if v := os.environ.get("ZETTELFORGE_LLM_LOCAL_BACKEND"):
        cfg.llm.local_backend = v

    llm_token_env = {
        "ZETTELFORGE_LLM_MAX_TOKENS": "max_tokens",
        "ZETTELFORGE_LLM_MAX_TOKENS_CAUSAL": "max_tokens_causal",
        "ZETTELFORGE_LLM_MAX_TOKENS_SYNTHESIS": "max_tokens_synthesis",
        "ZETTELFORGE_LLM_MAX_TOKENS_EXTRACTION": "max_tokens_extraction",
        "ZETTELFORGE_LLM_MAX_TOKENS_NER": "max_tokens_ner",
        "ZETTELFORGE_LLM_MAX_TOKENS_EVOLVE": "max_tokens_evolve",
    }
    for env_name, attr in llm_token_env.items():
        if v := os.environ.get(env_name):
            parsed = _parse_env_int(env_name, v)
            if parsed is not None:
                setattr(cfg.llm, attr, parsed)
    if v := os.environ.get("ZETTELFORGE_LLM_REASONING_MODEL"):
        cfg.llm.reasoning_model = _env_bool(v)

    # LLM NER
    if v := os.environ.get("ZETTELFORGE_LLM_NER_ENABLED"):
        cfg.llm_ner.enabled = v.lower() in ("true", "1", "yes")

    # Background enrichment master switch (benchmarks, offline ingestion)
    if v := os.environ.get("ZETTELFORGE_ENRICHMENT_ENABLED"):
        cfg.enrichment.enabled = v.lower() in ("true", "1", "yes")

    # Cross-encoder rerank kill switch
    if v := os.environ.get("ZETTELFORGE_RERANK_ENABLED"):
        cfg.retrieval.rerank_enabled = v.lower() in ("true", "1", "yes")

    # RFC-013: PII detection via Presidio
    if v := os.environ.get("ZETTELFORGE_PII_ENABLED"):
        cfg.governance.pii.enabled = v.lower() in ("true", "1", "yes")
    if v := os.environ.get("ZETTELFORGE_PII_ACTION"):
        cfg.governance.pii.action = v

    # RFC-014: Operation limits (DoS mitigation)
    if v := os.environ.get("ZETTELFORGE_LIMITS_MAX_CONTENT_LENGTH"):
        cfg.governance.limits.max_content_length = int(v)
    if v := os.environ.get("ZETTELFORGE_LIMITS_RECALL_TIMEOUT"):
        cfg.governance.limits.recall_timeout_seconds = float(v)

    # SEC-011 / MemSAD write-time memory defense
    if v := os.environ.get("ZETTELFORGE_MEMORY_DEFENSE_ENABLED"):
        cfg.governance.memory_defense.enabled = v.lower() in ("true", "1", "yes")
    if v := os.environ.get("ZETTELFORGE_MEMORY_DEFENSE_MODE"):
        cfg.governance.memory_defense.mode = v
    if v := os.environ.get("ZETTELFORGE_MEMORY_DEFENSE_MIN_CALIBRATION"):
        cfg.governance.memory_defense.min_calibration_notes = int(v)
    if v := os.environ.get("ZETTELFORGE_MEMORY_DEFENSE_KAPPA"):
        cfg.governance.memory_defense.kappa = float(v)

    # Extensions license key (used by zettelforge-enterprise fallback path)
    if v := os.environ.get("THREATENGRAM_LICENSE_KEY"):
        cfg.enterprise.license_key = v

    # OpenCTI
    if os.environ.get("OPENCTI_URL"):
        cfg.opencti.url = os.environ["OPENCTI_URL"]
    if os.environ.get("OPENCTI_TOKEN"):
        cfg.opencti.token = os.environ["OPENCTI_TOKEN"]
    if os.environ.get("OPENCTI_SYNC_INTERVAL"):
        cfg.opencti.sync_interval = int(os.environ["OPENCTI_SYNC_INTERVAL"])

    # RFC-015: Web UI
    if v := os.environ.get("ZETTELFORGE_WEB_ENABLED"):
        cfg.web.enabled = v.lower() in ("true", "1", "yes")
    if v := os.environ.get("ZETTELFORGE_WEB_PORT"):
        try:
            cfg.web.port = int(v)
        except ValueError:
            get_logger("zettelforge.config").warning("invalid_web_port", value=v)
    if v := os.environ.get("ZETTELFORGE_WEB_UI_DIR"):
        cfg.web.ui_dir = v


_REASONING_TOKEN_FLOORS = {
    "max_tokens_causal": 8000,
    "max_tokens_synthesis": 2500,
    "max_tokens_extraction": 2500,
    "max_tokens_ner": 2500,
    "max_tokens_evolve": 2500,
}


def _apply_reasoning_model_scaling(cfg: ZettelForgeConfig) -> None:
    """Raise LLM limits to known-good floors when reasoning models are enabled."""
    if not cfg.llm.reasoning_model:
        return

    cfg.llm.timeout = max(float(cfg.llm.timeout), 180.0)
    for attr, floor in _REASONING_TOKEN_FLOORS.items():
        current = getattr(cfg.llm, attr)
        if isinstance(current, int):
            setattr(cfg.llm, attr, max(current, floor))


# ── Singleton ──────────────────────────────────────────────

_config: ZettelForgeConfig | None = None


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
        _apply_reasoning_model_scaling(_config)

    return _config


def reload_config() -> ZettelForgeConfig:
    """Force reload configuration from file + environment."""
    global _config
    _config = None
    return get_config()
