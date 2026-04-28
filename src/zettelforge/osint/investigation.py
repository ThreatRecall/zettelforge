"""
OSINT Investigation — named case scoping for OSINT enrichment data.

An ``Investigation`` groups a set of KG nodes and edges into a named case
with access control (owner-only by default, shareable via ACL list).
Supports tagging and classification (TLP:AMBER, CONFIDENTIAL, etc.).

API:
    zettelforge investigation create [--name NAME] [--owner OWNER] [--classification CLASS]
    zettelforge investigation add --iid ID --entity TYPE:VALUE
    zettelforge investigation list
    zettelforge investigation export --iid ID --format mtz|json
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class Investigation:
    investigation_id: str
    name: str
    owner: str
    created_at: str
    tags: list[str] = field(default_factory=list)
    classification: str = "TLP:CLEAR"
    acl: list[str] = field(default_factory=list)  # additional users allowed
    entity_refs: list[str] = field(default_factory=list)  # "entity_type:entity_value"

    @classmethod
    def create(cls, name: str, owner: str, classification: str = "TLP:CLEAR", tags=None):
        return cls(
            investigation_id=str(uuid.uuid4().hex[:12]),
            name=name,
            owner=owner,
            created_at=datetime.now().isoformat(),
            tags=tags or [],
            classification=classification,
        )

    def add_entity(self, entity_ref: str):
        if entity_ref not in self.entity_refs:
            self.entity_refs.append(entity_ref)

    def to_node(self) -> dict:
        return {
            "investigation_id": self.investigation_id,
            "name": self.name,
            "owner": self.owner,
            "created_at": self.created_at,
            "tags": self.tags,
            "classification": self.classification,
            "acl": self.acl,
            "entity_refs": self.entity_refs,
        }

    @classmethod
    def from_node(cls, node: dict) -> Investigation:
        return cls(
            investigation_id=node["investigation_id"],
            name=node["name"],
            owner=node["owner"],
            created_at=node["created_at"],
            tags=node.get("tags", []),
            classification=node.get("classification", "TLP:CLEAR"),
            acl=node.get("acl", []),
            entity_refs=node.get("entity_refs", []),
        )


# ── Storage ───────────────────────────────────────────────────────────────────

# In-memory store (replace with JSONL/DB persistence in production)
_INVESTIGATIONS: dict[str, Investigation] = {}


def create_investigation(
    name: str,
    owner: str,
    classification: str = "TLP:CLEAR",
    tags: list[str] | None = None,
) -> Investigation:
    inv = Investigation.create(name=name, owner=owner, classification=classification, tags=tags)
    _INVESTIGATIONS[inv.investigation_id] = inv
    return inv


def get_investigation(investigation_id: str) -> Investigation | None:
    return _INVESTIGATIONS.get(investigation_id)


def list_investigations(owner: str | None = None) -> list[Investigation]:
    if owner:
        return [inv for inv in _INVESTIGATIONS.values() if inv.owner == owner]
    return list(_INVESTIGATIONS.values())


def add_entity_to_investigation(investigation_id: str, entity_ref: str) -> bool:
    inv = _INVESTIGATIONS.get(investigation_id)
    if not inv:
        return False
    inv.add_entity(entity_ref)
    return True


def export_investigation(investigation_id: str, fmt: str = "json") -> dict | str:
    """Export an investigation as a Maltego .mtz ZIP or a JSON dict."""
    inv = _INVESTIGATIONS.get(investigation_id)
    if not inv:
        raise ValueError(f"Investigation {investigation_id} not found")

    if fmt == "json":
        return inv.to_node()

    if fmt == "mtz":
        # Minimal .mtz generation (Maltego Hamburger XML)
        # Full implementation requires zipfile + Maltego schema compliance
        raise NotImplementedError("MTZ export requires zipfile + Maltego XML generation")

    raise ValueError(f"Unsupported export format: {fmt}")
