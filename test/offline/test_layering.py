"""Component layering: only the data layer imports vendor libraries, and no
component reaches into another's private names.

Vendor calls belong in dataflows, where failures are raised as VendorError
subclasses; a call made elsewhere can report an outage as a fact about the market.

New components must talk to each other through public interfaces. A private name
(``_helper``, ``_config``) is internal to its component; importing it from
another component, or reading it through an imported alias, is a boundary
violation. A hit names the source file and the private dependency it reached for.

Implements: REQ-TA-QR-003; test-plan #25.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENDOR_LIBRARIES = {"yfinance"}

# The components whose boundaries REQ-TA-QR-003 protects (test-plan #25).
COMPONENTS = ("agents", "graph", "dataflows", "memory", "llm_clients")
PACKAGE = "tradingagents"


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.unit
def test_vendor_libraries_are_imported_only_by_the_data_layer():
    data_layer = ROOT / "src" / "tradingagents" / "dataflows"
    offenders = sorted(
        str(path.relative_to(ROOT))
        for package in ("tradingagents", "cli")
        for path in (ROOT / "src" / package).rglob("*.py")
        if data_layer not in path.parents and _imports(path) & VENDOR_LIBRARIES
    )
    assert offenders == []


# --- component boundary scanner (REQ-TA-QR-003) -----------------------------


def _module_info(path: Path, src_root: Path) -> tuple[list[str], bool]:
    """Dotted name of a file relative to the package root, and whether it is a package.

    ``src/tradingagents/graph/setup.py`` -> ``(["tradingagents", "graph", "setup"], False)``;
    a package ``__init__.py`` -> ``(["tradingagents", "graph"], True)``. The package
    flag matters because a relative import inside ``__init__.py`` counts from the
    package itself, not from its parent.
    """
    rel = path.relative_to(src_root)
    parts = list(rel.parts)
    parts[-1] = parts[-1][:-3]  # strip ".py"
    if parts[-1] == "__init__":
        parts.pop()
        return parts, True
    return parts, False


def _component_of_module(parts: list[str]) -> str | None:
    if len(parts) >= 2 and parts[0] == PACKAGE and parts[1] in COMPONENTS:
        return parts[1]
    return None


def _resolve_from(parts: list[str], is_package: bool, node: ast.ImportFrom) -> list[str]:
    """Absolute dotted parts the ``from ...`` clause points at.

    An absolute ``from a.b import`` is used verbatim. A relative import counts
    from the importing module's package: for a plain module that is its parent;
    for a package's ``__init__.py`` it is the package itself (``from .`` = self,
    ``from ..`` = one level up).
    """
    if not node.level:
        return (node.module or "").split(".") if node.module else []
    package = parts if is_package else parts[:-1]
    base = package[: len(package) - (node.level - 1)]
    if node.module:
        base = base + node.module.split(".")
    return base


def _is_private_name(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _private_module_segment(path_parts: list[str]) -> str | None:
    """The first ``_``-prefixed module segment in a dotted path, if any."""
    for segment in path_parts:
        if _is_private_name(segment):
            return segment
    return None


def _private_import_violations(path: Path, src_root: Path) -> list[str]:
    parts, is_package = _module_info(path, src_root)
    own = _component_of_module(parts)
    violations: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_parts = alias.name.split(".")
                target_comp = _component_of_module(module_parts)
                crosses = (
                    target_comp is not None and own is not None and target_comp != own
                )
                private = _private_module_segment(module_parts[len(PACKAGE.split(".")) :])
                if crosses and private:
                    violations.append(
                        f"{path}: imports private module '{alias.name}' "
                        f"from component '{target_comp}'"
                    )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        target = _resolve_from(parts, is_package, node)
        target_comp = _component_of_module(target)
        crosses = target_comp is not None and own is not None and target_comp != own
        if not crosses:
            continue
        target_private = _private_module_segment(target)
        for alias in node.names:
            dep = ".".join(target + [alias.name])
            if target_private:
                # Importing anything from a private module crosses the boundary,
                # even when the imported name is public.
                violations.append(
                    f"{path}: imports '{dep}' from private module "
                    f"'{'.'.join(target)}' of component '{target_comp}'"
                )
            elif _is_private_name(alias.name):
                violations.append(
                    f"{path}: imports private '{dep}' from component '{target_comp}'"
                )
    return violations


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Statements owned directly by ``scope`` (not descending into nested scopes)."""
    if isinstance(scope, ast.Module):
        return list(scope.body)
    if isinstance(scope, ast.Lambda):
        return [scope.body]
    return list(scope.body)


def _walk_own_scope(nodes: list[ast.AST]):
    """Yield nodes under ``nodes`` without descending into nested scopes."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue  # nested scope: its statements are not this scope's bindings
        stack.extend(ast.iter_child_nodes(node))


def _direct_binding_events(
    scope: ast.AST, parts: list[str], is_package: bool
) -> list[tuple[tuple[int, int], str, tuple]]:
    """Every binding made directly in ``scope``, as ``(position, name, binding)``.

    ``binding`` is ``("import", dotted_parts)`` or ``("local", None)``. Positions
    keep source order so a read resolves to the most recent preceding binding:
    a later ``import`` overrides an earlier assignment to the same name, and an
    assignment after an import shadows it for reads that follow. Parameters are
    placed at ``(-1, -1)`` so they precede every statement in the body. Nested
    function/lambda/class bodies are skipped: their names belong to their own scope.
    """
    events: list[tuple[tuple[int, int], str, tuple]] = []

    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs:
            events.append(((-1, -1), arg.arg, ("local", None)))
        if args.vararg:
            events.append(((-1, -1), args.vararg.arg, ("local", None)))
        if args.kwarg:
            events.append(((-1, -1), args.kwarg.arg, ("local", None)))

    own_nodes = list(_walk_own_scope(_scope_nodes(scope)))
    parents = _local_parents(own_nodes)
    for child in own_nodes:
        pos = (getattr(child, "lineno", 0), getattr(child, "col_offset", 0))
        if isinstance(child, ast.Import):
            for alias in child.names:
                if alias.asname:
                    events.append((pos, alias.asname, ("import", alias.name.split("."))))
                else:
                    top = alias.name.split(".")[0]
                    events.append((pos, top, ("import", [top])))
        elif isinstance(child, ast.ImportFrom):
            target = _resolve_from(parts, is_package, child)
            for alias in child.names:
                if alias.asname:
                    events.append((pos, alias.asname, ("import", target + [alias.name])))
                elif alias.name and alias.name != "*":
                    events.append((pos, alias.name, ("import", target + [alias.name])))
        elif isinstance(child, ast.arg):
            events.append((pos, child.arg, ("local", None)))
        elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            events.append((_binding_position(child, parents), child.id, ("local", None)))
    return events


def _local_parents(nodes: list[ast.AST]) -> dict[int, ast.AST]:
    """Parent links over an already-flattened own-scope node list."""
    ids = {id(node) for node in nodes}
    parents: dict[int, ast.AST] = {}
    for node in nodes:
        for child in ast.iter_child_nodes(node):
            if id(child) in ids:
                parents[id(child)] = node
    return parents


# ``for``/``with`` bind their targets before the block runs, so their events sit
# at the statement start; a plain assignment binds only after its right-hand side,
# so its event sits at the statement end.
_BLOCK_TARGET_STATEMENTS = (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.comprehension)
_ASSIGN_STATEMENTS = (ast.Assign, ast.AnnAssign, ast.AugAssign)
_BINDING_STATEMENTS = _BLOCK_TARGET_STATEMENTS + _ASSIGN_STATEMENTS


def _header_end(current: ast.AST) -> tuple[int, int] | None:
    """End position of the header expression a for/with target binds after.

    A ``for`` target binds after its iterable is evaluated; a ``with ... as``
    target binds after the last context-manager expression. Placing the binding
    at that expression's end lets a private read *in the header* still resolve to
    the previous binding, while the block body sees the new target.
    """
    expr: ast.AST | None = None
    if isinstance(current, (ast.For, ast.AsyncFor, ast.comprehension)):
        expr = current.iter
    elif isinstance(current, (ast.With, ast.AsyncWith)) and current.items:
        expr = current.items[-1].context_expr
    if expr is None:
        return None
    return (
        getattr(expr, "end_lineno", getattr(expr, "lineno", 0)),
        getattr(expr, "end_col_offset", getattr(expr, "col_offset", 0)),
    )


def _binding_position(node: ast.AST, parents: dict[int, ast.AST]) -> tuple[int, int]:
    """Where a Store target takes effect, by the statement that owns it.

    A ``for``/``with`` target is bound after its header expression but before the
    block, so it takes effect at that header expression's end (a private read in
    the header resolves to the previous binding; a read in the block resolves to
    the target). An assignment target is bound after its right-hand side, so it
    takes effect at the statement end.
    """
    current: ast.AST = node
    while current is not None and not isinstance(current, _BINDING_STATEMENTS):
        current = parents.get(id(current))
    if current is None:
        return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
    if isinstance(current, _BLOCK_TARGET_STATEMENTS):
        end = _header_end(current)
        if end is not None:
            return end
    return (
        getattr(current, "end_lineno", getattr(current, "lineno", 0)),
        getattr(current, "end_col_offset", getattr(current, "col_offset", 0)),
    )


def _binding_at(events: list[tuple[tuple[int, int], str, tuple]], name: str, read_pos: tuple[int, int]) -> tuple | None:
    """The binding of ``name`` from the latest event at or before ``read_pos``."""
    latest: tuple[tuple[int, int], tuple] | None = None
    for pos, bound_name, binding in events:
        if bound_name == name and pos <= read_pos and (latest is None or pos >= latest[0]):
            latest = (pos, binding)
    return latest[1] if latest is not None else None


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _scopes(tree: ast.Module) -> list[ast.AST]:
    """Every scope node in the module: the module itself plus each function/lambda."""
    found: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            found.append(node)
    return found


def _resolve_name(
    name: str,
    node: ast.AST,
    parents: dict[int, ast.AST],
    events: dict[int, list[tuple[tuple[int, int], str, tuple]]],
) -> tuple | None:
    """Binding of ``name`` visible where ``node`` uses it, walking scopes outward.

    Returns ``("import", parts)``, ``("local", None)``, or ``None`` if unbound.
    Within a scope the most recent binding before the read wins (ordered
    statements); the nearest enclosing scope with any preceding binding wins over
    outer scopes, so a function-local import/assignment shadows the module-level
    import and a nested function can still see an outer function's parameter.
    """
    read_pos = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
    current: ast.AST | None = node
    while current is not None:
        if id(current) in events:
            binding = _binding_at(events[id(current)], name, read_pos)
            if binding is not None:
                return binding
        current = parents.get(id(current))
    return None


def _leftmost_name(node: ast.AST) -> str | None:
    """The leftmost ``Name`` of an attribute chain (``a.b.c`` -> ``a``)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _chain_from_alias(node: ast.AST, root: list[str]) -> list[str] | None:
    """Dotted path named by an attribute chain given its root's import target."""
    if isinstance(node, ast.Name):
        return root
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        base = _chain_from_alias(node.value, root)
        if base is not None:
            return base + [node.attr]
    return None


def _private_alias_violations(path: Path, src_root: Path) -> list[str]:
    parts, is_package = _module_info(path, src_root)
    own = _component_of_module(parts)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = _parent_map(tree)
    events = {
        id(scope): _direct_binding_events(scope, parts, is_package) for scope in _scopes(tree)
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
            continue
        if node.attr.startswith("__"):
            continue
        value = node.value
        left = _leftmost_name(value)
        if left is None:
            continue
        binding = _resolve_name(left, node, parents, events)
        if binding is None or binding[0] != "import":
            continue  # local assignment/parameter, or an unknown name: not an import read
        target = _chain_from_alias(value, binding[1])
        if target is None:
            continue
        target_comp = _component_of_module(target)
        if target_comp is not None and own is not None and target_comp != own:
            dep = ".".join(target + [node.attr])
            violations.append(
                f"{path}: reads private '{dep}' via alias from component '{target_comp}'"
            )
    return violations


def _boundary_violations(src_root: Path) -> list[str]:
    """Every cross-component private import/alias-read under ``src_root``.

    Walks ``rglob("*.py")`` so a newly added module is scanned automatically.
    """
    found: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        if _component_of_module(_module_info(path, src_root)[0]) is None:
            continue
        found += _private_import_violations(path, src_root)
        found += _private_alias_violations(path, src_root)
    return found


SRC_ROOT = ROOT / "src"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _names_path(message: str, path: Path) -> bool:
    """True if ``message`` names ``path``, whatever the OS separator.

    The violation message renders a ``Path``; on Windows it uses backslashes and
    may be absolute or relative, so compare separator-normalised suffixes anchored
    on the package directory instead of an exact string.
    """
    suffix = path.as_posix().split("/", path.as_posix().split("/").index("tradingagents"))[-1]
    return suffix in message.replace("\\", "/")


# --- the baseline must be clean ---------------------------------------------


@pytest.mark.unit
def test_no_component_reaches_into_anothers_private_names():
    """REQ-TA-QR-003: the five components have zero private-crossing boundaries."""
    assert _boundary_violations(SRC_ROOT) == []


# --- cross-component private access is rejected -----------------------------


def _tree(tmp_path: Path) -> Path:
    """A minimal src tree with one module per component, so imports resolve."""
    root = tmp_path / "src"
    _write(root, "tradingagents/__init__.py", "")
    for comp in COMPONENTS:
        _write(root, f"tradingagents/{comp}/__init__.py", "")
    _write(root, "tradingagents/dataflows/config.py", "_config = None\n\ndef _merge(b, c):\n    return b\n")
    _write(root, "tradingagents/dataflows/router.py", "def route_to_vendor(m, *a, **k):\n    return None\n")
    _write(
        root,
        "tradingagents/dataflows/vendors/yahoo/ohlcv.py",
        "def _assert_ohlcv_not_stale(*a, **k):\n    return None\n",
    )
    _write(root, "tradingagents/dataflows/vendors/yahoo/__init__.py", "")
    _write(root, "tradingagents/dataflows/vendors/__init__.py", "")
    _write(root, "tradingagents/llm_clients/factory.py", "def _coerce_max_tokens(v):\n    return v\n\ndef create_llm_client(c):\n    return None\n")
    _write(root, "tradingagents/graph/setup.py", "def _analyst_graph(s, a, m):\n    return None\n\ndef build(it):\n    return None\n")
    return root


@pytest.mark.unit
def test_public_cross_component_import_passes(tmp_path):
    """REQ-TA-QR-003: importing a public entry point is allowed."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.llm_clients.factory import create_llm_client\n"
        "from tradingagents.dataflows.router import route_to_vendor\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_own_component_private_import_passes(tmp_path):
    """REQ-TA-QR-003: a component may import its own private helper."""
    root = _tree(tmp_path)
    _write(root, "tradingagents/graph/g.py", "from .setup import _analyst_graph\n")
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_cross_component_private_import_absolute_fails(tmp_path):
    """REQ-TA-QR-003: absolute private import from another component is rejected."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.llm_clients.factory import _coerce_max_tokens\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert str(root / "tradingagents/graph/g.py") in message       # source file
    assert "tradingagents.llm_clients.factory._coerce_max_tokens" in message  # dependency


@pytest.mark.unit
def test_cross_component_private_import_relative_fails(tmp_path):
    """REQ-TA-QR-003: relative private import from another component is rejected."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from ..dataflows.vendors.yahoo.ohlcv import _assert_ohlcv_not_stale\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert str(root / "tradingagents/graph/g.py") in message
    assert "tradingagents.dataflows.vendors.yahoo.ohlcv._assert_ohlcv_not_stale" in message


@pytest.mark.unit
def test_importing_private_module_from_other_component_fails(tmp_path):
    """REQ-TA-QR-003: importing a private module's public name crosses the boundary.

    ``from tradingagents.dataflows._internal import helper`` reaches into a
    private module of another component even though ``helper`` is public.
    """
    root = _tree(tmp_path)
    _write(root, "tradingagents/dataflows/_internal.py", "def helper():\n    return None\n")
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows._internal import helper\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert _names_path(message, root / "tradingagents/graph/g.py")
    assert "tradingagents.dataflows._internal" in message


@pytest.mark.unit
def test_importing_private_submodule_from_other_component_fails(tmp_path):
    """REQ-TA-QR-003: ``import a.b._secret`` of another component is rejected.

    A plain import of a private submodule from another component is a boundary
    crossing, whether or not any name is taken from it.
    """
    root = _tree(tmp_path)
    _write(root, "tradingagents/dataflows/_secret.py", "X = 1\n")
    _write(
        root,
        "tradingagents/graph/g.py",
        "import tradingagents.dataflows._secret\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert _names_path(message, root / "tradingagents/graph/g.py")
    assert "tradingagents.dataflows._secret" in message


@pytest.mark.unit
def test_cross_component_private_import_from_package_init_fails(tmp_path):
    """REQ-TA-QR-003: a package's __init__.py relative import resolves from itself.

    ``graph/__init__.py`` doing ``from ..dataflows.config import _merge`` reaches
    into dataflows, so it must be reported (the package flag must not drop a level).
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/__init__.py",
        "from ..dataflows.config import _merge\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert _names_path(message, root / "tradingagents/graph/__init__.py")
    assert "tradingagents.dataflows.config._merge" in message


@pytest.mark.unit
def test_cross_component_private_alias_read_fails(tmp_path):
    """REQ-TA-QR-003: reading a private attr through a module alias is rejected."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config\n"
        "result = config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert str(root / "tradingagents/graph/g.py") in message
    assert "tradingagents.dataflows.config._merge" in message


@pytest.mark.unit
def test_cross_component_private_read_via_package_alias_fails(tmp_path):
    """REQ-TA-QR-003: ``df.config._merge`` through a package alias is rejected."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "import tradingagents.dataflows as df\n"
        "result = df.config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert str(root / "tradingagents/graph/g.py") in message
    assert "tradingagents.dataflows.config._merge" in message


@pytest.mark.unit
def test_private_alias_read_within_own_component_passes(tmp_path):
    """REQ-TA-QR-003: same-component alias reads are internal, not violations."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/dataflows/g.py",
        "from tradingagents.dataflows import config\n"
        "result = config._merge({}, {})\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_same_alias_name_in_different_files_is_independent(tmp_path):
    """REQ-TA-QR-003: an alias named in one file must not leak into another.

    ``a.py`` binds ``config`` to dataflows; ``b.py`` binds ``config`` to its own
    component. Reading ``config._merge`` in ``b.py`` is internal and must pass.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/a.py",
        "from tradingagents.dataflows import config\n"
        "result = config._merge({}, {})\n",
    )
    _write(
        root,
        "tradingagents/dataflows/b.py",
        "from tradingagents.dataflows import config\n"
        "result = config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert _names_path(violations[0], root / "tradingagents/graph/a.py")
    assert all(not _names_path(v, root / "tradingagents/dataflows/b.py") for v in violations)


@pytest.mark.unit
def test_alias_shadowed_by_function_parameter_passes(tmp_path):
    """REQ-TA-QR-003: a parameter shadowing an alias is a local, not a module read."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config\n"
        "def f(config):\n"
        "    return config._merge({}, {})\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_function_local_import_private_read_in_same_function_fails(tmp_path):
    """REQ-TA-QR-003: a function-local import aliasing dataflows, used privately there, is caught.

    ``inner`` imports dataflows ``config`` locally and reads ``config._merge`` in
    the same function: that is a real cross-component private read and must be
    reported exactly once.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def inner():\n"
        "    from tradingagents.dataflows import config\n"
        "    return config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert _names_path(violations[0], root / "tradingagents/graph/g.py")
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_function_local_import_does_not_leak_into_other_functions(tmp_path):
    """REQ-TA-QR-003: a local import in one function must not bind the name elsewhere.

    ``inner`` imports dataflows ``config``; ``other`` binds its own ``config``
    (a local object) and reads ``config._merge``. ``other`` must not be judged by
    ``inner``'s import, so only the ``inner`` read is reported.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def inner():\n"
        "    from tradingagents.dataflows import config\n"
        "    return config._merge({}, {})\n"
        "def other():\n"
        "    config = object()\n"
        "    return config._merge\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_module_alias_reassigned_as_local_in_function_passes(tmp_path):
    """REQ-TA-QR-003: a local assignment to a module-alias name shadows it in that function.

    ``cfg`` is imported at module level from dataflows, but ``f`` reassigns
    ``cfg`` to a local object before reading ``cfg._merge``; the read is of the
    local object, not the import, so it is not a boundary violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config as cfg\n"
        "def f():\n"
        "    cfg = make_local()\n"
        "    return cfg._merge\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_inner_function_reads_outer_parameter(tmp_path):
    """REQ-TA-QR-003: a nested function reading the outer function's parameter is local.

    ``outer(cfg)`` receives a ``cfg`` parameter; ``inner`` closes over it and
    reads ``cfg._merge``. ``cfg`` resolves to the outer parameter, not the
    module-level import, so it is not a boundary violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config as cfg\n"
        "def outer(cfg):\n"
        "    def inner():\n"
        "        return cfg._merge\n"
        "    return inner\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_statement_order_import_then_local_assignment_then_read_passes(tmp_path):
    """REQ-TA-QR-003: within one function, the latest preceding binding wins.

    ``cfg`` is imported, then reassigned to a local object, then its private
    attribute is read: the read sees the local object, so zero violations.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config as cfg\n"
        "def f():\n"
        "    cfg = make_local()\n"
        "    return cfg._merge\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_for_target_binds_after_iterable_before_block(tmp_path):
    """REQ-TA-QR-003: a ``for`` target binds after its iterable is evaluated.

    ``cfg`` is imported, then ``for cfg in cfg._items():`` first reads
    ``cfg._items`` against the import (one violation) and only then rebinds
    ``cfg``; reading ``cfg._merge`` inside the body is the iteration local (clean).
    """
    root = _tree(tmp_path)
    _write(root, "tradingagents/dataflows/config.py", "def _merge(b, c):\n    return b\n\ndef _items():\n    return []\n")
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    for cfg in cfg._items():\n"
        "        return cfg._merge\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._items" in violations[0]


@pytest.mark.unit
def test_with_as_target_binds_after_context_expr_before_block(tmp_path):
    """REQ-TA-QR-003: a ``with ... as`` target binds after its context expression.

    ``cfg`` is imported, then ``with cfg._open() as cfg:`` first reads
    ``cfg._open`` against the import (one violation) and only then rebinds ``cfg``;
    reading ``cfg._merge`` inside the block is the local object (clean).
    """
    root = _tree(tmp_path)
    _write(root, "tradingagents/dataflows/config.py", "def _merge(b, c):\n    return b\n\ndef _open():\n    return None\n")
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    with cfg._open() as cfg:\n"
        "        return cfg._merge\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._open" in violations[0]


@pytest.mark.unit
def test_statement_order_rhs_reads_previous_binding_before_assignment(tmp_path):
    """REQ-TA-QR-003: an assignment's right-hand side resolves before the target binds.

    Imports ``cfg`` from dataflows inside the function, then ``cfg = cfg._merge``:
    the right-hand read runs before the target is rebound, so it still points at
    dataflows ``config`` and is reported exactly once. The assignment's end
    position, not a same-line sentinel, decides that.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    cfg = cfg._merge({}, {})\n"
        "    return cfg\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_multiline_rhs_call_resolves_before_assignment(tmp_path):
    """REQ-TA-QR-003: a right-hand call spanning several lines still reads the old binding.

    ``cfg`` is imported in the function, then ``cfg = cfg._merge(`` continues on
    the next lines; the call's end lies past the assignment target, but the whole
    right-hand side is evaluated before binding, so exactly one violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    cfg = cfg._merge(\n"
        "        {},\n"
        "        {},\n"
        "    )\n"
        "    return cfg\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_next_statement_same_line_reads_new_local_binding(tmp_path):
    """REQ-TA-QR-003: a statement after the assignment on the same line sees the local.

    ``cfg = make_local(); cfg._merge`` — the second statement runs after the
    assignment ends, so ``cfg._merge`` reads the local object: zero violations.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    cfg = make_local(); cfg._merge\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_statement_order_assignment_then_import_then_read_fails(tmp_path):
    """REQ-TA-QR-003: a later import overrides an earlier assignment.

    ``cfg`` is assigned a local object, then imported from dataflows ``config``,
    then ``cfg._merge`` is read: the import is the latest binding, so one violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "def f():\n"
        "    cfg = make_local()\n"
        "    from tradingagents.dataflows import config as cfg\n"
        "    return cfg._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert _names_path(violations[0], root / "tradingagents/graph/g.py")
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_statement_order_read_before_reassignment_reports_only_first_access(tmp_path):
    """REQ-TA-QR-003: only the read bound to the import is reported.

    ``cfg`` is imported, ``cfg._merge`` is read (bound to the import -> violation),
    then ``cfg`` is reassigned to a local object and read again (local -> clean).
    Exactly one violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config as cfg\n"
        "def f():\n"
        "    first = cfg._merge({}, {})\n"
        "    cfg = make_local()\n"
        "    second = cfg._merge\n"
        "    return first, second\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_inner_function_parameter_does_not_shadow_outer_alias(tmp_path):
    """REQ-TA-QR-003: a nested function's parameter must not shadow an outer read.

    ``outer`` reads ``config._merge`` where ``config`` is the module alias; the
    nested ``inner(config)`` parameter belongs to ``inner`` only, so the outer
    read is still a boundary violation.
    """
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "from tradingagents.dataflows import config\n"
        "def outer():\n"
        "    def inner(config):\n"
        "        return config\n"
        "    return config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert "tradingagents.dataflows.config._merge" in violations[0]


@pytest.mark.unit
def test_package_alias_shadowed_by_parameter_passes(tmp_path):
    """REQ-TA-QR-003: ``df.config._merge`` is local when the leftmost ``df`` is a param."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "import tradingagents.dataflows as df\n"
        "def f(df):\n"
        "    return df.config._merge({}, {})\n",
    )
    assert _boundary_violations(root) == []


@pytest.mark.unit
def test_private_read_via_full_module_path_after_plain_import_fails(tmp_path):
    """REQ-TA-QR-003: ``import a.b.c`` then ``a.b.c._x`` is a private read after import."""
    root = _tree(tmp_path)
    _write(
        root,
        "tradingagents/graph/g.py",
        "import tradingagents.dataflows.config\n"
        "result = tradingagents.dataflows.config._merge({}, {})\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    message = violations[0]
    assert _names_path(message, root / "tradingagents/graph/g.py")
    assert "tradingagents.dataflows.config._merge" in message


@pytest.mark.unit
def test_a_newly_added_module_is_scanned(tmp_path):
    """REQ-TA-QR-003: a module added after this test was written is still checked."""
    root = _tree(tmp_path)
    _write(root, "tradingagents/memory/brand_new.py", "X = 1\n")
    assert _boundary_violations(root) == []          # clean new module: no false positive
    _write(
        root,
        "tradingagents/memory/brand_new.py",
        "from tradingagents.dataflows.config import _merge\n",
    )
    violations = _boundary_violations(root)
    assert len(violations) == 1
    assert _names_path(violations[0], root / "tradingagents/memory/brand_new.py")
    assert "tradingagents.dataflows.config._merge" in violations[0]
