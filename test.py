"""
自动扫描 DroidBot / HapTest 事件 JSON 字段

目标：
1) 自动判断文件来源（droidbot 或 haptest） 
2) 递归提取所有字段路径（如 event.view.bounds[]）
3) 统计字段出现次数、出现文件数、类型、示例值
4) 输出可读终端报告 + JSON + CSV 报告

默认输入目录：
- d:\GithubProjects\hap-droid\droidbot_events
- d:\GithubProjects\hap-droid\haptest_events
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple


# -----------------------------
# 统计结构：记录每个字段路径的信息
# -----------------------------
@dataclass
class FieldInfo:
    count: int = 0
    files: Set[str] = field(default_factory=set)
    types: Set[str] = field(default_factory=set)
    samples: List[str] = field(default_factory=list)
    by_source: Dict[str, int] = field(default_factory=lambda: {"droidbot": 0, "haptest": 0})

    def add(self, source: str, file_path: Path, value: Any) -> None:
        """记录一次字段命中。"""
        self.count += 1
        self.files.add(str(file_path))
        self.types.add(_type_name(value))
        self.by_source[source] = self.by_source.get(source, 0) + 1

        # 只保留最多 3 个标量示例，避免报告过大
        if len(self.samples) < 3 and not isinstance(value, (dict, list)):
            self.samples.append(_short_repr(value))


def _type_name(v: Any) -> str:
    """把 Python 值类型转成更直观名称。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _short_repr(v: Any, max_len: int = 80) -> str:
    s = repr(v)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _read_json_safely(file_path: Path) -> Any:
    """尽量容错读取 JSON（utf-8 / utf-8-sig / gbk）。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return json.loads(file_path.read_text(encoding=enc))
        except Exception:
            pass
    return None


def detect_source(file_path: Path, data: Any) -> str:
    """
    自动判断来源：
    1) 先按文件名判断
    2) 再按 JSON 结构特征判断
    """
    name = file_path.name.lower()

    if name.startswith("event_"):
        return "droidbot"
    if name.startswith("transition_"):
        return "haptest"

    if isinstance(data, dict):
        # DroidBot 常见：start_state/stop_state/event_str/tag
        droidbot_keys = {"start_state", "stop_state", "event_str", "tag"}
        # HapTest 常见：from/to/fromContentSig/toContentSig
        haptest_keys = {"from", "to", "fromContentSig", "toContentSig"}

        d_score = len(set(data.keys()) & droidbot_keys)
        h_score = len(set(data.keys()) & haptest_keys)

        if d_score > h_score:
            return "droidbot"
        if h_score > d_score:
            return "haptest"

    return "unknown"


def walk_json(obj: Any, path: str, source: str, file_path: Path, stats: Dict[str, FieldInfo]) -> None:
    """
    递归扫描字段：
    - dict: path.key
    - list: path[]
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            next_path = f"{path}.{k}" if path else k
            stats[next_path].add(source, file_path, v)
            walk_json(v, next_path, source, file_path, stats)

    elif isinstance(obj, list):
        list_path = f"{path}[]"
        stats[list_path].add(source, file_path, obj)
        for item in obj:
            walk_json(item, list_path, source, file_path, stats)


def scan_files(json_files: Iterable[Path]) -> Dict[str, FieldInfo]:
    """扫描所有 JSON 文件，汇总字段统计。"""
    stats: Dict[str, FieldInfo] = defaultdict(FieldInfo)

    for fp in json_files:
        data = _read_json_safely(fp)
        if data is None:
            continue

        source = detect_source(fp, data)
        walk_json(data, "", source, fp, stats)

    return stats


def save_json_report(stats: Dict[str, FieldInfo], out_file: Path) -> None:
    """保存 JSON 报告。"""
    out_file.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for path, info in sorted(stats.items(), key=lambda x: (-x[1].count, x[0])):
        rows.append(
            {
                "path": path,
                "count": info.count,
                "file_count": len(info.files),
                "types": sorted(info.types),
                "samples": info.samples,
                "by_source": info.by_source,
            }
        )

    out_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv_report(stats: Dict[str, FieldInfo], out_file: Path) -> None:
    """保存 CSV 报告（方便 Excel 打开）。"""
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with out_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "count", "file_count", "types", "droidbot_count", "haptest_count", "sample1", "sample2", "sample3"])

        for path, info in sorted(stats.items(), key=lambda x: (-x[1].count, x[0])):
            s = info.samples + ["", "", ""]
            writer.writerow(
                [
                    path,
                    info.count,
                    len(info.files),
                    ",".join(sorted(info.types)),
                    info.by_source.get("droidbot", 0),
                    info.by_source.get("haptest", 0),
                    s[0],
                    s[1],
                    s[2],
                ]
            )


def print_top(stats: Dict[str, FieldInfo], top_n: int) -> None:
    """终端输出前 N 条字段统计。"""
    print(f"\n总字段路径数: {len(stats)}")
    print("-" * 125)
    print(f"{'path':58} {'count':>8} {'files':>8} {'types':24} {'d/h':>8}  sample")
    print("-" * 125)

    items = sorted(stats.items(), key=lambda x: (-x[1].count, x[0]))[:top_n]
    for path, info in items:
        types_str = ",".join(sorted(info.types))
        dh = f"{info.by_source.get('droidbot',0)}/{info.by_source.get('haptest',0)}"
        sample = info.samples[0] if info.samples else ""
        print(f"{path[:58]:58} {info.count:8d} {len(info.files):8d} {types_str[:24]:24} {dh:>8}  {sample}")


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描 DroidBot/HapTest 事件 JSON 字段")
    parser.add_argument(
        "--droidbot-dir",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\droidbot_events"),
        help="DroidBot 事件目录",
    )
    parser.add_argument(
        "--haptest-dir",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\haptest_events"),
        help="HapTest 事件目录",
    )
    parser.add_argument("--top", type=int, default=200, help="终端显示前 N 条")
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\out\field_report.json"),
        help="JSON 报告输出路径",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=Path(r"d:\GithubProjects\hap-droid\out\field_report.csv"),
        help="CSV 报告输出路径",
    )
    args = parser.parse_args()

    all_files: List[Path] = []
    if args.droidbot_dir.exists():
        all_files.extend(args.droidbot_dir.rglob("*.json"))
    if args.haptest_dir.exists():
        all_files.extend(args.haptest_dir.rglob("*.json"))

    all_files = sorted(set(all_files))
    print(f"扫描 JSON 文件数: {len(all_files)}")
    if not all_files:
        print("未找到 JSON 文件，请检查目录路径。")
        return

    stats = scan_files(all_files)

    print_top(stats, args.top)
    save_json_report(stats, args.out_json)
    save_csv_report(stats, args.out_csv)

    print(f"\nJSON 报告已保存: {args.out_json}")
    print(f"CSV  报告已保存: {args.out_csv}")


if __name__ == "__main__":
    main()