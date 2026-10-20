"""Load persona YAML files (built-in ones plus any directory the user passes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import FAILURE_CATEGORIES

REQUIRED = ["id", "name", "summary", "goal", "tactics", "attack_succeeds_if", "good_agent_should"]


class PersonaError(ValueError):
    pass


@dataclass
class Persona:
    id: str
    name: str
    summary: str
    goal: str
    tactics: list[str]
    attack_succeeds_if: list[str]
    good_agent_should: list[str]
    probes: list[str] = field(default_factory=list)
    openers: list[str] = field(default_factory=list)
    new_session_last_turn: bool = False
    run_last: bool = False
    source: str = ""

    def brief(self) -> str:
        lines = [
            f"Persona: {self.name} ({self.id})",
            f"Who you are: {self.summary}",
            f"Your goal: {self.goal}",
            "Tactics:",
            *[f"- {t}" for t in self.tactics],
            "The attack succeeds if the agent:",
            *[f"- {t}" for t in self.attack_succeeds_if],
        ]
        if self.openers:
            lines.append("Example openers (adapt, don't copy):")
            lines.extend(f"- {o}" for o in self.openers)
        return "\n".join(lines)

    def attacker_brief(self) -> str:
        """What the simulated user model sees: who to play and how, without judging language."""
        lines = [
            f"Character: {self.name}",
            f"Who they are: {self.summary}",
            f"What they are trying to find out: {self.goal}",
            "How they behave:",
            *[f"- {t}" for t in self.tactics],
        ]
        if self.openers:
            lines.append("Example messages (adapt, don't copy):")
            lines.extend(f"- {o}" for o in self.openers)
        return "\n".join(lines)


def builtin_dir() -> Path:
    here = Path(__file__).resolve().parent
    packaged = here / "personas"
    if packaged.is_dir():
        return packaged
    repo = here.parent.parent / "personas"  # editable / source checkout
    if repo.is_dir():
        return repo
    raise PersonaError("built-in personas directory not found")


def _load_file(path: Path) -> Persona:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise PersonaError(f"{path}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PersonaError(f"{path}: expected a mapping")
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise PersonaError(f"{path}: missing required fields: {', '.join(missing)}")
    for key in ("tactics", "attack_succeeds_if", "good_agent_should", "probes", "openers"):
        if key in data and not isinstance(data[key], list):
            raise PersonaError(f"{path}: {key} must be a list")
    bad = [p for p in data.get("probes", []) if p not in FAILURE_CATEGORIES]
    if bad:
        raise PersonaError(f"{path}: unknown probes {bad}; valid: {sorted(FAILURE_CATEGORIES)}")
    return Persona(
        id=str(data["id"]),
        name=str(data["name"]),
        summary=str(data["summary"]).strip(),
        goal=str(data["goal"]).strip(),
        tactics=[str(x) for x in data["tactics"]],
        attack_succeeds_if=[str(x) for x in data["attack_succeeds_if"]],
        good_agent_should=[str(x) for x in data["good_agent_should"]],
        probes=list(data.get("probes", [])),
        openers=[str(x) for x in data.get("openers", [])],
        new_session_last_turn=bool(data.get("new_session_last_turn", False)),
        run_last=bool(data.get("run_last", False)),
        source=str(path),
    )


def load_personas(selection: str = "all", extra_dirs: list[str] | None = None) -> list[Persona]:
    """selection: "all" or a comma-separated list of persona ids."""
    dirs = [builtin_dir()] + [Path(d) for d in (extra_dirs or [])]
    found: dict[str, Persona] = {}
    for d in dirs:
        if not d.is_dir():
            raise PersonaError(f"persona directory not found: {d}")
        for path in sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml"))):
            p = _load_file(path)
            found[p.id] = p  # later dirs override built-ins with the same id
    if selection.strip() == "all":
        return list(found.values())
    wanted = [s.strip() for s in selection.split(",") if s.strip()]
    unknown = [w for w in wanted if w not in found]
    if unknown:
        raise PersonaError(f"unknown persona(s): {', '.join(unknown)}. Available: {', '.join(found)}")
    return [found[w] for w in wanted]
