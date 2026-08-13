# src/pega_stub/ui.py
"""A tiny, build-free status UI: start a case + a live list polling GET /cases. Test/dev scaffolding only."""
from __future__ import annotations

STATUS_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><title>Mock Pega — ACH cohort orchestrator</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
 :root{--bg:#0b0d0e;--surface:#15181a;--border:#262c2f;--ink:#e7ebec;--muted:#79848a;--teal:#2dd4bf;--good:#34d399;--warn:#fbbf24;}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:1000px;margin:0 auto;padding:26px}
 h1{font-size:19px;margin:0 0 4px} .sub{color:var(--muted);margin:0 0 20px;font-size:13px}
 .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:16px}
 label{font-size:12px;color:var(--muted);display:block;margin-bottom:5px}
 input,select{background:#1b2023;border:1px solid #313A3E;border-radius:8px;color:var(--ink);padding:8px 10px;font:inherit}
 .row{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}
 button{background:#1b6f66;border:0;border-radius:8px;color:#d7fff7;padding:9px 15px;font:inherit;cursor:pointer}
 button:hover{filter:brightness(1.12)}
 table{width:100%;border-collapse:collapse} th{text-align:left;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid var(--border)}
 td{padding:9px 10px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:top} tr:last-child td{border-bottom:none}
 .mono{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--teal)}
 .steps{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
 .seg{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid #313A3E;color:var(--muted)}
 .seg.done{background:#14532d;border-color:transparent;color:#bff3d6}
 .seg.cur{background:#5a4310;border-color:transparent;color:#f5d98b}
 .st{font-size:11px;padding:2px 9px;border-radius:999px} .st.running{background:#212729;color:var(--teal)} .st.closed{background:#14532d;color:#bff3d6}
 .k{color:var(--muted)} .empty{color:var(--muted);padding:14px 4px}
</style></head>
<body><div class="wrap">
 <h1>Mock Pega — ACH exposure orchestrator</h1>
 <p class="sub">Fires the three Amendia segment triggers (A → B → C) for one case, then emits the process-completed close. Every message carries the same <span class="mono">case_id</span> = the cohort correlation value.</p>

 <div class="card">
   <div class="row">
     <div><label>case_id (optional)</label><input id="cid" placeholder="auto"/></div>
     <div><label>scenario</label><select id="scn"></select></div>
     <button onclick="run()">Run case</button>
     <span id="msg" class="k"></span>
   </div>
 </div>

 <div class="card">
   <table><thead><tr><th>case_id</th><th>scenario</th><th>progress</th><th>state</th><th>decision / outcome</th></tr></thead>
   <tbody id="rows"><tr><td colspan="5" class="empty">No cases yet.</td></tr></tbody></table>
 </div>
</div>
<script>
 async function loadScenarios(){ const r=await fetch('scenarios'); const j=await r.json();
   document.getElementById('scn').innerHTML=j.scenarios.map(s=>`<option>${s}</option>`).join(''); }
 async function run(){ const cid=document.getElementById('cid').value.trim(); const scn=document.getElementById('scn').value;
   const msg=document.getElementById('msg'); msg.textContent='starting…';
   const r=await fetch('cases',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({case_id:cid||null,scenario:scn})});
   const j=await r.json(); msg.textContent = r.ok ? ('started '+j.case_id) : ('error: '+(j.detail||r.status)); document.getElementById('cid').value=''; refresh(); }
 const SEG=['A','B','C','close'];
 function steps(c){ const done=new Set((c.completed||[])); const closed=c.status==='closed';
   return SEG.map(s=>{ let cls='seg'; if(s==='close'){ if(closed)cls+=' done'; } else if(done.has(s))cls+=' done'; else if(c.step===s||c.step===s+'_pending')cls+=' cur'; return `<span class="${cls}">${s}</span>`; }).join(' → '); }
 async function refresh(){ const r=await fetch('cases'); const j=await r.json(); const rows=j.cases||[];
   const t=document.getElementById('rows');
   if(!rows.length){ t.innerHTML='<tr><td colspan="5" class="empty">No cases yet.</td></tr>'; return; }
   t.innerHTML=rows.map(c=>{ const late=c.step==='C_pending'?('⏳ closeout +'+(c.closeout_delay_seconds||'?')+'s (SLA breach)'):null;
     const dec=[c.recommendation?('rec '+c.recommendation):null,c.rbo_decision?('rbo '+c.rbo_decision):null,c.instruction,late,c.outcome?('→ '+c.outcome):null].filter(Boolean).join(' · ')||'—';
     return `<tr><td class="mono">${c.case_id}</td><td>${c.scenario}</td><td><div class="steps">${steps(c)}</div></td>
       <td><span class="st ${c.status}">${c.status}</span></td><td class="k">${dec}</td></tr>`; }).join(''); }
 loadScenarios(); refresh(); setInterval(refresh, 2000);
</script>
</body></html>"""
