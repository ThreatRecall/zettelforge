"""
Ontology Integration - Typed Entity System with Constraints
ZettelForge + Ontology (2026-04-06)

Adds typed entities with validation to ZettelForge knowledge graph.
Supports Person, Project, Task, Event, Document, Credential, and more.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Core entity types from ontology skill
ENTITY_TYPES = {
    # Agents & People
    "Person": {
        "required": ["name"],
        "optional": ["email", "phone", "notes", "organization"],
        "properties": {},
    },
    "Organization": {
        "required": ["name"],
        "optional": ["type", "members", "url"],
        "properties": {},
    },
    # Work
    "Project": {
        "required": ["name", "status"],
        "optional": ["goals", "owner", "start_date", "end_date"],
        "properties": {},
    },
    "Task": {
        "required": ["title", "status"],
        "optional": ["due", "priority", "assignee", "blockers", "project"],
        "properties": {},
    },
    "Goal": {
        "required": ["description"],
        "optional": ["target_date", "metrics", "owner"],
        "properties": {},
    },
    # Time & Place
    "Event": {
        "required": ["title", "start"],
        "optional": ["end", "location", "attendees", "recurrence"],
        "properties": {},
    },
    "Location": {"required": ["name"], "optional": ["address", "coordinates"], "properties": {}},
    # Information
    "Document": {
        "required": ["title"],
        "optional": ["path", "url", "summary", "tags"],
        "properties": {},
    },
    "Note": {  # Maps to MemoryNote
        "required": ["content"],
        "optional": ["tags", "refs", "author"],
        "properties": {},
    },
    # Resources
    "Account": {
        "required": ["service", "username"],
        "optional": ["credential_ref"],
        "properties": {},
    },
    "Device": {
        "required": ["name"],
        "optional": ["type", "identifiers", "status"],
        "properties": {},
    },
    # CTI types (extending for security domain)
    "IntrusionSet": {
        "required": ["name"],
        "optional": ["aliases", "first_seen", "last_seen", "goals", "resource_level", "ttps"],
        "properties": {},
    },
    "ThreatActor": {
        "required": ["name"],
        "optional": ["aliases", "country", "motivation", "ttps", "targets"],
        "properties": {},
    },
    "Vulnerability": {
        "required": ["cve_id"],
        "optional": [
            # Structured scoring fields (populated during OpenCTI sync, not text extraction)
            "cvss_v3_score",  # float 0.0–10.0
            "cvss_v3_vector",  # e.g. "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
            "epss_score",  # float 0.0–1.0, probability of exploitation in the wild
            "epss_percentile",  # float 0.0–1.0
            "cisa_kev",  # bool — present in CISA Known Exploited Vulnerabilities catalog
            # Descriptive fields
            "description",
            "affected_products",
            "references",
        ],
        "properties": {},
    },
    "Malware": {
        "required": ["name"],
        "optional": ["family", "platforms", "capabilities", "references"],
        "properties": {},
    },
    "Campaign": {
        "required": ["name"],
        "optional": ["actor", "start_date", "end_date", "targets", "ttps"],
        "properties": {},
    },
    "Incident": {
        "required": ["title", "status"],
        "optional": ["severity", "timeline", "affected_assets", "root_cause"],
        "properties": {},
    },
    "AttackPattern": {
        "required": ["technique_id"],
        "optional": ["name", "tactic", "platform", "description", "references"],
        "properties": {},
    },
    # Detection rules (Phase 1c: first-class Sigma + YARA memory)
    "DetectionRule": {
        "required": ["rule_id", "title", "source_format", "content_sha256"],
        "optional": [
            "description",
            "author",
            "date",
            "modified",
            "references",
            "tags",
            "level",
            "status",
            "tlp",
            "license",
            "source_repo",
            "source_path",
        ],
        "properties": {},
    },
    "SigmaRule": {
        "required": ["rule_id", "title", "source_format", "content_sha256"],
        "optional": [
            "description",
            "author",
            "date",
            "modified",
            "references",
            "tags",
            "level",
            "status",
            "tlp",
            "license",
            "source_repo",
            "source_path",
            "logsource_product",
            "logsource_service",
            "logsource_category",
            "rule_level",
            "rule_status",
            "sigma_format_version",
        ],
        "properties": {},
    },
    "YaraRule": {
        "required": ["rule_id", "title", "source_format", "content_sha256"],
        "optional": [
            "description",
            "author",
            "date",
            "modified",
            "references",
            "tags",
            "level",
            "status",
            "tlp",
            "license",
            "source_repo",
            "source_path",
            "cccs_id",
            "fingerprint",
            "category",
            "technique_tag",
            "cccs_version",
            "hash_of_sample",
        ],
        "properties": {},
    },
    "SigmaTag": {
        "required": ["namespace", "name"],
        "optional": [],
        "properties": {},
    },
    "YaraTag": {
        "required": ["namespace", "name"],
        "optional": [],
        "properties": {},
    },
    "LogSource": {
        "required": [],
        "optional": ["product", "service", "category"],
        "properties": {},
    },
    # IOC / STIX Cyber Observables
    "IPv4Address": {
        "required": ["value"],
        "optional": ["belongs_to_ref", "resolves_to_refs"],
        "properties": {},
    },
    "DomainName": {
        "required": ["value"],
        "optional": ["resolves_to_refs"],
        "properties": {},
    },
    "URL": {
        "required": ["value"],
        "optional": ["belongs_to_ref"],
        "properties": {},
    },
    "FileHash": {
        "required": ["value", "hash_type"],
        "optional": ["file_name", "size", "parent_directory_ref"],
        "properties": {},
    },
    "EmailAddress": {
        "required": ["value"],
        "optional": ["display_name", "belongs_to_ref"],
        "properties": {},
    },
    # Meta
    "Action": {
        "required": ["type", "timestamp"],
        "optional": ["target", "outcome", "actor"],
        "properties": {},
    },
    "Policy": {
        "required": ["scope", "rule"],
        "optional": ["enforcement", "version"],
        "properties": {},
    },
}


# Relation definitions with constraints
RELATION_TYPES = {
    "has_owner": {
        "from_types": ["Project", "Task", "Event", "Document"],
        "to_types": ["Person", "Organization"],
        "cardinality": "many_to_one",
    },
    "has_assignee": {
        "from_types": ["Task", "Incident"],
        "to_types": ["Person"],
        "cardinality": "many_to_one",
    },
    "has_task": {"from_types": ["Project"], "to_types": ["Task"], "cardinality": "one_to_many"},
    "blocks": {
        "from_types": ["Task"],
        "to_types": ["Task"],
        "cardinality": "many_to_many",
        "acyclic": True,  # No circular dependencies
    },
    "related_to": {
        "from_types": list(ENTITY_TYPES.keys()),
        "to_types": list(ENTITY_TYPES.keys()),
        "cardinality": "many_to_many",
    },
    "part_of": {
        "from_types": ["Task", "Document", "Event"],
        "to_types": ["Project"],
        "cardinality": "many_to_one",
    },
    "attributed_to": {
        "from_types": [
            "Incident",
            "Campaign",
            "Malware",
            "IntrusionSet",
            "DetectionRule",
            "SigmaRule",
            "YaraRule",
        ],
        "to_types": ["ThreatActor", "IntrusionSet"],
        "cardinality": "many_to_one",
    },
    "uses": {
        "from_types": ["IntrusionSet"],
        "to_types": ["Malware"],
        "cardinality": "many_to_many",
    },
    "uses_technique": {
        "from_types": ["ThreatActor", "Campaign", "IntrusionSet"],
        "to_types": ["AttackPattern"],
        "cardinality": "many_to_many",
    },
    "uses_tool": {
        "from_types": ["ThreatActor", "Campaign"],
        "to_types": ["Malware", "Tool"],
        "cardinality": "many_to_many",
    },
    "exploits": {
        "from_types": ["ThreatActor", "Campaign", "Malware"],
        "to_types": ["Vulnerability"],
        "cardinality": "many_to_many",
    },
    "implements": {
        "from_types": ["Malware"],
        "to_types": ["AttackPattern"],
        "cardinality": "many_to_many",
    },
    "targets": {
        "from_types": ["ThreatActor", "Campaign", "Malware"],
        "to_types": ["Organization", "Location", "Device"],
        "cardinality": "many_to_many",
    },
    "superseded_by": {
        "from_types": [
            "Note",
            "Document",
            "Policy",
            "DetectionRule",
            "SigmaRule",
            "YaraRule",
        ],
        "to_types": [
            "Note",
            "Document",
            "Policy",
            "DetectionRule",
            "SigmaRule",
            "YaraRule",
        ],
        "cardinality": "many_to_one",
        "acyclic": True,
    },
    # Detection-rule relations (Phase 1c)
    "detects": {
        "from_types": ["DetectionRule", "SigmaRule", "YaraRule"],
        "to_types": ["AttackPattern"],
        "cardinality": "many_to_many",
    },
    "references_cve": {
        "from_types": ["DetectionRule", "SigmaRule", "YaraRule"],
        "to_types": ["Vulnerability"],
        "cardinality": "many_to_many",
    },
    "tagged_with": {
        "from_types": ["DetectionRule", "SigmaRule", "YaraRule"],
        "to_types": ["SigmaTag", "YaraTag"],
        "cardinality": "many_to_many",
    },
    "applies_to": {
        "from_types": ["SigmaRule", "DetectionRule"],
        "to_types": ["LogSource"],
        "cardinality": "many_to_many",
    },
}


class OntologyValidator:
    """
    Validates entity and relation operations against type constraints.
    """

    def __init__(self, schema_path: str | None = None):
        self.schema_path = schema_path
        self.custom_types = {}
        self.custom_relations = {}

        if schema_path and Path(schema_path).exists():
            self._load_schema()

    def _load_schema(self):
        """Load custom schema from YAML."""
        with open(self.schema_path) as f:
            schema = yaml.safe_load(f)
            self.custom_types = schema.get("types", {})
            self.custom_relations = schema.get("relations", {})

    def get_type_definition(self, type_name: str) -> dict:
        """Get type definition, falling back to defaults."""
        return self.custom_types.get(type_name, ENTITY_TYPES.get(type_name, {}))

    def validate_entity(self, entity_type: str, properties: dict) -> tuple[bool, list[str]]:
        """
        Validate entity against type constraints.
        Returns (is_valid, error_messages)
        """
        errors = []

        type_def = self.get_type_definition(entity_type)
        if not type_def:
            return True, []  # Unknown types are allowed

        required = type_def.get("required", [])
        for field in required:
            if field not in properties or not properties[field]:
                errors.append(f"Missing required field: {field}")

        # Check for forbidden properties
        forbidden = type_def.get("forbidden_properties", [])
        for field in forbidden:
            if field in properties:
                errors.append(f"Forbidden property: {field}")

        # Enum validation
        for field, enum_values in type_def.get("enum_properties", {}).items():
            if field in properties and properties[field] not in enum_values:
                errors.append(f"Invalid value for {field}: must be one of {enum_values}")

        # Custom validation function
        if "validate" in type_def:
            try:
                # Simple eval for common patterns
                validate_expr = type_def["validate"]
                if (
                    "end >= start" in validate_expr
                    and "end" in properties
                    and "start" in properties
                ) and properties["end"] < properties["start"]:
                    errors.append("End time must be >= start time")
            except Exception as e:
                errors.append(f"Validation error: {e}")

        return len(errors) == 0, errors

    def validate_relation(
        self, from_type: str, relation_type: str, to_type: str
    ) -> tuple[bool, list[str]]:
        """
        Validate relation is allowed between types.
        Returns (is_valid, error_messages)
        """
        errors = []

        rel_def = self.custom_relations.get(relation_type, RELATION_TYPES.get(relation_type, {}))
        if not rel_def:
            return True, []  # Unknown relations allowed

        from_types = rel_def.get("from_types", [])
        to_types = rel_def.get("to_types", [])

        if from_types and from_type not in from_types:
            errors.append(f"{from_type} cannot have relation {relation_type}")

        if to_types and to_type not in to_types:
            errors.append(f"{relation_type} cannot point to {to_type}")

        return len(errors) == 0, errors


class TypedEntityStore:
    """
    Typed entity storage with validation.
    Integrates with ZettelForge KnowledgeGraph.
    """

    def __init__(self, data_dir: str, validator: OntologyValidator | None = None):
        self.data_dir = Path(data_dir)
        self.entities_file = self.data_dir / "ontology_entities.jsonl"
        self.relations_file = self.data_dir / "ontology_relations.jsonl"
        self.validator = validator or OntologyValidator()

        # In-memory cache
        self._entities: dict[str, dict] = {}
        self._relations: list[dict] = []

        self._load()

    def _load(self):
        """Load entities and relations from JSONL."""
        if self.entities_file.exists():
            with open(self.entities_file) as f:
                for line in f:
                    if line.strip():
                        entity = json.loads(line)
                        self._entities[entity["id"]] = entity

        if self.relations_file.exists():
            with open(self.relations_file) as f:
                for line in f:
                    if line.strip():
                        rel = json.loads(line)
                        self._relations.append(rel)

    def _save_entity(self, entity: dict):
        """Append entity to JSONL."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.entities_file, "a") as f:
            f.write(json.dumps(entity) + "\n")

    def _save_relation(self, relation: dict):
        """Append relation to JSONL."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.relations_file, "a") as f:
            f.write(json.dumps(relation) + "\n")

    def create_entity(
        self, entity_type: str, properties: dict, entity_id: str | None = None
    ) -> tuple[str | None, bool, list[str]]:
        """
        Create typed entity with validation.
        Returns (entity_id, success, errors)
        """
        # Validate
        is_valid, errors = self.validator.validate_entity(entity_type, properties)
        if not is_valid:
            return None, False, errors

        # Generate ID
        if not entity_id:
            prefix = entity_type.lower()[:4]
            entity_id = f"{prefix}_{uuid.uuid4().hex[:8]}"

        entity = {
            "id": entity_id,
            "type": entity_type,
            "properties": properties,
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
        }

        self._entities[entity_id] = entity
        self._save_entity(entity)

        return entity_id, True, []

    def create_relation(
        self, from_id: str, relation_type: str, to_id: str, properties: dict | None = None
    ) -> tuple[bool, list[str]]:
        """
        Create relation with validation.
        Returns (success, errors)
        """
        # Get entity types
        from_entity = self._entities.get(from_id)
        to_entity = self._entities.get(to_id)

        if not from_entity:
            return False, [f"Source entity not found: {from_id}"]
        if not to_entity:
            return False, [f"Target entity not found: {to_id}"]

        # Validate relation
        is_valid, errors = self.validator.validate_relation(
            from_entity["type"], relation_type, to_entity["type"]
        )
        if not is_valid:
            return False, errors

        # Check acyclic if required
        rel_def = RELATION_TYPES.get(relation_type, {})
        if rel_def.get("acyclic") and self._would_create_cycle(from_id, relation_type, to_id):
            return False, [f"Relation {relation_type} would create cycle (acyclic constraint)"]

        relation = {
            "from": from_id,
            "rel": relation_type,
            "to": to_id,
            "properties": properties or {},
            "created": datetime.now().isoformat(),
        }

        self._relations.append(relation)
        self._save_relation(relation)

        return True, []

    def _would_create_cycle(self, from_id: str, relation_type: str, to_id: str) -> bool:
        """Check if adding relation would create a cycle."""
        # Simple DFS to detect cycle
        visited = set()
        stack = [to_id]

        while stack:
            current = stack.pop()
            if current == from_id:
                return True
            if current in visited:
                continue
            visited.add(current)

            # Find all relations from current
            for rel in self._relations:
                if rel["from"] == current and rel["rel"] == relation_type:
                    stack.append(rel["to"])

        return False

    def get_entity(self, entity_id: str) -> dict | None:
        """Get entity by ID."""
        return self._entities.get(entity_id)

    def query_by_type(self, entity_type: str) -> list[dict]:
        """Query all entities of a type."""
        return [e for e in self._entities.values() if e["type"] == entity_type]

    def query_by_property(self, entity_type: str, property_name: str, value: Any) -> list[dict]:
        """Query entities by property value."""
        results = []
        for entity in self._entities.values():
            if entity["type"] == entity_type and entity["properties"].get(property_name) == value:
                results.append(entity)
        return results

    def get_related(self, entity_id: str, relation_type: str | None = None) -> list[dict]:
        """Get related entities."""
        results = []
        for rel in self._relations:
            if rel["from"] == entity_id and (relation_type is None or rel["rel"] == relation_type):
                target = self._entities.get(rel["to"])
                if target:
                    results.append(
                        {
                            "relation": rel["rel"],
                            "entity": target,
                            "properties": rel.get("properties", {}),
                        }
                    )
        return results

    def list_types(self) -> list[str]:
        """List all entity types in store."""
        return list(set(e["type"] for e in self._entities.values()))


# Global singleton
_ontology_store: TypedEntityStore | None = None
_ontology_lock = None  # Will be imported


def get_ontology_store(data_dir: str | None = None) -> TypedEntityStore:
    """Get global ontology store instance."""
    import threading

    global _ontology_store, _ontology_lock

    if _ontology_lock is None:
        _ontology_lock = threading.Lock()

    if _ontology_store is None:
        with _ontology_lock:
            if _ontology_store is None:
                from zettelforge.memory_store import get_default_data_dir

                base_dir = Path(data_dir) if data_dir else get_default_data_dir()
                _ontology_store = TypedEntityStore(str(base_dir / "ontology"))

    return _ontology_store


def get_ontology_validator() -> OntologyValidator:
    """Get ontology validator."""
    return OntologyValidator()
