"""
Join Graph Utility  (Story 1.3)

Builds a bidirectional FK graph from schema_catalog.json.
Exposes:
  get_join_path(a, b)       → shortest chain of (from_table, from_col, to_table, to_col) edges
  get_join_context(tables)  → human-readable JOIN hints string for schema context injection
"""
import json
import os
from collections import deque
from typing import Optional

SCHEMA_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "schema_catalog.json")

# Each adjacency entry: (neighbor_table, local_col, neighbor_col)
_GRAPH: Optional[dict] = None


def _build_graph() -> dict:
    with open(SCHEMA_CATALOG_PATH) as f:
        catalog = json.load(f)

    graph: dict = {t: [] for t in catalog["tables"]}

    for table_name, table_info in catalog["tables"].items():
        for fk in table_info.get("foreign_keys", []):
            ref_table = fk["references_table"]
            local_col = fk["column"]
            ref_col = fk["references_column"]

            # Forward edge: table_name.local_col → ref_table.ref_col
            graph[table_name].append((ref_table, local_col, ref_col))

            # Reverse edge — lets BFS traverse in both directions
            if ref_table in graph:
                graph[ref_table].append((table_name, ref_col, local_col))

    return graph


def _get_graph() -> dict:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


def get_join_path(
    start: str, end: str
) -> Optional[list[tuple[str, str, str, str]]]:
    """
    BFS shortest path between two tables via FK edges.
    Returns a list of (from_table, from_col, to_table, to_col) edges,
    or None if no path exists.
    """
    graph = _get_graph()
    if start not in graph or end not in graph:
        return None
    if start == end:
        return []

    queue: deque = deque([(start, [])])
    visited = {start}

    while queue:
        node, path = queue.popleft()
        for neighbor, local_col, neighbor_col in graph[node]:
            if neighbor in visited:
                continue
            edge = (node, local_col, neighbor, neighbor_col)
            new_path = path + [edge]
            if neighbor == end:
                return new_path
            visited.add(neighbor)
            queue.append((neighbor, new_path))

    return None


def _edges_to_sql_joins(path: list[tuple[str, str, str, str]]) -> list[str]:
    """Convert a path of edges into MySQL JOIN clause strings."""
    return [
        f"JOIN `{to_t}` ON `{from_t}`.`{from_c}` = `{to_t}`.`{to_c}`"
        for from_t, from_c, to_t, to_c in path
    ]


def get_join_context(table_names: list[str]) -> str:
    """
    For every pair of tables in table_names, find the shortest FK path
    (up to 2 hops to keep context concise).  Returns a string block
    listing JOIN conditions to append to schema context.
    Returns empty string if no joins are found.
    """
    graph = _get_graph()
    seen: set = set()
    join_blocks: list[str] = []

    for i, t1 in enumerate(table_names):
        if t1 not in graph:
            continue
        for t2 in table_names[i + 1 :]:
            pair = tuple(sorted([t1, t2]))
            if pair in seen:
                continue
            seen.add(pair)

            path = get_join_path(t1, t2)
            if path is None or len(path) > 2:
                # Skip unreachable pairs and long paths (too speculative)
                continue

            joins = _edges_to_sql_joins(path)
            hop_label = "direct FK" if len(path) == 1 else f"via `{path[0][2]}`"
            join_blocks.append(
                f"-- {t1} ↔ {t2}  ({hop_label})\n" + "\n".join(joins)
            )

    if not join_blocks:
        return ""

    return (
        "=== Suggested JOIN paths between relevant tables ===\n"
        + "\n\n".join(join_blocks)
    )


def get_graph_stats() -> dict:
    """Returns basic stats about the FK graph — used by agent trace."""
    graph = _get_graph()
    total_edges = sum(len(v) for v in graph.values()) // 2  # bidirectional, so halve
    return {"tables": len(graph), "fk_edges": total_edges}
