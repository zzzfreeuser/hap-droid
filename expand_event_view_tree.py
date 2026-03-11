"""
将 DroidBot 事件中的 event.view.children(仅ID)展开为完整树结构。

需求对应：
1) 根据 event.json 的 start_state 找到对应 state.jso(state_str)
2) 在该 state 的 views 中，根据 children 的 id 递归展开
3) 一个 event 最多只有一个 view 字段（按此假设处理）
4) 输出到新目录，避免污染原始数据

默认输入目录结构（可通过参数改）：
- <run_dir>/events/event_*.json
- <run_dir>/states/state_*.json
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    """容错读取 JSON。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def write_json(path: Path, data: Dict[str, Any]) -> None:
    """写出格式化 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def to_int_id(value: Any) -> Optional[int]:
    """将 children 中的 id 统一转换为 int; 无法转换则返回 None。"""
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def build_state_index(states_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    建立 state_str -> state_json 的索引。
    这样可以快速通过 event.start_state 定位对应 state。
    """
    index: Dict[str, Dict[str, Any]] = {}
    for fp in sorted(states_dir.glob("state_*.json")):
        data = read_json(fp)
        if not isinstance(data, dict):
            continue
        state_str = data.get("state_str")
        if isinstance(state_str, str) and state_str:
            index[state_str] = data
    return index


def build_view_index(state_json: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """
    从 state.views 建立 temp_id -> view 的索引。
    注意: DroidBot 的 children 常引用 temp_id。
    """
    views = state_json.get("views", [])
    result: Dict[int, Dict[str, Any]] = {}

    if not isinstance(views, list):
        return result

    for i, v in enumerate(views):
        if not isinstance(v, dict):
            continue

        # 优先用 temp_id；缺失时退化为数组下标 i
        vid = to_int_id(v.get("temp_id"))
        if vid is None:
            vid = i

        result[vid] = v

    return result


def expand_view_from_state(
    view_id: int,
    view_index: Dict[int, Dict[str, Any]],
    visited: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """
    从 state 的 view_index 递归展开一个节点。
    - children 从 [id, id, ...] 转为 [node, node, ...]
    - 为避免环，使用 visited
    """
    if visited is None:
        visited = set()

    if view_id in visited:
        # 遇到环时返回最小占位，避免无限递归
        return {"temp_id": view_id, "children": [], "_cycle_cut": True}

    visited.add(view_id)

    raw = view_index.get(view_id)
    if raw is None:
        return {"temp_id": view_id, "children": [], "_missing_in_state": True}

    node = copy.deepcopy(raw)
    child_ids_raw = node.get("children", [])

    expanded_children: List[Dict[str, Any]] = []
    if isinstance(child_ids_raw, list):
        for cid_raw in child_ids_raw:
            cid = to_int_id(cid_raw)
            if cid is None:
                continue
            expanded_children.append(expand_view_from_state(cid, view_index, visited))

    # 保留原始 children id，便于调试/追溯
    node["children_ids"] = child_ids_raw if isinstance(child_ids_raw, list) else []
    # 覆盖为展开后的树结构
    node["children"] = expanded_children

    visited.remove(view_id)
    return node


def expand_event_view(
    event_view: Dict[str, Any],
    view_index: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    展开 event.view。
    优先通过 event.view.temp_id 作为根节点去 state 中找标准节点并展开。
    若 temp_id 缺失，则以 event.view 自身为根，仅展开其 children 指向的子节点。
    """
    root_id = to_int_id(event_view.get("temp_id"))

    if root_id is not None and root_id in view_index:
        return expand_view_from_state(root_id, view_index)

    # 兜底：复制 event.view 自身，并尝试展开它的 children
    node = copy.deepcopy(event_view)
    child_ids_raw = node.get("children", [])

    expanded_children: List[Dict[str, Any]] = []
    if isinstance(child_ids_raw, list):
        for cid_raw in child_ids_raw:
            cid = to_int_id(cid_raw)
            if cid is None:
                continue
            expanded_children.append(expand_view_from_state(cid, view_index, set()))

    node["children_ids"] = child_ids_raw if isinstance(child_ids_raw, list) else []
    node["children"] = expanded_children
    return node


def process_events(run_dir: Path, out_dir: Path) -> Tuple[int, int, int]:
    """
    主处理流程：
    - 返回 (总事件数, 成功展开数, 跳过数)
    """
    events_dir = run_dir / "events"
    states_dir = run_dir / "states"
    out_events_dir = out_dir / "events"

    state_index = build_state_index(states_dir)

    total = 0
    expanded = 0
    skipped = 0

    for event_fp in sorted(events_dir.glob("event_*.json")):
        total += 1
        data = read_json(event_fp)
        if not isinstance(data, dict):
            skipped += 1
            continue

        start_state = data.get("start_state")
        event_obj = data.get("event", {})

        # 无 start_state 或无 event/view，直接拷贝输出
        if not isinstance(start_state, str) or not isinstance(event_obj, dict) or not isinstance(event_obj.get("view"), dict):
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            continue

        state_json = state_index.get(start_state)
        if state_json is None:
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            continue

        view_index = build_view_index(state_json)
        if not view_index:
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            continue

        # 展开 event.view
        original_view = event_obj["view"]
        event_obj["view"] = expand_event_view(original_view, view_index)
        data["event"] = event_obj

        write_json(out_events_dir / event_fp.name, data)
        expanded += 1

    return total, expanded, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="根据 start_state 展开 DroidBot event.view.children 为树结构")
    parser.add_argument(
        "-i",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\baidunetdisk_1000"),
        dest="run_dir",
        help="包含 events/ 和 states/ 的运行目录",
    )
    parser.add_argument(
        "-o",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\baidunetdisk_1000_expanded"),
        dest="out_dir",
        help="输出目录（会写入 events/）",
    )
    args = parser.parse_args()

    total, expanded, skipped = process_events(args.run_dir, args.out_dir)

    print("处理完成")
    print(f"总事件数: {total}")
    print(f"成功展开: {expanded}")
    print(f"跳过数量: {skipped}")
    print(f"输出目录: {args.out_dir}")


if __name__ == "__main__":
    main()