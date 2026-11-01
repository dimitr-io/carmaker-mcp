"""The documentation that is derived from the code must match the code."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tools_reference_is_up_to_date():
    gen = load_script("gen_tools_doc")
    assert (ROOT / "docs" / "tools.md").read_text(encoding="utf-8") == gen.generate(), (
        "docs/tools.md is out of date: run `python scripts/gen_tools_doc.py`")


def test_the_docs_explain_every_environment_variable():
    """Every CM_* variable the code reads is explained in docs/setup.md, and neither that page nor the
    README invents one."""
    used = set()
    for py in (ROOT / "src" / "carmaker_mcp").glob("*.py"):
        used |= set(re.findall(r'"(CM_[A-Z_]+)"', py.read_text(encoding="utf-8")))
    setup = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(CM_[A-Z_]+)`", setup))
    named = documented | set(re.findall(r"`(CM_[A-Z_]+)`", readme))
    assert used - documented == set(), f"not in docs/setup.md: {sorted(used - documented)}"
    assert named - used == set(), f"the docs mention unknown variables: {sorted(named - used)}"


def test_relative_links_between_the_docs_lead_somewhere():
    for page in (ROOT / "docs").glob("*.md"):
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([\w.-]+\.md)(?:#[\w-]+)?\)", text):
            assert (page.parent / target).is_file(), f"{page.name} links to {target}"


def test_links_from_the_readme_to_this_repository_lead_somewhere():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"github\.com/dimitr-io/carmaker-mcp/blob/main/([\w./-]+)", readme)
    assert links and all((ROOT / link).is_file() for link in links)
    headings = {re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-")
                for h in re.findall(r"^#+ (.+)$", readme, flags=re.M)}
    assert set(re.findall(r"\]\(#([\w-]+)\)", readme)) <= headings
