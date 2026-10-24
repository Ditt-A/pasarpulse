import assert from "node:assert/strict";
import test from "node:test";
import {
  forecastsToCsv,
  rankForecasts,
  resolveDashboardParams,
  summarizeForecasts,
} from "../../lib/overview.mjs";

const rows = [
  {
    province_code: "32",
    province_name: "Jawa Barat",
    projected_change_pct: 12,
    current_price: 40000,
    predicted_price: 44800,
    warning_level: "ELEVATED",
    historical_evaluation: { realized_price: 100 },
  },
  {
    province_code: "12",
    province_name: "Sumatera Utara",
    projected_change_pct: -3,
    current_price: 50000,
    predicted_price: 48500,
    warning_level: "STABLE",
    historical_evaluation: { realized_price: 999999 },
  },
  {
    province_code: "31",
    province_name: "DKI Jakarta",
    projected_change_pct: 6,
    current_price: 60000,
    predicted_price: 63600,
    warning_level: "WATCH",
  },
];
const metadata = {
  commodities: [{ code: "CRM" }, { code: "BM" }],
  market_levels: ["retail", "producer"],
  horizons: [7, 14],
  forecast_origins: ["2026-07-17", "2026-06-22"],
  latest_origin: "2026-07-17",
};

test("ranking uses forecast movement and never later realized outcomes", () => {
  assert.deepEqual(
    rankForecasts(rows).map((x) => x.province_code),
    ["32", "31", "12"],
  );
  assert.deepEqual(
    rows.map((x) => x.province_code),
    ["32", "12", "31"],
    "source snapshot is immutable",
  );
  assert.deepEqual(
    rankForecasts(rows, { sort: "predicted_price", direction: "asc" }).map(
      (x) => x.province_code,
    ),
    ["32", "12", "31"],
  );
});
test("province search and warning filter compose, including empty states", () => {
  assert.deepEqual(
    rankForecasts(rows, { search: "  jAwA ", warning: "ELEVATED" }).map(
      (x) => x.province_code,
    ),
    ["32"],
  );
  assert.equal(rankForecasts(rows, { warning: "HIGH" }).length, 0);
});
test("summary counts monitoring levels without inventing confidence or reclassifying outcomes", () => {
  const summary = summarizeForecasts(rows);
  assert.equal(summary.provinces, 3);
  assert.equal(summary.attention, 2);
  assert.equal(summary.counts.STABLE, 1);
  assert.equal(summary.largest.province_code, "32");
  assert.equal(summarizeForecasts([]).largest, undefined);
});
test("deep links accept only available dates, horizons, and filter values", () => {
  const valid = resolveDashboardParams(
    "?commodity=BM&market=producer&horizon=14&origin=2026-06-22&province=32&layer=change",
    metadata,
  );
  assert.deepEqual(valid, {
    commodity: "BM",
    marketLevel: "producer",
    horizon: 14,
    origin: "2026-06-22",
    selectedProvince: "32",
    layer: "change",
  });
  const invalid = resolveDashboardParams(
    "?commodity=FAKE&market=invalid&horizon=90&origin=2099-01-01&province=script&layer=confidence",
    metadata,
  );
  assert.equal(invalid.commodity, "CRM");
  assert.equal(invalid.marketLevel, "retail");
  assert.equal(invalid.horizon, 7);
  assert.equal(invalid.origin, "2026-07-17");
  assert.equal(invalid.selectedProvince, "");
  assert.equal(invalid.layer, "risk");
});
test("returning to the overview preserves valid analyst context", () => {
  const current = {
    commodity: "BM",
    marketLevel: "producer",
    horizon: 14,
    origin: "2026-06-22",
    selectedProvince: "12",
    layer: "evidence",
  };
  assert.deepEqual(resolveDashboardParams("", metadata, current), current);
  assert.equal(
    resolveDashboardParams("", {
      ...metadata,
      forecast_origins: [],
      latest_origin: null,
    }).origin,
    "",
  );
});
test("CSV export whitelists forecast-time fields and escapes quoted names", () => {
  const csv = forecastsToCsv([
    {
      ...rows[0],
      province_name: 'Province, "A"',
      target_price: 123,
      model: "real-model",
    },
  ]);
  assert.match(csv, /"Province, ""A"""/);
  assert.match(csv, /44800/);
  assert.doesNotMatch(
    csv,
    /target_price|historical_evaluation|realized_price|123/,
  );
  assert.equal(forecastsToCsv([]).split("\r\n").length, 1);
});
