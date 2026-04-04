#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
把 DroidBot state.json 里的 views 列表还原为组件树

输入:
- state.json (包含 views 列表, 每个 view 有 temp_id / parent / children)

输出:
- tree.json (单根树; 若有多个根会自动挂到虚拟根节点)
"""

import json
import copy
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_json(path: Path) -> Dict[str, Any]:
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            pass
    raise ValueError(f"无法解析 JSON: {path}")


def to_int(v: Any) -> Optional[int]:
    try:
        if isinstance(v, bool):
            return None
        return int(v)
    except Exception:
        return None


def build_tree_from_views(views: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    核心逻辑:
    1) 建 id -> 节点映射
    2) 按 children id 建父子关系
    3) 用 parent 字段补关系（若 children 不完整）
    4) 找根节点；多根时挂虚拟根
    """
    # 1) 复制节点，准备容器
    node_map: Dict[int, Dict[str, Any]] = {}
    for idx, v in enumerate(views):
        node = copy.deepcopy(v)
        nid = to_int(node.get("temp_id"))
        if nid is None:
            nid = idx
            node["temp_id"] = nid

        # 保存原始 children id
        raw_children = node.get("children", [])
        node["children_ids_raw"] = raw_children if isinstance(raw_children, list) else []
        # 这里先用对象 children，后续填充
        node["children"] = []
        node_map[nid] = node

    # 防止重复挂载，记录每个父节点已经挂了哪些子节点
    attached: Dict[int, set] = {nid: set() for nid in node_map}

    # 2) 先按 children id 挂载
    for pid, pnode in node_map.items():
        for cid_raw in pnode.get("children_ids_raw", []):
            cid = to_int(cid_raw)
            if cid is None:
                continue
            cnode = node_map.get(cid)
            if cnode is None:
                continue
            if cid not in attached[pid]:
                pnode["children"].append(cnode)
                attached[pid].add(cid)

    # 3) 再按 parent 字段补挂载（避免 children 不完整）
    for cid, cnode in node_map.items():
        pid = to_int(cnode.get("parent"))
        if pid is None or pid == -1:
            continue
        pnode = node_map.get(pid)
        if pnode is None:
            continue
        if cid not in attached[pid]:
            pnode["children"].append(cnode)
            attached[pid].add(cid)

    # 4) 找根
    roots: List[Dict[str, Any]] = []
    for nid, node in node_map.items():
        pid = to_int(node.get("parent"))
        if pid is None or pid == -1 or pid not in node_map:
            roots.append(node)

    # 单根直接返回；多根构造虚拟根
    if len(roots) == 1:
        return roots[0]

    return {
        "temp_id": -999999,
        "class": "virtual.root",
        "text": "virtual_root",
        "parent": -1,
        "children_ids_raw": [r.get("temp_id") for r in roots],
        "children": roots
    }


def main():
    parser = argparse.ArgumentParser(description="把 DroidBot views 列表还原成树")
    parser.add_argument("-i", dest="input", required=True, help="state.json 路径")
    # parser.add_argument("--output", required=True, help="输出 tree.json 路径")
    args = parser.parse_args()

    in_path = Path(args.input) / f"states"
    out_path = Path(args.input) / f"trees"

    state_files = sorted(in_path.glob("state_*.json"))

    ok = 0

    for state_file in state_files:
        out_file = out_path / f"{state_file.stem}.json"
        state = load_json(state_file)
        views = state.get("views", [])
        if not isinstance(views, list):
            raise ValueError("state.json 中 views 不是列表")

        tree = build_tree_from_views(views)

        state['viewTree'] = tree

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"完成: {out_path} | 原始节点数: {len(views)}")
        ok += 1
    print(f"\n批处理完成: 成功 {ok} 个, 失败 {len(state_files) - ok} 个, 总计 {len(state_files)} 个")

if __name__ == "__main__":
    main()
    