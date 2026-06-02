from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

from common import build_error_result, print_json
from ovfs import OVFSClient, OVFSConfig, OVFSError, OVFSHTTPError, ensure_dir


ROOT_PAGES = {
    "index.md",
    "overview.md",
    "log.md",
}

WIKI_SUBDIRS = [
    "sources",
    "entities",
    "concepts",
    "syntheses",
]


def build_kb_root(kb_name: str) -> str:
    normalized_name = kb_name.strip().strip("/")
    if not normalized_name:
        raise ValueError("--kb-name cannot be empty")
    if normalized_name.startswith("viking://"):
        raise ValueError("--kb-name should be a resource name, not a full URI")
    return f"viking://resources/{normalized_name}/"


def build_graph_output_paths(kbRoot: str) -> tuple[str, str]:
    normalized_root = kbRoot.rstrip("/") + "/"
    return (
        normalized_root + "graph/graph.json",
        normalized_root + "graph/graph.html",
    )


def build_graph_output_dir_uri(kbRoot: str) -> str:
    normalized_root = kbRoot.rstrip("/") + "/"
    return normalized_root + "graph/"


def ensure_graph_output_dir(client: OVFSClient, kbRoot: str) -> None:
    graph_dir_uri = build_graph_output_dir_uri(kbRoot)
    ensure_dir(client, graph_dir_uri, description="wiki graph output dir")


def find_direct_content_child(client: OVFSClient, uri: str, extensions: tuple[str, ...] = (".md",)) -> str | None:
    if not uri.endswith("/"):
        uri = uri.rstrip("/") + "/"
    try:
        children = client.ls(uri, recursive=False)
    except Exception:
        return None

    candidates: List[str] = []

    for child in children:
        child_uri: Optional[str] = None
        child_is_dir: Optional[bool] = None

        if isinstance(child, str):
            child_uri = child
        elif isinstance(child, dict):
            child_uri = child.get("uri") or child.get("path")
            if isinstance(child.get("isDir"), bool):
                child_is_dir = child["isDir"]

        if not child_uri or not isinstance(child_uri, str):
            continue

        name = PurePosixPath(child_uri).name

        if name == "abstract.md":
            continue

        if not name.endswith(extensions):
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if child_is_dir:
            continue

        candidates.append(child_uri)

    parent_name = PurePosixPath(uri.rstrip("/")).name

    for candidate in candidates:
        if PurePosixPath(candidate).name == parent_name:
            return candidate

    for candidate in candidates:
        if PurePosixPath(candidate).name.startswith("tmp"):
            return candidate

    return candidates[0] if candidates else None


def get_uri_stat(client: OVFSClient, uri: str) -> Dict[str, Any] | None:
    try:
        return client.stat(uri)
    except OVFSHTTPError as exc:
        message = str(exc).lower()
        if "404" in message or "not found" in message:
            return None
        raise


def resolve_canonical_markdown_uri(client: OVFSClient, uri: str) -> str | None:
    stat = get_uri_stat(client, uri)
    if not stat:
        return None

    if not stat.get("isDir", False):
        return uri

    direct_child = find_direct_content_child(client, uri, extensions=(".md",))
    if direct_child:
        return direct_child

    basename = PurePosixPath(uri.rstrip("/")).name
    if not basename:
        return None

    nested_uri = uri.rstrip("/") + f"/{basename}"
    nested_stat = get_uri_stat(client, nested_uri)
    if nested_stat and not nested_stat.get("isDir", False):
        return nested_uri

    try:
        children = client.ls(uri.rstrip("/") + "/", recursive=False)
    except Exception:
        children = []

    for child in children:
        child_uri: Optional[str] = None
        child_is_dir: Optional[bool] = None

        if isinstance(child, str):
            child_uri = child
        elif isinstance(child, dict):
            child_uri = child.get("uri") or child.get("path")
            if isinstance(child.get("isDir"), bool):
                child_is_dir = child["isDir"]

        if not child_uri or not isinstance(child_uri, str):
            continue
        if not child_uri.endswith(".md"):
            continue
        name = PurePosixPath(child_uri).name
        if name == "abstract.md":
            continue

        if child_is_dir is None:
            child_stat = get_uri_stat(client, child_uri)
            child_is_dir = bool(child_stat and child_stat.get("isDir", False))

        if not child_is_dir:
            return child_uri

    return None


def extract_uri_from_ls_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item

    if not isinstance(item, dict):
        return None

    for key in ("uri", "path", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            if key == "name" and not value.startswith("viking://"):
                continue
            return value

    return None


def list_markdown_pages(client: OVFSClient, root_uri: str) -> List[str]:
    try:
        items = client.ls(root_uri, recursive=True)
    except Exception:
        return []

    uris: List[str] = []
    for item in items:
        uri = extract_uri_from_ls_item(item)
        if not uri:
            continue
        if not uri.startswith("viking://"):
            continue

        if isinstance(item, dict) and isinstance(item.get("isDir"), bool):
            is_dir = item["isDir"]
        else:
            stat = get_uri_stat(client, uri)
            is_dir = bool(stat and stat.get("isDir", False))

        if is_dir:
            continue
        if uri.endswith(".md"):
            uris.append(uri)

    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in uris:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)

    return deduped


def wiki_relative_path(kb_root: str, uri: str) -> str:
    prefix = kb_root + "wiki/"
    if uri.startswith(prefix):
        return uri[len(prefix):]
    return PurePosixPath(uri).name


def normalize_relative_wiki_target(target: str) -> str | None:
    target = target.strip()
    if not target:
        return None

    lower_target = target.lower()
    blocked_schemes = (
        "mailto:",
        "tel:",
        "javascript:",
        "data:",
        "viking://",
        "http://",
        "https://",
    )
    if lower_target.startswith(blocked_schemes):
        return None

    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target:
        return None
    if target.startswith("#"):
        return None

    if target.startswith("wiki/"):
        target = target[len("wiki/"):]

    target_path = PurePosixPath(target)
    if target_path.is_absolute():
        target_path = PurePosixPath(str(target_path).lstrip("/"))

    normalized_parts: List[str] = []
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if normalized_parts:
                normalized_parts.pop()
            continue
        normalized_parts.append(part)

    target = "/".join(normalized_parts)
    if not target:
        return None

    if target.endswith("/"):
        return None

    if not target.endswith(".md"):
        target = f"{target}.md"

    return target


def extract_internal_links(text: str) -> Set[str]:
    results: Set[str] = set()

    wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for raw in wikilink_pattern.findall(text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    for raw in markdown_link_pattern.findall(text):
        normalized = normalize_relative_wiki_target(raw)
        if normalized:
            results.add(normalized)

    return results


def build_candidate_target_uris(kb_root: str, source_page_uri: str, relative_target: str) -> List[str]:
    target = relative_target.strip().lstrip("/")
    source_rel = wiki_relative_path(kb_root, source_page_uri)
    source_dir = str(PurePosixPath(source_rel).parent)

    candidates: List[str] = []

    if "/" in target:
        candidates.append(kb_root + "wiki/" + target)
        return candidates

    if source_dir and source_dir != ".":
        candidates.append(kb_root + f"wiki/{source_dir}/{target}")

    for subdir in WIKI_SUBDIRS:
        candidates.append(kb_root + f"wiki/{subdir}/{target}")

    candidates.append(kb_root + "wiki/" + target)

    seen: Set[str] = set()
    deduped: List[str] = []
    for uri in candidates:
        if uri not in seen:
            seen.add(uri)
            deduped.append(uri)
    return deduped


def page_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def page_category(kb_root: str, uri: str) -> str:
    rel = wiki_relative_path(kb_root, uri)
    p = PurePosixPath(rel)
    if len(p.parts) >= 2:
        return p.parts[0]
    return "root"


def node_id_for_uri(uri: str) -> str:
    return uri


def build_nodes_and_edges(
    client: OVFSClient,
    kb_root: str,
    include_root_pages: bool = True,
) -> Dict[str, Any]:
    page_uris = list_markdown_pages(client, kb_root + "wiki/")
    page_map: Dict[str, str] = {}

    for uri in page_uris:
        try:
            page_map[uri] = client.read_text(uri)
        except Exception:
            page_map[uri] = ""

    nodes: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()

    for uri, text in page_map.items():
        rel = wiki_relative_path(kb_root, uri)
        name = PurePosixPath(rel).name
        if not include_root_pages and name in ROOT_PAGES:
            continue

        node = {
            "id": node_id_for_uri(uri),
            "uri": uri,
            "label": page_title(text) or name,
            "rel_path": rel,
            "category": page_category(kb_root, uri),
            "is_root": name in ROOT_PAGES,
        }
        nodes.append(node)
        node_ids.add(node["id"])

    edges: List[Dict[str, Any]] = []
    edge_seen: Set[Tuple[str, str]] = set()

    for source_uri, text in page_map.items():
        source_rel = wiki_relative_path(kb_root, source_uri)
        source_name = PurePosixPath(source_rel).name
        if not include_root_pages and source_name in ROOT_PAGES:
            continue

        for rel_target in sorted(extract_internal_links(text)):
            candidates = build_candidate_target_uris(kb_root, source_uri, rel_target)
            resolved_target: Optional[str] = None

            for candidate in candidates:
                canonical = resolve_canonical_markdown_uri(client, candidate)
                if canonical and canonical in page_map:
                    target_name = PurePosixPath(wiki_relative_path(kb_root, canonical)).name
                    if not include_root_pages and target_name in ROOT_PAGES:
                        continue
                    resolved_target = canonical
                    break

            if not resolved_target:
                continue

            key = (source_uri, resolved_target)
            if key in edge_seen:
                continue
            edge_seen.add(key)

            edges.append(
                {
                    "source": node_id_for_uri(source_uri),
                    "target": node_id_for_uri(resolved_target),
                    "kind": "explicit_link",
                }
            )

    return {
        "nodes": nodes,
        "edges": edges,
    }


def render_graph_html(graph_data: Dict[str, Any], kb_root: str) -> str:
    payload = json.dumps(graph_data, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>知识图谱</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0b1020;
      color: #e8ecf1;
    }}
    .wrap {{
      display: grid;
      grid-template-columns: 320px 1fr;
      height: 100vh;
    }}
    .sidebar {{
      border-right: 1px solid rgba(255,255,255,0.08);
      padding: 16px;
      overflow: auto;
      background: #0f152b;
    }}
    .sidebar h1 {{
      font-size: 18px;
      margin: 0 0 8px;
    }}
    .sidebar .meta {{
      font-size: 12px;
      color: #9fb0c3;
      margin-bottom: 16px;
      line-height: 1.4;
    }}
    .sidebar input {{
      width: 100%;
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.1);
      background: #0b1020;
      color: #fff;
      margin-bottom: 12px;
      box-sizing: border-box;
    }}
    .node-list {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .node-item {{
      padding: 8px 10px;
      border-radius: 10px;
      background: rgba(255,255,255,0.04);
      cursor: pointer;
      border: 1px solid transparent;
    }}
    .node-item:hover, .node-item.active {{
      border-color: rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
    }}
    .node-item .title {{
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 4px;
    }}
    .node-item .sub {{
      font-size: 11px;
      color: #9fb0c3;
      word-break: break-all;
    }}
    .canvas-wrap {{
      position: relative;
      overflow: hidden;
    }}
    svg {{
      width: 100%;
      height: 100%;
      display: block;
      background: radial-gradient(circle at center, #111936 0%, #09101f 100%);
    }}
    .legend {{
      position: absolute;
      top: 16px;
      right: 16px;
      background: rgba(11,16,32,0.82);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 12px;
      line-height: 1.6;
      color: #c8d4e2;
    }}
    .details {{
      position: absolute;
      bottom: 16px;
      right: 16px;
      width: 360px;
      max-width: calc(100vw - 380px);
      background: rgba(11,16,32,0.88);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.5;
      color: #dce6f0;
      box-sizing: border-box;
    }}
    .details h2 {{
      font-size: 14px;
      margin: 0 0 6px;
    }}
    .details .muted {{
      color: #9fb0c3;
      word-break: break-all;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <aside class="sidebar">
      <h1>知识图谱</h1>
      <div class="meta">
        知识库根路径: <br /><code>{kb_root}</code><br />
        节点: <span id="meta-nodes"></span> · 连边: <span id="meta-edges"></span>
      </div>
      <input id="search" type="text" placeholder="搜索页面标题或路径..." />
      <div id="node-list" class="node-list"></div>
    </aside>

    <div class="canvas-wrap">
      <svg id="graph" viewBox="0 0 1200 900" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="legend">
        <div><strong>分类</strong></div>
        <div>sources = 资料来源 (#6ee7b7)</div>
        <div>entities = 实体 (#93c5fd)</div>
        <div>concepts = 概念 (#f9a8d4)</div>
        <div>syntheses = 综合结论 (#fde68a)</div>
        <div>root = 根页面 (#c4b5fd)</div>
      </div>
      <div class="details" id="details">
        <h2>未选择页面</h2>
        <div class="muted">点击图节点，或从左侧列表选择页面。</div>
      </div>
    </div>
  </div>

  <script>
    const GRAPH_DATA = {payload};

    const svg = document.getElementById("graph");
    const details = document.getElementById("details");
    const nodeList = document.getElementById("node-list");
    const searchInput = document.getElementById("search");
    document.getElementById("meta-nodes").textContent = GRAPH_DATA.nodes.length;
    document.getElementById("meta-edges").textContent = GRAPH_DATA.edges.length;

    const W = 1200;
    const H = 900;
    const CENTER_X = W / 2;
    const CENTER_Y = H / 2;

    const colorMap = {{
      sources: "#6ee7b7",
      entities: "#93c5fd",
      concepts: "#f9a8d4",
      syntheses: "#fde68a",
      root: "#c4b5fd",
    }};
    const categoryLabelMap = {{
      sources: "资料来源",
      entities: "实体",
      concepts: "概念",
      syntheses: "综合结论",
      root: "根页面",
    }};

    const nodes = GRAPH_DATA.nodes.map((n, i) => {{
      const angle = (Math.PI * 2 * i) / Math.max(GRAPH_DATA.nodes.length, 1);
      const radius = 220 + (i % 5) * 25;
      return {{
        ...n,
        x: CENTER_X + Math.cos(angle) * radius,
        y: CENTER_Y + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      }};
    }});

    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const edges = GRAPH_DATA.edges
      .map(e => {{
        const s = nodeById.get(e.source);
        const t = nodeById.get(e.target);
        if (!s || !t) return null;
        return {{ ...e, s, t }};
      }})
      .filter(Boolean);

    const gEdges = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const gNodes = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(gEdges);
    svg.appendChild(gNodes);

    const edgeEls = edges.map(() => {{
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("stroke", "rgba(255,255,255,0.18)");
      line.setAttribute("stroke-width", "1.2");
      gEdges.appendChild(line);
      return line;
    }});

    const nodeEls = nodes.map(n => {{
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");

      c.setAttribute("r", n.is_root ? "9" : "7");
      c.setAttribute("fill", colorMap[n.category] || "#d1d5db");
      c.setAttribute("stroke", "rgba(255,255,255,0.5)");
      c.setAttribute("stroke-width", "1.2");

      t.textContent = n.label;
      t.setAttribute("fill", "#e8ecf1");
      t.setAttribute("font-size", "11");
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("dy", "-12");

      g.appendChild(c);
      g.appendChild(t);
      g.style.cursor = "pointer";
      gNodes.appendChild(g);
      return {{ g, c, t, node: n }};
    }});

    function clamp(val, min, max) {{
      return Math.max(min, Math.min(max, val));
    }}

    function tick() {{
      // repulsion
      for (let i = 0; i < nodes.length; i++) {{
        for (let j = i + 1; j < nodes.length; j++) {{
          const a = nodes[i];
          const b = nodes[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let dist2 = dx * dx + dy * dy + 0.01;
          let dist = Math.sqrt(dist2);
          let force = 5000 / dist2;

          let fx = force * dx / dist;
          let fy = force * dy / dist;

          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }}
      }}

      // spring edges
      for (const e of edges) {{
        const a = e.s;
        const b = e.t;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const target = 130;
        const k = 0.0035;
        const force = (dist - target) * k;

        let fx = force * dx;
        let fy = force * dy;

        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }}

      // mild gravity toward center
      for (const n of nodes) {{
        n.vx += (CENTER_X - n.x) * 0.0008;
        n.vy += (CENTER_Y - n.y) * 0.0008;
      }}

      // integrate
      for (const n of nodes) {{
        n.vx *= 0.86;
        n.vy *= 0.86;
        n.x += n.vx;
        n.y += n.vy;
        n.x = clamp(n.x, 40, W - 40);
        n.y = clamp(n.y, 40, H - 40);
      }}

      render();
      requestAnimationFrame(tick);
    }}

    function render() {{
      edges.forEach((e, i) => {{
        edgeEls[i].setAttribute("x1", e.s.x);
        edgeEls[i].setAttribute("y1", e.s.y);
        edgeEls[i].setAttribute("x2", e.t.x);
        edgeEls[i].setAttribute("y2", e.t.y);
      }});

      nodeEls.forEach(({{g, t, node}}) => {{
        g.setAttribute("transform", `translate(${{node.x}}, ${{node.y}})`);
        t.setAttribute("display", node.hidden ? "none" : "block");
        g.setAttribute("opacity", node.hidden ? "0.12" : "1");
      }});
    }}

    function selectNode(node) {{
      nodeEls.forEach(({{c, node: n, g}}) => {{
        c.setAttribute("stroke-width", n.id === node.id ? "3" : "1.2");
        c.setAttribute("stroke", n.id === node.id ? "#ffffff" : "rgba(255,255,255,0.5)");
      }});

      const inbound = edges.filter(e => e.t.id === node.id).map(e => e.s.label);
      const outbound = edges.filter(e => e.s.id === node.id).map(e => e.t.label);

      details.innerHTML = `
        <h2>${{escapeHtml(node.label)}}</h2>
        <div><strong>分类:</strong> ${{escapeHtml(categoryLabelMap[node.category] || node.category)}}</div>
        <div class="muted"><strong>URI:</strong><br />${{escapeHtml(node.uri)}}</div>
        <div style="margin-top:8px;"><strong>入链:</strong> ${{inbound.length}}</div>
        <div class="muted">${{escapeHtml(inbound.slice(0, 12).join(", ") || "无")}}</div>
        <div style="margin-top:8px;"><strong>出链:</strong> ${{outbound.length}}</div>
        <div class="muted">${{escapeHtml(outbound.slice(0, 12).join(", ") || "无")}}</div>
      `;

      document.querySelectorAll(".node-item").forEach(el => {{
        el.classList.toggle("active", el.dataset.id === node.id);
      }});
    }}

    function escapeHtml(str) {{
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }}

    function renderNodeList(filterText = "") {{
      const q = filterText.trim().toLowerCase();
      nodeList.innerHTML = "";

      const filtered = nodes.filter(n => {{
        if (!q) return true;
        return n.label.toLowerCase().includes(q) || n.rel_path.toLowerCase().includes(q);
      }});

      nodes.forEach(n => {{
        n.hidden = !filtered.includes(n);
      }});

      filtered
        .sort((a, b) => a.label.localeCompare(b.label))
        .forEach(n => {{
          const el = document.createElement("div");
          el.className = "node-item";
          el.dataset.id = n.id;
          el.innerHTML = `
            <div class="title">${{escapeHtml(n.label)}}</div>
            <div class="sub">${{escapeHtml(n.rel_path)}}</div>
          `;
          el.addEventListener("click", () => selectNode(n));
          nodeList.appendChild(el);
        }});

      render();
    }}

    nodeEls.forEach(({{g, node}}) => {{
      g.addEventListener("click", () => selectNode(node));
    }});

    searchInput.addEventListener("input", (e) => {{
      renderNodeList(e.target.value || "");
    }});

    renderNodeList("");
    render();
    requestAnimationFrame(tick);
  </script>
</body>
</html>
"""


def expected_content_child_uri(uri: str) -> str:
    normalized = uri.rstrip("/")
    basename = PurePosixPath(normalized).name
    return f"{normalized}/{basename}"


def resolve_write_target_uri(client: OVFSClient, uri: str) -> tuple[str, bool]:
    stat = get_uri_stat(client, uri)
    if not stat:
        return uri, True

    if not stat.get("isDir", False):
        return uri, False

    same_name_child = expected_content_child_uri(uri)
    same_name_stat = get_uri_stat(client, same_name_child)
    if same_name_stat and not same_name_stat.get("isDir", False):
        return same_name_child, False

    extension = PurePosixPath(uri.rstrip("/")).suffix
    content_child = find_direct_content_child(client, uri, extensions=(extension,) if extension else (".md",))
    if content_child:
        return content_child, False

    fallback_child = find_direct_content_child(client, uri, extensions=(".md", ".json", ".html"))
    if fallback_child:
        return fallback_child, False

    return same_name_child, True


def write_page(client: OVFSClient, uri: str, content: str, reason: str) -> None:
    target_uri, should_create = resolve_write_target_uri(client, uri)
    if should_create:
        suffix = ".md" if target_uri.endswith(".md") else ".json"
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fp:
            fp.write(content)
            local_file_path = fp.name

        client.add_local_resource(
            file_path=local_file_path,
            to=target_uri,
            reason=reason,
            wait=False,
        )
        return

    client.write_text(target_uri, content, create=False, wait=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an explicit-link graph from a remote OpenViking wiki KB.")
    parser.add_argument("--kb-name", required=True, help="Knowledge base name under viking://resources/")
    parser.add_argument("--config", default=None, help="Path to config JSON")
    parser.add_argument("--profile", default=None, help="Profile name")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kb_root = ""

    try:
        kb_root = build_kb_root(args.kb_name)
        config = OVFSConfig.load(config_path=args.config, profile=args.profile)

        with OVFSClient(config) as client:
            graph_data = build_nodes_and_edges(
                client=client,
                kb_root=kb_root,
                include_root_pages=False,
            )

            node_count = len(graph_data["nodes"])
            edge_count = len(graph_data["edges"])

            ensure_graph_output_dir(client, kb_root)
            graph_json_uri, graph_html_uri = build_graph_output_paths(kb_root)

            graph_json_text = json.dumps(graph_data, ensure_ascii=False, indent=2)
            graph_html_text = render_graph_html(graph_data, kb_root)

            write_page(client, graph_json_uri, graph_json_text, reason="wiki graph json")
            write_page(client, graph_html_uri, graph_html_text, reason="wiki graph html")

            result = {
                "status": "ok",
                "kb_root": kb_root,
                "node_count": node_count,
                "edge_count": edge_count,
                "graph_json_uri": graph_json_uri,
                "graph_html_uri": graph_html_uri,
            }

            print_json(result, pretty=args.pretty)
            return 0

    except Exception as exc:
        print_json(build_error_result(exc, kb_root=kb_root), pretty=args.pretty)
        return 1


if __name__ == "__main__":
    sys.exit(main())
