import test from "node:test";
import assert from "node:assert/strict";

// Regression: NO_LOG_API_KEY_IDS ids were deleted from the in-memory set the first time
// src/lib/db/apiKeys.ts synced a key whose api_keys.no_log column was 0 (setNoLog(id, false)).
test("an id from NO_LOG_API_KEY_IDS stays no-log after setNoLog(id, false)", async () => {
  const saved = process.env.NO_LOG_API_KEY_IDS;
  process.env.NO_LOG_API_KEY_IDS = "env-key-1, env-key-2";
  try {
    const m = await import(`../../src/lib/compliance/noLog.ts?precedence=${Date.now()}`);
    assert.equal(m.isNoLog("env-key-1"), true);
    m.setNoLog("env-key-1", false); // what apiKeys.ts does when the DB flag is false
    assert.equal(m.isNoLog("env-key-1"), true, "env-configured id must survive a DB sync");
    assert.equal(m.isNoLog("env-key-2"), true);
    assert.equal(m.isNoLog("other"), false);
  } finally {
    if (saved === undefined) delete process.env.NO_LOG_API_KEY_IDS;
    else process.env.NO_LOG_API_KEY_IDS = saved;
  }
});

test("setNoLog still toggles DB-driven keys", async () => {
  const m = await import(`../../src/lib/compliance/noLog.ts?toggle=${Date.now()}`);
  m.setNoLog("db-key", true);
  assert.equal(m.isNoLog("db-key"), true);
  m.setNoLog("db-key", false);
  // DB cache now says false inside its TTL; no env entry -> not no-log
  assert.equal(m.isNoLog("db-key"), false);
});
