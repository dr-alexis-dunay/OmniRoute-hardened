"""Self-contained tests for orchestrator.py using a local fake OpenAI-compatible server.
Run:  python3 -I examples/multi-agent/test_orchestrator.py
"""
import json, os, subprocess, sys, threading, http.server, pathlib, tempfile

HERE = pathlib.Path(__file__).parent
SEEN = []          # (role-marker, user text)
STATE = {"critic_calls": 0, "mode": "ok"}

PLAN = {"tasks": [
    {"id": "t1", "role": "investigador", "instruction": "Investiga el mercado", "acceptance": "3 hallazgos", "depends_on": []},
    {"id": "t2", "role": "analista", "instruction": "Analiza competencia", "acceptance": "tabla", "depends_on": []},
    {"id": "t3", "role": "redactor", "instruction": "Redacta el plan", "acceptance": "coherente", "depends_on": ["t1", "t2"]},
]}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        sys_msg, user = body["messages"][0]["content"], body["messages"][1]["content"]
        SEEN.append((sys_msg[:12], user))
        if "PLANIFICADOR" in sys_msg:
            out = "no es json" if STATE["mode"] == "bad_plan" else "```json\n" + json.dumps(PLAN) + "\n```"
        elif "CRITICO" in sys_msg:
            STATE["critic_calls"] += 1
            reject_first = STATE["mode"] == "reject_once" and STATE["critic_calls"] == 1
            out = json.dumps({"approved": not reject_first, "issues": ["falta detalle"] if reject_first else []})
        elif "SINTETIZADOR" in sys_msg:
            out = "FINAL-OK"
        else:
            out = "resultado del trabajador"
        data = json.dumps({"choices": [{"message": {"content": out}}]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/v1"

def run(*extra, goal="Plan de marketing", env_key="k"):
    env = {"PATH": os.environ["PATH"], "OMNIROUTE_API_KEY": env_key} if env_key else {"PATH": os.environ["PATH"]}
    return subprocess.run([sys.executable, "-I", str(HERE / "orchestrator.py"), "--goal", goal,
                           "--base-url", BASE, *extra], capture_output=True, text=True, env=env, timeout=60)

def reset(mode="ok"):
    SEEN.clear(); STATE.update(critic_calls=0, mode=mode)

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))
    if not cond: fails.append(name)

# 1 happy path: 1 planner + 3*(worker+critic) + 1 synth = 8 calls
reset(); r = run()
check("happy path exit 0", r.returncode == 0, r.stderr + r.stdout)
check("happy path final text", "FINAL-OK" in r.stdout)
check("happy path 8 calls", "[llamadas al modelo: 8/40]" in r.stdout, r.stdout[-200:])
# dependency ordering: t3's worker prompt must contain outputs of t1 and t2
t3 = [u for s, u in SEEN if "Redacta el plan" in u]
check("dependent task receives upstream context", bool(t3) and "[t1]" in t3[0] and "[t2]" in t3[0])

# 2 critic rejects once -> one revision -> approved
reset("reject_once"); r = run()
check("revision loop completes", r.returncode == 0, r.stdout + r.stderr)
check("revision used corrective feedback", any("Corrige según el crítico" in u for _, u in SEEN))

# 3 budget
reset(); r = run("--max-calls", "3")
check("budget stops execution (exit 3)", r.returncode == 3, f"{r.returncode} {r.stderr}")

# 4 scrub
reset(); r = run("--scrub", goal="Contactar a 12.345.678-5 en juan@ejemplo.cl o +56 9 1234 5678")
sent = "\n".join(u for _, u in SEEN)
check("scrub removes RUT/email/phone from outbound text",
      "12.345.678-5" not in sent and "juan@ejemplo.cl" not in sent and "1234 5678" not in sent and "[RUT]" in sent, sent[:200])
reset(); r = run(goal="Contactar a 12.345.678-5")
check("without --scrub text is unchanged (documents the opt-in)", "12.345.678-5" in "\n".join(u for _, u in SEEN))

# 5 invalid plan twice
reset("bad_plan"); r = run()
check("invalid plan fails cleanly", r.returncode != 0 and "planner failed" in (r.stderr + r.stdout) or r.returncode != 0)

# 6 missing key
reset(); r = run(env_key="")
check("missing API key rejected (exit 2)", r.returncode == 2)

# 7 trace stores metadata only by default
reset(); tf = tempfile.mktemp(suffix=".jsonl"); r = run("--trace", tf)
rows = [json.loads(l) for l in open(tf)]
check("trace has no bodies by default", rows and all("in" not in x and "out" not in x for x in rows))
os.unlink(tf)

print(f"\n{len(fails)} failure(s)"); sys.exit(1 if fails else 0)
