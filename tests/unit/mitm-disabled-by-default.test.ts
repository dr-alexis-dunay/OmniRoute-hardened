import test from "node:test";
import assert from "node:assert/strict";

test("MITM start/regenerate are refused with 403 MITM_DISABLED unless OMNIROUTE_ENABLE_MITM=true", async () => {
  const saved = process.env.OMNIROUTE_ENABLE_MITM;
  delete process.env.OMNIROUTE_ENABLE_MITM;
  try {
    const gate = await import("../../src/mitm/enabledGate.ts");
    assert.equal(gate.isMitmEnabled({}), false);
    assert.equal(gate.isMitmEnabled({ OMNIROUTE_ENABLE_MITM: "false" } as never), false);
    assert.equal(gate.isMitmEnabled({ OMNIROUTE_ENABLE_MITM: "true" } as never), true);
    const res = gate.mitmDisabledResponse();
    assert.ok(res);
    assert.equal(res.status, 403);
    assert.equal((await res.json()).error.code, "MITM_DISABLED");

    const start = await import("../../src/app/api/cli-tools/antigravity-mitm/route.ts");
    const r1 = await start.POST(new Request("http://localhost/api/cli-tools/antigravity-mitm", { method: "POST", body: "{}" }));
    assert.equal(r1.status, 403);
    const regen = await import("../../src/app/api/settings/mitm/route.ts");
    const r2 = await regen.POST(new Request("http://localhost/api/settings/mitm", { method: "POST", body: "{}" }));
    assert.equal(r2.status, 403);

    process.env.OMNIROUTE_ENABLE_MITM = "true";
    assert.equal(gate.mitmDisabledResponse(), null);
  } finally {
    if (saved === undefined) delete process.env.OMNIROUTE_ENABLE_MITM;
    else process.env.OMNIROUTE_ENABLE_MITM = saved;
  }
});
