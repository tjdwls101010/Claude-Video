"""The skill's tree is an interface read before any file, so its shape is checked here rather than described: `scripts/` holds `cli.py` and one package, `filmcraft/`; every top-level name in the package has a kind in `KINDS`; imports point only the way the kinds allow; nothing outside a unit (`cli.py`, another unit, a test) reaches past the unit's interface; and no skill file edits `sys.path`.

A unit's interface is its `__init__.py`'s `__all__` for a subpackage and its names without a leading underscore for a module. Every check is a function of a tree, so each one is also run against a small tree built to break it."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".claude/skills/filmcraft/scripts"
TESTS = REPO / "tests"
PKG = "filmcraft"

# The kind of every top-level name under filmcraft/. A name missing here fails, so a new unit is placed on purpose.
KINDS = {
    "transcribe": "feature", "captions": "feature", "timeline": "feature", "frames": "feature", "qc": "feature",
    "filmcraft_cli": "system", "whisper": "system", "ffmpeg": "system", "mp4": "system",
    "timecode": "shared", "errors": "shared", "__init__": "shared",
}

# What each kind may import besides its own unit: features rely on systems and shared helpers, systems on shared helpers only, so a feature can change or go without touching the rest.
MAY_IMPORT = {"feature": {"system", "shared"}, "system": {"shared"}, "shared": {"shared"}}

# Imports between two features or two systems that are allowed on purpose. None so far.
EXTRA_EDGES: set[tuple[str, str]] = set()


def py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def unit_of(path: Path, package: Path) -> str:
    rel = path.relative_to(package)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def imports(path: Path):
    """`(line, dotted name, names)` for every absolute import in a file, including those inside functions; `from filmcraft import qc` yields `filmcraft.qc`."""
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, ()
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield node.lineno, "." * node.level + (node.module or ""), tuple(a.name for a in node.names)
            elif node.module == PKG:
                for alias in node.names:
                    yield node.lineno, f"{PKG}.{alias.name}", ()
            else:
                yield node.lineno, node.module or "", tuple(a.name for a in node.names)


def declared_all(init: Path):
    for node in ast.parse(init.read_text()).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return None


# -- checks: each takes the scripts directory (and a tests directory) and returns violations as strings --------------------

def check_top_level(scripts: Path) -> list[str]:
    names = {p.name for p in scripts.iterdir() if p.name != "__pycache__" and not p.name.startswith(".")}
    return [] if names == {"cli.py", PKG} else [f"scripts/ holds {sorted(names)}, expected ['cli.py', '{PKG}']"]


def check_kinds(scripts: Path) -> list[str]:
    package = scripts / PKG
    units = {unit_of(p, package) for p in py_files(package)}
    return [f"{u}: no kind in KINDS" for u in sorted(units - KINDS.keys())]


def check_relative_imports(scripts: Path) -> list[str]:
    """Relative imports only inside a subpackage (`from .x import y` in `qc/__init__.py`); across units they hide the direction this test reads."""
    package = scripts / PKG
    out = []
    for p in py_files(package):
        depth = len(p.relative_to(package).parts) - 1
        for line, name, _ in imports(p):
            if name.startswith(".") and (len(name) - len(name.lstrip("."))) > depth:
                out.append(f"{p.relative_to(scripts)}:{line} relative import leaves its unit: {name}")
    return out


def check_direction(scripts: Path) -> list[str]:
    package = scripts / PKG
    out = []
    for p in py_files(package):
        src = unit_of(p, package)
        for line, name, _ in imports(p):
            parts = name.split(".")
            if parts[0] == "cli":
                out.append(f"{p.relative_to(scripts)}:{line} the package imports cli")
            if parts[0] != PKG or len(parts) < 2:
                continue
            dst = parts[1]
            if dst == src or dst not in KINDS or src not in KINDS:
                continue
            if KINDS[dst] not in MAY_IMPORT[KINDS[src]] and (src, dst) not in EXTRA_EDGES:
                out.append(f"{p.relative_to(scripts)}:{line} {KINDS[src]} {src} imports {KINDS[dst]} {dst}")
            elif KINDS[src] == KINDS[dst] != "shared" and (src, dst) not in EXTRA_EDGES:
                out.append(f"{p.relative_to(scripts)}:{line} {KINDS[src]} {src} imports {KINDS[dst]} {dst}")
    return out


def check_interfaces(scripts: Path, tests: Path | None) -> list[str]:
    """Outside a unit, only `filmcraft.<unit>` is imported, and a name taken from a subpackage is in its `__all__`."""
    package = scripts / PKG
    subpackages = {p.parent.name for p in package.glob("*/__init__.py")}
    files = [(p, unit_of(p, package)) for p in py_files(package)] + [(scripts / "cli.py", None)]
    if tests is not None:
        files += [(p, None) for p in py_files(tests)]
    out = [f"{u}/__init__.py has no literal __all__" for u in sorted(subpackages) if declared_all(package / u / "__init__.py") is None]
    for p, own in files:
        if not p.exists():
            continue
        for line, name, names in imports(p):
            parts = name.split(".")
            if parts[0] != PKG or len(parts) < 2 or parts[1] == own:
                continue
            if len(parts) > 2:
                out.append(f"{p}:{line} reaches past the interface: {name}")
            elif parts[1] in subpackages and names:
                exported = declared_all(package / parts[1] / "__init__.py") or set()
                out += [f"{p}:{line} {parts[1]}.{n} is not in __all__" for n in names if n not in exported]
            elif parts[1] not in subpackages and names:
                out += [f"{p}:{line} {parts[1]}.{n} is private" for n in names if n.startswith("_")]
    return out


def check_attribute_reach(scripts: Path, tests: Path | None) -> list[str]:
    """`from filmcraft import ffmpeg` then `ffmpeg.extract.extract_frame(...)` reaches past the interface as surely as importing `filmcraft.ffmpeg.extract`."""
    package = scripts / PKG
    units = {p.parent.name for p in package.glob("*/__init__.py")}
    # an inner module's name is fine when the interface exports something by that name (ffmpeg.probe is the function)
    inner = {u: {p.stem if p.is_file() else p.name for p in (package / u).iterdir() if p.name not in ("__init__.py", "__pycache__") and (p.suffix == ".py" or p.is_dir())}
                - (declared_all(package / u / "__init__.py") or set()) for u in units}
    files = [(p, unit_of(p, package)) for p in py_files(package)] + [(scripts / "cli.py", None)] + ([(p, None) for p in py_files(tests)] if tests else [])
    out = []
    for p, own in files:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text())
        bound: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == PKG and not node.level:
                bound.update({(a.asname or a.name): a.name for a in node.names if a.name in inner})
            elif isinstance(node, ast.Import):
                bound.update({a.asname: a.name.split(".")[1] for a in node.names if a.asname and a.name.count(".") == 1 and a.name.startswith(PKG + ".") and a.name.split(".")[1] in inner})
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if isinstance(base, ast.Name) and base.id in bound and bound[base.id] != own and node.attr in inner[bound[base.id]]:
                out.append(f"{p}:{node.lineno} reaches past the interface: {base.id}.{node.attr}")
            if (isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == PKG and base.attr in inner
                    and base.attr != own and node.attr in inner[base.attr]):
                out.append(f"{p}:{node.lineno} reaches past the interface: {PKG}.{base.attr}.{node.attr}")
    return out


def check_no_sys_path(scripts: Path) -> list[str]:
    """`cli.py` run directly already has `scripts/` first on sys.path; editing it hides an import bug until the skill runs from elsewhere."""
    out = []
    for p in py_files(scripts):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "path" and isinstance(node.value, ast.Name) and node.value.id == "sys":
                out.append(f"{p.relative_to(scripts)}:{node.lineno} touches sys.path")
            if isinstance(node, ast.Attribute) and node.attr == "addsitedir":
                out.append(f"{p.relative_to(scripts)}:{node.lineno} calls site.addsitedir")
    return out


def all_violations(scripts: Path, tests: Path | None) -> list[str]:
    return (check_top_level(scripts) + check_kinds(scripts) + check_relative_imports(scripts) + check_direction(scripts)
            + check_interfaces(scripts, tests) + check_attribute_reach(scripts, tests) + check_no_sys_path(scripts))


# -- the real tree ----------------------------------------------------------------------------------------------------------

def test_skill_tree_has_no_violations():
    assert all_violations(SCRIPTS, TESTS) == []


def test_every_kind_is_present_in_the_tree():
    """A kind listed for a unit that no longer exists is stale and would let a new unit of that name in unplaced."""
    package = SCRIPTS / PKG
    units = {unit_of(p, package) for p in py_files(package)}
    assert sorted(KINDS.keys() - units) == []


# -- each check against a tree built to break it ----------------------------------------------------------------------------

def make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    scripts = tmp_path / "scripts"
    base = {"cli.py": "from filmcraft import qc\n", f"{PKG}/__init__.py": "", f"{PKG}/timecode.py": "def x(): pass\n",
            f"{PKG}/qc/__init__.py": "from .judge import judge\n__all__ = ['judge']\n", f"{PKG}/qc/judge.py": "def judge(): pass\n",
            f"{PKG}/ffmpeg/__init__.py": "__all__ = ['probe']\ndef probe(): pass\n"}
    base.update(files)
    for rel, text in base.items():
        if text is None:
            continue
        f = scripts / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return scripts


def test_clean_tree_passes(tmp_path):
    assert all_violations(make_tree(tmp_path, {}), None) == []


@pytest.mark.parametrize("files, expected", [
    ({"helpers.py": "x = 1\n"}, "scripts/ holds"),
    ({f"{PKG}/extra.py": "x = 1\n"}, "extra: no kind"),
    ({f"{PKG}/ffmpeg/__init__.py": "from filmcraft import qc\n__all__ = []\n"}, "system ffmpeg imports feature qc"),
    ({f"{PKG}/timecode.py": "import filmcraft.ffmpeg\n"}, "shared timecode imports system ffmpeg"),
    ({f"{PKG}/frames/__init__.py": "from filmcraft.qc import judge\n__all__ = []\n"}, "feature frames imports feature qc"),
    ({f"{PKG}/whisper/__init__.py": "from filmcraft import ffmpeg\n__all__ = []\n"}, "system whisper imports system ffmpeg"),
    ({"cli.py": "from filmcraft.qc.judge import judge\n"}, "reaches past the interface"),
    ({"cli.py": "from filmcraft.qc import helper\n"}, "qc.helper is not in __all__"),
    ({"cli.py": "from filmcraft import qc\nqc.bands.x()\n", f"{PKG}/qc/bands.py": "def x(): pass\n"}, "reaches past the interface: qc.bands"),
    ({"cli.py": "import filmcraft\nfilmcraft.qc.bands.x()\n", f"{PKG}/qc/bands.py": "def x(): pass\n"}, "reaches past the interface: filmcraft.qc.bands"),
    ({"cli.py": "from filmcraft.timecode import _private\n"}, "timecode._private is private"),
    ({f"{PKG}/qc/__init__.py": "from .judge import judge\n"}, "has no literal __all__"),
    ({f"{PKG}/qc/judge.py": "from ..ffmpeg import probe\n"}, "relative import leaves its unit"),
    ({"cli.py": "import sys\nsys.path.insert(0, 'x')\n"}, "touches sys.path"),
    ({f"{PKG}/timecode.py": "import cli\n"}, "the package imports cli"),
])
def test_each_check_catches_its_break(tmp_path, files, expected):
    found = all_violations(make_tree(tmp_path, files), None)
    assert any(expected in v for v in found), found


def test_a_test_reaching_past_an_interface_is_caught(tmp_path):
    scripts = make_tree(tmp_path, {})
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from filmcraft.qc.judge import judge\n")
    assert any("reaches past the interface" in v for v in check_interfaces(scripts, tests))
