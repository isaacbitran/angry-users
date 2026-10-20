"""Write report.json and a single-file, dependency-free report.html."""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import FAILURE_CATEGORIES


def write_reports(results: dict, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jpath = out / "report.json"
    hpath = out / "report.html"
    jpath.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    hpath.write_text(render_html(results))
    return jpath, hpath


def render_html(results: dict) -> str:
    data = json.dumps(results, ensure_ascii=False).replace("</", "<\\/")
    cats = json.dumps(FAILURE_CATEGORIES).replace("</", "<\\/")
    title = f"angry-users report: {html.escape(results['target']['label'])}"
    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", data).replace("__CATS__", cats)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0d0f12;--panel:#151920;--panel2:#1b2029;--line:#262c37;--text:#e6e9ef;--dim:#8b94a5;
--red:#ff5c5c;--amber:#ffb347;--green:#3ddc97;--blue:#6aa8ff;--violet:#b48cff;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
h1 span{color:var(--red)}
.sub{color:var(--dim);font-size:13px;margin-bottom:24px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:28px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.v.bad{color:var(--red)}.v.good{color:var(--green)}
.bars{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:20px}
.bars h2{font-size:13px;color:var(--dim);margin:0 0 10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.bar{display:grid;grid-template-columns:210px 1fr 40px;gap:10px;align-items:center;margin:6px 0}
.bar .track{background:var(--panel2);height:10px;border-radius:5px;overflow:hidden}
.bar .fill{background:var(--red);height:100%}
.bar .n{text-align:right;font-variant-numeric:tabular-nums;color:var(--dim)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.tools input,.tools select{background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:7px 10px;font:inherit}
.tools input{flex:1;min-width:180px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;background:var(--panel)}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--panel2);color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.05em;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--text)}
th.sorted::after{content:" \25BE"}th.sorted.asc::after{content:" \25B4"}
tr.row{cursor:pointer}tr.row:hover td{background:#1a1f28}
td.ev{color:#cfd5df;max-width:420px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.fail{background:rgba(255,92,92,.15);color:var(--red)}
.pill.pass{background:rgba(61,220,151,.13);color:var(--green)}
.pill.error{background:rgba(139,148,165,.18);color:var(--dim)}
.sev-critical{color:var(--red);font-weight:700}.sev-high{color:#ff8a65}.sev-medium{color:var(--amber)}.sev-low{color:var(--dim)}
.cat{font-family:var(--mono);font-size:12px;color:var(--violet)}
.unv{color:var(--amber);font-size:11px;margin-left:4px}
tr.detail td{background:#11151b;padding:0}
.detail-inner{padding:16px 18px}
.findings{margin:0 0 14px;padding:0;list-style:none}
.findings li{border-left:3px solid var(--red);padding:6px 10px;margin:6px 0;background:var(--panel2);border-radius:0 6px 6px 0}
.msg{margin:10px 0;padding:10px 12px;border-radius:8px;white-space:pre-wrap;word-wrap:break-word;max-width:900px}
.msg .who{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin-bottom:4px}
.msg.user{background:#1d1a24;border:1px solid #2d2640}
.msg.assistant{background:#16202b;border:1px solid #22324a;margin-left:24px}
.msg.error{background:#2a1515;border:1px solid #4a2222}
.msg.flag{outline:2px solid var(--red)}
mark{background:rgba(255,92,92,.28);color:inherit;border-radius:3px;padding:0 2px}
.newsess{color:var(--amber);font-size:11px;margin-left:6px}
.meta{color:var(--dim);font-size:12px;margin-top:24px}
.meta code{font-family:var(--mono)}
.note{color:var(--dim);font-size:12px;margin:-8px 0 18px}
@media (max-width:640px){.bar{grid-template-columns:120px 1fr 30px}.msg.assistant{margin-left:8px}}
</style>
</head>
<body>
<main>
<h1><span>angry-users</span> red-team report</h1>
<div class="sub" id="sub"></div>
<div class="cards" id="cards"></div>
<p class="note">LLM judges are noisy. A failure here is a lead to read, not a verdict; a pass is not a safety certificate. Evidence marked "unverified" was not found word-for-word in the agent's replies.</p>
<div class="bars" id="bars"></div>
<div class="tools">
  <input id="q" placeholder="Filter by persona, category, evidence...">
  <select id="fv"><option value="">All verdicts</option><option>fail</option><option>pass</option><option>error</option></select>
</div>
<div class="tablewrap"><table id="t">
<thead><tr>
<th data-k="persona_name">Persona</th><th data-k="verdict">Verdict</th><th data-k="category">Category</th>
<th data-k="severity">Severity</th><th data-k="evidence">Evidence</th><th data-k="turns">Turns</th><th data-k="seconds">Time</th>
</tr></thead><tbody></tbody></table></div>
<div class="meta" id="meta"></div>
</main>
<script>
const R = __DATA__;
const CATS = __CATS__;
const SEV = {critical:4, high:3, medium:2, low:1};
const VER = {fail:2, error:1, pass:0};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const s = R.summary, c = R.config;
document.getElementById("sub").textContent = `Target: ${R.target.label} (${R.target.kind}) | ${R.started_at} | backend ${c.backend}, attacker ${c.attacker_model}, judge ${c.judge_model}, ${c.turns} turns`;
const pct = s.fail_rate == null ? "n/a" : Math.round(s.fail_rate * 100) + "%";
document.getElementById("cards").innerHTML = [
  ["Conversations", s.conversations, ""],
  ["Failed", s.failed, s.failed ? "bad" : "good"],
  ["Passed", s.passed, "good"],
  ["Fail rate", pct, s.fail_rate ? "bad" : "good"],
  ["Errors", s.errors, ""],
].map(([k, v, cls]) => `<div class="card"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`).join("");
const bc = s.findings_by_category, maxc = Math.max(1, ...Object.values(bc));
document.getElementById("bars").innerHTML = "<h2>Findings by category</h2>" + (Object.keys(bc).length ? Object.entries(bc).map(([k, n]) =>
  `<div class="bar" title="${esc(CATS[k] || "")}"><span class="cat">${esc(k)}</span><div class="track"><div class="fill" style="width:${100*n/maxc}%"></div></div><span class="n">${n}</span></div>`).join("") : `<div style="color:var(--dim)">No findings.</div>`);
document.getElementById("meta").innerHTML = `${s.scripted_turns ? `${s.scripted_turns} persona turns were scripted fallbacks (the persona model refused) | ` : ""}${s.llm_calls} LLM calls${s.llm_cost_usd ? `, about $${s.llm_cost_usd.toFixed(2)}` : ""} | ${R.duration_s} s | angry-users ${R.version} | <code>report.json</code> has the same data.`;

let sortK = "verdict", asc = false, open = new Set();
function val(r, k) {
  if (k === "severity") return SEV[r.severity] || 0;
  if (k === "verdict") return VER[r.verdict] * 10 + (SEV[r.severity] || 0);
  return r[k] ?? "";
}
function highlight(text, quotes) {
  let h = esc(text);
  for (const q of quotes) { const e = esc(q); if (e.length > 3 && h.includes(e)) h = h.split(e).join(`<mark>${e}</mark>`); }
  return h;
}
function detail(r) {
  const quotes = r.findings.map(f => f.evidence).filter(Boolean);
  const flagged = new Set(r.findings.map(f => f.turn));
  const f = r.findings.length ? `<ul class="findings">${r.findings.map(f =>
    `<li><span class="sev-${f.severity}">${f.severity}</span> <span class="cat">${esc(f.category)}</span> (agent turn ${f.turn})${f.evidence_verified === false ? '<span class="unv">evidence unverified</span>' : ""}<br>${esc(f.reason)}</li>`).join("")}</ul>` : "";
  let at = 0;
  const msgs = r.transcript.map(t => {
    if (t.role === "assistant") at++;
    const who = t.role === "user" ? `${esc(r.persona_name)}${t.new_session ? '<span class="newsess">new session</span>' : ""}${t.scripted ? '<span class="newsess" title="The persona model refused; a scripted message from the persona file was sent instead">scripted</span>' : ""}` : t.role === "assistant" ? `Agent, turn ${at}${t.latency_s != null ? ` (${t.latency_s} s)` : ""}` : "Target error";
    const cls = t.role + (t.role === "assistant" && flagged.has(at) ? " flag" : "");
    return `<div class="msg ${cls}"><div class="who">${who}</div>${t.role === "assistant" ? highlight(t.content, quotes) : esc(t.content)}</div>`;
  }).join("");
  return `<div class="detail-inner"><div style="color:var(--dim);margin-bottom:8px">${esc(r.persona_summary)}</div>${r.summary ? `<p><b>Judge:</b> ${esc(r.summary)}</p>` : ""}${f}${msgs}</div>`;
}
function render() {
  const q = document.getElementById("q").value.toLowerCase(), fv = document.getElementById("fv").value;
  let rows = R.conversations.filter(r => (!fv || r.verdict === fv) &&
    (!q || [r.persona_name, r.persona, r.category, r.evidence, r.summary].join(" ").toLowerCase().includes(q)));
  rows.sort((a, b) => { const x = val(a, sortK), y = val(b, sortK); return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1); });
  document.querySelectorAll("th").forEach(th => { th.classList.toggle("sorted", th.dataset.k === sortK); th.classList.toggle("asc", th.dataset.k === sortK && asc); });
  document.querySelector("#t tbody").innerHTML = rows.map(r => `
    <tr class="row" data-id="${esc(r.id)}">
      <td><b>${esc(r.persona_name)}</b>${r.repeat > 1 ? ` #${r.repeat}` : ""}</td>
      <td><span class="pill ${r.verdict}">${r.verdict}</span></td>
      <td><span class="cat">${esc(r.category || "")}</span></td>
      <td class="sev-${r.severity || ""}">${esc(r.severity || "")}</td>
      <td class="ev">${r.evidence ? "&ldquo;" + esc(r.evidence) + "&rdquo;" : `<span style="color:var(--dim)">${esc(r.summary).slice(0, 160)}</span>`}${r.evidence_verified === false ? '<span class="unv">unverified</span>' : ""}</td>
      <td>${r.turns}</td><td>${r.seconds}s</td>
    </tr>${open.has(r.id) ? `<tr class="detail"><td colspan="7">${detail(r)}</td></tr>` : ""}`).join("");
}
document.querySelector("#t thead").addEventListener("click", e => {
  const k = e.target.dataset.k; if (!k) return;
  if (sortK === k) asc = !asc; else { sortK = k; asc = k === "persona_name" || k === "category"; }
  render();
});
document.querySelector("#t tbody").addEventListener("click", e => {
  const tr = e.target.closest("tr.row"); if (!tr) return;
  const id = tr.dataset.id; open.has(id) ? open.delete(id) : open.add(id); render();
});
document.getElementById("q").addEventListener("input", render);
document.getElementById("fv").addEventListener("change", render);
render();
</script>
</body>
</html>
"""
