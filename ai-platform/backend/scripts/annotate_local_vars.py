"""用标准库 AST 为函数体内的简单赋值补类型注解（不依赖第三方包）。

将可安全推断的 ``name = expr`` 改为 ``name: T = expr``。
复杂调用/属性访问无法可靠推断时跳过，留给人工处理。

用法:
  .venv\\Scripts\\python.exe scripts/annotate_local_vars.py
  .venv\\Scripts\\python.exe scripts/annotate_local_vars.py --dry-run
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
SKIP_NAMES = frozenset({"__all__", "_", "cls", "self"})

CALL_TYPE_MAP: dict[str, str] = {
    "dict": "dict[str, Any]",
    "list": "list[Any]",
    "set": "set[Any]",
    "frozenset": "frozenset[Any]",
    "tuple": "tuple[Any, ...]",
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "bytes": "bytes",
    "bytearray": "bytearray",
    "Path": "Path",
    "deque": "deque[Any]",
    "defaultdict": "defaultdict[Any, Any]",
    "OrderedDict": "OrderedDict[str, Any]",
    "Counter": "Counter[Any]",
    "Lock": "asyncio.Lock",
    "Event": "asyncio.Event",
    "Semaphore": "asyncio.Semaphore",
}


def _infer_type(value: ast.expr) -> str | None:
    if isinstance(value, ast.Constant):
        lit = value.value
        if lit is None:
            return "None"
        if isinstance(lit, bool):
            return "bool"
        if isinstance(lit, int):
            return "int"
        if isinstance(lit, float):
            return "float"
        if isinstance(lit, str):
            return "str"
        if isinstance(lit, bytes):
            return "bytes"
        return None

    if isinstance(value, ast.JoinedStr):
        return "str"

    if isinstance(value, ast.List):
        if not value.elts:
            return "list[Any]"
        elt_types = {_infer_type(e) for e in value.elts}
        if len(elt_types) == 1 and None not in elt_types:
            return f"list[{next(iter(elt_types))}]"
        return "list[Any]"

    if isinstance(value, ast.Set):
        if not value.elts:
            return "set[Any]"
        elt_types = {_infer_type(e) for e in value.elts}
        if len(elt_types) == 1 and None not in elt_types:
            return f"set[{next(iter(elt_types))}]"
        return "set[Any]"

    if isinstance(value, ast.Dict):
        if not value.keys:
            return "dict[str, Any]"
        key_types = {_infer_type(k) for k in value.keys if k is not None}
        if key_types == {"str"} or (len(key_types) == 1 and "str" in key_types):
            return "dict[str, Any]"
        return "dict[Any, Any]"

    if isinstance(value, ast.Tuple):
        if not value.elts:
            return "tuple[()]"
        parts: list[str] = []
        for e in value.elts:
            t = _infer_type(e)
            if t is None:
                return "tuple[Any, ...]"
            parts.append(t)
        return f"tuple[{', '.join(parts)}]"

    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        return "bool"
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)):
        return _infer_type(value.operand)

    if isinstance(value, ast.Compare):
        return "bool"

    if isinstance(value, ast.IfExp):
        a = _infer_type(value.body)
        b = _infer_type(value.orelse)
        if a is not None and a == b:
            return a
        if a is not None and b is not None:
            return f"{a} | {b}"
        return None

    if isinstance(value, ast.ListComp):
        elt = _infer_type(value.elt)
        return f"list[{elt}]" if elt else "list[Any]"

    if isinstance(value, ast.SetComp):
        elt = _infer_type(value.elt)
        return f"set[{elt}]" if elt else "set[Any]"

    if isinstance(value, ast.DictComp):
        return "dict[Any, Any]"

    if isinstance(value, ast.BinOp):
        left = _infer_type(value.left)
        right = _infer_type(value.right)
        if isinstance(value.op, ast.Add) and left == "str" and right == "str":
            return "str"
        if left == "int" and right == "int" and isinstance(
            value.op,
            (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.BitOr, ast.BitAnd, ast.BitXor),
        ):
            return "int"
        return None

    if isinstance(value, ast.Call):
        func = value.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name and name in CALL_TYPE_MAP:
            return CALL_TYPE_MAP[name]
        if name and re.match(r"^[A-Z][A-Za-z0-9_]*$", name):
            # CamelCase 构造：用类名作注解（常见于本项目模型）
            return name
        if isinstance(func, ast.Attribute):
            if func.attr in {"model_dump", "dict", "to_dict", "to_api_dict"}:
                return "dict[str, Any]"
            if func.attr in {
                "isoformat",
                "strftime",
                "hex",
                "decode",
                "strip",
                "lower",
                "upper",
                "replace",
                "format",
                "join",
                "getvalue",
                "read_text",
                "as_posix",
            }:
                return "str"
            if func.attr == "read_bytes":
                return "bytes"
        return None

    return None


class Annotator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.edits: list[tuple[int, int, str, str]] = []
        self.need_any = False
        self.need_path = False
        self._func_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_depth += 1
        self.generic_visit(node)
        self._func_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._func_depth += 1
        self.generic_visit(node)
        self._func_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._func_depth == 0:
            self.generic_visit(node)
            return
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            self.generic_visit(node)
            return
        target = node.targets[0]
        if target.id in SKIP_NAMES or (
            target.id.startswith("__") and target.id.endswith("__")
        ):
            self.generic_visit(node)
            return
        ann = _infer_type(node.value)
        if ann is None:
            self.generic_visit(node)
            return
        if "Any" in ann:
            self.need_any = True
        if ann == "Path" or ann.startswith("Path "):
            self.need_path = True
        self.edits.append((target.lineno, target.col_offset, target.id, ann))
        self.generic_visit(node)


def _ensure_imports(source: str, need_any: bool, need_path: bool) -> str:
    if not need_any and not need_path:
        return source

    has_any = bool(re.search(r"from\s+typing\s+import\s+.*\bAny\b", source))
    has_path = bool(re.search(r"from\s+pathlib\s+import\s+.*\bPath\b", source))
    inserts: list[str] = []
    if need_any and not has_any:
        inserts.append("from typing import Any")
    if need_path and not has_path:
        inserts.append("from pathlib import Path")
    if not inserts:
        return source

    tree = ast.parse(source)
    insert_at = 0
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_at = node.end_lineno or node.lineno
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_at = max(insert_at, node.end_lineno or node.lineno)
            continue
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            # docstring
            if insert_at == 0:
                insert_at = node.end_lineno or node.lineno
            continue
        break

    lines = source.splitlines(keepends=True)
    text = "\n".join(inserts) + "\n"
    lines.insert(insert_at, text)
    return "".join(lines)


def apply_edits(source: str, edits: list[tuple[int, int, str, str]]) -> str:
    if not edits:
        return source
    lines = source.splitlines(keepends=True)
    by_line: dict[int, list[tuple[int, str, str]]] = {}
    for lineno, col, name, ann in edits:
        by_line.setdefault(lineno, []).append((col, name, ann))

    for lineno in sorted(by_line.keys(), reverse=True):
        line_edits = sorted(by_line[lineno], key=lambda x: x[0], reverse=True)
        idx = lineno - 1
        line = lines[idx]
        for col, name, ann in line_edits:
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(\s*)=")
            segment = line[col:]
            m = pattern.search(segment)
            if m:
                abs_start = col + m.start()
                ws = m.group(1)
                line = line[:abs_start] + f"{name}: {ann}{ws}=" + line[col + m.end() :]
            else:
                m = pattern.search(line)
                if not m:
                    continue
                ws = m.group(1)
                line = line[: m.start()] + f"{name}: {ann}{ws}=" + line[m.end() :]
            lines[idx] = line
    return "".join(lines)


def process_file(path: Path, dry_run: bool) -> tuple[int, bool]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0, False

    annotator = Annotator()
    annotator.visit(tree)
    if not annotator.edits:
        return 0, False

    new_source = apply_edits(source, annotator.edits)
    new_source = _ensure_imports(new_source, annotator.need_any, annotator.need_path)
    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        print(f"SKIP (syntax): {path}: {exc}", file=sys.stderr)
        return 0, False

    if not dry_run and new_source != source:
        path.write_text(new_source, encoding="utf-8", newline="\n")
    return len(annotator.edits), new_source != source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", type=Path, default=SRC_ROOT)
    args = parser.parse_args()

    root: Path = args.path
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    total = 0
    changed_files = 0
    for f in files:
        n, changed = process_file(f, dry_run=args.dry_run)
        if n and changed:
            total += n
            changed_files += 1
            try:
                rel = f.relative_to(SRC_ROOT)
            except ValueError:
                rel = f
            print(f"{rel}: {n}")
    print(f"Total annotations: {total} in {changed_files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
