---
title: The tariffs it compares
nav_order: 4
---

# The tariffs it compares

The Octopus tariffs use real prices. The first row uses the price SigenEnergyManager recorded for each half-hour, which is the price you actually paid. Agile, Go, Cosy, Flux and Economy 7 use the prices Octopus published for your region, as they stood on each day of the period, so a price change part way through is counted from the moment it happened. The Ofgem cap and the fixed deals from other suppliers use typical prices written into the plugin, last checked on 2 May 2026. Treat those as a guide, not as your exact contract — the report prints the date they were checked.

The standing charges are real for every Octopus tariff. The first row uses the standing charge SigenEnergyManager recorded for each day, and the other Octopus tariffs use the standing charge Octopus publishes for your region, day by day.

All prices include VAT.

## Import tariffs

These are the tariffs you buy electricity on. The names are as they appear in the report.

The first row is named after the tariff you were on, such as **Octopus Tracker (actual)** or **Octopus Flux (actual)**. The plugin takes the name from SigenEnergyManager's Tariff Monitor and checks it against the pattern of the recorded prices — one price a day for Tracker, a few bands a day for Flux or Go, a new price every half-hour for Agile. If the name does not fit the prices it shows **Your tariff (actual)**, and if your tariff changed during the period it shows **Your tariffs (actual, mixed)** and the report says when it changed. Its standing charge is the one SigenEnergyManager recorded for each day. SigenEnergyManager's older records have no standing charge, and for those days the plugin uses Octopus's figure for the tariff the row is named after or, failing that, 61.64p a day. The report says which days those were.

| Tariff | Unit price | Standing charge |
|---|---|---|
| **Your tariff (actual)** | The price SigenEnergyManager recorded for each half-hour | The one SigenEnergyManager recorded for each day |
| **Octopus Go** | Octopus's published prices for your region: a cheap rate from 12:30am to 5:30am | Octopus's figure for your region |
| **Octopus Agile** | Octopus's published price for each half-hour in your region, capped at 100p | Octopus's figure for your region |
| **Octopus Cosy** | Octopus's published prices for your region: cheap from 4am to 7am, 1pm to 4pm and 10pm to midnight, dearest from 4pm to 7pm | Octopus's figure for your region |
| **Octopus Flux** | Octopus's published prices for your region: cheap from 2am to 5am, dearest from 4pm to 7pm | Octopus's figure for your region |
| **Economy 7 (Octopus Flexible)** | Octopus's day and night prices for its Flexible tariff on a two-rate meter, with the night rate from 12:30am to 7:30am | Octopus's figure for your region |
| **Ofgem Price Cap (SVT)** | 24.5p at all times | 61.64p a day |
| **E.ON Next Fixed (typical)** | 24p at all times | 60p a day |
| **EDF Fixed (typical)** | 24p at all times | 60p a day |
| **Scottish Power Fixed (typical)** | 24p at all times | 60p a day |

Octopus publishes the hours of each band with its prices, except for Economy 7, whose night hours depend on your meter. The plugin assumes 12:30am to 7:30am and the report says so.

The plugin fetches Octopus's unit prices and standing charges from the same public price list as the Agile prices, which needs no account, and keeps them in its own database, asking again at most once a day for a period it already holds. If it cannot reach Octopus, the Event Log says which tariff it could not fetch, and the plugin uses the prices it fetched before or, failing that, its own. Its own are Octopus's prices for North East England, paying by direct debit, on 5 October 2026:

| Tariff | The plugin's own prices |
|---|---|
| **Octopus Go** | 8.21p from 12:30am to 5:30am, 28.31p the rest of the day |
| **Octopus Cosy** | 11.90p in the three cheap windows, 36.38p from 4pm to 7pm, 24.25p the rest of the day |
| **Octopus Flux** | 13.92p from 2am to 5am, 32.48p from 4pm to 7pm, 23.19p the rest of the day |
| **Economy 7 (Octopus Flexible)** | 13.72p at night, 31.65p by day |
| **Octopus Flux Export** | 4.21p from 2am to 5am, 27.69p from 4pm to 7pm, 9.71p the rest of the day |

The report says when any half-hours were priced with these, and its standing charges are Octopus's figures for North East England on 27 September 2026 — Go 63.22p, Agile 70.05p, and Cosy and Flux 61.52p a day.

## Export tariffs

These are the tariffs you sell electricity on.

- **Your tariff (actual)** is paid for export at the price SigenEnergyManager recorded for each day — the flat Outgoing price while you were on it, and on a banded tariff such as Flux Export the day's export earnings divided by what you sold. A day with no recorded price uses the export tariff chosen in the settings, and the report says how much of your export that covered.
- **Octopus Flux** is always paid at Octopus Flux Export prices, because Octopus sells Flux only as an import and export pair.
- **Every other tariff** is paid at the export tariff you choose in the settings, so the ranking shows the difference the import prices make.

| Choice in the settings | Price |
|---|---|
| **Octopus Outgoing 12p flat** | 12p for every unit sold |
| **Octopus Agile Outgoing (variable)** | Octopus's published export price for each half-hour in your region |
| **Octopus Flux Export (banded)** | Octopus's published Flux Export prices for your region: dearest from 4pm to 7pm |
| **SEG low rate (illustrative 1.63p)** | 1.63p for every unit sold |
| **SEG typical rate (illustrative 7.5p)** | 7.5p for every unit sold |

SEG is the Smart Export Guarantee, the scheme that obliges larger suppliers to pay for the electricity you sell. Ofgem sets no minimum price for it, so the two SEG choices are only examples of a low and a typical offer, to show what selling might earn away from Octopus.
