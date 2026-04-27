import json
from pathlib import Path

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.alias_resolver")

# TypeDB entity type mapping (same as typedb_client.py)
_TYPEDB_TYPE_MAP = {
    "actor": "threat-actor",
    "tool": "tool",
    "malware": "malware",
}


class AliasResolver:
    """Resolves entity aliases to their canonical names.

    Tries TypeDB alias-of relations first (if available),
    falls back to local JSON/hardcoded aliases.
    """

    def __init__(self, alias_file: str | None = None):
        from zettelforge.memory_store import get_default_data_dir

        if alias_file is None:
            alias_file = get_default_data_dir() / "entity_aliases.json"
        self.alias_file = Path(alias_file)

        # Fallback hardcoded aliases
        self.aliases = {
            "actor": {
                "fancy bear": "apt28",
                "fancy-bear": "apt28",
                "pawn storm": "apt28",
                "pawn-storm": "apt28",
                "cozy bear": "apt29",
                "cozy-bear": "apt29",
            },
            "tool": {},
        }
        self._typedb_available = None
        self.load()

    def load(self):
        if self.alias_file.exists():
            try:
                with open(self.alias_file) as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if k not in self.aliases:
                            self.aliases[k] = {}
                        self.aliases[k].update(v)
            except Exception:
                _logger.debug("typedb_alias_lookup_failed", exc_info=True)

    def _try_typedb_resolve(self, entity_type: str, entity_lower: str) -> str | None:
        """Query TypeDB for alias-of relation. Returns canonical name or None."""
        if self._typedb_available is False:
            return None

        typedb_type = _TYPEDB_TYPE_MAP.get(entity_type)
        if not typedb_type:
            return None

        try:
            from zettelforge.knowledge_graph import get_knowledge_graph

            kg = get_knowledge_graph()

            # Only use TypeDB if it's the TypeDB client
            if not hasattr(kg, "_driver") or kg._driver is None:
                self._typedb_available = False
                return None

            from typedb.driver import TransactionType

            tx = kg._driver.transaction(kg.database, TransactionType.READ)
            rows = list(
                tx.query(
                    f'match $a isa {typedb_type}, has name "{entity_lower}"; '
                    f"(canonical: $c, aliased: $a) isa alias-of; "
                    f"$c has name $n; select $n;"
                ).resolve()
            )
            tx.close()

            if rows:
                # Extract name from Attribute(name: "apt28")
                raw = str(rows[0].get("n"))
                name = raw.split(": ")[1].strip('")')
                self._typedb_available = True
                return name

            self._typedb_available = True
            return None
        except Exception:
            _logger.warning("typedb_unavailable", exc_info=True)
            self._typedb_available = False
            return None

    def resolve(self, entity_type: str, entity: str) -> str:
        entity_lower = entity.lower().replace("-", " ")

        # Try TypeDB first
        canonical = self._try_typedb_resolve(entity_type, entity_lower)
        if canonical:
            return canonical

        # Also try with hyphens (TypeDB stores both forms)
        entity_hyphenated = entity.lower()
        if entity_hyphenated != entity_lower:
            canonical = self._try_typedb_resolve(entity_type, entity_hyphenated)
            if canonical:
                return canonical

        # Fallback to local aliases
        mapping = self.aliases.get(entity_type, {})
        if entity_lower in mapping:
            return mapping[entity_lower]

        return entity.lower()
