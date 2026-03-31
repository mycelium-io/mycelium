# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Node:
    id: str
    labels: list[str]
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Node ID cannot be empty")
        self._validate_properties()

    def _validate_properties(self):
        for key in self.properties:
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Invalid property key: {key}")

    def to_cypher_exists(self) -> tuple[str, tuple]:
        return "MATCH (n {id: %s}) RETURN n LIMIT 1", (self.id,)

    def to_cypher_get(self) -> tuple[str, tuple]:
        if not self.id:
            raise ValueError("Node must have an ID for get queries")
        query = "MATCH (n {id: %s}) RETURN collect(n) as nodes"
        return query, (self.id,)

    def to_cypher_create(self) -> tuple[str, tuple]:
        labels = self.labels[0] if self.labels else "Node"
        properties = self.properties.copy()
        properties["id"] = self.id
        for key, value in properties.items():
            if isinstance(value, list):
                properties[key] = json.dumps(value)
        props = ", ".join([f"{k}: %s" for k in properties])
        query = f"CREATE (n:{labels} {{ {props} }}) RETURN n"
        return query, tuple(properties.values())

    def to_cypher_delete(self) -> tuple[str, tuple]:
        return "MATCH (n {id: %s}) DETACH DELETE n", (self.id,)

    def to_cypher_neighbor_query(self) -> tuple[str, tuple]:
        if not self.id:
            raise ValueError("Node must have an ID for neighbor queries")
        query = (
            "MATCH (n {id: %s})"
            "\nWITH n LIMIT 1"
            "\nOPTIONAL MATCH (n)-[r]-(m)"
            "\nRETURN n, collect(DISTINCT r) as relationships, collect(DISTINCT m) as neighbors"
        )
        return query, (self.id,)

    def to_cypher_path_query(self, node_dst: "Node", depth: int | None = None) -> tuple[str, tuple]:
        if depth is not None:
            query = f"MATCH p = (start {{id: %s}})-[*1..{depth}]-(finish {{id: %s}}) RETURN p"
        else:
            query = "MATCH p = (start {id: %s})-[*]-(finish {id: %s}) RETURN p"
        return query, (self.id, node_dst.id)

    def to_cypher_path_query_with_direction(
        self, node_dst: "Node", depth: int | None = None
    ) -> tuple[str, tuple]:
        if depth is not None:
            query = f"MATCH p = (start {{id: %s}})-[*1..{depth}]->(finish {{id: %s}}) RETURN p"
        else:
            query = "MATCH p = (start {id: %s})-[*]->(finish {id: %s}) RETURN p"
        return query, (self.id, node_dst.id)

    def to_executable_cypher_with_params(
        self, query: str, params: tuple, param_names: list | None = None
    ) -> str:
        if not params:
            return query + (";" if not query.strip().endswith(";") else "")
        if param_names is None:
            param_names = ["id"] if len(params) == 1 else [f"param{i}" for i in range(len(params))]
        converted = query
        params_dict = {}
        for param_name, param_value in zip(param_names, params, strict=False):
            converted = converted.replace("%s", f"${param_name}", 1)
            params_dict[param_name] = param_value
        for key, value in params_dict.items():
            val_str = "null" if value is None else "'" + str(value).replace("'", "\\'") + "'"
            converted = converted.replace(f"${key}", val_str)
        if not converted.strip().endswith(";"):
            converted += ";"
        return converted
