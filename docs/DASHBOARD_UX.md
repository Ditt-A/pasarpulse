# Dashboard interaction guide

PasarPulse uses a consistent light interface with forest green, sage, warm
white, and muted earth colors. Amber, terracotta, and red distinguish monitoring
levels. Labels accompany every warning color.

## Workspaces

- **Market overview** keeps commodity, market level, horizon, and forecast date
  visible. Coverage and monitoring counts reflect the selected snapshot.
- **National map** renders the repository's BIG province geometry locally, with
  warning, projected-change, and evidence layers. No external map tiles or font
  service are needed. Select a province or return to the national view.
- **Province detail** shows the price at the origin, the forecast endpoint,
  projected change, dates, and source evidence. Saved model contributions are
  shown only when a real attribution artifact exists.
- **Province table** supports search, warning filters, numeric sorting,
  pagination, and keyboard-accessible selection. CSV export includes only
  forecast-time fields from the selected snapshot.
- **Alert queue** opens the corresponding province while retaining forecast
  context.
- **Regional intelligence** compares two provinces under the same filters,
  using their actual observed and predicted endpoints.
- **Model performance** separates saved evaluation families and horizons.
  Diagnostic same-fold-weighted results remain explicitly excluded from
  headline comparisons.
- **Assistant** displays service availability and disables requests when the
  optional reasoning service is not configured. No synthetic answer is shown.

## Replay and data boundaries

Runtime mode remains **Historical Replay**. The interface reads:

- `demo_data/forecasts/forecast_snapshot.csv` — 3,893 saved forecast rows;
- `demo_data/evidence/evidence_snapshot.json` — forecast-time source context;
- `demo_data/geography/indonesia_provinces.geojson` — 38 province geometries;
- `results/` — saved benchmark and attribution artifacts exposed by the API.

The selected filters can have fewer than 34 forecast provinces. Coverage is
calculated from that selection, not the geometry count. Missing provinces show
an explicit unavailable state and never inherit another province's forecast.

Later realized prices require an explicit reveal and are labeled as historical
evaluation. Changing province, date, commodity, market level, or horizon resets
the reveal. Warnings, rankings, comparisons, and CSV exports never use the later
realized price.

The chart in province detail connects two values: an observation and a forecast
endpoint. Its dashed line does not claim a daily price trajectory.

## Interaction and accessibility

Navigation has active states, a skip link, visible keyboard focus, and a native
mobile dialog with Escape dismissal. Detail tabs support arrow keys. Mobile
table selections scroll to the province detail. Tables scroll within their own
container without widening the page. Map bounds adapt to narrow screens.

Transitions are short and respect `prefers-reduced-motion`. Data loading,
request failures, empty filters, missing forecasts, and an unavailable assistant
have distinct states.

## Validation

From `app/frontend`:

```bash
npm ci
npm run test
npm run typecheck
npm run lint
npm run build
```

Frontend tests cover forecast-only ranking, composed search and warning filters,
summary counts, valid and invalid deep links, preserved analyst context,
benchmark-only dates, CSV escaping, and exclusion of later outcomes.

Browser checks cover real map selection, layer controls, forecast/evidence tabs,
evaluation reveal/reset, table interactions, downloads, alert routing, province
comparisons, benchmark filters, assistant availability, missing-province states,
and layouts at desktop, tablet, and mobile widths. Screenshot examples use
actual historical data and are stored in `docs/images/`.

The frontend continues to use the same-origin `/api` proxy. See
`README_DEPLOYMENT.md` for runtime variables and container setup.
