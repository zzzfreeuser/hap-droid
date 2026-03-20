"""
将 DroidBot 事件 JSON 转换为 HapTest replay 事件 JSON

输入（默认）:
- d:/GithubProjects/hap-droid/droidbot_events/event_*.json

输出（默认）:
- d:/GithubProjects/hap-droid/converted_haptest_events/events/transition_*.json

说明：
1) 重点对齐 event 字段(HapTest replay 核心消费字段)
2) 同时补齐 from/to/fromContentSig/toContentSig, 保证结构完整
3) 对未知事件类型给出 warning, 并跳过(可在论文中统计“不可映射率”)
"""

from __future__ import annotations

import subprocess
import argparse
import json
import re
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# -----------------------------
# 基础数据结构
# -----------------------------
@dataclass
class ConvertStats:
    total: int = 0
    converted: int = 0
    skipped: int = 0
    warnings: int = 0


# -----------------------------
# 通用工具函数
# -----------------------------

def normalize_point(
    x: int, y: int,
    src_w: int, src_h: int,
    dst_w: int, dst_h: int
) -> Tuple[int, int]:
    """
    将源设备坐标(x,y)映射到目标设备坐标
    """
    nx = round(x / src_w * dst_w)
    ny = round(y / src_h * dst_h)
 
    # 边界裁剪
    nx = max(0, min(nx, dst_w - 1))  
    ny = max(0, min(ny, dst_h - 1))
    return nx, ny
  
def normalize_bounds(
    x1: float, y1: float, x2: float, y2: float,
    src_w: int, src_h: int,
    dst_w: int, dst_h: int
) -> Tuple[int, int, int, int]:
    """
    将矩形边界映射到目标设备
    """
    nx1, ny1 = normalize_point(x1, y1, src_w, src_h, dst_w, dst_h)
    nx2, ny2 = normalize_point(x2, y2, src_w, src_h, dst_w, dst_h)
    return nx1, ny1, nx2, ny2

def read_json(fp: Path) -> Optional[Dict[str, Any]]:
    """读取 JSON, 兼容常见编码。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(fp.read_text(encoding=enc))
        except Exception:
            continue
    return None


def write_json(fp: Path, obj: Dict[str, Any]) -> None:
    """写出格式化 JSON。"""
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_bounds_to_xyxy(bounds: Any) -> Optional[Tuple[int, int, int, int]]:
    """
    解析 DroidBot view.bounds 的多种可能形态:
    1) [[x1, y1], [x2, y2]]
    2) [x1, y1, x2, y2]
    """
    if isinstance(bounds, list):
        # 形态1: [[x1,y1],[x2,y2]]
        if len(bounds) == 2 and all(isinstance(p, list) and len(p) == 2 for p in bounds):
            try:
                x1, y1 = int(bounds[0][0]), int(bounds[0][1])
                x2, y2 = int(bounds[1][0]), int(bounds[1][1])
                return x1, y1, x2, y2
            except Exception:
                return None

        # 形态2: [x1,y1,x2,y2]
        if len(bounds) == 4 and all(isinstance(v, (int, float)) for v in bounds):
            x1, y1, x2, y2 = map(int, bounds)
            return x1, y1, x2, y2

    return None


def center_from_view(view: Dict[str, Any], src_w: int, src_h: int, dst_w: int, dst_h: int) -> Optional[Dict[str, int]]:
    """从 DroidBot 的 view.bounds 计算点击中心点。"""
    xyxy = parse_bounds_to_xyxy(view.get("bounds"))
    if not xyxy:
        return None
    x1, y1, x2, y2 = xyxy
    x1, y1, x2, y2 = normalize_bounds(x1, y1, x2, y2, src_w, src_h, dst_w, dst_h)
    view["bounds"] = [{'x': x1, 'y': y1}, {'x': x2, 'y': y2}]  # 更新 view 中的 bounds 为规范化后的坐标
    return {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}
  

def _normalize_view_bounds_inplace(view: Dict[str, Any], src_w: int, src_h: int, dst_w: int, dst_h: int) -> None:
    """递归归一化 view 树中每个节点的 bounds。"""
    xyxy = parse_bounds_to_xyxy(view.get("bounds"))
    if xyxy:
        x1, y1, x2, y2 = normalize_bounds(*xyxy, src_w, src_h, dst_w, dst_h)
        view["bounds"] = [{"x": x1, "y": y1}, {"x": x2, "y": y2}]

    children = view.get("children", [])
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _normalize_view_bounds_inplace(child, src_w, src_h, dst_w, dst_h)


def _view_to_component_tree(view: Dict[str, Any]) -> Dict[str, Any]:
    """把已展开的 view 树递归映射为 HapTest component 树。"""
    children_comp = []
    for child in view.get("children", []):
        if isinstance(child, dict):
            children_comp.append(_view_to_component_tree(child))

    return {
        "id": "",
        "key": "",
        "text": "",
        "type": "",
        "bounds": view.get("bounds") or [],
        "origBounds": view.get("bounds") or [],
        "checkable": bool(view.get("checkable", False)),
        "checked": bool(view.get("checked", False)),
        "clickable": bool(view.get("clickable", False)),
        "enabled": bool(view.get("enabled", True)),
        "focused": bool(view.get("focused", False)),
        "hint": "",
        "longClickable": bool(view.get("long_clickable", False)),
        "scrollable": bool(view.get("scrollable", False)),
        "selected": bool(view.get("selected", False)),
        "visible": bool(view.get("visible", True)),
        "children": children_comp,
    }


def build_component_from_view(
    view: Dict[str, Any],
    src_w: int, src_h: int,
    dst_w: int, dst_h: int
) -> Optional[Dict[str, Any]]:
    """将 DroidBot view（含已展开 children）转成 HapTest component（递归）。"""
    if not isinstance(view, dict):
        return None

    # 用副本，避免污染原事件 JSON
    v = copy.deepcopy(view)
    _normalize_view_bounds_inplace(v, src_w, src_h, dst_w, dst_h)
    return _view_to_component_tree(v)


def parse_am_start_intent(intent: str) -> Tuple[str, str]:
    """
    解析 Android am start:
    示例: am start com.tencent.mm/com.tencent.mm.ui.LauncherUI
    返回: (bundleName, abilityName)
    """
    # 尝试提取 pkg/activity
    m = re.search(r"am\s+start\s+([^\s/]+)/([^\s]+)", intent or "")
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def parse_force_stop_intent(intent: str) -> str:
    """
    解析 Android am force-stop:
    示例: am force-stop com.tencent.mm
    返回: com.tencent.mm
    """
    m = re.search(r"am\s+force-stop\s+([^\s]+)", intent or "")
    return m.group(1) if m else ""


# -----------------------------
# 核心映射：DroidBot event -> HapTest event
# -----------------------------
def map_droid_event_to_hap_event(d_event: Dict[str, Any], bundle_name: str,
                                 W_H: int, H_H: int, W_D: int, H_D: int) -> Optional[Dict[str, Any]]:
    """
    将单条 DroidBot event 映射成 HapTest event(createEventFromJson 可识别)
    """
    et = (d_event or {}).get("event_type", "")
    view = d_event.get("view") if isinstance(d_event.get("view"), dict) else None

    # 1) kill_app -> StopHapEvent
    if et == "kill_app":
        return None
        # bundle = parse_force_stop_intent(d_event.get("stop_intent", ""))
        # return {"type": "StopHapEvent", "bundleName": bundle}

    # 2) intent -> AbilityEvent
    if et == "intent":
        intent = d_event.get("intent", "")
        if intent.startswith("am force-stop"):
            return {"type": "StopHapEvent", "bundleName": bundle_name}
        # bundle = bundle_name
        # bundle, ability = parse_am_start_intent(intent)
        elif intent.startswith("am start"):
            return {"type": "AbilityEvent", "bundleName": bundle_name, "abilityName": "EntryAbility"}
        else:
            return None

    # 3) key -> KeyEvent
    if et == "key":
        name = str(d_event.get("name", "")).upper()
        # 这里先做最小映射：BACK
        if name == "BACK":
            return {"type": "KeyEvent", "keyCode": 2}
        elif name == "HOME":
            return {"type": "KeyEvent", "keyCode": 1}
        # 其他按键可按需补充
        return None

    # 4) touch -> TouchEvent
    if et == "touch":
        point = None
        if isinstance(d_event.get("x"), (int, float)) and isinstance(d_event.get("y"), (int, float)):
            nx, ny = normalize_point(int(d_event["x"]), int(d_event["y"]), W_D, H_D, W_H, H_H)
            point = {"x": nx, "y": ny}
        elif view:
            point = center_from_view(view, W_D, H_D, W_H, H_H)

        event_obj: Dict[str, Any] = {"type": "TouchEvent"}
        if view:
            comp = build_component_from_view(view, W_D, H_D, W_H, H_H)
            if comp:
                event_obj["component"] = comp
        if point:
            event_obj["point"] = point
        return event_obj

    # 5) long_touch -> LongTouchEvent
    if et in ("long_touch", "long_click"):
        point = None
        if isinstance(d_event.get("x"), (int, float)) and isinstance(d_event.get("y"), (int, float)):
            nx, ny = normalize_point(int(d_event["x"]), int(d_event["y"]), W_D, H_D, W_H, H_H)
            point = {"x": nx, "y": ny}
        elif view:
            point = center_from_view(view, W_D, H_D, W_H, H_H)

        event_obj = {"type": "LongTouchEvent"}
        if view:
            comp = build_component_from_view(view, W_D, H_D, W_H, H_H)
            if comp:
                event_obj["component"] = comp
        if point:
            event_obj["point"] = point
        return event_obj

    # 6) set_text/input_text -> InputTextEvent
    if et in ("set_text", "input_text"):
        point = None

        text = d_event.get("text", "")
        event_obj: Dict[str, Any] = {"type": "InputTextEvent", "text": text}

        if view:
            point = center_from_view(view, W_D, H_D, W_H, H_H)
            if point:
                event_obj["point"] = point
            comp = build_component_from_view(view, W_D, H_D, W_H, H_H)
            if comp:
                event_obj["component"] = comp
                return event_obj

        # 无 view 时尽量给 point
        if isinstance(d_event.get("x"), (int, float)) and isinstance(d_event.get("y"), (int, float)):
            nx, ny = normalize_point(int(d_event["x"]), int(d_event["y"]), W_D, H_D, W_H, H_H)
            point = {"x": nx, "y": ny}
            if point:
                event_obj["point"] = point
        return event_obj 

    # 7) swipe / scroll（粗映射）
    # if et == "swipe":
    #     # HapTest createEventFromJson 支持 ScrollEvent/SwipeEvent。
    #     # 这里用 ScrollEvent 做保守映射（方向缺失时默认 0）。
    #     event_obj: Dict[str, Any] = {
    #         "type": "ScrollEvent",
    #         "direct": int(d_event.get("direction", 0)) if str(d.event.get("direction", "")).isdigit() else 0,
    #         "step": int(d.event.get("step", 60)),
    #         "speed": int(d.event.get("speed", 40000)),
    #     }
    #     if view:
    #         comp = build_component_from_view(view)
    #         if comp:
    #             event_obj["component"] = comp
    #     return event_obj

    if et == "scroll":
        direct = 0
        if d_event.get("direction") == "up":
            direct = 2
        elif d_event.get("direction") == "down":
            direct = 3
        elif d_event.get("direction") == "left":
            direct = 1
        elif d_event.get("direction") == "right":
            direct = 0
        event_obj: Dict[str, Any] = {
            "type": "ScrollEvent",
            "direct": direct,
            "step": int(d_event.get("step", 60)),
            "speed": int(d_event.get("speed", 40000)),
        }
        if view:
            point = center_from_view(view, W_D, H_D, W_H, H_H)
            if point:
                event_obj["point"] = point
            comp = build_component_from_view(view, W_D, H_D, W_H, H_H)
            if comp:
                event_obj["component"] = comp
        return event_obj

    # 未支持类型
    return None


def build_hap_transition_like_json(
    hap_event: Dict[str, Any],
    droid_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    构造 HapTest replay 可读取的 transition 风格 JSON。
    replay 主要用 event;from/to 这里补齐最小结构。
    """
    return {
        "from": {
            # 仅做占位；replay 当前不强依赖完整 viewTree
            "pagePath": "",
            "bundleName": "",
            "abilityName": "",
        },
        "event": hap_event,
        "to": {
            "pagePath": "",
        },
        # 使用 droid state 作为可追踪签名（非 HapTest 原生内容签名，但便于调试）
        "fromContentSig": droid_json.get("start_state", ""),
        "toContentSig": droid_json.get("stop_state", ""),
    }


# -----------------------------
# 主流程
# -----------------------------
def convert(
    droid_dir: Path,
    out_dir: Path,
    bundle_name: str,
    dry_run: bool = False,
) -> ConvertStats:
    stats = ConvertStats()

    files = sorted(droid_dir.glob("event_*.json"))
    events_out_dir = out_dir / "events"
    events_out_dir.mkdir(parents=True, exist_ok=True)

    res = subprocess.run('hdc shell hidumper -s RenderService -a screen', capture_output=True)
    m = re.search(r"render resolution=(\d+)x(\d+)", res.stdout.decode())
    W_H, H_H = (int(m.group(1)), int(m.group(2)))
    res = subprocess.run('adb shell wm size', capture_output=True)
    m = re.search(r"Physical size:\s*(\d+)x(\d+)", res.stdout.decode())
    W_D, H_D = (int(m.group(1)), int(m.group(2)))

    for fp in files:
        stats.total += 1
        data = read_json(fp)
        if not isinstance(data, dict):
            stats.skipped += 1
            stats.warnings += 1
            print(f"[WARN] 无法解析 JSON: {fp}")
            continue

        d_event = data.get("event", {})
        if not isinstance(d_event, dict):
            stats.skipped += 1
            stats.warnings += 1
            print(f"[WARN] event 字段不是对象: {fp}")
            continue

        hap_event = map_droid_event_to_hap_event(d_event, bundle_name=bundle_name, 
                                                 W_H=W_H, H_H=H_H, W_D=W_D, H_D=H_D)
        if hap_event is None:
            stats.skipped += 1
            stats.warnings += 1
            et = d_event.get("event_type", "<unknown>")
            print(f"[WARN] 跳过未支持事件类型: {et} @ {fp.name}")
            continue

        out_obj = build_hap_transition_like_json(hap_event, data)

        # 输出文件名：transition_<原tag格式化>.json
        tag = str(data.get("tag", fp.stem.replace("event_", "")))
        tag = tag.replace("_", "-")
        out_name = f"transition_{tag}.json"
        out_fp = events_out_dir / out_name

        if not dry_run:
            write_json(out_fp, out_obj)

        stats.converted += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="DroidBot event JSON -> HapTest replay JSON 转换器")
    parser.add_argument(
        # "--bundle-name",
        '-b',
        dest="bundle_name",
        type=str,
        help="必须指定 bundleName",
        required=True,
    )
    parser.add_argument(
        '-i',
        type=Path,
        dest="droid_dir",
        default=Path(r"d:\GithubProjects\hap-droid\droidbot_events"),
        help="DroidBot 事件目录(event_*.json)",
    )
    parser.add_argument(
        "-o",
        dest="out_dir",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\converted_haptest_events"),
        help="输出目录(将生成 events/transition_*.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计不写文件",
    )
    args = parser.parse_args()

    if not args.droid_dir.exists():
        print(f"[ERROR] 输入目录不存在: {args.droid_dir}")
        return

    stats = convert(
        droid_dir=args.droid_dir,
        out_dir=args.out_dir,
        bundle_name=args.bundle_name,
        dry_run=args.dry_run,
    )

    print("\n====== 转换完成 ======")
    print(f"总文件:   {stats.total}")
    print(f"已转换:   {stats.converted}")
    print(f"已跳过:   {stats.skipped}")
    print(f"警告数:   {stats.warnings}")
    print(f"输出目录: {args.out_dir}")


if __name__ == "__main__":
    main()