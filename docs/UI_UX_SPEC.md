# PasarPulse UI/UX specification

The primary user path is:

```text
Indonesia risk map → forecast intelligence → evidence → alert prioritization → Copilot investigation
```

The interface uses four primary sections: Overview, Alerts, Intelligence, and
Model. Copilot is global. The Overview page leads with a 65/35 map-to-panel
composition, compact filters, a national alert queue, and a chronological
replay timeline.

The default map layer is Projected Price-Shock Risk. Labels always accompany
color. Risk is a configurable product heuristic:

```text
<5% STABLE · 5–<10% WATCH · 10–<15% ELEVATED · >=15% HIGH
```

It is not a learned probability or official threshold. Evidence and freshness
are shown as separate status rows. The forecast chart intentionally renders an
observed point to forecast endpoint slope because the replay artifact contains
an endpoint, not a daily predicted trajectory. No uncertainty band is drawn
without a real interval artifact.

Historical evaluation is visually separated and labeled as information not
available to the model at forecast time. The “Reveal future” control is a demo
presentation affordance, not a feature used to generate warnings.
