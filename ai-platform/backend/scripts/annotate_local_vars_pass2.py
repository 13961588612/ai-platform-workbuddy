"""第二轮：为剩余未注解局部赋值补类型。

策略：
1. 扫描整个 src，建立函数/方法名 -> 返回类型索引
2. 对 ``name = ...`` / ``name = await ...`` 尽量用具体返回类型
3. 仍无法推断时用 ``Any``（保证「变量必须写类型」全覆盖）

用法:
  .venv\\Scripts\\python.exe scripts/annotate_local_vars_pass2.py
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
SKIP_NAMES = frozenset({"__all__", "_", "cls", "self"})

# 常见方法名 -> 返回类型（启发式）
ATTR_RETURN: dict[str, str] = {
    "get": "Any",
    "pop": "Any",
    "get_proxy_url": "str | None",
    "model_dump": "dict[str, Any]",
    "dict": "dict[str, Any]",
    "to_dict": "dict[str, Any]",
    "to_api_dict": "dict[str, Any]",
    "isoformat": "str",
    "strftime": "str",
    "hex": "str",
    "decode": "str",
    "encode": "bytes",
    "strip": "str",
    "lower": "str",
    "upper": "str",
    "replace": "str",
    "format": "str",
    "join": "str",
    "read_text": "str",
    "read_bytes": "bytes",
    "as_posix": "str",
    "resolve": "Path",
    "absolute": "Path",
    "exists": "bool",
    "is_file": "bool",
    "is_dir": "bool",
    "startswith": "bool",
    "endswith": "bool",
    "isdigit": "bool",
    "keys": "Any",
    "values": "Any",
    "items": "Any",
    "copy": "Any",
    "json": "Any",
    "loads": "Any",
    "dumps": "str",
    "safe_load": "Any",
    "safe_dump": "str | None",
}


def _ann_to_str(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _strip_awaitable(ann: str) -> str:
    """Coroutine[Any, Any, T] / Awaitable[T] / AsyncIterator[T] 等尽量剥到 T。"""
    m = re.match(r"^(?:Coroutine|Awaitable|AsyncIterator|AsyncGenerator)\[(.+)\]$", ann)
    if not m:
        return ann
    inner = m.group(1)
    # Coroutine[Any, Any, T] -> T
    parts: list[str] = []
    depth = 0
    cur = ""
    for ch in inner:
        if ch == "[":
            depth += 1
            cur += ch
        elif ch == "]":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    if ann.startswith("Coroutine") and len(parts) >= 3:
        return parts[-1]
    if parts:
        return parts[0]
    return ann


def build_return_index(root: Path) -> dict[str, str]:
    """name / Class.method -> return annotation string."""
    index: dict[str, str] = {}
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ret = _ann_to_str(node.returns)
                if ret:
                    index[node.name] = ret
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        ret = _ann_to_str(item.returns)
                        if ret:
                            index[f"{node.name}.{item.name}"] = ret
                            # 也按短名索引（后写覆盖先写，够用）
                            index[item.name] = ret
    return index


def _infer_from_call(call: ast.Call, index: dict[str, str]) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
        if name in {"dict", "list", "set", "tuple", "str", "int", "float", "bool", "bytes"}:
            mapping = {
                "dict": "dict[str, Any]",
                "list": "list[Any]",
                "set": "set[Any]",
                "tuple": "tuple[Any, ...]",
                "str": "str",
                "int": "int",
                "float": "float",
                "bool": "bool",
                "bytes": "bytes",
            }
            return mapping[name]
        if re.match(r"^[A-Z]", name):
            return name
        if name in index:
            return _strip_awaitable(index[name])
        return None
    if isinstance(func, ast.Attribute):
        attr = func.attr
        # Class.method 风格：obj.method — 用短名
        if attr in index:
            return _strip_awaitable(index[attr])
        if attr in ATTR_RETURN:
            return ATTR_RETURN[attr]
        if re.match(r"^[A-Z]", attr):
            return attr
        return None
    return None


def infer_type(value: ast.expr, index: dict[str, str]) -> str:
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
        return "Any"

    if isinstance(value, ast.JoinedStr):
        return "str"
    if isinstance(value, ast.List):
        return "list[Any]"
    if isinstance(value, ast.Set):
        return "set[Any]"
    if isinstance(value, ast.Dict):
        return "dict[str, Any]"
    if isinstance(value, ast.Tuple):
        return "tuple[Any, ...]"
    if isinstance(value, ast.Compare):
        return "bool"
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        return "bool"
    if isinstance(value, ast.ListComp):
        return "list[Any]"
    if isinstance(value, ast.SetComp):
        return "set[Any]"
    if isinstance(value, ast.DictComp):
        return "dict[Any, Any]"
    if isinstance(value, ast.GeneratorExp):
        return "Any"

    if isinstance(value, ast.Await):
        return infer_type(value.value, index)

    if isinstance(value, ast.Call):
        t = _infer_from_call(value, index)
        return t if t else "Any"

    if isinstance(value, ast.Attribute):
        if value.attr in ATTR_RETURN:
            return ATTR_RETURN[value.attr]
        return "Any"

    if isinstance(value, ast.Subscript):
        return "Any"

    if isinstance(value, ast.Name):
        return "Any"

    if isinstance(value, ast.IfExp):
        a = infer_type(value.body, index)
        b = infer_type(value.orelse, index)
        if a == b:
            return a
        if a != "Any" and b != "Any":
            return f"{a} | {b}"
        return "Any"

    if isinstance(value, ast.BinOp):
        left = infer_type(value.left, index)
        right = infer_type(value.right, index)
        if left == "str" or right == "str":
            if isinstance(value.op, ast.Add):
                return "str"
        if left == "int" and right == "int":
            return "int"
        return "Any"

    if isinstance(value, ast.BoolOp):
        return "Any"

    if isinstance(value, ast.Lambda):
        return "Any"

    if isinstance(value, ast.Yield) or isinstance(value, ast.YieldFrom):
        return "Any"

    return "Any"


class Annotator(ast.NodeVisitor):
    def __init__(self, index: dict[str, str]) -> None:
        self.index = index
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
        ann = infer_type(node.value, self.index)
        # 规范化奇怪的返回注解
        if ann in {"NoneType", "None"}:
            # 赋值成 None 字面量才是 None；函数返回 None 的变量用 Any|None 太吵，用 Any
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                ann = "None"
            else:
                ann = "Any"
        if "Any" in ann:
            self.need_any = True
        if "Path" in ann and not re.search(r"\bPath\b", " ".join([])):
            if re.search(r"\bPath\b", ann):
                self.need_path = True
        if re.search(r"\bPath\b", ann):
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
            if insert_at == 0:
                insert_at = node.end_lineno or node.lineno
            continue
        break

    lines = source.splitlines(keepends=True)
    lines.insert(insert_at, "\n".join(inserts) + "\n")
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
            # 已有注解则跳过
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*:", line):
                continue
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


def process_file(path: Path, index: dict[str, str], dry_run: bool) -> tuple[int, bool]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0, False

    annotator = Annotator(index)
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

    root: Path = args.path if args.path.is_dir() else SRC_ROOT
    index = build_return_index(SRC_ROOT)
    print(f"Indexed {len(index)} return types")

    files = sorted(root.rglob("*.py")) if args.path.is_dir() else [args.path]
    total = 0
    changed_files = 0
    for f in files:
        n, changed = process_file(f, index, dry_run=args.dry_run)
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
