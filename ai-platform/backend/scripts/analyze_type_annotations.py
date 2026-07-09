"""Analyze missing type annotations in src/**/*.py (analysis only)."""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
SKIP_ASSIGN_NAMES = frozenset({"__all__", "_"})


@dataclass
class FileStats:
    unannotated_assigns: int = 0
    total_functions: int = 0
    assign_examples: list[tuple[int, str]] = field(default_factory=list)
    funcs_missing_return: int = 0
    funcs_missing_arg: int = 0
    func_sig_examples: list[tuple[int, str]] = field(default_factory=list)


def _is_dunder_name(name: str) -> bool:
    if name in SKIP_ASSIGN_NAMES:
        return True
    return name.startswith("__") and name.endswith("__")


def _target_names(node: ast.expr) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            names.extend(_target_names(elt))
    elif isinstance(node, ast.Starred):
        names.extend(_target_names(node.value))
    return names


def _should_count_assign(targets: list[ast.expr]) -> bool:
    all_names: list[str] = []
    for t in targets:
        all_names.extend(_target_names(t))
    if not all_names:
        return False
    return not any(_is_dunder_name(n) for n in all_names)


def _check_function_def(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    stats: FileStats,
    source_lines: list[str],
) -> None:
    stats.total_functions += 1
    missing_return = node.returns is None
    missing_arg = False
    for arg in node.args.args + node.args.kwonlyargs:
        if arg.arg in ("self", "cls"):
            continue
        if arg.annotation is None:
            missing_arg = True
            break
    if node.args.vararg and node.args.vararg.annotation is None:
        missing_arg = True
    if node.args.kwarg and node.args.kwarg.annotation is None:
        missing_arg = True

    if missing_return:
        stats.funcs_missing_return += 1
    if missing_arg:
        stats.funcs_missing_arg += 1

    if (missing_return or missing_arg) and len(stats.func_sig_examples) < 5:
        line = source_lines[node.lineno - 1].rstrip() if node.lineno <= len(source_lines) else node.name
        issues = []
        if missing_return:
            issues.append("no return")
        if missing_arg:
            issues.append("no arg")
        stats.func_sig_examples.append((node.lineno, f"{line}  # [{', '.join(issues)}]"))


class Analyzer(ast.NodeVisitor):
    def __init__(self, stats: FileStats, source_lines: list[str]) -> None:
        self.stats = stats
        self.source_lines = source_lines
        self._in_function_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        _check_function_def(node, self.stats, self.source_lines)
        self._in_function_depth += 1
        self.generic_visit(node)
        self._in_function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        _check_function_def(node, self.stats, self.source_lines)
        self._in_function_depth += 1
        self.generic_visit(node)
        self._in_function_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._in_function_depth > 0 and _should_count_assign(node.targets):
            self.stats.unannotated_assigns += 1
            if len(self.stats.assign_examples) < 8:
                line = self.source_lines[node.lineno - 1].rstrip() if node.lineno <= len(self.source_lines) else ""
                self.stats.assign_examples.append((node.lineno, line))
        self.generic_visit(node)


def analyze_file(path: Path) -> FileStats:
    stats = FileStats()
    text = path.read_text(encoding="utf-8")
    source_lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        print(f"SYNTAX ERROR: {path}: {e}", file=sys.stderr)
        return stats
    Analyzer(stats, source_lines).visit(tree)
    return stats


def main() -> None:
    py_files = sorted(SRC_ROOT.rglob("*.py"))
    per_file: dict[Path, FileStats] = {}
    total_assigns = total_missing_return = total_missing_arg = total_funcs = 0

    for path in py_files:
        st = analyze_file(path)
        per_file[path.relative_to(SRC_ROOT)] = st
        total_assigns += st.unannotated_assigns
        total_missing_return += st.funcs_missing_return
        total_missing_arg += st.funcs_missing_arg
        total_funcs += st.total_functions

    print("=" * 72)
    print("Type annotation gap analysis")
    print(f"Root: {SRC_ROOT}")
    print(f"Python files scanned: {len(py_files)}")
    print("=" * 72)
    print()
    print("LOCAL VARIABLES (Assign in function bodies, excluding AnnAssign)")
    print(f"  Total unannotated assignments: {total_assigns}")
    print()
    print("FUNCTION SIGNATURES (all FunctionDef / AsyncFunctionDef, incl. nested)")
    print(f"  Total functions/methods: {total_funcs}")
    print(f"  Missing return annotation: {total_missing_return}")
    print(f"  Missing at least one arg annotation (excl. self/cls): {total_missing_arg}")
    print()

    ranked = sorted(per_file.items(), key=lambda x: x[1].unannotated_assigns, reverse=True)
    print("TOP 20 FILES by unannotated local assigns:")
    print("  (columns: assigns | missing-return | missing-arg)")
    print("-" * 72)
    for i, (rel, st) in enumerate(ranked[:20], 1):
        if st.unannotated_assigns == 0:
            continue
        print(
            f"  {i:2d}. {st.unannotated_assigns:5d}  "
            f"(ret-{st.funcs_missing_return:3d}, arg-{st.funcs_missing_arg:3d})  {rel}"
        )

    print()
    print("EXAMPLE UNANNOTATED ASSIGN LINES:")
    print("-" * 72)
    shown = 0
    for rel, st in ranked:
        if st.unannotated_assigns == 0:
            break
        for lineno, line in st.assign_examples[:3]:
            print(f"  {rel}:{lineno}: {line[:100]}")
            shown += 1
            if shown >= 15:
                break
        if shown >= 15:
            break

    print()
    print("TOP 10 FILES by missing function signature annotations (return+arg counts):")
    print("-" * 72)
    sig_ranked = sorted(
        per_file.items(),
        key=lambda x: (x[1].funcs_missing_return + x[1].funcs_missing_arg, x[1].unannotated_assigns),
        reverse=True,
    )
    for i, (rel, st) in enumerate(sig_ranked[:10], 1):
        if st.funcs_missing_return + st.funcs_missing_arg == 0:
            break
        print(
            f"  {i:2d}. ret-{st.funcs_missing_return:3d}, arg-{st.funcs_missing_arg:3d}  "
            f"(of {st.total_functions} funcs)  {rel}"
        )

    print()
    print("EXAMPLE FUNCTIONS WITH MISSING SIGNATURE ANNOTATIONS:")
    print("-" * 72)
    shown_sig = 0
    for rel, st in sig_ranked:
        for lineno, line in st.func_sig_examples[:2]:
            print(f"  {rel}:{lineno}: {line[:100]}")
            shown_sig += 1
            if shown_sig >= 10:
                break
        if shown_sig >= 10:
            break

    files_with_any = sum(1 for st in per_file.values() if st.unannotated_assigns > 0)
    print()
    print("SUMMARY")
    print(f"  Files with >=1 unannotated local assign: {files_with_any} / {len(py_files)}")
    if total_assigns:
        top5 = sum(st.unannotated_assigns for _, st in ranked[:5])
        print(f"  Top 5 files account for {top5} assigns ({100.0 * top5 / total_assigns:.1f}% of total)")


if __name__ == "__main__":
    main()
