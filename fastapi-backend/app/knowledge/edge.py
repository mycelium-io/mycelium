import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Edge:
    id: str
    node_ids: list[str]
    relation: str
    properties: dict[str, Any] = field(default_factory=dict)
    direction: str = "->"

    def __post_init__(self):
        if not self.id:
            raise ValueError("Edge ID cannot be empty")
        if len(self.node_ids) != 2:
            raise ValueError("Exactly two node IDs are required")
        if not all(self.node_ids):
            raise ValueError("Node IDs cannot be empty")
        if not self.relation or not re.match(r"^[A-Z_]+$", self.relation):
            raise ValueError("Relation type must be uppercase with underscores")
        if self.direction not in ("->", "<-", "--"):
            raise ValueError("Direction must be one of: '->', '<-', '--'")
        self._validate_properties()

    def _validate_properties(self):
        for key in self.properties:
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Invalid property key: {key}")

    def to_cypher_exists(self) -> tuple[str, tuple]:
        return "MATCH ()-[r {id: %s}]-() RETURN r LIMIT 1", (self.id,)

    def to_cypher_create(self) -> tuple[str, tuple]:
        source_id, target_id = self.node_ids
        properties = self.properties.copy()
        properties["id"] = self.id
        for key, value in properties.items():
            if isinstance(value, list):
                properties[key] = json.dumps(value)
        props = ", ".join([f"{k}: %s" for k in properties.keys()])
        if self.direction == "->":
            rel_pattern = f"(a)-[r:{self.relation} {{ {props} }}]->(b)"
        elif self.direction == "<-":
            rel_pattern = f"(a)<-[r:{self.relation} {{ {props} }}]-(b)"
        else:
            rel_pattern = f"(a)-[r:{self.relation} {{ {props} }}]-(b)"
        query = f"MATCH (a {{id: %s}}), (b {{id: %s}}) CREATE {rel_pattern} RETURN r"
        params = (source_id, target_id) + tuple(properties.values())
        return query, params

    def to_cypher_delete(self) -> tuple[str, tuple]:
        return "MATCH ()-[r {id: %s}]-() DELETE r", (self.id,)
