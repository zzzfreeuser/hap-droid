# """扫描 HapTest / DroidBot 事件 JSON 的字段分布。

# 功能说明：
# 1. 自动发现常见事件目录：
#    - haptest:  <workspace>/events
#    - droidbot: <workspace>/droidbot-master/output/*/events
# 2. 递归统计 JSON 字段路径（例如 event.view.bounds[][]）
# 3. 记录字段出现次数、数据类型、示例值
# 4. 生成按来源拆分的可读文本报告到 out/ 目录

# 用法示例：
#     python scan_fields.py
#     python scan_fields.py --workspace d:/GithubProjects/hap-droid --top 120
# """

# from __future__ import annotations

# import argparse
# import json
# from collections import Counter, defaultdict
# from dataclasses import dataclass, field
# from pathlib import Path
# from typing import Any


# @dataclass
# class FieldStats:
#     """保存某一批 JSON 文件的字段统计信息。"""

#     field_count: Counter[str] = field(default_factory=Counter)
#     field_types: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
#     field_samples: dict[str, Any] = field(default_factory=dict)
#     file_count: int = 0
#     failed_files: list[tuple[Path, str]] = field(default_factory=list)


# def to_type_name(value: Any) -> str:
#     """将 Python 值映射为更友好的类型名。"""
#     if value is None:
#         return "null"
#     if isinstance(value, bool):
#         return "bool"
#     if isinstance(value, int) and not isinstance(value, bool):
#         return "int"
#     if isinstance(value, float):
#         return "float"
#     if isinstance(value, str):
#         return "str"
#     if isinstance(value, dict):
#         return "object"
#     if isinstance(value, list):
#         return "list"
#     return type(value).__name__


# def format_sample(value: Any, limit: int = 120) -> str:
#     """把示例值格式化为单行短字符串，避免报告过长。"""
#     text = json.dumps(value, ensure_ascii=False)
#     if len(text) <= limit:
#         return text
#     return text[: limit - 3] + "..."


# def walk_json(value: Any, path: str, stats: FieldStats) -> None:
#     """递归遍历 JSON，统计字段路径、类型和示例值。"""
#     if isinstance(value, dict):
#         for key, sub_value in value.items():
#             current_path = f"{path}.{key}" if path else key
#             stats.field_count[current_path] += 1
#             stats.field_types[current_path].add(to_type_name(sub_value))

#             if current_path not in stats.field_samples and not isinstance(sub_value, (dict, list)):
#                 stats.field_samples[current_path] = sub_value

#             walk_json(sub_value, current_path, stats)
#         return

#     if isinstance(value, list):
#         # 用 [] 标记数组层级，便于区分 object 字段与数组字段。
#         list_path = f"{path}[]" if path else "[]"
#         stats.field_count[list_path] += 1
#         stats.field_types[list_path].add("list")
#         for item in value:
#             walk_json(item, list_path, stats)


# def collect_json_stats(json_files: list[Path]) -> FieldStats:
#     """对一组 JSON 文件做汇总统计。"""
#     stats = FieldStats()

#     for file_path in sorted(json_files):
#         try:
#             # 部分文件可能有 BOM，因此使用 utf-8-sig 更稳妥。
#             content = file_path.read_text(encoding="utf-8-sig")
#             data = json.loads(content)
#             walk_json(data, "", stats)
#             stats.file_count += 1
#         except Exception as exc:  # noqa: BLE001
#             stats.failed_files.append((file_path, str(exc)))

#     return stats


# def discover_sources(workspace: Path) -> dict[str, list[Path]]:
#     """自动发现 haptest / droidbot 的事件目录并返回来源 -> 文件列表。"""
#     sources: dict[str, list[Path]] = {}

#     # HapTest 常见目录：项目根目录 events/
#     haptest_dir = workspace / "events"
#     if haptest_dir.exists():
#         sources["haptest"] = list(haptest_dir.glob("event_*.json"))

#     # DroidBot 常见目录：droidbot-master/output/*/events/
#     droidbot_files: list[Path] = []
#     droidbot_output = workspace / "droidbot-master" / "output"
#     if droidbot_output.exists():
#         for app_output in droidbot_output.iterdir():
#             events_dir = app_output / "events"
#             if events_dir.exists():
#                 droidbot_files.extend(events_dir.glob("event_*.json"))

#     if droidbot_files:
#         sources["droidbot"] = droidbot_files

#     return sources


# def build_report_text(source_name: str, stats: FieldStats, top_n: int) -> str:
#     """生成单一来源的文本报告。"""
#     lines: list[str] = []
#     lines.append(f"# 事件字段统计报告 - {source_name}")
#     lines.append("")
#     lines.append(f"成功解析文件数: {stats.file_count}")
#     lines.append(f"解析失败文件数: {len(stats.failed_files)}")
#     lines.append(f"去重后字段路径数: {len(stats.field_count)}")
#     lines.append("")

#     lines.append("## 字段明细（按出现次数降序）")
#     lines.append("")
#     lines.append("字段路径 | 次数 | 类型 | 示例")
#     lines.append("--- | ---: | --- | ---")

#     for field_path, count in stats.field_count.most_common(top_n):
#         type_text = ", ".join(sorted(stats.field_types[field_path]))
#         sample = stats.field_samples.get(field_path, "")
#         sample_text = format_sample(sample) if sample != "" else ""
#         lines.append(f"{field_path} | {count} | {type_text} | {sample_text}")

#     if stats.failed_files:
#         lines.append("")
#         lines.append("## 解析失败文件（最多展示前 20 个）")
#         lines.append("")
#         for file_path, error in stats.failed_files[:20]:
#             lines.append(f"- {file_path}: {error}")

#     lines.append("")
#     return "\n".join(lines)


# def parse_args() -> argparse.Namespace:
#     """解析命令行参数。"""
#     parser = argparse.ArgumentParser(description="扫描 HapTest / DroidBot 事件 JSON 字段")
#     parser.add_argument(
#         "--workspace",
#         type=Path,
#         default=Path(__file__).resolve().parent,
#         help="工作区根目录，默认是当前脚本所在目录",
#     )
#     parser.add_argument(
#         "--out-dir",
#         type=Path,
#         default=Path("out"),
#         help="报告输出目录（可用相对路径）",
#     )
#     parser.add_argument(
#         "--top",
#         type=int,
#         default=200,
#         help="每个来源报告展示前 N 个字段（按出现次数）",
#     )
#     return parser.parse_args()


# def main() -> None:
#     """程序入口。"""
#     args = parse_args()
#     workspace = args.workspace.resolve()
#     out_dir = args.out_dir
#     if not out_dir.is_absolute():
#         out_dir = (workspace / out_dir).resolve()
#     out_dir.mkdir(parents=True, exist_ok=True)

#     sources = discover_sources(workspace)
#     if not sources:
#         print("未发现可扫描的事件目录。")
#         print("已尝试：events/ 与 droidbot-master/output/*/events/")
#         return

#     print(f"工作区: {workspace}")
#     print(f"输出目录: {out_dir}")
#     print("")

#     for source_name, json_files in sources.items():
#         print(f"[{source_name}] 发现事件文件: {len(json_files)}")
#         stats = collect_json_stats(json_files)

#         report_path = out_dir / f"{source_name}_fields_report.md"
#         report_text = build_report_text(source_name, stats, top_n=args.top)
#         report_path.write_text(report_text, encoding="utf-8")

#         print(
#             f"[{source_name}] 成功: {stats.file_count}, 失败: {len(stats.failed_files)}, "
#             f"字段数: {len(stats.field_count)}"
#         )
#         print(f"[{source_name}] 报告已写入: {report_path}")
#         print("")


# if __name__ == "__main__":
#     main()


import json
from pathlib import Path
from collections import Counter, defaultdict

def walk(obj, prefix="", counter=None, types=None, samples=None):
    if counter is None:
        counter = Counter()
    if types is None:
        types = defaultdict(set)
    if samples is None:
        samples = {}

    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            counter[p] += 1
            types[p].add(type(v).__name__)
            if p not in samples and not isinstance(v, (dict, list)):
                samples[p] = v
            walk(v, p, counter, types, samples)
    elif isinstance(obj, list):
        p = f"{prefix}[]"
        counter[p] += 1
        types[p].add("list")
        for item in obj:
            walk(item, p, counter, types, samples)

    return counter, types, samples

def scan_json_dir(root: Path):
    counter = Counter()
    types = defaultdict(set)
    samples = {}
    files = sorted(root.rglob("*.json"))

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            c, t, s = walk(data)
            counter.update(c)
            for k, v in t.items():
                types[k].update(v)
            for k, v in s.items():
                samples.setdefault(k, v)
        except Exception:
            pass

    return files, counter, types, samples

if __name__ == "__main__":
    root = Path(r"D:\\GithubProjects\\hap-droid\\out\\2026-03-03-18-21-21\\events")
    files, counter, types, samples = scan_json_dir(root)

    print(f"JSON nums: {len(files)}")
    print("-" * 90)
    for k, n in counter.most_common():
        tp = ",".join(sorted(types[k]))
        sv = samples.get(k, "")
        print(f"{k:<50} count={n:<6} type={tp:<20} sample={sv}")