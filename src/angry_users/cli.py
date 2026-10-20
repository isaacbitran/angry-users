"""Command line: `angry-users run ...` and `angry-users personas`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .backends import BackendError, make_backend
from .personas import PersonaError, load_personas
from .report import write_reports
from .runner import RunConfig, run_all
from .targets import TargetError, make_target

EPILOG = """examples:
  angry-users run --target http://localhost:8765/chat --describe "A bookstore assistant"
  angry-users run --target "python my_agent.py" --adapter cmd --backend claude-cli
  angry-users run --target https://api.openai.com/v1 --adapter openai --target-model gpt-4o-mini \\
      --target-api-key-env OPENAI_API_KEY --system-prompt-file prompt.txt
  angry-users personas
"""


def _read_opt(text: str | None, path: str | None) -> str | None:
    if path:
        return Path(path).read_text()
    return text


def _headers(raw: list[str]) -> dict[str, str]:
    out = {}
    for h in raw:
        if ":" not in h:
            raise SystemExit(f"bad --header {h!r}; use 'Name: value'")
        k, v = h.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="angry-users", description="Persona agents red-team your AI agent before your users do.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG)
    p.add_argument("--version", action="version", version=f"angry-users {__version__}")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="run personas against a target and write a report",
                       formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG)
    t = r.add_argument_group("target")
    t.add_argument("--target", required=True, help="URL (http/openai adapters) or shell command (cmd adapter)")
    t.add_argument("--adapter", default="auto", choices=["auto", "http", "openai", "cmd"],
                   help="auto: http for URLs (openai if --target-model is set), cmd otherwise")
    t.add_argument("--header", action="append", default=[], help="extra HTTP header 'Name: value' (repeatable)")
    t.add_argument("--reply-field", default="reply", help="dot path to the reply in the http adapter's JSON (default reply)")
    t.add_argument("--target-model", help="model name for the openai adapter")
    t.add_argument("--target-api-key-env", help="env var holding the openai adapter's API key")
    t.add_argument("--system-prompt-file", help="openai adapter: system prompt of the agent under test")
    t.add_argument("--timeout", type=float, default=120, help="seconds per target reply (default 120)")

    c = r.add_argument_group("what the agent is")
    c.add_argument("--describe", help="what the agent does and what is out of scope (helps attackers and judge)")
    c.add_argument("--describe-file", help="file with the description")
    c.add_argument("--facts-file", help="ground-truth facts (text/JSON) the judge checks claims against")
    c.add_argument("--personas-see-facts", action="store_true",
                   help="also show the facts to the personas, so skeptics can ask about real items and check answers")

    a = r.add_argument_group("attack")
    a.add_argument("--personas", default="all", help="'all' or comma-separated ids (see `angry-users personas`)")
    a.add_argument("--personas-dir", action="append", default=[], help="extra directory of persona YAML files")
    a.add_argument("--turns", type=int, default=4, help="persona messages per conversation (default 4)")
    a.add_argument("--repeats", type=int, default=1, help="conversations per persona (default 1)")
    a.add_argument("--concurrency", type=int, default=4, help="conversations in parallel (default 4)")

    m = r.add_argument_group("models")
    m.add_argument("--backend", default="anthropic", choices=["anthropic", "claude-cli", "mock"],
                   help="anthropic (ANTHROPIC_API_KEY), claude-cli (shells out to `claude -p`), mock (offline, no real judging)")
    m.add_argument("--judge", default="claude-haiku-4-5", help="judge model (default claude-haiku-4-5)")
    m.add_argument("--attacker", default=None, help="persona model (default: same as --judge)")

    o = r.add_argument_group("output")
    o.add_argument("--out", default="angry-users-report", help="output directory (default ./angry-users-report)")
    o.add_argument("--max-fail-rate", type=float, default=None,
                   help="exit 1 if the fail rate is above this (0-1), for CI")
    o.add_argument("-q", "--quiet", action="store_true")

    ps = sub.add_parser("personas", help="list available personas")
    ps.add_argument("--personas-dir", action="append", default=[])
    return p


def cmd_personas(args) -> int:
    for p in load_personas("all", args.personas_dir):
        probes = ", ".join(p.probes)
        print(f"{p.id:<18} {p.name:<24} {probes}")
        print(f"{'':<18} {p.summary}")
    return 0


def cmd_run(args, backend_factory=make_backend) -> int:
    personas = load_personas(args.personas, args.personas_dir)
    system_prompt = Path(args.system_prompt_file).read_text() if args.system_prompt_file else None
    target = make_target(args.target, args.adapter, headers=_headers(args.header), reply_field=args.reply_field,
                         model=args.target_model, api_key_env=args.target_api_key_env,
                         system_prompt=system_prompt, timeout=args.timeout)
    backend = backend_factory(args.backend)
    cfg = RunConfig(
        turns=max(1, args.turns),
        attacker_model=args.attacker or args.judge,
        judge_model=args.judge,
        agent_description=_read_opt(args.describe, args.describe_file) or "",
        facts=_read_opt(None, args.facts_file),
        personas_see_facts=args.personas_see_facts,
        concurrency=args.concurrency,
        repeats=max(1, args.repeats),
    )
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))
    if args.backend == "mock":
        log("note: --backend mock sends canned messages and a canned judge; results are NOT a real red-team.")
    log(f"angry-users: {len(personas)} personas x {cfg.repeats} x {cfg.turns} turns -> {target.label}")

    def done(conv):
        d = conv.to_dict()
        mark = {"fail": "FAIL", "pass": "pass", "error": "ERR "}[d["verdict"]]
        extra = f" {d['category']} ({d['severity']})" if d["verdict"] == "fail" else ""
        if d["verdict"] == "error":
            extra = f" {d['summary'][:120]}"
        log(f"  [{mark}] {d['persona_name']}{extra}")

    results = run_all(personas, target, backend, cfg, on_done=done)
    jpath, hpath = write_reports(results, args.out)
    s = results["summary"]
    rate = "n/a" if s["fail_rate"] is None else f"{s['fail_rate']:.0%}"
    print(f"{s['failed']}/{s['judged']} conversations failed ({rate}); {s['errors']} errors. Report: {hpath}")
    if s["findings_by_category"]:
        print("  " + ", ".join(f"{k} {v}" for k, v in s["findings_by_category"].items()))
    if args.max_fail_rate is not None and s["fail_rate"] is not None and s["fail_rate"] > args.max_fail_rate:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "run":
            return cmd_run(args)
        if args.cmd == "personas":
            return cmd_personas(args)
    except (PersonaError, TargetError, BackendError) as e:
        print(f"angry-users: error: {e}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
