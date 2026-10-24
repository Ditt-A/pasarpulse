# Monitoring workspace

The interface is organized around an analyst's first task: comparing provincial
price forecasts. A compact navigation bar links **Pemantauan**, **Perbandingan**,
and **Data & metode**. Monitoring begins with data rows, rather than a stack of
summary cards. The optional assistant is secondary and appears in navigation
only when its health endpoint reports an available reasoning service.

## Layout and typography

- A 56 px global header contains the identity, navigation, and active data mode.
- The workspace title is 22 px; normal body text is 14 px; table values are 13 px;
  controls and secondary labels are 11–12 px. Forecast prices use stronger weight
  than snapshot prices. Numeric columns are right-aligned and use tabular figures.
- White and neutral gray form the interface. Forest green indicates active
  controls and selection. Amber, terracotta, and red carry price-rise warnings.
- Four forecast controls fit into a compact row: commodity, market, horizon,
  and snapshot date. A second row contains review scope, warning level, search,
  and the List / Map switch.
- Coverage is a small inline summary. The main content begins immediately below
  the controls and uses the remaining viewport height.

## List, map, and inspector

**Daftar** is the default. A sticky table header and an internal scroll area keep
controls visible while reading all available provinces. Rows show province,
snapshot price, projected price, change, and warning. Selecting a row opens a
372 px inspector on wide screens. The original table remains available.

**Peta** occupies the same workspace, with shared filters and selection. It
renders local BIG geometry and requires no external map tiles. A filter limits
highlighted and selectable provinces; muted background geometry remains context,
not a fabricated unavailable forecast. Layer controls and a national reset are
adjacent to the canvas. There is no duplicate table underneath the map.

On compact screens, province detail uses a native dialog with focus containment,
Escape dismissal, and restored focus. The table's province column stays visible
while numeric columns scroll horizontally. No page-wide horizontal scroll is
required. Closing detail retains view, query, filters, and sorting.

Inspector tabs show forecast values, source evidence, and saved model
contributions when the attribution API provides them. The chart contains only
an observed endpoint and a forecast endpoint, not an invented daily price path.

## Context and compatibility

List/map view, warning scope, search, province, commodity, market, horizon, and
origin can be restored from the monitoring URL. For example:

```text
/?commodity=CRM&market=retail&horizon=7&origin=2026-02-02&view=map&warning=ATTENTION
```

Invalid values recover to valid available settings. `/alerts` remains a
compatible entry point and redirects to monitoring with the review filter.

**Perbandingan** compares two provinces using the same origin, commodity, market,
and horizon. **Data & metode** separates the six-modality inventory, selected-model
benchmark families, and chronological validation into three tabs.

The versioned UI data catalog is `app/frontend/lib/data-catalog.json`. Tests check
its feature examples and horizon-use flags against the actual saved feature
contracts; they also verify that the documented artifact paths exist.

## Artifact and evaluation boundary

Runtime remains **Historical Replay**, using the 3,893 saved forecast rows,
source evidence, BIG geometry, benchmark CSVs, and available saved native
LightGBM contributions. No model is loaded or trained for a view or interaction.

Later realized prices are opt-in evaluation data. Changing forecast context
resets the reveal. Warning counts, ranking, CSV export, and comparisons use only
snapshot prices and stored predictions. CSV export follows the current scope
and search, not just the currently visible scroll position.

The six groups and horizon-specific use are documented in the repository README.
Raw-source availability is distinct from feature-contract membership. In
particular, the 14-day selected model uses price/calendar, while the other
modalities are additional context. Thirty SP2KP downloads have recorded parsing
failures; PIHPS supplies the deployed price snapshot.

## Accessibility and motion

Navigation has active states and a skip link. Table rows are keyboard-selectable;
arrow keys move between province buttons. View and detail tabs support arrow
keys. Dialogs use native focus handling. Empty search, missing provinces, request
failures, and an unavailable assistant have explicit states.

Control feedback is short; inspector entry uses 180 ms and map focusing uses
450 ms. `prefers-reduced-motion` is respected. Filtering changes the current
workspace in place rather than running a whole-page entrance sequence.

## Verification

From `app/frontend`:

```bash
npm run test
npm run typecheck
npm run lint
npm run build
```

Tests cover forecast-only ranking, attention scope, search, URL recovery,
preserved context, CSV escaping, exclusion of realized outcomes, modality
contracts, and replay provenance. Browser checks additionally exercise list/map
selection, detail/evidence/reveal, matching exported rows, compatible alerts
routing, comparison, data/method tabs, compact dialogs, and responsive layouts.
Screenshots in `docs/images/` use the actual 2 February 2026 snapshot.

The layout direction was informed by the official Vercel Analytics interface,
Linear issue views, and CARTO Builder's 2026 map layout. Their product assets are
not bundled into PasarPulse; only the interaction and information-organization
principles are adapted.
