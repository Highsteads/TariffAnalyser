# TariffAnalyser — Indigo Plugin

Compares your real recorded energy flows against UK electricity tariffs to show what you would have paid on each tariff.

The [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) plugin records your energy flows every 30 minutes. TariffAnalyser reads that record, works out what each tariff would have cost you, and writes an HTML report that opens in your browser.

## Features

- Half-hourly comparison using your actual grid import, export, solar generation, and battery usage
- Supports Octopus Tracker (actual per-slot prices), Go, Go Faster, Agile, Cosy, Flux, Economy 7, Ofgem SVT price cap, E.ON, EDF, and Scottish Power
- **Fair like-for-like ranking** — every tariff is priced over the same set of half-hourly slots (those where all selected tariffs have a price), with the standing charge pro-rated to that set. A tariff with too little price data is flagged as insufficient rather than ranked misleadingly cheap
- Export revenue comparison: Octopus Outgoing 12p, Agile Outgoing, SEG minimum, SEG typical
- Octopus Agile prices fetched automatically from the public API (no credentials needed)
- Reports come out as HTML and open in your browser
- Schedulable actions: generate a report, update Agile price data, refresh the daily summary
- Menu items for on-demand use, including a Test Octopus API Connection check

## Requirements

- Indigo 2022.1 or later (Python 3.10+)
- [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) v4.6+ (provides the half-hourly energy database)
- A web browser to read the reports — any Mac already has one

## Installation

1. Go to the [Releases](https://github.com/Highsteads/TariffAnalyser/releases) page and download `TariffAnalyser.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `TariffAnalyser.indigoPlugin`
3. Double-click `TariffAnalyser.indigoPlugin` — Indigo will install it automatically

## Credentials — `IndigoSecrets.py` vs `IndigoSecrets_example.py`

This plugin, like every CliveS Indigo plugin, reads sensitive values from one
shared master file:

`/Library/Application Support/Perceptive Automation/IndigoSecrets.py`

| File | Purpose | Real data? | Committed to GitHub? |
|------|---------|------------|----------------------|
| `IndigoSecrets.py` | Working file the plugin reads at runtime. Keep a backup in a password manager. | YES | **NO** — listed in `.gitignore` |
| `IndigoSecrets_example.py` | Template only — empty placeholders. Shipped in the plugin bundle. | NO | YES |

If you don't have `IndigoSecrets.py`, copy `IndigoSecrets_example.py` out of
the plugin bundle into `/Library/Application Support/Perceptive Automation/`,
rename it to `IndigoSecrets.py`, and fill in your values. Or skip the file
altogether and type the values into the plugin's configuration dialog — where
both are set, `IndigoSecrets.py` wins.

If neither source supplies a value the plugin needs, it logs an ERROR naming
the key and telling you to either fill in the matching field or add the key to
`IndigoSecrets.py`.

**Keys read by TariffAnalyser:**

```python
OCTOPUS_API_KEY       = "sk_live_..."
OCTOPUS_MPAN          = ""
OCTOPUS_SERIAL        = ""
OCTOPUS_EXPORT_MPAN   = ""   # optional — export tariff comparisons
OCTOPUS_EXPORT_SERIAL = ""
OCTOPUS_GAS_MPRN      = ""   # optional — gas cost calculations
OCTOPUS_GAS_SERIAL    = ""
```

Each key has a matching field under **Plugins → Tariff Analyser → Configure**
(see Plugin Configuration below) so the plugin can be set up entirely via
the GUI for users who don't maintain `IndigoSecrets.py`. *(PluginConfig
fallback added in v1.3.)*

## Output

The plugin writes reports to:
```
/Library/Application Support/Perceptive Automation/TariffAnalyser/
```

Each one is an HTML file named `tariff_comparison_<from>_<to>_<timestamp>.html`, and the plugin hands it to macOS to open, so it lands in your default browser.

## Usage

### Menu Items (Indigo → Plugins → Tariff Analyser)

| Menu item | What it does |
|---|---|
| Energy Summary | Savings summary (today / yesterday / this week / month / year) as an HTML page in your browser |
| Tariff Comparison | Choose a lookback period, then it ranks every tariff by what your real usage would have cost and opens the HTML report |
| Test Octopus API Connection | Checks the Agile products endpoint, the discovered import/export product codes for your region, and cached-price coverage |
| Toggle Timestamps in Log | Turns the `[HH:MM:SS.mmm]` log prefix on or off |
| Show Plugin Info | Displays plugin version, paths, region, and credential status |

### Schedulable Actions

| Action | Description |
|---|---|
| Generate Report | Generates a comparison report for the last N days |
| Update Prices | Fetches missing Agile prices |
| Update Daily Summary | Refreshes the rolling daily_summary from the Octopus API |
| Energy Summary | Regenerates and opens the savings summary |

## Tariffs Covered

### Import

| Key | Tariff | Type |
|---|---|---|
| tracker | Octopus Tracker | Actual per-slot prices from DB |
| go | Octopus Go | 5h cheap window 00:30–05:30 |
| go_faster | Octopus Go Faster | 6h cheap window 23:30–05:30 |
| agile | Octopus Agile | Half-hourly variable, auto-fetched |
| cosy | Octopus Cosy | Two 3h cheap windows + peak |
| flux | Octopus Flux | 3h cheap window 02:00–05:00 + 3h peak 16:00–19:00 |
| economy7 | Economy 7 | 7h night rate |
| ofgem_cap | Ofgem SVT Price Cap | Single flat rate |
| eon_fixed | E.ON Next Fixed | Typical fixed rate |
| edf_fixed | EDF Fixed | Typical fixed rate |
| scottishpower_fixed | Scottish Power Fixed | Typical fixed rate |

### Export

| Key | Tariff |
|---|---|
| outgoing_12p | Octopus Outgoing 12p flat |
| agile_outgoing | Octopus Agile Outgoing (variable) |
| seg_min | SEG Minimum (Ofgem floor, 1.63p) |
| seg_typical | SEG Typical (e.g. EDF/E.ON, 7.5p) |

## Plugin Configuration

Open it from Indigo → Plugins → Tariff Analyser → Configure:

| Field | Default | Description |
|---|---|---|
| Timeseries DB path | Auto (SigenEnergyManager prefs) | Path to energy_timeseries.db |
| Output folder | Auto (/Library/.../TariffAnalyser) | Where HTML reports are saved |
| Open report after scheduled run | Off | Opens the report once a schedule or action generates it |
| Octopus region | F (North East England) | Used for Agile price lookups |
| Export tariff | Octopus Outgoing 12p | Applied to all import tariff comparisons |
| Default date range | Last 30 days | Default for scheduled action |
| Octopus API key | (blank) | Fallback for `IndigoSecrets.OCTOPUS_API_KEY` |
| Import MPAN | (blank) | Fallback for `IndigoSecrets.OCTOPUS_MPAN` |
| Import meter serial | (blank) | Fallback for `IndigoSecrets.OCTOPUS_SERIAL` |
| Export MPAN | (blank) | Fallback for `IndigoSecrets.OCTOPUS_EXPORT_MPAN` |
| Export meter serial | (blank) | Fallback for `IndigoSecrets.OCTOPUS_EXPORT_SERIAL` |
| Gas MPRN | (blank) | Fallback for `IndigoSecrets.OCTOPUS_GAS_MPRN` |
| Gas meter serial | (blank) | Fallback for `IndigoSecrets.OCTOPUS_GAS_SERIAL` |

## Logging

Every log line carries a millisecond timestamp `[HH:MM:SS.mmm]`, so you can
line events up precisely against the other CliveS plugins — Device Activity
Monitor uses the same format.

To turn the prefix off, or back on, at any time:

**Plugins → Tariff Analyser → Toggle Timestamps in Log (on/off)**

The plugin stores the setting in `pluginPrefs` (`timestampEnabled`) and it
survives a restart. It defaults to ON.

## Version history

**v1.9.3** — **Added the missing support link.** Every Indigo plugin is meant to carry a web address inside its bundle — it is what the "About" item in the Plugins menu opens. This one had the entry but left it blank, so that menu item went nowhere. It now points at this repository. Nothing else changed.
- **1.9.1–1.9.2** (21-07-2026) — housekeeping pair. Named log levels now map to the real logging levels — warnings and errors raised through the shared helper had been appearing as plain info lines, so amber and red entries people relied on for diagnosis never showed. Shared-utility refresh: calling the log timestamp filter twice no longer double-stamps every line, and the module imports cleanly outside Indigo.
- **1.9** (18-07-2026) — deep-review improvements: a Test Octopus API Connection menu item, and the report now states when the illustrative "typical" fixed tariffs were last checked (Tracker and Agile always use live rates).
- **1.8** (18-07-2026) — deep-review test buildout: 27 tests covering the comparison arithmetic and the collector's time-of-use, gas and timezone helpers.
- **1.7** (18-07-2026) — deep-review financial fixes. Tariffs are now ranked fairly over a common set of half-hourly slots so a tariff with patchy price data can no longer appear cheapest just because part of your usage was never counted. A missing Tracker rate no longer records a false £0 day, the Go and Flux "saving vs Tracker" figures now include the standing-charge difference, and the Octopus fetch windows were widened so the first slots of a day are not lost in British Summer Time. First test suite added.
- **1.6** (10-06-2026) — housekeeping. Lint clean-up and a continuous-integration check added as part of a fleet-wide audit. No change in behaviour.
- **1.5** (05-06-2026) — estate bug-sweep. Opening the report automatically after a scheduled run called a function that no longer existed, so that option failed every time it was used. The coverage lookup now catches only database errors, letting genuine programming mistakes surface rather than hiding them.
- **1.4** (23-05-2026) — millisecond timestamp `[HH:MM:SS.mmm]` prefix on every `self.logger` line via `plugin_utils.install_timestamp_filter()`; new "Toggle Timestamps in Log" menu item.
- **1.3** (23-05-2026) — PluginConfig fallback for all 7 Octopus credential keys; secrets-policy compliance. `IndigoSecrets.py` still takes precedence when set.
- **1.2** — current SigenEnergyManager integration; daily auto-update at 02:00.

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
