# TariffAnalyser — Indigo Plugin

Compares your real recorded energy flows against UK electricity tariffs to show what you would have paid on each tariff.

Energy data is recorded every 30 minutes by the [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) plugin. TariffAnalyser reads that data and computes the cost under each tariff, then writes a CSV report you can open in LibreOffice or Numbers.

## Features

- Half-hourly comparison using your actual grid import, export, solar generation, and battery usage
- Supports Octopus Tracker (actual per-slot prices), Go, Go Faster, Agile, Cosy, Economy 7, Ofgem SVT price cap, E.ON, EDF, and Scottish Power
- Export revenue comparison: Octopus Outgoing 12p, Agile Outgoing, SEG minimum, SEG typical
- Octopus Agile prices fetched automatically from the public API (no credentials needed)
- Reports generated as CSV, auto-opened in LibreOffice (Numbers fallback)
- Schedulable actions: generate a report, update Agile price data
- Menu items for on-demand use in Indigo

## Requirements

- Indigo 2025.2 or later (Python 3.13)
- [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) v4.6+ (provides the half-hourly energy database)
- LibreOffice or Numbers (optional, for auto-opening reports)

## Installation

1. Go to the [Releases](https://github.com/Highsteads/TariffAnalyser/releases) page and download `TariffAnalyser.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `TariffAnalyser.indigoPlugin`
3. Double-click `TariffAnalyser.indigoPlugin` — Indigo will install it automatically

## Credentials

TariffAnalyser does not require any API keys or credentials. The Octopus Energy Agile price API is fully public and requires no authentication.

See `Contents/Server Plugin/secrets_example.py` for details.

## Output

Reports are saved to:
```
/Library/Application Support/Perceptive Automation/TariffAnalyser/
```

Each report is a CSV named `tariff_report_YYYYMMDD_HHMMSS.csv`.

## Usage

### Menu Items (Indigo → Plugins → Tariff Analyser)

| Menu item | What it does |
|---|---|
| Run Tariff Comparison Report | Opens a dialog to choose date range, generates and optionally opens the report |
| Export Raw Half-Hourly Data | Dumps the entire timeseries as a flat CSV for external analysis |
| Update Octopus Agile Price Data | Fetches missing Agile prices from the Octopus public API |
| Show Data Coverage | Logs earliest and latest data dates plus row count |
| Open Last Report | Re-opens the most recently generated report |
| Show Plugin Info | Displays plugin version and path information |

### Schedulable Actions

| Action | Description |
|---|---|
| Generate Tariff Comparison Report | Generates a report for the last N days (30/60/90/180/365) |
| Update Octopus Agile Price Data | Fetches missing Agile prices |

## Tariffs Covered

### Import

| Key | Tariff | Type |
|---|---|---|
| tracker | Octopus Tracker | Actual per-slot prices from DB |
| go | Octopus Go | 5h cheap window 00:30–05:30 |
| go_faster | Octopus Go Faster | 6h cheap window 23:30–05:30 |
| agile | Octopus Agile | Half-hourly variable, auto-fetched |
| cosy | Octopus Cosy | Two 3h cheap windows + peak |
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

Accessed via Indigo → Plugins → Tariff Analyser → Configure:

| Field | Default | Description |
|---|---|---|
| Timeseries DB path | Auto (SigenEnergyManager prefs) | Path to energy_timeseries.db |
| Output folder | Auto (/Library/.../TariffAnalyser) | Where CSV reports are saved |
| Open report after scheduled run | Off | Auto-open in LibreOffice/Numbers |
| Octopus region | F (North East England) | Used for Agile price lookups |
| Export tariff | Octopus Outgoing 12p | Applied to all import tariff comparisons |
| Default date range | Last 30 days | Default for scheduled action |

## Author

CliveS & Claude Sonnet 4.6 — Medomsley, County Durham, England

## Licence

Copyright 2026 CliveS. All rights reserved.
