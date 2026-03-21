"""
将 HapTest 的 .dot 文件转换为 DroidBot 的 utg.js 格式

输入: ptg.dot (graphviz 文件)
输出: utg.js (DroidBot 可视化格式)
"""

import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any


def parse_dot_file(dot_path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    解析 .dot 文件，提取节点和边信息
    支持：
    1) 节点空属性: "A" [ ];
    2) 节点有属性: "A" [label="xxx", image="..."];
    3) 边有/无属性: "A" -> "B"; / "A" -> "B" [label="tap"];
    """
    content = dot_path.read_text(encoding="utf-8", errors="ignore")

    def parse_attrs(attr_text: str) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        if not attr_text:
            return attrs
        # 只提取 key="value" 形式
        for k, v in re.findall(r'([A-Za-z_]\w*)\s*=\s*"((?:[^"\\]|\\.)*)"', attr_text, flags=re.S):
            attrs[k] = v
        return attrs

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    node_seen: Set[str] = set()

    # 节点语句："id" [ ... ];
    node_stmt_re = re.compile(
        r'"([^"]+)"\s*\[(.*?)\]\s*;',
        flags=re.S
    )

    # 边语句："from" -> "to" [ ... ]; 或 "from" -> "to";
    edge_stmt_re = re.compile(
        r'"([^"]+)"\s*->\s*"([^"]+)"(?:\s*\[(.*?)\])?\s*;',
        flags=re.S
    )

    # 先解析边，后面可补齐节点
    for m in edge_stmt_re.finditer(content):
        from_id = m.group(1)
        to_id = m.group(2)
        edge_attrs = parse_attrs(m.group(3) or "")
        edges.append({
            "from": from_id,
            "to": to_id,
            "attrs": edge_attrs
        })

    # 解析节点（排除边语句）
    for m in node_stmt_re.finditer(content):
        stmt = m.group(0)
        if "->" in stmt:
            continue  # 避免误判
        node_id = m.group(1)
        attrs = parse_attrs(m.group(2) or "")
        label = (attrs.get("label") or node_id).strip()
        image = attrs.get("image", "").strip()

        if node_id not in node_seen:
            node_seen.add(node_id)
            nodes.append({
                "id": node_id,
                "label": label,
                "image": image
            })

    # 若 dot 里没单独声明节点，则从边里补齐
    for e in edges:
        for nid in (e["from"], e["to"]):
            if nid not in node_seen:
                node_seen.add(nid)
                nodes.append({
                    "id": nid,
                    "label": nid,
                    "image": ""
                })

    return nodes, edges


def normalize_label(label: str) -> str:
    """
    规范化标签（去掉尾部换行）
    """
    return label.replace("\\n", "").strip()


def build_utg_js_object(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    构建 DroidBot utg.js 格式的对象
    """
    
    # 构建节点列表
    utg_nodes = []
    for node in nodes:
        node_id = node["id"]
        label = normalize_label(node["label"])
        image = node["image"]
        
        utg_node = {
            "id": node_id,
            "label": label,
            "package": "",
            "activity": "",
            "state_str": node_id,
            "state_str_content_free": node_id,
            "screenshot": image if image else None,
            "image": image if image else None,
            "shape": "image" if image else "box",
            "title": f"<table class=\"table\">\n<tr><th>state_str</th><td>{node_id}</td></tr>\n</table>",
            "content": label
        }
        utg_nodes.append(utg_node)
    
    # 构建边列表
    utg_edges = []
    edge_id_counter = {}
    
    for i, edge in enumerate(edges):
        from_id = edge["from"]
        to_id = edge["to"]
        edge_key = f"{from_id}-->{to_id}"
        
        # 同一对节点的多条边用编号区分
        if edge_key in edge_id_counter:
            edge_id_counter[edge_key] += 1
            label = str(edge_id_counter[edge_key])
        else:
            edge_id_counter[edge_key] = 1
            label = "1"
        
        utg_edge = {
            "from": from_id,
            "to": to_id,
            "id": edge_key,
            "title": f"<table class=\"table\">\n<tr><th>{label}</th><td>Event</td></tr>\n</table>",
            "label": label,
            "events": [
                {
                    "event_str": "TouchEvent",
                    "event_id": i,
                    "event_type": "touch",
                    "view_images": []
                }
            ]
        }
        utg_edges.append(utg_edge)
    
    # 构建完整 utg 对象
    utg = {
        "nodes": utg_nodes,
        "edges": utg_edges,
        "num_nodes": len(utg_nodes),
        "num_edges": len(utg_edges),
        "num_effective_events": len(utg_edges),
        "num_reached_activities": len(set(n["activity"] for n in utg_nodes if n["activity"])) or len(utg_nodes),
        "test_date": "2026-03-21",
        "time_spent": 0,
        "device_serial": "emulator-5554",
        "device_model_number": "unknown",
        "device_sdk_version": 0,
        "app_package": "com.example.app",
        "app_main_activity": "MainActivity"
    }
    
    return utg


def convert_dot_to_utg_js(dot_path: Path, output_path: Path) -> None:
    """
    主转换函数
    """
    print(f"[INFO] 读取 .dot 文件: {dot_path}")
    
    nodes, edges = parse_dot_file(dot_path)
    print(f"[INFO] 解析得到 {len(nodes)} 个节点，{len(edges)} 条边")
    
    utg_obj = build_utg_js_object(nodes, edges)
    
    # 生成 utg.js 内容
    utg_js_content = f"var utg = {json.dumps(utg_obj, ensure_ascii=False, indent=2)};"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(utg_js_content, encoding="utf-8")
    
    print(f"[INFO] utg.js 已生成: {output_path}")
    print(f"       节点数: {utg_obj['num_nodes']}")
    print(f"       边数: {utg_obj['num_edges']}")


def main():
    parser = argparse.ArgumentParser(description="将 HapTest .dot 转换为 DroidBot utg.js")
    parser.add_argument("dot_file", type=Path, help="输入 .dot 文件路径")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="输出 utg.js 文件路径（默认: 同目录下 utg.js）"
    )
    
    args = parser.parse_args()
    
    if not args.dot_file.exists():
        print(f"[ERROR] 文件不存在: {args.dot_file}")
        return
    
    output = args.output or args.dot_file.parent / "utg.js"
    convert_dot_to_utg_js(args.dot_file, output)


if __name__ == "__main__":
    main()