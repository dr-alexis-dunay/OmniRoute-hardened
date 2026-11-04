#!/usr/bin/env python3
"""Coordinated multi-agent orchestrator for an OpenAI-compatible endpoint (e.g. OmniRoute).

Pattern: planner -> parallel workers (by dependency level) -> critic loop -> synthesizer.
Stdlib only. Designed to be small, auditable and safe by default:

  * hard budget on total model calls (--max-calls)
  * per-call timeout
  * optional human approval of the plan before any worker runs (--require-approval)
  * optional scrubbing of Chilean RUT / email / phone numbers before text leaves the machine
    (--scrub). This is a REGEX SCRUB, NOT real de-identification: names, diagnoses, dates and
    free-text identifiers are NOT removed. Do not rely on it for patient data.
  * trace file stores metadata only unless --trace-bodies is passed

Usage:
  export OMNIROUTE_API_KEY=...            # an OmniRoute API key
  python3 orchestrator.py --goal "Plan de marketing para una panadería en Temuco" \
      --base-url http://127.0.0.1:20128/v1 --model auto --require-approval
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

RUT_RE = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?56\s?)?9\s?\d{4}\s?\d{4}(?!\d)")


def scrub(text: str) -> str:
    text = RUT_RE.sub("[RUT]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    return PHONE_RE.sub("[TEL]", text)


class BudgetExceeded(RuntimeError):
    pass


class Client:
    def __init__(self, base_url, api_key, model, timeout, max_calls, do_scrub, trace_path, trace_bodies):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_calls = max_calls
        self.do_scrub = do_scrub
        self.trace_path = trace_path
        self.trace_bodies = trace_bodies
        self._lock = threading.Lock()
        self.calls = 0

    def chat(self, role: str, system: str, user: str, temperature: float = 0.2) -> str:
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"call budget of {self.max_calls} exhausted")
            self.calls += 1
            n = self.calls
        if self.do_scrub:
            system, user = scrub(system), scrub(user)
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json", "authorization": f"Bearer {self.api_key}"},
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.load(resp)
            text = body["choices"][0]["message"]["content"] or ""
            status = "ok"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
            text, status = "", f"error:{type(exc).__name__}"
        self._trace(n, role, status, time.time() - started, user, text)
        if status != "ok":
            raise RuntimeError(f"{role}: model call failed ({status})")
        return text

    def _trace(self, n, role, status, secs, user, text):
        if not self.trace_path:
            return
        row = {"n": n, "role": role, "status": status, "secs": round(secs, 3),
               "chars_in": len(user), "chars_out": len(text)}
        if self.trace_bodies:
            row.update({"in": user, "out": text})
        with self._lock, open(self.trace_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_json(text: str):
    """Parse the first JSON object in a model reply (tolerates ```json fences and chatter)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object")


PLANNER = (
    "Eres el PLANIFICADOR de un equipo de agentes. Descompón el objetivo en 2 a 6 tareas "
    "concretas. Responde SOLO JSON: {\"tasks\":[{\"id\":\"t1\",\"role\":\"<rol>\","
    "\"instruction\":\"...\",\"acceptance\":\"criterio verificable\",\"depends_on\":[]}]}. "
    "Roles posibles: investigador, analista, redactor, finanzas, legal_general, ventas, marketing, soporte."
)
WORKER = ("Eres el agente '{role}'. Cumple SOLO tu tarea, sé concreto y señala supuestos e incertidumbre. "
          "No inventes cifras ni citas: si no sabes, di 'no sé'.")
CRITIC = (
    "Eres el CRITICO. Evalúa si el resultado cumple el criterio de aceptación. Responde SOLO JSON: "
    "{\"approved\":true|false,\"issues\":[\"...\"]}. Sé estricto con afirmaciones sin sustento."
)
SYNTH = ("Eres el SINTETIZADOR. Integra los resultados aprobados en una respuesta final coherente, "
         "marcando explícitamente lo no verificado.")


def plan(client: Client, goal: str) -> list[dict]:
    last_err = None
    for _ in range(2):
        try:
            tasks = extract_json(client.chat("planner", PLANNER, f"Objetivo: {goal}"))["tasks"]
            ids = {t["id"] for t in tasks}
            for t in tasks:
                t.setdefault("depends_on", [])
                if not set(t["depends_on"]) <= ids or t["id"] in t["depends_on"]:
                    raise ValueError("invalid dependency graph")
            return tasks
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            last_err = exc
    raise RuntimeError(f"planner failed twice: {last_err}")


def levels(tasks: list[dict]) -> list[list[dict]]:
    done, out, pending = set(), [], list(tasks)
    while pending:
        ready = [t for t in pending if set(t["depends_on"]) <= done]
        if not ready:
            raise RuntimeError("cyclic dependencies in plan")
        out.append(ready)
        done |= {t["id"] for t in ready}
        pending = [t for t in pending if t["id"] not in done]
    return out


def run_task(client: Client, task: dict, results: dict, max_revisions: int) -> dict:
    ctx = "\n\n".join(f"[{d}] {results[d]['output']}" for d in task["depends_on"] if d in results)
    prompt = f"Tarea: {task['instruction']}\nCriterio: {task['acceptance']}\n\nContexto previo:\n{ctx or '(ninguno)'}"
    output, feedback = "", ""
    for rev in range(max_revisions + 1):
        output = client.chat(task["role"], WORKER.format(role=task["role"]),
                             prompt + (f"\n\nCorrige según el crítico: {feedback}" if feedback else ""))
        try:
            verdict = extract_json(client.chat("critic", CRITIC,
                                               f"Criterio: {task['acceptance']}\n\nResultado:\n{output}"))
        except (ValueError, RuntimeError):
            verdict = {"approved": False, "issues": ["critic reply was not valid JSON"]}
        if verdict.get("approved") is True:
            return {"output": output, "approved": True, "revisions": rev}
        feedback = "; ".join(map(str, verdict.get("issues", []))) or "sin detalle"
    return {"output": output, "approved": False, "revisions": max_revisions, "issues": feedback}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--base-url", default=os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1"))
    ap.add_argument("--model", default="auto")
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--max-revisions", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--require-approval", action="store_true")
    ap.add_argument("--scrub", action="store_true")
    ap.add_argument("--trace", default="")
    ap.add_argument("--trace-bodies", action="store_true")
    a = ap.parse_args()

    key = os.environ.get("OMNIROUTE_API_KEY", "")
    if not key:
        print("Define OMNIROUTE_API_KEY (no se acepta por argumento para no filtrarlo al historial).", file=sys.stderr)
        return 2
    client = Client(a.base_url, key, a.model, a.timeout, a.max_calls, a.scrub, a.trace, a.trace_bodies)

    tasks = plan(client, a.goal)
    print("PLAN:")
    for t in tasks:
        print(f"  {t['id']} [{t['role']}] <- {t['depends_on']}: {t['instruction']}")
    if a.require_approval and input("¿Ejecutar este plan? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
        print("Cancelado por el usuario.")
        return 1

    results: dict[str, dict] = {}
    try:
        for level in levels(tasks):
            with cf.ThreadPoolExecutor(max_workers=a.workers) as pool:
                futs = {pool.submit(run_task, client, t, results, a.max_revisions): t for t in level}
                for fut in cf.as_completed(futs):
                    results[futs[fut]["id"]] = fut.result()
        body = "\n\n".join(f"## {tid} ({'aprobado' if r['approved'] else 'NO aprobado'})\n{r['output']}"
                           for tid, r in results.items())
        final = client.chat("synthesizer", SYNTH, f"Objetivo: {a.goal}\n\nResultados:\n{body}")
    except BudgetExceeded as exc:
        print(f"Detenido por presupuesto: {exc}", file=sys.stderr)
        return 3
    unapproved = [t for t, r in results.items() if not r["approved"]]
    print("\n=== RESULTADO FINAL ===\n" + final)
    if unapproved:
        print(f"\n[ADVERTENCIA] tareas sin aprobación del crítico: {unapproved}")
    print(f"\n[llamadas al modelo: {client.calls}/{a.max_calls}]")
    return 0 if not unapproved else 4


if __name__ == "__main__":
    sys.exit(main())
