import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { cleanupTempDataDir } from "../../_setup/tempDataDir.ts";

const TEST_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "omr-nonloopback-anon-"));
process.env.DATA_DIR = TEST_DATA_DIR;
process.env.API_KEY_SECRET = "test-secret";
process.env.OMNIROUTE_DISABLE_REDIS_AUTH_CACHE = "1";

const core = await import("../../../src/lib/db/core.ts");
const settingsDb = await import("../../../src/lib/db/settings.ts");

test.after(async () => {
  delete process.env.OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK;
  core.resetDbInstance();
  await cleanupTempDataDir(TEST_DATA_DIR);
});

function ctx(p: string, remoteAddress: string) {
  return {
    request: {
      method: "GET",
      headers: new Headers(),
      url: `http://localhost:20128${p}`,
      nextUrl: { pathname: p },
      socket: { remoteAddress },
    },
    classification: { routeClass: "MANAGEMENT" as const, reason: "management_api" as const, normalizedPath: p },
    requestId: "req_nonloopback",
  };
}

async function policy() {
  const m = await import(`../../../src/server/authz/policies/management.ts?ts=${Date.now()}${Math.random()}`);
  return m.managementPolicy;
}

test("requireLogin=false: a loopback peer is still served anonymously", async () => {
  await settingsDb.updateSettings({ requireLogin: false, setupComplete: true });
  const r = await (await policy()).evaluate(ctx("/api/providers", "127.0.0.1"));
  assert.equal(r.allow, true);
});

test("requireLogin=false: a private-LAN peer is NOT served anonymously (hardened default)", async () => {
  await settingsDb.updateSettings({ requireLogin: false, setupComplete: true });
  delete process.env.OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK;
  for (const peer of ["192.168.1.50", "10.0.0.7", "172.17.0.2"]) {
    const r = await (await policy()).evaluate(ctx("/api/providers", peer));
    assert.equal(r.allow, false, `${peer} must not be anonymous`);
  }
});

test("requireLogin=false: OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK=true restores the old behaviour", async () => {
  await settingsDb.updateSettings({ requireLogin: false, setupComplete: true });
  process.env.OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK = "true";
  try {
    const r = await (await policy()).evaluate(ctx("/api/providers", "192.168.1.50"));
    assert.equal(r.allow, true);
  } finally {
    delete process.env.OMNIROUTE_ALLOW_ANONYMOUS_NON_LOOPBACK;
  }
});
