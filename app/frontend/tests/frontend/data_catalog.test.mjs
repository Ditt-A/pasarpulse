import assert from "node:assert/strict";
import { readFile, access } from "node:fs/promises";
import test from "node:test";
const root = new URL("../../../../", import.meta.url);
test("documented modality usage matches the actual selected feature contracts", async () => {
  const catalog = JSON.parse(
    await readFile(
      new URL("../../lib/data-catalog.json", import.meta.url),
      "utf8",
    ),
  );
  const contracts = JSON.parse(
    await readFile(
      new URL("results/multimodal_ablation/feature_contract.json", root),
      "utf8",
    ),
  );
  assert.equal(catalog.modalities.length, 6);
  const model7 = new Set(contracts.ALL_MODALITIES_DYNAMIC_GRAPH),
    model14 = new Set(contracts.PRICE_CALENDAR);
  for (const item of [...catalog.modalities, catalog.dynamicGraph]) {
    assert.equal(
      item.features.every((x) => model7.has(x)),
      item.days7,
      item.id + " / 7 days",
    );
    assert.equal(
      item.features.every((x) => model14.has(x)),
      item.days14,
      item.id + " / 14 days",
    );
    for (const path of item.paths) await access(new URL(path, root));
  }
  await access(new URL(catalog.geometry.path, root));
});
test("replay coverage and selected experts are read from the saved manifest", async () => {
  const m = JSON.parse(
    await readFile(
      new URL("demo_data/manifests/forecast_manifest.json", root),
      "utf8",
    ),
  );
  assert.equal(m.rows, 3893);
  assert.equal(m.province_codes.length, 34);
  assert.equal(m.forecast_origins.length, 7);
  assert.equal(
    m.model_selection[7].feature_contract,
    "ALL_MODALITIES_DYNAMIC_GRAPH",
  );
  assert.equal(m.model_selection[14].feature_contract, "PRICE_CALENDAR");
});
