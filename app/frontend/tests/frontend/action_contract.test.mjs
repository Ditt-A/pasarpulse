import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("dashboard action whitelist contains only explicit control actions", async () => {
  const source = await readFile(new URL("../../lib/actions.ts", import.meta.url), "utf8");
  for (const action of ["SET_PROVINCE", "SET_COMMODITY", "SET_MARKET_LEVEL", "SET_HORIZON", "SET_MAP_LAYER", "SET_REPLAY_ORIGIN", "FILTER_RISK", "COMPARE_PROVINCES", "OPEN_ALERT", "RESET_FILTERS"]) {
    assert.match(source, new RegExp(`\\"${action}\\"`));
  }
  assert.doesNotMatch(source, /target_price/);
});
