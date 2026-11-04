import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// ---- network exposure ------------------------------------------------------
test("resolveServerHost binds loopback by default", async () => {
  const { resolveServerHost } = await import("../../bin/cli/utils/serverHost.mjs");
  assert.equal(resolveServerHost({}, "linux", "machine"), "127.0.0.1");
  assert.equal(resolveServerHost({ OMNIROUTE_SERVER_HOST: "0.0.0.0" }, "linux", "m"), "0.0.0.0");
});

// ---- API key required by default ------------------------------------------
test("REQUIRE_API_KEY defaults to true", async () => {
  const saved = process.env.REQUIRE_API_KEY;
  delete process.env.REQUIRE_API_KEY;
  try {
    const { isRequireApiKeyEnabled } = await import("../../src/shared/utils/featureFlags.ts");
    assert.equal(isRequireApiKeyEnabled(), true);
  } finally {
    if (saved !== undefined) process.env.REQUIRE_API_KEY = saved;
  }
});

// ---- rate limiter latency --------------------------------------------------
test("default minTimeBetweenRequests no longer adds a fixed 350ms gap", async () => {
  const { DEFAULT_API_LIMITS } = await import("../../open-sse/config/constants.ts");
  assert.equal(DEFAULT_API_LIMITS.minTimeBetweenRequests, 0);
});

// ---- body logging is opt-in -------------------------------------------------
test("call-log bodies are disabled unless OMNIROUTE_CALL_LOG_BODIES=true", async () => {
  const { isBodyLoggingDisabled } = await import("../../src/lib/compliance/noLog.ts");
  const saved = process.env.OMNIROUTE_CALL_LOG_BODIES;
  try {
    delete process.env.OMNIROUTE_CALL_LOG_BODIES;
    assert.equal(isBodyLoggingDisabled(), true);
    process.env.OMNIROUTE_CALL_LOG_BODIES = "false";
    assert.equal(isBodyLoggingDisabled(), true);
    process.env.OMNIROUTE_CALL_LOG_BODIES = "true";
    assert.equal(isBodyLoggingDisabled(), false);
  } finally {
    if (saved === undefined) delete process.env.OMNIROUTE_CALL_LOG_BODIES;
    else process.env.OMNIROUTE_CALL_LOG_BODIES = saved;
  }
});

// ---- encryption fails closed ------------------------------------------------
test("encrypt() refuses plaintext when OMNIROUTE_REQUIRE_ENCRYPTION=true and no key", async () => {
  const savedKey = process.env.STORAGE_ENCRYPTION_KEY;
  const savedReq = process.env.OMNIROUTE_REQUIRE_ENCRYPTION;
  delete process.env.STORAGE_ENCRYPTION_KEY;
  process.env.OMNIROUTE_REQUIRE_ENCRYPTION = "true";
  try {
    const mod = await import(`../../src/lib/db/encryption.ts?nokey=${Date.now()}`);
    assert.throws(() => mod.encrypt("sk-secret"), /refusing to store a credential in plaintext/);
  } finally {
    if (savedKey !== undefined) process.env.STORAGE_ENCRYPTION_KEY = savedKey;
    if (savedReq === undefined) delete process.env.OMNIROUTE_REQUIRE_ENCRYPTION;
    else process.env.OMNIROUTE_REQUIRE_ENCRYPTION = savedReq;
  }
});

// ---- SSRF: names that resolve to cloud metadata are blocked ---------------------
test("block-metadata guard rejects hostnames that RESOLVE to 169.254.169.254", async () => {
  const { safeOutboundFetch } = await import("../../src/shared/network/safeOutboundFetch.ts");
  const fakeLookup = async () => [{ address: "169.254.169.254", family: 4 }];
  await assert.rejects(
    () =>
      safeOutboundFetch("http://attacker.example.test/latest/meta-data", {
        guard: "block-metadata",
        dnsLookup: fakeLookup,
        timeoutMs: 1000,
        retry: false,
      } as never),
    (error: any) => error?.code === "URL_GUARD_BLOCKED"
  );
});

// ---- .env creation: random password + private mode ---------------------------------
test("syncEnv replaces the CHANGEME placeholder and writes .env with mode 0600", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "omni-sync-env-"));
  try {
    fs.writeFileSync(
      path.join(dir, ".env.example"),
      "INITIAL_PASSWORD=CHANGEME\nJWT_SECRET=\nSTORAGE_ENCRYPTION_KEY=\n"
    );
    const { syncEnv } = await import("../../scripts/dev/sync-env.mjs");
    const result = syncEnv({ rootDir: dir, quiet: true });
    assert.equal(result.created, true);
    const content = fs.readFileSync(path.join(dir, ".env"), "utf8");
    assert.doesNotMatch(content, /INITIAL_PASSWORD=CHANGEME/i);
    assert.match(content, /INITIAL_PASSWORD=[A-Za-z0-9_-]{16,}/);
    if (process.platform !== "win32") {
      assert.equal(fs.statSync(path.join(dir, ".env")).mode & 0o777, 0o600);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
