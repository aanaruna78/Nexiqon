from pathlib import Path

from tools.lint.check_architecture import ROOT, domain_violations, vendor_violations


def test_vendor_import_outside_adapters_is_flagged() -> None:
    path = ROOT / "services" / "x" / "src" / "x" / "core.py"
    assert vendor_violations(path, "import openai\n")
    assert vendor_violations(path, "from anthropic.types import Message\n")
    assert not vendor_violations(path, "import openai  # arch: allow\n")
    assert not vendor_violations(path, "import fastapi\n")


def test_vendor_import_inside_adapters_is_allowed() -> None:
    path = ROOT / "services" / "x" / "src" / "x" / "adapters" / "openai_provider.py"
    assert not vendor_violations(path, "import openai\n")


def test_domain_words_are_flagged() -> None:
    path = Path(ROOT / "services" / "x" / "a.py")
    assert domain_violations(path, "def create_ticket(): ...\n")
    assert domain_violations(path, "SUBSCRIPTIONS = []\n")
    assert not domain_violations(path, "def create_record(): ...\n")
    assert not domain_violations(path, "ticket = 1  # arch: allow\n")


def test_dotted_vendor_prefixes() -> None:
    path = ROOT / "libs" / "x" / "core.py"
    assert not vendor_violations(path, "from openfeature import api\n")
    assert vendor_violations(path, "from openfeature.contrib.provider.flagd import FlagdProvider\n")
