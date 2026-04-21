#!/usr/bin/env python3
"""
CI 静态检查：禁止 `state.memories.append(` 直接调用。

白名单：
- backend/memory/                 （整个 memory 模块：ingest.py 的 record_moment 降级回写
                                   + consolidation.py 的 self_heal 崩溃恢复补齐，皆为合法内部用法）
- backend/scripts/                （本脚本自身和其他 lint 工具）
- backend/tests/                  （测试可能需要直接操纵，白名单）
- backend/specs/                  （spec 文档里的代码示例）

用法：
    python3 scripts/lint_no_direct_memory_append.py            # 检查 backend/ 全量
    python3 scripts/lint_no_direct_memory_append.py path/a.py  # 检查指定文件

退出码：
    0   无违反
    1   有违反（CI 红灯）
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

WHITELIST = {
    BACKEND_ROOT / "memory",     # 整个 memory 模块内部合法（record_moment / self_heal）
    BACKEND_ROOT / "scripts",
    BACKEND_ROOT / "tests",
    BACKEND_ROOT / "specs",      # spec 文档里的代码示例
}


def _is_whitelisted(path: Path) -> bool:
    p = path.resolve()
    for w in WHITELIST:
        try:
            p.relative_to(w)
            return True
        except ValueError:
            continue
    return False


def _iter_py_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for t in targets:
        if t.is_file() and t.suffix == ".py":
            files.append(t)
        elif t.is_dir():
            for p in t.rglob("*.py"):
                files.append(p)
    return files


def _check_file(path: Path) -> list[tuple[int, str]]:
    """返回违反行（line, snippet）列表。"""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # 匹配 xxx.memories.append(...)
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "append":
            continue
        inner = func.value
        if not isinstance(inner, ast.Attribute):
            continue
        if inner.attr != "memories":
            continue
        # 命中
        lineno = node.lineno
        line_src = src.splitlines()[lineno - 1].strip() if lineno - 1 < len(src.splitlines()) else ""
        violations.append((lineno, line_src))
    return violations


def main() -> int:
    argv = sys.argv[1:]
    targets = [Path(a) for a in argv] if argv else [BACKEND_ROOT]
    files = _iter_py_files(targets)
    bad = 0
    for f in files:
        if _is_whitelisted(f):
            continue
        vs = _check_file(f)
        for lineno, line in vs:
            bad += 1
            # 相对路径展示
            try:
                rel = f.relative_to(BACKEND_ROOT)
            except ValueError:
                rel = f
            print(f"[lint] FORBIDDEN: {rel}:{lineno}: {line}")

    if bad:
        print(f"\nFound {bad} direct state.memories.append(...) calls outside memory/ingest.py")
        print("Use memory.record_moment(...) instead. See specs/long-term-memory/design.md §4.1.")
        return 1
    print(f"[lint] OK — scanned {len(files)} files, no direct state.memories.append outside whitelist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
