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
from datetime import datetime


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

def parse_timestamp(time_str: str) -> Optional[datetime]:
    """
    解析时间戳字符串为 datetime 对象。
    支持格式: "2026-04-05_201428" 等
    """
    try:
        return datetime.strptime(time_str, "%Y-%m-%d_%H%M%S")
    except Exception:
        return None


def build_state_index_by_time(states_dir: Path) -> List[Tuple[datetime, Dict[str, Any], str]]:
    """
    按时间戳建立 state 索引。
    返回: [(时间戳, state_json, 文件名), ...] 按时间排序
    """
    states_list: List[Tuple[datetime, Dict[str, Any], str]] = []
    
    for fp in sorted(states_dir.glob("state_*.json")):
        # 从文件名提取时间戳，如 "state_2026-04-05_201457.json"
        stem = fp.stem  # "state_2026-04-05_201457"
        time_str = stem.replace("state_", "")
        
        ts = parse_timestamp(time_str)
        if ts is None:
            print(f'解析时间戳失败: {time_str}')
            continue
        
        data = read_json(fp)
        if not isinstance(data, dict):
            print(f'解析 JSON 失败: {fp}')
            continue
        
        states_list.append((ts, data, fp.name))
    
    states_list.sort(key=lambda x: x[0])
    return states_list


def find_nearest_state(
    event_time: datetime,
    states_list: List[Tuple[datetime, Dict[str, Any], str]],
) -> Optional[Dict[str, Any]]:
    """
    根据事件时间戳，找到最近的最早的 state。
    即: 找到时间戳 <= event_time 且最接近的 state。
    """
    candidates = [s for s in states_list if s[0] <= event_time]
    if not candidates:
        return None
    
    # 取最后一个（时间最近的且 <= event_time）
    return candidates[-1][1]


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
        visited.remove(view_id)
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

def build_child_index_maps(
    view_index: Dict[int, Dict[str, Any]],
) -> Tuple[Dict[Tuple[int, int], int], Dict[int, int]]:
    """
    返回:
    1) (parent_id, child_id) -> child_index
    2) child_id -> parent_id
    """
    parent_child_to_index: Dict[Tuple[int, int], int] = {}
    child_to_parent: Dict[int, int] = {}

    for pid, pnode in view_index.items():
        raw_children = pnode.get("children", [])
        if not isinstance(raw_children, list):
            continue

        for idx, cid_raw in enumerate(raw_children):
            cid = to_int_id(cid_raw)
            if cid is None:
                continue
            parent_child_to_index[(pid, cid)] = idx
            child_to_parent[cid] = pid

    return parent_child_to_index, child_to_parent


def build_view_child_index_path_from_state(
    target_view_id: int,
    view_index: Dict[int, Dict[str, Any]],
) -> Tuple[List[int], List[str], List[int]]:
    """
    返回:
    1) child_index_path: 从 root 到 target 的"第几个孩子"路径，如 [0, 0, 2, 1]
    2) path_classes: root->target 每层 class
    3) path_node_ids: root->target 节点 id（仅调试用，可不落盘）
    """
    parent_child_to_index, child_to_parent = build_child_index_maps(view_index)

    # 先回溯 root->target 的节点链
    node_chain: List[int] = []
    seen: Set[int] = set()
    cur: Optional[int] = target_view_id

    while cur is not None and cur not in seen and cur in view_index:
        seen.add(cur)
        node_chain.append(cur)

        p = child_to_parent.get(cur)
        if p is None:
            # 再兜底用 parent 字段
            p = to_int_id(view_index[cur].get("parent"))
            if p is None or p == -1:
                break
        cur = p if p in view_index else None

    node_chain.reverse()  # root -> target

    # 根据相邻父子节点求 child_index_path
    child_index_path: List[int] = []
    for i in range(1, len(node_chain)):
        pid = node_chain[i - 1]
        cid = node_chain[i]
        idx = parent_child_to_index.get((pid, cid), -1)
        child_index_path.append(idx)

    path_classes: List[str] = []
    for vid in node_chain:
        cls = view_index.get(vid, {}).get("class")
        path_classes.append(cls if isinstance(cls, str) else "")

    return child_index_path, path_classes, node_chain

def resolve_event_view_id(
    event_view: Dict[str, Any],
    view_index: Dict[int, Dict[str, Any]],
) -> Optional[int]:
    """
    尝试确定 event.view 对应的 temp_id
    优先级:
    1) event.view.temp_id
    2) 用 view_str / signature / content_free_signature 在 state 中匹配
    """
    rid = to_int_id(event_view.get("temp_id"))
    if rid is not None and rid in view_index:
        return rid

    for key in ("view_str", "signature", "content_free_signature"):
        v = event_view.get(key)
        if not isinstance(v, str) or not v:
            continue
        for vid, node in view_index.items():
            if node.get(key) == v:
                return vid

    return None


def build_view_path_from_state(
    target_view_id: int,
    view_index: Dict[int, Dict[str, Any]],
) -> Tuple[List[int], List[str]]:
    """
    根据 parent 指针，从目标节点回溯到根，再反转得到 root->target 路径
    返回:
    - path_ids: [0, 1, 2, ... , target]
    - path_classes: ["android.widget.FrameLayout", ...]
    """
    path_ids: List[int] = []
    seen: Set[int] = set()
    cur: Optional[int] = target_view_id

    while cur is not None and cur not in seen:
        seen.add(cur)
        node = view_index.get(cur)
        if node is None:
            break

        path_ids.append(cur)

        parent_id = to_int_id(node.get("parent"))
        if parent_id is None or parent_id == -1:
            break
        cur = parent_id

    path_ids.reverse()
    path_classes: List[str] = []
    for vid in path_ids:
        cls = view_index.get(vid, {}).get("class")
        path_classes.append(cls if isinstance(cls, str) else "")

    return path_ids, path_classes

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


def build_state_index_by_name(states_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    按文件名/文件 stem 建立 state 索引，优先用于 start_state 匹配。
    """
    index: Dict[str, Dict[str, Any]] = {}

    for fp in sorted(states_dir.glob("state_*.json")):
        data = read_json(fp)
        if not isinstance(data, dict):
            continue

        stem = fp.stem              # state_2026-04-05_201457
        name = fp.name              # state_2026-04-05_201457.json
        short = stem.replace("state_", "", 1)   # 2026-04-05_201457

        for key in {stem, name, short, f"{stem}.json", f"state_{short}"}:
            index[key] = data

    return index


def normalize_state_ref(value: Any) -> Optional[str]:
    """
    归一化 start_state 引用，兼容：
    - state_2026-04-05_201457
    - state_2026-04-05_201457.json
    - 2026-04-05_201457
    - 路径形式
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    s = s.replace("\\", "/")
    name = s.split("/")[-1]
    if name.endswith(".json"):
        name = name[:-5]
    return name or None


def find_state_by_start_state(
    start_state: Any,
    state_index_by_name: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    优先按 start_state 精确匹配 state。
    """
    key = normalize_state_ref(start_state)
    if key is None:
        return None

    candidates = [
        key,
        f"{key}.json",
        f"state_{key}" if not key.startswith("state_") else key,
        f"state_{key}.json" if not key.startswith("state_") else f"{key}.json",
    ]

    for k in candidates:
        if k in state_index_by_name:
            return state_index_by_name[k]

    return None


def process_events(run_dir: Path, out_dir: Path) -> Tuple[int, int, int]:
    """
    主处理流程：
    - 优先按 event.start_state 找状态
    - 找不到再按时间戳找最近且最早的 state
    - 返回 (总事件数, 成功展开数, 跳过数)
    """
    events_dir = run_dir / "events"
    states_dir = run_dir / "trees"
    out_events_dir = out_dir / "events"

    # 两套索引：按名称、按时间
    state_index = build_state_index(states_dir)
    states_list = build_state_index_by_time(states_dir)

    if not states_list:
        print("警告: 未找到任何状态文件")
        return 0, 0, 0

    total = 0
    expanded = 0
    skipped = 0

    for event_fp in sorted(events_dir.glob("event_*.json")):
        total += 1
        data = read_json(event_fp)
        if not isinstance(data, dict):
            skipped += 1
            print(f"跳过原因: 解析 JSON 失败 - {event_fp}")
            continue

        stem = event_fp.stem
        time_str = stem.replace("event_", "")
        event_time = parse_timestamp(time_str)

        start_state = data.get("start_state")
        event_obj = data.get("event", {})
        if not isinstance(event_obj, dict) or not isinstance(event_obj.get("view"), dict):
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            print(f"跳过原因: event.view 不存在或格式不正确 - {event_fp}")
            continue

        # 1) 优先按 start_state 找
        state_json = state_index.get(start_state)

        # 2) 找不到再按时间戳找最近且最早的 state
        if state_json is None:
            print(f"未通过 start_state 匹配到状态{start_state}，尝试按时间戳匹配 - {event_fp}")
            if event_time is None:
                write_json(out_events_dir / event_fp.name, data)
                skipped += 1
                print(f"跳过原因: start_state 未命中且事件时间戳解析失败 - {event_fp}")
                continue

            state_json = find_nearest_state(event_time, states_list)

        if state_json is None:
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            print(f"跳过原因: 未找到对应状态 - {event_fp}")
            continue

        view_index = build_view_index(state_json)
        if not view_index:
            write_json(out_events_dir / event_fp.name, data)
            skipped += 1
            print(f"跳过原因: 未找到有效的 view_index - {event_fp}")
            continue

        original_view = event_obj["view"]
        event_obj["view"] = expand_event_view(original_view, view_index)
        event_obj["viewTree"] = state_json.get("viewTree", {})
        event_obj["imageUrl"] = state_json.get("imageUrl")

        data["event"] = event_obj
        write_json(out_events_dir / event_fp.name, data)
        expanded += 1

    return total, expanded, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="根据时间戳展开 DroidBot event.view.children 为树结构")
    parser.add_argument(
        "-i",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\baidunetdisk_1000"),
        dest="run_dir",
        help="包含 events/ 和 trees/ 的运行目录",
    )
    parser.add_argument(
        "-o",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\baidunetdisk_1000_expanded"),
        dest="out_dir",
        help="输出目录(会写入 events/)",
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