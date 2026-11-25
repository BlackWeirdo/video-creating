"""Scope-aware Python AST static linter enforcing Ruff/Pyflakes F821 (undefined name) and F401 (unused import)."""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from videocreator.paths import REPO_ROOT

pytestmark = pytest.mark.local

BUILTINS: frozenset[str] = frozenset(dir(builtins)) | {
    "__annotations__",
    "__doc__",
    "__file__",
    "__name__",
    "__package__",
    "__path__",
    "__spec__",
}


@dataclass
class _Scope:
    kind: str  # "module" | "class" | "function" | "comp"
    defined: set[str] = field(default_factory=set)
    loads: list[tuple[int, str]] = field(default_factory=list)
    children: list[_Scope] = field(default_factory=list)


def _extract_target_names(target: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(target):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            names.add(sub.id)
    return names


class _ScopeBuilder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.root = _Scope("module")
        self.stack: list[_Scope] = [self.root]
        self.all_loaded_names: set[str] = set()
        self.dunder_all_exports: set[str] = set()
        self.module_imports: list[tuple[int, str]] = []

    @property
    def cur(self) -> _Scope:
        return self.stack[-1]

    def _push(self, kind: str) -> _Scope:
        sc = _Scope(kind)
        self.cur.children.append(sc)
        self.stack.append(sc)
        return sc

    def _pop(self) -> None:
        self.stack.pop()

    def _nearest_non_comp_non_class(self) -> _Scope:
        for sc in reversed(self.stack):
            if sc.kind in ("function", "module"):
                return sc
        return self.root

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.cur.loads.append((node.lineno, node.id))
            self.all_loaded_names.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.cur.defined.add(node.id)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        if isinstance(node.target, ast.Name):
            self._nearest_non_comp_non_class().defined.add(node.target.id)
        self.visit(node.value)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            self.cur.defined.add(bound)
            if self.cur is self.root:
                self.module_imports.append((node.lineno, bound))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "__future__":
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self.cur.defined.add(bound)
            if self.cur is self.root:
                self.module_imports.append((node.lineno, bound))

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.cur is self.root:
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__" and isinstance(
                    node.value, (ast.List, ast.Tuple, ast.Set)
                ):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self.dunder_all_exports.add(elt.value)
        self.visit(node.value)
        for t in node.targets:
            self.cur.defined.update(_extract_target_names(t))
            for sub in ast.walk(t):
                if isinstance(sub, (ast.Attribute, ast.Subscript)):
                    self.visit(sub.value)
                    if isinstance(sub, ast.Subscript):
                        self.visit(sub.slice)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.cur.defined.update(_extract_target_names(node.target))
        if isinstance(node.target, (ast.Attribute, ast.Subscript)):
            self.visit(node.target.value)
            if isinstance(node.target, ast.Subscript):
                self.visit(node.target.slice)

    def visit_Global(self, node: ast.Global) -> None:
        self.cur.defined.update(node.names)
        self.root.defined.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.cur.defined.update(node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.cur.defined.add(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for d in node.args.defaults:
            self.visit(d)
        for kd in node.args.kw_defaults:
            if kd is not None:
                self.visit(kd)
        for arg in (
            node.args.posonlyargs
            + node.args.args
            + node.args.kwonlyargs
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        ):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.returns is not None:
            self.visit(node.returns)

        self.cur.defined.add(node.name)
        fn_scope = self._push("function")
        for arg in (
            node.args.posonlyargs
            + node.args.args
            + node.args.kwonlyargs
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        ):
            fn_scope.defined.add(arg.arg)
        for stmt in node.body:
            self.visit(stmt)
        self._pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for d in node.args.defaults:
            self.visit(d)
        for kd in node.args.kw_defaults:
            if kd is not None:
                self.visit(kd)
        lam_scope = self._push("function")
        for arg in (
            node.args.posonlyargs
            + node.args.args
            + node.args.kwonlyargs
            + ([node.args.vararg] if node.args.vararg else [])
            + ([node.args.kwarg] if node.args.kwarg else [])
        ):
            lam_scope.defined.add(arg.arg)
        self.visit(node.body)
        self._pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        self.cur.defined.add(node.name)
        self._push("class")
        for stmt in node.body:
            self.visit(stmt)
        self._pop()

    def _visit_comprehension(self, generators: list[ast.comprehension], *exprs: ast.AST) -> None:
        if generators:
            self.visit(generators[0].iter)
        comp_scope = self._push("comp")
        for idx, gen in enumerate(generators):
            if idx > 0:
                self.visit(gen.iter)
            comp_scope.defined.update(_extract_target_names(gen.target))
            for if_expr in gen.ifs:
                self.visit(if_expr)
        for ex in exprs:
            self.visit(ex)
        self._pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, node.key, node.value)


def _check_scope_undefined(scope: _Scope, visible_from_enclosing: set[str]) -> list[tuple[int, str]]:
    visible_here = visible_from_enclosing | scope.defined | BUILTINS
    errors: list[tuple[int, str]] = []
    for lineno, name in scope.loads:
        if name not in visible_here:
            errors.append((lineno, name))
    # Python lexical rule: class scopes do NOT propagate bindings to nested methods/functions
    child_visible = (
        visible_from_enclosing if scope.kind == "class" else visible_here
    )
    for child in scope.children:
        errors.extend(_check_scope_undefined(child, child_visible))
    return errors


def test_python_src_has_zero_f821_undefined_names() -> None:
    """Ruff/Pyflakes F821 equivalent: zero undefined variable/symbol references anywhere in `src/`."""
    src_root = REPO_ROOT / "src" / "videocreator"
    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=rel)
        builder = _ScopeBuilder()
        builder.visit(tree)
        for lineno, name in sorted(set(_check_scope_undefined(builder.root, set()))):
            violations.append(f"{rel}:{lineno}: F821 undefined name '{name}'")
    assert violations == [], "Undefined names detected in src/:\n" + "\n".join(violations)


def test_python_src_has_zero_f401_unused_imports() -> None:
    """Ruff/Pyflakes F401 equivalent: zero unused module-level imports in `src/` (excluding `__init__.py` & `__all__`)."""
    src_root = REPO_ROOT / "src" / "videocreator"
    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=rel)
        builder = _ScopeBuilder()
        builder.visit(tree)
        used = builder.all_loaded_names | builder.dunder_all_exports
        for lineno, bound in builder.module_imports:
            if bound not in used and not bound.startswith("_"):
                violations.append(f"{rel}:{lineno}: F401 '{bound}' imported but unused")
    assert violations == [], "Unused imports detected in src/:\n" + "\n".join(violations)
