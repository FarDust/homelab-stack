"""Guard the `docker stack deploy` interpolation quirk for required-variable messages.

As decided in docs/adr/swarm_interpolation_required_message_adr.md.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BRACED = re.compile(r"\$\{([^}]*)\}")
REQUIRED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:?\?(.*)$", re.DOTALL)


def misparsed_required_expressions(text: str) -> list[str]:
    """Return `${VAR?message}` expressions whose message holds a hyphen.

    The Docker CLI interpolation used by `docker stack deploy` looks for the `-` default operator
    before the `?` required operator, so such an expression resolves to the text after the first
    hyphen, whether or not the variable is set.
    """
    found = []
    # `$$` is the escaped dollar sign; drop the pairs so `$$${VAR?a-b}` (escaped dollar, then an expression) is still seen.
    for match in BRACED.finditer(text.replace("$$", "")):
        required = REQUIRED.match(match.group(1))
        if required and "-" in required.group(1):
            found.append(match.group(0))
    return found


def compose_files() -> list[Path]:
    files = sorted(path for path in (ROOT / "stacks").glob("*/*.yml") if not path.name.startswith(".tmp_"))
    if not files:
        raise AssertionError("no compose files found under stacks/")
    return files


@pytest.mark.parametrize("path", compose_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_required_variable_messages_have_no_hyphen(path: Path) -> None:
    assert misparsed_required_expressions(path.read_text(encoding="utf-8")) == []


def test_detector_flags_the_hyphenated_message_and_accepts_the_safe_forms() -> None:
    bad = "file: ${PRIVATE_DIR:?PRIVATE_DIR must be set (docs/homelab-private.md)}/x.yaml"
    assert misparsed_required_expressions(bad) == ["${PRIVATE_DIR:?PRIVATE_DIR must be set (docs/homelab-private.md)}"]
    assert misparsed_required_expressions("${PRIVATE_DIR?a-b}") == ["${PRIVATE_DIR?a-b}"]
    assert misparsed_required_expressions("$$${PRIVATE_DIR:?a-b}") == ["${PRIVATE_DIR:?a-b}"]
    for safe in ("${PRIVATE_DIR:?PRIVATE_DIR must be set}", "${PRIVATE_DIR?err}", "${NAME:-a-b}", "${NAME-a-b}", "$${NAME:?a-b}"):
        assert misparsed_required_expressions(safe) == []


def test_private_directory_references_fail_closed_with_one_message() -> None:
    text = (ROOT / "stacks/main/traefik.yml").read_text(encoding="utf-8")
    expressions = re.findall(r"\$\{HOMELAB_PRIVATE_DIR[^}]*\}", text)
    assert len(expressions) == 6
    assert len(set(expressions)) == 1
    assert expressions[0].startswith("${HOMELAB_PRIVATE_DIR:?")
