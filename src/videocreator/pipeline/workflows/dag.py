"""Workflow DAG validation and Kahn topological sort."""
from __future__ import annotations

from collections import deque
from typing import Any

VALID_NODE_KINDS: frozenset[str] = frozenset(
    {
        "character_node",
        "product_node",
        "news_node",
        "scene_node",
        "voice_node",
        "render_node",
        "publish_node",
    }
)


def node_kind(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    raw = str(data.get("node_kind") or node.get("type") or "").strip()
    return raw if raw in VALID_NODE_KINDS else "scene_node"


def topological_sort_workflow(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Validates acyclic DAG structure via Kahn's algorithm and returns `(ordered_nodes, parents_map)`."""
    if not nodes:
        raise ValueError("Workflow must contain at least 1 node")

    by_id: dict[str, dict[str, Any]] = {}
    in_degree: dict[str, int] = {}
    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}

    for node in nodes:
        nid = str(node.get("id") or "").strip()
        if not nid:
            raise ValueError("Every workflow node must have a non-empty id")
        if nid in by_id:
            raise ValueError(f"Duplicate workflow node id '{nid}'")
        by_id[nid] = node
        in_degree[nid] = 0
        children[nid] = []
        parents[nid] = []

    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        src = str(edge.get("source") or "").strip()
        dst = str(edge.get("target") or "").strip()
        if src not in by_id or dst not in by_id:
            raise ValueError(f"Workflow edge references unknown node: {src} -> {dst}")
        if src == dst:
            raise ValueError(f"Workflow graph contains a self-loop on node '{src}'")
        if (src, dst) in seen_edges:
            continue
        seen_edges.add((src, dst))
        children[src].append(dst)
        parents[dst].append(src)
        in_degree[dst] += 1

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    ordered: list[dict[str, Any]] = []
    while queue:
        nid = queue.popleft()
        ordered.append(by_id[nid])
        for nxt in children[nid]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(by_id):
        raise ValueError("Workflow graph contains a cycle and cannot be executed as a DAG")

    return ordered, parents
