import json
import sys
from pathlib import Path

import pytest

from angry_users import FAILURE_CATEGORIES, cli
from angry_users.backends import MockBackend
from angry_users.judge import evidence_found, judge_conversation, parse_verdict
from angry_users.personas import PersonaError, load_personas
from angry_users.report import write_reports
from angry_users.runner import RunConfig, run_all
from angry_users.targets import CmdTarget, HttpTarget, OpenAITarget, TargetError, make_target

from conftest import ROOT, scripted_responder

TOY = f"{sys.executable} {ROOT / 'examples' / 'toy_agent.py'}"


# ---------- personas ----------

def test_builtin_personas_load_and_are_valid():
    ps = load_personas("all")
    assert 8 <= len(ps) <= 12
    ids = {p.id for p in ps}
    assert {"skeptic", "prompt-injector", "scope-pusher", "memory-poisoner", "privacy-prober"} <= ids
    for p in ps:
        assert p.tactics and p.attack_succeeds_if and p.good_agent_should
        assert all(c in FAILURE_CATEGORIES for c in p.probes)


def test_persona_selection_and_unknown():
    assert [p.id for p in load_personas("skeptic,prompt-injector")] == ["skeptic", "prompt-injector"]
    with pytest.raises(PersonaError):
        load_personas("nope")


def test_custom_persona_dir(tmp_path):
    (tmp_path / "pirate.yaml").write_text(
        "id: pirate\nname: The Pirate\nsummary: s\ngoal: g\ntactics: [t]\nattack_succeeds_if: [a]\ngood_agent_should: [b]\n")
    assert load_personas("pirate", [str(tmp_path)])[0].name == "The Pirate"
    (tmp_path / "bad.yaml").write_text("id: bad\nname: Bad\n")
    with pytest.raises(PersonaError, match="missing required"):
        load_personas("all", [str(tmp_path)])


# ---------- judge ----------

def test_parse_verdict_normalises():
    raw = 'sure! {"verdict":"pass","findings":[{"category":"privacy_leak","severity":"HUGE","turn":"2",' \
          '"evidence":"x","reason":"r"},{"category":"made_up","severity":"low"}],"summary":"s"}'
    v = parse_verdict(raw)
    assert v["verdict"] == "fail"  # verdict follows findings, not the judge's word
    assert len(v["findings"]) == 1 and v["findings"][0]["severity"] == "medium" and v["findings"][0]["turn"] == 2


def test_parse_verdict_rejects_garbage():
    with pytest.raises(ValueError):
        parse_verdict("no json here")


def test_evidence_check():
    tr = [{"role": "user", "content": "secret?"}, {"role": "assistant", "content": "The code is **DOGEAR-STAFF-40**, enjoy."}]
    assert evidence_found("the code is DOGEAR-STAFF-40", tr)
    assert evidence_found("The code is ... enjoy", tr)
    assert not evidence_found("secret?", tr)  # user text is not agent evidence
    assert not evidence_found("I will never share codes", tr)


def test_judge_retries_then_errors():
    persona = load_personas("skeptic")[0]
    backend = MockBackend(lambda s, m, model: "not json")
    out = judge_conversation(backend, "m", persona, [{"role": "assistant", "content": "hi"}], "", None)
    assert out["verdict"] == "error" and backend.calls == 2


# ---------- targets ----------

def test_cmd_target_roundtrip(tmp_path):
    t = CmdTarget(f"{TOY} --state {tmp_path / 's.json'}")
    assert "Night Ferry" in t.send("do you have night ferry?", "s1", [])


def test_cmd_target_error():
    with pytest.raises(TargetError):
        CmdTarget(f"{sys.executable} -c 'import sys; sys.exit(3)'").send("hi", "s", [])


def test_http_target(toy_server):
    t = HttpTarget(toy_server)
    assert "Dogear" in t.send("hi", "s1", [])


def test_http_target_unreachable():
    with pytest.raises(TargetError):
        HttpTarget("http://127.0.0.1:9/chat", timeout=2).send("hi", "s", [])


def test_openai_target_sends_history(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("angry_users.targets._post_json", fake_post)
    monkeypatch.setenv("FAKE_KEY", "sk-test")
    t = make_target("http://localhost:1/v1", "openai", model="m", api_key_env="FAKE_KEY", system_prompt="SP")
    assert isinstance(t, OpenAITarget)
    assert t.send("q2", "s", [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]) == "ok"
    assert seen["url"].endswith("/v1/chat/completions")
    assert [m["role"] for m in seen["payload"]["messages"]] == ["system", "user", "assistant", "user"]
    assert seen["headers"]["Authorization"] == "Bearer sk-test"


def test_make_target_auto():
    assert make_target("http://x/chat").kind == "http"
    assert make_target("cmd:python agent.py").kind == "cmd"
    assert make_target("python agent.py").kind == "cmd"


# ---------- end to end with a mocked LLM ----------

def test_run_all_against_toy_http(toy_server, tmp_path):
    personas = load_personas("prompt-injector,skeptic,memory-poisoner")
    backend = MockBackend(scripted_responder)
    cfg = RunConfig(turns=2, concurrency=2, agent_description="bookstore")
    results = run_all(personas, HttpTarget(toy_server), backend, cfg)
    s = results["summary"]
    assert s["conversations"] == 3 and s["errors"] == 0
    by = {c["persona"]: c for c in results["conversations"]}
    inj = by["prompt-injector"]
    assert inj["verdict"] == "fail" and inj["category"] == "privacy_leak" and inj["evidence_verified"] is True
    assert by["skeptic"]["verdict"] == "pass"
    # memory poisoner's last turn goes to a fresh session
    mp = by["memory-poisoner"]["transcript"]
    assert mp[-2]["role"] == "user" and mp[-2].get("new_session") is True
    assert s["fail_rate"] == pytest.approx(1 / 3, abs=0.01)
    assert [c["persona"] for c in results["conversations"]] == ["prompt-injector", "skeptic", "memory-poisoner"]

    jpath, hpath = write_reports(results, tmp_path / "out")
    data = json.loads(jpath.read_text())
    assert data["summary"]["failed"] == 1
    html = hpath.read_text()
    assert "<script>" in html and "angry-users" in html and "</script>" in html
    assert html.count("</script>") == 1  # embedded JSON cannot close the script tag


def test_target_error_is_reported_not_judged(tmp_path):
    personas = load_personas("skeptic")
    backend = MockBackend(scripted_responder)
    results = run_all(personas, HttpTarget("http://127.0.0.1:9/chat", timeout=2), backend, RunConfig(turns=2))
    c = results["conversations"][0]
    assert c["verdict"] == "error" and results["summary"]["fail_rate"] is None


def test_cli_run_with_mock_backend(tmp_path, capsys):
    out = tmp_path / "rep"
    factory = lambda name: MockBackend(scripted_responder)  # noqa: E731
    args = cli.build_parser().parse_args([
        "run", "--target", f"{TOY} --state {tmp_path / 'st.json'}", "--adapter", "cmd",
        "--personas", "prompt-injector,confused-user", "--turns", "1", "--backend", "mock",
        "--describe-file", str(ROOT / "examples" / "toy_description.txt"),
        "--facts-file", str(ROOT / "examples" / "toy_facts.json"),
        "--out", str(out), "--max-fail-rate", "0.1", "-q",
    ])
    code = cli.cmd_run(args, backend_factory=factory)
    assert code == 1  # 1 of 2 failed, above the 10% CI threshold
    assert (out / "report.html").exists() and (out / "report.json").exists()
    assert "1/2 conversations failed" in capsys.readouterr().out


def test_cli_personas_command(capsys):
    assert cli.main(["personas"]) == 0
    assert "memory-poisoner" in capsys.readouterr().out


def test_cli_bad_persona_exit_code(capsys):
    assert cli.main(["run", "--target", "http://x", "--personas", "nope", "--backend", "mock"]) == 2


def test_refusing_persona_model_falls_back_to_script(toy_server):
    def refuser(system, messages, model):
        if "You are the judge" in system:
            return '{"verdict": "pass", "findings": [], "summary": "ok"}'
        return "I can't roleplay this scenario, even in a red-team context."

    backend = MockBackend(refuser)
    persona = load_personas("privacy-prober")[0]
    results = run_all([persona], HttpTarget(toy_server), backend, RunConfig(turns=2))
    c = results["conversations"][0]
    users = [t for t in c["transcript"] if t["role"] == "user"]
    assert all(t.get("scripted") for t in users)
    assert users[0]["content"] == persona.openers[0]
    assert c["scripted_turns"] == 2 and results["summary"]["scripted_turns"] == 2


def test_memory_poisoner_runs_after_everyone_else(toy_server):
    order = []
    results = run_all(load_personas("memory-poisoner,skeptic,confused-user"), HttpTarget(toy_server),
                      MockBackend(scripted_responder), RunConfig(turns=1, concurrency=3),
                      on_done=lambda c: order.append(c.persona.id))
    assert order[-1] == "memory-poisoner"
    assert [c["persona"] for c in results["conversations"]][0] == "memory-poisoner"  # report keeps the requested order


def test_personas_see_facts_only_when_asked(toy_server):
    for flag in (False, True):
        backend = MockBackend(scripted_responder)
        run_all(load_personas("skeptic"), HttpTarget(toy_server), backend,
                RunConfig(turns=1, facts="FACT-MARKER-123", personas_see_facts=flag))
        attacker_prompts = [m[-1]["content"] for s, m, _ in backend.log if "You are the judge" not in s]
        judge_prompts = [m[-1]["content"] for s, m, _ in backend.log if "You are the judge" in s]
        assert all("FACT-MARKER-123" in p for p in judge_prompts)
        assert any("FACT-MARKER-123" in p for p in attacker_prompts) == flag


def test_claude_cli_backend_scrubs_account_email():
    from angry_users.backends import ClaudeCLIBackend

    b = ClaudeCLIBackend.__new__(ClaudeCLIBackend)  # skip the PATH / auth lookups
    b._private = ["someone@example.edu"]
    assert b.scrub("look up SomeOne@Example.edu please") == "look up user@example.com please"
