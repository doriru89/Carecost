#!/usr/bin/env python3
"""Generate interactive LEGO module map from GitNexus knowledge graph.

Queries the GitNexus graph for communities (modules) and their relationships,
then renders an interactive d3-force HTML visualization.

Usage:
    python scripts/generate_lego_map.py
    # Opens docs/lego-map.html
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "lego-map.html"


def _cypher(query: str) -> dict:
    result = subprocess.run(
        ["npx", "gitnexus", "cypher", "--repo", "Carecost", query],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"GitNexus cypher failed: {result.stderr}", file=sys.stderr)
        return {"markdown": ""}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Warning: truncated Cypher response, using partial data", file=sys.stderr)
        return {"markdown": ""}


def _parse_markdown_table(markdown: str) -> list[list[str]]:
    lines = markdown.split("\n")
    rows = []
    for line in lines[2:]:  # skip header + separator
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if parts and parts[0]:
            rows.append(parts)
    return rows


def _get_communities() -> list[dict]:
    data = _cypher(
        "MATCH (c:Community) "
        "RETURN c.id AS id, c.label AS label, c.cohesion AS cohesion, "
        "c.symbolCount AS symbols "
        "ORDER BY symbols DESC LIMIT 30"
    )
    rows = []
    for parts in _parse_markdown_table(data.get("markdown", "")):
        if len(parts) == 4:
            rows.append({
                "id": parts[0],
                "label": parts[1],
                "cohesion": float(parts[2]) if parts[2] else 0,
                "symbols": int(parts[3]) if parts[3] else 0,
            })
    return rows


def _get_cross_community_edges(communities: list[dict]) -> list[dict]:
    """Derive inter-community edges via function membership + CALLS."""
    # Get function→community membership (Function:path:name → comm_X)
    data = _cypher(
        "MATCH (f)-[r:CodeRelation]->(c:Community) "
        "WHERE r.type = 'MEMBER_OF' "
        "RETURN f.id AS fn_id, c.id AS community_id "
        "LIMIT 500"
    )
    fn_to_community: dict[str, str] = {}
    for parts in _parse_markdown_table(data.get("markdown", "")):
        if len(parts) == 2:
            fn_to_community[parts[0]] = parts[1]

    # Get function→function CALLS
    data = _cypher(
        "MATCH (a)-[r:CodeRelation]->(b) "
        "WHERE r.type = 'CALLS' "
        "RETURN a.id AS source, b.id AS target "
        "LIMIT 300"
    )

    # Aggregate into community→community edges
    community_ids = {c["id"] for c in communities}
    edge_counts: dict[tuple[str, str], int] = {}
    for parts in _parse_markdown_table(data.get("markdown", "")):
        if len(parts) == 2:
            src_comm = fn_to_community.get(parts[0])
            dst_comm = fn_to_community.get(parts[1])
            if src_comm and dst_comm and src_comm != dst_comm:
                if src_comm in community_ids and dst_comm in community_ids:
                    key = (src_comm, dst_comm)
                    edge_counts[key] = edge_counts.get(key, 0) + 1

    return [{"source": s, "target": t, "weight": w} for (s, t), w in edge_counts.items()]


def _render_html(communities: list[dict], edges: list[dict]) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CareCost LEGO Module Map</title>
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }}
  h1 {{ text-align: center; padding: 1rem; margin: 0; font-size: 1.4rem; }}
  .info {{ text-align: center; font-size: 0.85rem; color: #8b949e; margin-bottom: 1rem; }}
  svg {{ display: block; margin: 0 auto; }}
  .node circle {{ stroke: #30363d; stroke-width: 1.5px; cursor: pointer; }}
  .node text {{ font-size: 10px; fill: #c9d1d9; pointer-events: none; }}
  .link {{ stroke: #30363d; stroke-opacity: 0.4; }}
  .tooltip {{ position: absolute; background: #161b22; border: 1px solid #30363d;
              padding: 8px 12px; border-radius: 6px; font-size: 12px; pointer-events: none;
              display: none; }}
</style>
</head>
<body>
<h1>CareCost LEGO Module Map</h1>
<p class="info">Derived from GitNexus knowledge graph. {len(communities)} modules, {len(edges)} import edges. Regenerate: <code>make lego</code></p>
<div class="tooltip" id="tooltip"></div>
<svg width="900" height="600"></svg>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const communities = {json.dumps(communities)};
const edges = {json.dumps(edges)};

const colorScale = d3.scaleOrdinal(d3.schemeTableau10);
const sizeScale = d3.scaleSqrt().domain([1, 50]).range([6, 24]);

const svg = d3.select("svg");
const width = +svg.attr("width");
const height = +svg.attr("height");

const simulation = d3.forceSimulation(communities)
  .force("link", d3.forceLink(edges).id(d => d.id).distance(80))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(d => sizeScale(d.symbols) + 4));

const link = svg.append("g")
  .selectAll("line")
  .data(edges)
  .enter().append("line")
  .attr("class", "link");

const node = svg.append("g")
  .selectAll("g")
  .data(communities)
  .enter().append("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", dragstarted)
    .on("drag", dragged)
    .on("end", dragended));

node.append("circle")
  .attr("r", d => sizeScale(d.symbols))
  .attr("fill", d => colorScale(d.label));

node.append("text")
  .attr("dy", d => sizeScale(d.symbols) + 12)
  .attr("text-anchor", "middle")
  .text(d => d.label + (communities.filter(c => c.label === d.label).length > 1 ? ` (${{d.symbols}})` : ""));

const tooltip = d3.select("#tooltip");
node.on("mouseover", (event, d) => {{
  tooltip.style("display", "block")
    .html(`<strong>${{d.label}}</strong><br>Symbols: ${{d.symbols}}<br>Cohesion: ${{(d.cohesion * 100).toFixed(0)}}%`);
}}).on("mousemove", (event) => {{
  tooltip.style("left", (event.pageX + 12) + "px").style("top", (event.pageY - 28) + "px");
}}).on("mouseout", () => tooltip.style("display", "none"));

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});

function dragstarted(event, d) {{ if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }}
function dragged(event, d) {{ d.fx = event.x; d.fy = event.y; }}
function dragended(event, d) {{ if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}
</script>
</body>
</html>"""


def main() -> int:
    print("Querying GitNexus for communities...")
    communities = _get_communities()
    if not communities:
        print("No communities found. Run 'npx gitnexus analyze' first.", file=sys.stderr)
        return 1

    print(f"Found {len(communities)} communities")
    print("Deriving cross-community edges...")
    edges = _get_cross_community_edges(communities)
    print(f"Found {len(edges)} inter-module edges")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(_render_html(communities, edges))
    print(f"Written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
