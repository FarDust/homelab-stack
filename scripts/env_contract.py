#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich", "pydantic", "pydantic-settings", "pyyaml"]
# ///
"""Environment-variable contract for the compose stacks.

The stacks interpolate `${VAR}`, `${VAR:-default}` and `${VAR?message}` from the deployment environment, which is a
layered shell script (`.env`: literals, secret-file reads, computed values). This tool keeps one typed contract,
`config/env-contract.yaml`, in step with what the stacks use, with `.env.example`, and (by name only) with a live `.env`.

Commands:
  scan           list the variables the stacks interpolate and where
  check          fail when the contract, the stacks and `.env.example` disagree
  generate-example  render `.env.example` from the contract
  check-live     compare the NAMES defined in a live `.env` with the contract; values are never read into output

The contract and every report hold names, kinds and file-name patterns only, never values.
As decided in docs/adr/env_contract_adr.md.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.markup import escape
from rich.table import Table

app = typer.Typer(add_completion=False, no_args_is_help=True)
out = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)

NAME = r"[A-Za-z_][A-Za-z0-9_]*"
NAME_RE = re.compile(NAME)
BRACED_RE = re.compile(rf"({NAME})(?:(:?[-?+])(.*))?", re.S)
# `export NAME=...` or `NAME=...`; only the name and the start of the right side are ever inspected.
REFERENCE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
LIVE_LINE_RE = re.compile(rf"^(?P<export>export\s+)?(?P<name>{NAME})=(?P<rest>.*)$")
SECRET_READ_PREFIX = "$(cat secrets/"
REQUIRED_OPERATORS = {"?", ":?"}
DEFAULT_OPERATORS = {"-", ":-"}
EXAMPLE_HEADER = (
    "# Generated from config/env-contract.yaml by scripts/env_contract.py generate-example; edit the contract, not this file.\n"
    "# Copy to .env and replace placeholders. `.env` is a shell script sourced from the compose root: literals are\n"
    "# `export NAME=value`, secrets are read from the secrets directory at source time, computed values run a command.\n"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENV_CONTRACT_")

    root: Path = Path(".")
    contract: Path = Path("config/env-contract.yaml")
    example: Path = Path(".env.example")
    stacks_dir: Path = Path("stacks")


class ContractError(Exception):
    """The contract, a stack file or an input file is malformed or inconsistent."""


class Kind(StrEnum):
    LITERAL = "literal"
    SECRET_FILE = "secret-file"
    COMPUTED = "computed"


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=rf"^{NAME}$")
    kind: Kind
    owner: str = Field(min_length=1)
    used_by: tuple[str, ...]
    external_consumers: tuple[str, ...] = ()
    required: bool
    default: str | None = None
    description: str = Field(min_length=1)
    example: str | None = None
    secret_file: str | None = None
    # False when the live `.env` defines it without `export`; it then reaches `docker stack deploy` only through
    # cluster-utils (which sources `.env` with `set -a`), never through a plain `source .env && docker stack deploy`.
    exported: bool = True
    # False for names that must never be written into a copyable .env.example (for example `PATH`).
    in_example: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> Variable:
        who = f"variable {self.name}"
        if not self.used_by and not self.external_consumers:
            raise ValueError(f"{who}: needs used_by stacks or external_consumers")
        if self.used_by and self.owner not in self.used_by:
            raise ValueError(f"{who}: owner {self.owner!r} must be one of used_by")
        if list(self.used_by) != sorted(set(self.used_by)):
            raise ValueError(f"{who}: used_by must be sorted and unique")
        if self.required and self.default is not None:
            raise ValueError(f"{who}: a required variable cannot carry a default")
        if not self.required and self.default is None:
            raise ValueError(f"{who}: an optional variable needs an explicit default (use '' for empty)")
        if self.kind is Kind.SECRET_FILE:
            if not self.secret_file:
                raise ValueError(f"{who}: kind secret-file needs secret_file (a name pattern under secrets/)")
            if self.default not in (None, ""):
                raise ValueError(f"{who}: a secret may only default to the empty string")
            if self.example is not None:
                raise ValueError(f"{who}: a secret holds no example value")
        elif self.secret_file is not None:
            raise ValueError(f"{who}: secret_file is only valid for kind secret-file")
        return self


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    variables: tuple[Variable, ...]

    @model_validator(mode="after")
    def _unique(self) -> Contract:
        if self.version != 1:
            raise ValueError(f"unsupported contract version {self.version}; expected 1")
        names = [v.name for v in self.variables]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate variables: {', '.join(duplicates)}")
        return self

    def by_name(self) -> dict[str, Variable]:
        return {v.name: v for v in self.variables}


@dataclass(frozen=True, slots=True)
class Use:
    name: str
    operator: str | None
    operand: str | None
    stack: str


@dataclass(slots=True)
class Usage:
    stacks: set[str]
    required: bool
    defaults: set[str]
    bare: bool  # at least one use without default and without a required message


def load_contract(path: Path) -> Contract:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"cannot read contract {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ContractError(f"contract {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"contract {path}: top level must be a mapping with version and variables")
    try:
        return Contract.model_validate(raw)
    except ValidationError as exc:
        raise ContractError(f"contract {path} is invalid:\n{exc}") from exc


def _braced_end(text: str, start: int, source: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text.startswith("${", i):
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ContractError(f"{source}: unterminated '${{' in {text[start:start + 40]!r}")


def interpolations(text: str, stack: str) -> list[Use]:
    """Return every variable interpolation in one string, following compose rules (`$$` escapes, nested operands)."""
    uses: list[Use] = []
    i = 0
    while i < len(text):
        if text[i] != "$":
            i += 1
            continue
        nxt = text[i + 1 : i + 2]
        if nxt == "$":
            i += 2
        elif nxt == "{":
            end = _braced_end(text, i, stack)
            body = text[i + 2 : end]
            match = BRACED_RE.fullmatch(body)
            if match is None:
                raise ContractError(f"{stack}: unsupported interpolation '${{{body[:40]}}}'")
            name, operator, operand = match.groups()
            uses.append(Use(name, operator, operand, stack))
            if operand:
                uses.extend(interpolations(operand, stack))
            i = end + 1
        else:
            bare = NAME_RE.match(text, i + 1)
            if bare:
                uses.append(Use(bare.group(0), None, None, stack))
                i = bare.end()
            else:
                i += 1
    return uses


def _strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def stack_files(root: Path, stacks_dir: Path) -> list[Path]:
    base = root / stacks_dir
    files = sorted([*base.glob("*/*.yml"), *base.glob("*/*.yaml")])
    if not files:
        raise ContractError(f"no stack files found under {base}/*/")
    return files


def scan_stacks(root: Path, stacks_dir: Path) -> dict[str, Usage]:
    usages: dict[str, Usage] = {}
    for path in stack_files(root, stacks_dir):
        stack = f"{path.parent.name}/{path.stem}"
        try:
            documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"cannot parse stack file {path}: {exc}") from exc
        for document in documents:
            for text in _strings(document):
                for use in interpolations(text, stack):
                    usage = usages.setdefault(use.name, Usage(set(), False, set(), False))
                    usage.stacks.add(stack)
                    if use.operator in REQUIRED_OPERATORS:
                        usage.required = True
                    elif use.operator in DEFAULT_OPERATORS:
                        usage.defaults.add(use.operand or "")
                    elif use.operator is None:
                        usage.bare = True
    return usages


def example_names(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read example {path}: {exc}") from exc
    names = set()
    for line in lines:
        match = LIVE_LINE_RE.match(line)
        if match:
            names.add(match["name"])
    return names


def check_contract(contract: Contract, usages: dict[str, Usage], example: set[str]) -> list[str]:
    problems: list[str] = []
    declared = contract.by_name()
    for name in sorted(set(usages) - set(declared)):
        problems.append(f"{name}: used by {', '.join(sorted(usages[name].stacks))} but missing from the contract")
    for name, var in sorted(declared.items()):
        usage = usages.get(name)
        if usage is None:
            if not var.external_consumers:
                problems.append(f"{name}: listed in the contract but no stack uses it (declare external_consumers or remove it)")
            continue
        if set(var.used_by) != usage.stacks:
            problems.append(
                f"{name}: used_by differs from the scan (contract {sorted(var.used_by)}, scan {sorted(usage.stacks)})"
            )
        if usage.required and not var.required:
            problems.append(f"{name}: a stack requires it (${{{name}?...}}) but the contract does not mark it required")
        if usage.bare and not var.required and var.default is None:
            problems.append(f"{name}: used without a default; set required: true or an explicit default")
    expected = {name for name, var in declared.items() if var.in_example}
    for name in sorted(expected - example):
        problems.append(f"{name}: missing from .env.example (run generate-example)")
    for name in sorted(example - expected):
        problems.append(f"{name}: present in .env.example but missing from the contract")
    return problems


def _placeholder(var: Variable) -> str:
    if var.example is not None:
        return var.example
    if var.default is not None:
        return var.default
    return f"your_{var.name.lower()}"


SAFE_UNQUOTED = re.compile(r"^[A-Za-z0-9_@%+=:,./${}-]*$")


def _shell_value(value: str) -> str:
    """Quote for a sourced shell file while keeping `${VAR}` expansion alive."""
    if value == "":
        return '""'
    if SAFE_UNQUOTED.fullmatch(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
    return f'"{escaped}"'


def render_example(contract: Contract) -> str:
    # `.env` is sourced top to bottom, so a name that another value interpolates (for example
    # LOCAL_DOMAIN in https://host.${LOCAL_DOMAIN}) must be defined before its first use.
    values = {
        var.name: _shell_value(_placeholder(var))
        for var in contract.variables
        if var.in_example and var.kind is not Kind.SECRET_FILE
    }
    referenced = {
        name
        for value in values.values()
        for name in REFERENCE_RE.findall(value)
        if name in values
    }
    groups: dict[str, list[Variable]] = defaultdict(list)
    for var in contract.variables:
        owner = var.owner if var.used_by else "external"
        groups["" if var.name in referenced else owner].append(var)
    lines = [EXAMPLE_HEADER.rstrip("\n")]
    for owner in sorted(groups):
        lines.append(f"\n# {owner or 'referenced by other values'}")
        for var in sorted(groups[owner], key=lambda v: v.name):
            if not var.in_example:
                continue
            if var.kind is Kind.SECRET_FILE:
                right = f"$(cat secrets/{var.secret_file} | tr -d '\\n')"
            else:
                right = values[var.name]
            flag = "required" if var.required else "optional"
            lines.append(f"export {var.name}={right}  # {flag} {var.kind.value}: {var.description}")
    return "\n".join(lines) + "\n"


def live_names(path: Path) -> dict[str, tuple[bool, Kind]]:
    """Map each name defined in a live `.env` to (exported, kind), keeping no value."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read live env {path}: {exc}") from exc
    found: dict[str, tuple[bool, Kind]] = {}
    for line in text.splitlines():
        match = LIVE_LINE_RE.match(line)
        if not match:
            continue
        rest = match["rest"]
        if rest.startswith(SECRET_READ_PREFIX):
            kind = Kind.SECRET_FILE
        elif "$(" in rest or "`" in rest:
            kind = Kind.COMPUTED
        else:
            kind = Kind.LITERAL
        found[match["name"]] = (match["export"] is not None, kind)
    return found


def compare_live(contract: Contract, live: dict[str, tuple[bool, Kind]]) -> tuple[list[str], list[str], list[str]]:
    """Return (errors, warnings, optional names the live env leaves undefined)."""
    errors: list[str] = []
    warnings: list[str] = []
    optional_missing: list[str] = []
    declared = contract.by_name()
    for name in sorted(set(live) - set(declared)):
        errors.append(f"{name}: defined in the live env but missing from the contract")
    for name, var in sorted(declared.items()):
        if name not in live:
            if var.required:
                errors.append(f"{name}: required in the contract but not defined in the live env")
            else:
                optional_missing.append(name)
            continue
        exported, kind = live[name]
        if kind is not var.kind:
            errors.append(f"{name}: contract kind {var.kind.value} but the live env defines it as {kind.value}")
        if exported is not var.exported:
            errors.append(f"{name}: contract exported={var.exported} but the live env defines it {'with' if exported else 'without'} `export`")
        elif not exported:
            warnings.append(
                f"{name}: defined without `export`; it reaches `docker stack deploy` only through cluster-utils (set -a)"
            )
    return errors, warnings, optional_missing


def _fail(title: str, problems: list[str]) -> None:
    err.print(f"[bold red]{title}[/bold red]")
    for problem in problems:
        err.print(f"  - {problem}", markup=False, highlight=False)
    raise typer.Exit(1)


def _guard(action):
    try:
        return action()
    except ContractError as exc:
        err.print(f"[bold red]error:[/bold red] {escape(str(exc))}", highlight=False)
        raise typer.Exit(2) from exc


RootOption = Annotated[Path | None, typer.Option(help="Repository root (default: ENV_CONTRACT_ROOT or .)")]


def _settings(root: Path | None) -> Settings:
    settings = Settings()
    if root is not None:
        settings = settings.model_copy(update={"root": root})
    return settings


@app.command()
def scan(root: RootOption = None, as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False) -> None:
    """List the variables interpolated by stacks/*/*.yml and where they are used."""
    s = _settings(root)
    usages = _guard(lambda: scan_stacks(s.root, s.stacks_dir))
    if as_json:
        payload = {
            name: {
                "stacks": sorted(u.stacks),
                "required": u.required,
                "defaults": sorted(u.defaults),
                "bare": u.bare,
            }
            for name, u in sorted(usages.items())
        }
        out.print_json(json.dumps(payload))
        return
    table = Table("variable", "stacks", "required", "defaults")
    for name, u in sorted(usages.items()):
        table.add_row(name, str(len(u.stacks)), "yes" if u.required else "", str(len(u.defaults)))
    out.print(table)
    shared = sum(1 for u in usages.values() if len(u.stacks) > 1)
    out.print(f"{len(usages)} variables used, {shared} shared across stacks")


@app.command()
def check(root: RootOption = None) -> None:
    """Fail when the contract, the stacks and .env.example disagree."""
    s = _settings(root)

    def run() -> list[str]:
        contract = load_contract(s.root / s.contract)
        return check_contract(contract, scan_stacks(s.root, s.stacks_dir), example_names(s.root / s.example))

    problems = _guard(run)
    if problems:
        _fail(f"env contract check failed: {len(problems)} problem(s)", problems)
    out.print("env contract check passed")


@app.command("generate-example")
def generate_example(
    root: RootOption = None,
    stdout: Annotated[bool, typer.Option("--stdout", help="Print instead of writing .env.example")] = False,
) -> None:
    """Render .env.example from the contract."""
    s = _settings(root)
    text = _guard(lambda: render_example(load_contract(s.root / s.contract)))
    if stdout:
        typer.echo(text, nl=False)
        return
    target = s.root / s.example
    target.write_text(text, encoding="utf-8", newline="\n")
    if target.read_text(encoding="utf-8") != text:
        _fail("generate-example could not verify the written file", [str(target)])
    out.print(f"wrote {target}")


@app.command("check-live")
def check_live(
    path: Path,
    root: RootOption = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Also list optional names the live env leaves undefined")] = False,
) -> None:
    """Compare the NAMES defined in a live .env with the contract; values are never printed."""
    s = _settings(root)

    def run() -> tuple[list[str], list[str], list[str]]:
        return compare_live(load_contract(s.root / s.contract), live_names(path))

    errors, warnings, optional_missing = _guard(run)
    if verbose:
        warnings = [*warnings, *(f"{name}: optional, not defined in the live env (default applies)" for name in optional_missing)]
    for warning in warnings:
        err.print(f"warning: {warning}", markup=False, highlight=False)
    if errors:
        _fail(f"live env differs from the contract: {len(errors)} error(s)", errors)
    out.print(
        f"live env names match the contract ({len(warnings)} warning(s), {len(optional_missing)} optional name(s) left to their default)"
    )


if __name__ == "__main__":
    app()
