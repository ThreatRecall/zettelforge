"""
Entity Indexer - Fast entity-based note retrieval
A-MEM Agentic Memory Architecture V1.0

Conversational Entity Extension (RFC-001):
- Added LLM-based NER for conversational entity types
- Regex fast-path preserved for CTI entity types (CVE, actor, tool, campaign)
- New entity types: person, location, organization, event, activity, temporal
- EntityExtractor is now the single source of truth (NoteConstructor delegates here)
"""

import atexit
import contextlib
import fcntl
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import ClassVar

from zettelforge.json_parse import extract_json
from zettelforge.log import get_logger

_logger = get_logger("zettelforge.entity_indexer")


class EntityExtractor:
    """Extract entities from text using regex (CTI) and LLM (conversational) patterns."""

    # Regex fast-path for CTI entities — deterministic, zero-latency
    REGEX_PATTERNS: ClassVar[dict[str, re.Pattern]] = {
        "cve": re.compile(r"(CVE-\d{4}-\d{4,})", re.IGNORECASE),
        "intrusion_set": re.compile(
            r"\b((?:apt|unc|ta|fin|temp)\s*-?\s*\d+)\b",
            re.IGNORECASE,
        ),
        "actor": re.compile(
            r"\b(lazarus|sandworm|volt\s+typhoon)\b",
            re.IGNORECASE,
        ),
        "tool": re.compile(
            r"\b(cobalt\s+strike|metasploit|mimikatz|bloodhound|dropbear|empire|covenant)\b",
            re.IGNORECASE,
        ),
        "campaign": re.compile(
            r"\b(operation\s+\w+)\b",
            re.IGNORECASE,
        ),
        "attack_pattern": re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b"),
        # IOC patterns (STIX Cyber Observables)
        "ipv4": re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
        ),
        "domain": re.compile(
            r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)"
            r"+(?:com|net|org|io|co|info|biz|gov|mil|edu|int|ru|cn|de|uk|fr|jp|br|in|au|us|ca"
            r"|nl|se|ch|es|it|pl|za|kr|tw|mx|ar|cl|no|fi|dk|cz|at|be|pt|ie|nz|il|sg|hk|my"
            r"|th|ph|vn|id|ua|tr|ro|bg|hr|sk|si|ee|lv|lt|lu|xyz|top|club|online|site|tech"
            r"|store|app|dev|cloud|pro|cc|me|tv|ws|name|mobi|asia|tel|travel|aero|coop"
            r"|museum|jobs|cat|post)\b",
        ),
        "url": re.compile(r"https?://[^\s<>\"')\]]+"),
        "md5": re.compile(r"\b[a-fA-F0-9]{32}\b"),
        "sha1": re.compile(r"\b[a-fA-F0-9]{40}\b"),
        "sha256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
        "email": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    }

    # All entity types the system recognizes
    ENTITY_TYPES: ClassVar[list[str]] = [
        # CTI (regex)
        "cve",
        "intrusion_set",
        "actor",
        "tool",
        "campaign",
        "attack_pattern",
        # IOC / STIX Cyber Observables (regex)
        "ipv4",
        "domain",
        "url",
        "md5",
        "sha1",
        "sha256",
        "email",
        # Conversational (LLM)
        "person",
        "location",
        "organization",
        "event",
        "activity",
        "temporal",
    ]

    # Signals that a hex string appears inside a code or VCS context, not as an IOC.
    # Any line that matches one of these patterns causes all hex strings on that line
    # to be excluded from hash results.
    _CODE_CONTEXT_PATTERN = re.compile(
        r"""
        (?:
            [a-zA-Z_]\w*\s*=\s*["']?[a-fA-F0-9]{32,64}   # var = hash (assignment)
          | \bcommit\s+[a-fA-F0-9]{7,40}\b                # git commit entry
          | \bmerge\s+[a-fA-F0-9]{7,40}\b                 # git merge line
          | \btree\s+[a-fA-F0-9]{7,40}\b                  # git tree line
          | \bparent\s+[a-fA-F0-9]{7,40}\b                # git parent line
          | \bAuthor:\s                                    # git log header
          | ```                                            # code fence marker
          | \bdef\s+\w                                     # function definition
          | [a-zA-Z_]\w*\([^)]*[a-fA-F0-9]{32,64}        # function call with hash arg
        )
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # NER prompt for conversational entity extraction
    NER_SYSTEM_PROMPT = (
        "You are a named entity recognizer. Extract entities from the text. "
        "Return ONLY a JSON object with these keys: "
        "person, location, organization, event, activity, temporal. "
        "Each key maps to a list of strings. "
        'Use empty lists for types not found. Example: {"person": ["Alice"], '
        '"location": ["Paris"], "organization": [], "event": ["birthday party"], '
        '"activity": ["swimming"], "temporal": ["last Tuesday"]}'
    )

    # Regex for conversational person names from dialogue format "Name: text"
    _PERSON_PATTERN = re.compile(r"(?:^|\n)\s*([A-Z][a-z]{2,15}):", re.MULTILINE)

    # Common words that match the person pattern but aren't names
    _NAME_STOPWORDS: ClassVar[set[str]] = {
        "the",
        "and",
        "but",
        "for",
        "not",
        "you",
        "all",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "are",
        "has",
        "his",
        "how",
        "note",
        "text",
        "content",
        "context",
        "session",
        "conversation",
        "hey",
        "wow",
        "thanks",
        "yeah",
        "sure",
        "well",
        "really",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }

    # Regex for common locations
    _LOCATION_PATTERN = re.compile(
        r"\b(New\s+York|Los\s+Angeles|San\s+Francisco|Chicago|London|Paris|Tokyo|"
        r"Barcelona|Bali|Hawaii|Alaska|Banff|Nashville|Austin|Seattle|Portland|"
        r"Denver|Miami|Boston|Atlanta|Dallas|Toronto|Vancouver|Sydney|Melbourne|"
        r"Amsterdam|Rome|Dublin|Edinburgh|Munich|Vienna|Prague|Budapest|Lisbon|"
        r"Madrid|Singapore|Bangkok|Seoul|Mumbai|Shanghai|Beijing|Dubai|Cairo)\b",
        re.IGNORECASE,
    )

    def _filter_false_positive_hashes(self, candidates: list[str], text: str) -> list[str]:
        """Remove hash candidates that appear in code or VCS contexts.

        Strategy: build the set of hex strings that sit on a line whose content
        matches _CODE_CONTEXT_PATTERN, then exclude those from the final results.
        This catches git log output, variable assignments, and fenced code blocks
        without requiring per-match lookahead assertions in the regex itself.

        Args:
            candidates: Raw hex strings extracted by a hash pattern.
            text: Full source text (used to derive per-line context).

        Returns:
            Filtered list with code-context false positives removed.
        """
        if not candidates:
            return candidates

        # Build set of hex strings that live on a code-context line
        fp_hashes: set[str] = set()
        for line in text.splitlines():
            if self._CODE_CONTEXT_PATTERN.search(line):
                # Mark every hex string on this line as a false positive
                for m in re.finditer(r"\b[a-fA-F0-9]{32,64}\b", line):
                    fp_hashes.add(m.group(0).lower())

        return [c for c in candidates if c.lower() not in fp_hashes]

    def extract_regex(self, text: str) -> dict[str, list[str]]:
        """Extract CTI + IOC + conversational entities using regex. Fast, no LLM."""
        results: dict[str, list[str]] = {}

        # Hash IOC types that need false-positive filtering
        hash_types = {"md5", "sha1", "sha256"}

        for entity_type, pattern in self.REGEX_PATTERNS.items():
            matches = pattern.findall(text)
            normalized = list(set(m.lower().replace(" ", "-") for m in matches))
            if entity_type in hash_types:
                normalized = self._filter_false_positive_hashes(normalized, text)
            results[entity_type] = normalized

        # Person names from dialogue format
        person_matches = self._PERSON_PATTERN.findall(text)
        persons = set()
        for name in person_matches:
            if name.lower() not in self._NAME_STOPWORDS and len(name) >= 3:
                persons.add(name.lower())
        results["person"] = list(persons)

        # Locations
        loc_matches = self._LOCATION_PATTERN.findall(text)
        results["location"] = list(set(m.lower().replace(" ", "-") for m in loc_matches))

        return results

    def extract_llm(self, text: str) -> dict[str, list[str]]:
        """Extract conversational entities using LLM NER.

        Returns dict with person, location, organization, event, activity, temporal keys.
        Falls back to empty dicts on failure.
        """
        conversational_types = [
            "person",
            "location",
            "organization",
            "event",
            "activity",
            "temporal",
        ]
        empty = {t: [] for t in conversational_types}

        if len(text.strip()) < 10:
            return empty

        try:
            from zettelforge.llm_client import generate

            prompt = f"Extract named entities from this text:\n\n{text[:2000]}\n\nJSON:"
            # 2500-token budget for reasoning-model headroom (v2.5.2; pre-fix
            # 300 was exhausted by qwen3.5+ <think> tokens, leaving the NER
            # JSON empty and entity extraction silently no-opping).
            output = generate(
                prompt,
                max_tokens=2500,
                temperature=0.0,
                system=self.NER_SYSTEM_PROMPT,
            )

            parsed = extract_json(output, expect="object")
            if parsed is None and output and output.strip():
                _logger.info("retry_parse", site="entity_indexer_ner", attempt=2)
                retry_prompt = prompt + "\n\nRespond with valid JSON only."
                output = generate(retry_prompt, max_tokens=2500, temperature=0.3, json_mode=True)
                parsed = extract_json(output, expect="object")
            return self._parse_ner_output_from_parsed(parsed, output, conversational_types)

        except Exception:
            _logger.warning("llm_entity_extraction_failed", exc_info=True)
            return empty

    def _parse_ner_output(self, output: str, expected_types: list[str]) -> dict[str, list[str]]:
        """Parse LLM NER output into normalized entity dict."""
        parsed = extract_json(output, expect="object")
        return self._parse_ner_output_from_parsed(parsed, output, expected_types)

    def _parse_ner_output_from_parsed(
        self, parsed, output: str, expected_types: list[str]
    ) -> dict[str, list[str]]:
        """Build normalized entity dict from a pre-parsed JSON object."""
        empty = {t: [] for t in expected_types}

        if parsed is None:
            raw = output or ""
            _logger.warning(
                "parse_failed",
                schema="ner_output",
                reason="empty_completion" if not raw.strip() else "json_decode",
                raw=raw[:240],
                raw_chars=len(raw),
            )
            return empty

        # Normalize values
        results: dict[str, list[str]] = {}
        for etype in expected_types:
            values = parsed.get(etype, [])
            if isinstance(values, list):
                results[etype] = list(
                    set(
                        str(v).lower().strip()
                        for v in values
                        if v and isinstance(v, str) and len(v.strip()) > 1
                    )
                )
            else:
                results[etype] = []

        return results

    def extract_all(self, text: str, use_llm: bool = False) -> dict[str, list[str]]:
        """Extract all entity types from text.

        Uses regex for CTI types (always) and LLM for conversational types
        (when use_llm=True and text is long enough).

        Args:
            text: Input text to extract entities from.
            use_llm: Whether to use LLM for conversational NER. Set False
                     for fast regex-only extraction.

        Returns:
            Dict mapping entity type to list of normalized entity values.
        """
        # Regex fast-path for CTI entities
        results = self.extract_regex(text)

        # LLM NER for conversational entities
        if use_llm:
            llm_results = self.extract_llm(text)
            # Merge LLM results with regex results (extend, don't overwrite)
            for etype, values in llm_results.items():
                if results.get(etype):
                    # Deduplicate across regex + LLM
                    merged = set(results[etype])
                    merged.update(values)
                    results[etype] = list(merged)
                else:
                    results[etype] = values
        else:
            # Ensure all non-regex types are present with empty lists
            for etype in ["person", "location", "organization", "event", "activity", "temporal"]:
                if etype not in results:
                    results[etype] = []

        return results


class EntityIndexer:
    """Index notes by entities for fast lookup"""

    def __init__(self, index_path: str | None = None):
        from zettelforge.memory_store import get_default_data_dir

        if index_path is None:
            index_path = get_default_data_dir() / "entity_index.json"
        self.index_path = Path(index_path)
        self.index: dict[str, dict[str, set[str]]] = {
            etype: {} for etype in EntityExtractor.ENTITY_TYPES
        }
        self.extractor = EntityExtractor()
        self._dirty = False
        self._flush_timer: threading.Timer | None = None
        # RLock so that paths which already hold the lock (e.g. add_note →
        # _schedule_flush) don't deadlock on the timer-coordination
        # acquisition. Same lock guards all index reads/writes/serialize
        # so the dict comprehension in save() cannot race with mutating
        # callers (RFC-001 Warning 6).
        self._flush_lock = threading.RLock()
        atexit.register(self._flush_sync)
        self.load()

    def load(self) -> bool:
        """Load index from disk."""
        if not self.index_path.exists():
            return False
        try:
            with self._flush_lock, open(self.index_path) as f:
                data = json.load(f)
                for entity_type in self.index:
                    if entity_type in data:
                        self.index[entity_type] = {k: set(v) for k, v in data[entity_type].items()}
            return True
        except Exception:
            _logger.warning("entity_index_load_failed", exc_info=True)
            return False

    def save(self) -> None:
        """Save index to disk atomically.

        RFC-001 Warning 4: previous implementation opened ``index_path``
        in ``"w"`` mode (truncating) BEFORE acquiring ``flock``, so a
        concurrent reader / crash mid-write left the file empty or
        partial. This implementation writes to a temp file in the same
        directory under the in-process lock, then atomically renames
        into place. ``flock`` is taken on the temp file to interlock
        cross-process writers; the rename is atomic on POSIX.
        """
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        # In-process critical section: serialize from a stable snapshot
        # of self.index. This excludes concurrent add_note / remove_note
        # via _flush_lock (RFC-001 Warning 6).
        with self._flush_lock:
            data = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in self.index.items()}

        fd, tmp_path = tempfile.mkstemp(
            prefix=".entity_index.", suffix=".json.tmp", dir=str(self.index_path.parent)
        )
        try:
            with os.fdopen(fd, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                fcntl.flock(f, fcntl.LOCK_UN)
            os.replace(tmp_path, self.index_path)  # atomic on POSIX
        except Exception:
            # Best-effort cleanup; raise so caller observes the failure.
            if os.path.exists(tmp_path):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            raise

    def add_note(self, note_id: str, entities: dict[str, list[str]]) -> None:
        """Add note to entity index."""
        # Hold _flush_lock for the whole mutation so concurrent save() /
        # remove_note() / load() can't observe a torn index. Same lock
        # nests safely with _schedule_flush via RLock.
        with self._flush_lock:
            for entity_type, entity_list in entities.items():
                if entity_type not in self.index:
                    self.index[entity_type] = {}
                for entity in entity_list:
                    entity_lower = entity.lower()
                    if entity_lower not in self.index[entity_type]:
                        self.index[entity_type][entity_lower] = set()
                    self.index[entity_type][entity_lower].add(note_id)
            self._dirty = True
        self._schedule_flush()

    def remove_note(self, note_id: str) -> None:
        """Remove a note ID from all entity sets in the index.

        RFC-001 Warning 5: previous implementation deleted the entity-type
        key when its dict emptied, breaking the 19-type invariant set up
        in __init__ — code elsewhere (e.g. ``add_note`` re-checking
        ``entity_type not in self.index``) relied on that invariant
        existing. We now leave empty type-buckets in place; only the
        per-value sets are pruned.
        """
        with self._flush_lock:
            for entity_type in list(self.index.keys()):
                for entity_value in list(self.index[entity_type].keys()):
                    self.index[entity_type][entity_value].discard(note_id)
                    # Clean up empty per-value sets only — preserve the
                    # parent entity_type bucket so ENTITY_TYPES invariant
                    # holds across the lifetime of the indexer.
                    if not self.index[entity_type][entity_value]:
                        del self.index[entity_type][entity_value]
            self._dirty = True
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        """Schedule a background flush in 5 seconds if not already scheduled."""
        with self._flush_lock:
            if self._flush_timer is None or not self._flush_timer.is_alive():
                self._flush_timer = threading.Timer(5.0, self._flush_sync)
                self._flush_timer.daemon = True
                self._flush_timer.start()

    def _flush_sync(self) -> None:
        """Write index to disk if dirty.

        RFC-001 Warning 6: hold the lock across the dirty-check + save +
        clear so the dirty flag and the on-disk state stay consistent
        even if a concurrent add_note arrives between read and write.
        RLock allows save() to re-enter for its own snapshot block.
        """
        with self._flush_lock:
            if self._dirty:
                self.save()
                self._dirty = False

    def get_note_ids(self, entity_type: str, entity_value: str) -> list[str]:
        """Get note IDs for a specific entity."""
        if entity_type not in self.index:
            return []
        return list(self.index[entity_type].get(entity_value.lower(), []))

    def search_entities(self, query: str, limit: int = 10) -> dict[str, list[str]]:
        """Search for entities matching a query across all types.

        Useful for recall when the entity type is unknown.

        Args:
            query: Search term (case-insensitive prefix match).
            limit: Maximum results per entity type.

        Returns:
            Dict mapping entity type to list of matching entity values.
        """
        query_lower = query.lower()
        results: dict[str, list[str]] = {}
        for etype, entities in self.index.items():
            matches = [ev for ev in entities if ev.startswith(query_lower)][:limit]
            if matches:
                results[etype] = matches
        return results

    def stats(self) -> dict:
        """Get index statistics."""
        return {
            entity_type: {
                "unique_entities": len(entities),
                "total_mappings": sum(len(notes) for notes in entities.values()),
            }
            for entity_type, entities in self.index.items()
        }

    def build(self) -> dict:
        """Rebuild index from all notes."""
        from zettelforge.memory_store import MemoryStore

        store = MemoryStore()
        self.index = {etype: {} for etype in EntityExtractor.ENTITY_TYPES}

        count = 0
        for note in store.iterate_notes():
            entities = self.extractor.extract_all(note.content.raw)
            self.add_note(note.id, entities)
            count += 1

        # Cancel any pending background timer and flush immediately — rebuild is
        # an authoritative rewrite that must be persisted before returning.
        with self._flush_lock:
            if self._flush_timer is not None and self._flush_timer.is_alive():
                self._flush_timer.cancel()
            self._flush_timer = None
        self.save()
        self._dirty = False

        return {"notes_indexed": count, "stats": self.stats()}
