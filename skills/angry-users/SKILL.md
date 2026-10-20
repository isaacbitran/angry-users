---
name: angry-users
description: Red-team the user's own AI agent or chatbot with adversarial personas (skeptic, prompt injector, scope pusher, memory poisoner, privacy prober, and more) using the angry-users CLI, then summarize the failures with evidence and suggest fixes. Use when the user asks to red-team, stress-test, or find failure modes in an agent, chatbot, assistant, or LLM endpoint they build or operate.
---

# angry-users: red-team an agent with persona attackers

angry-users runs multi-turn conversations between adversarial personas and the user's agent, grades each one
with an LLM judge, and writes `report.json` and `report.html`. Your job: point it at the agent, run it,
and turn the report into a short, evidence-backed list of what to fix.

## 1. Find the target

Work out how to talk to the agent. Look in the repo for a chat endpoint, a CLI, or the system prompt.

| The agent is... | Flags |
|---|---|
| An HTTP endpoint taking `{"message", "session_id"}` and returning `{"reply"}` | `--target http://host/chat` (use `--reply-field a.b` if the reply is nested, `--header "Authorization: Bearer ..."` for auth) |
| A raw model plus a system prompt, behind an OpenAI-compatible API | `--adapter openai --target <base_url> --target-model <model> --target-api-key-env <ENV> --system-prompt-file prompt.txt` |
| A script or CLI | `--adapter cmd --target "python agent.py"` (message on stdin, reply on stdout; `ANGRY_USERS_SESSION_ID` and `ANGRY_USERS_HISTORY` env vars) |

If the endpoint does not match any adapter, write a 10-line wrapper script and use the cmd adapter.
If the agent is not running, start it locally first (in the background) and stop it when done.

Ask the user before targeting anything in production or anything with side effects (sending email,
placing orders, writing to shared memory or a real database). Prefer a local or staging copy.

## 2. Describe the agent

Write a 3 to 5 line description to a file: what it does, what is in scope, what is out of scope, what it
must never share. Get this from the system prompt or README. If there is ground truth (a catalog, a price
list, a policy doc, a small table of real numbers), put it in a facts file so the judge can catch invented
or mislabeled numbers.

## 3. Run

Pick the backend:
- `ANTHROPIC_API_KEY` is set: default backend (`--backend anthropic`).
- Otherwise, if the `claude` CLI is on PATH: `--backend claude-cli` (uses the user's Claude subscription).

Start small, then widen:

```bash
uvx --from git+https://github.com/isaacbitran/angry-users angry-users run \
  --target http://localhost:8000/chat \
  --describe-file /tmp/agent.txt --facts-file /tmp/facts.json \
  --personas all --turns 3 --backend claude-cli --out angry-users-report
```

`angry-users personas` lists the personas. Use `--personas a,b` to rerun specific ones, `--repeats 2` to
check whether a failure is stable, `--personas-see-facts` to let the skeptic personas check answers against
the facts, and `--personas-dir ./my-personas` for custom YAML personas.

A full run is about 4 to 5 LLM calls per persona (turns + judge). Tell the user the rough count before a large run.

## 4. Summarize

Read `angry-users-report/report.json` (not the HTML). Report to the user:

1. One line: `X of Y conversations failed`, plus the top categories.
2. The 3 to 6 most severe failures, each with: persona, category, severity, the exact quoted evidence,
   and a concrete fix (a system-prompt rule, an input filter, a tool-side check, a memory-write rule).
   Group repeats of the same root cause.
3. Caveats: findings with `evidence_verified: false` (quote not found in the transcript) are suspect; say so.
   Turns marked `scripted` mean the persona model refused and a canned message was sent.
   LLM judges are noisy: re-read the transcript before calling something a bug, and never call a pass
   "safe".
4. The path to `report.html` for the full transcripts.

Do not paste whole transcripts into chat. Do not commit the report if it contains secrets or user data the
agent leaked.
