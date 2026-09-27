---
title: The tariffs it compares
nav_order: 4
---

# The tariffs it compares

Two of the tariffs use real prices: the first row uses the price SigenEnergyManager recorded for each half-hour, which is the price you actually paid, and Agile uses the prices Octopus published for your region. The others use the typical published prices written into the plugin, which were last checked on 2 May 2026. Treat those as a guide, not as your exact contract — prices change, and the report prints the date they were checked.

The standing charges are real for every Octopus tariff. The first row uses the standing charge SigenEnergyManager recorded for each day, and Go, Agile, Cosy and Flux use the standing charge Octopus publishes for your region, day by day, so a price change part way through the period is counted from the day it happened.

All prices include VAT.

## Import tariffs

These are the tariffs you buy electricity on. The names are as they appear in the report.

The first row is named after the tariff you were on, such as **Octopus Tracker (actual)** or **Octopus Flux (actual)**. The plugin takes the name from SigenEnergyManager's Tariff Monitor and checks it against the pattern of the recorded prices — one price a day for Tracker, a few bands a day for Flux or Go, a new price every half-hour for Agile. If the name does not fit the prices it shows **Your tariff (actual)**, and if your tariff changed during the period it shows **Your tariffs (actual, mixed)** and the report says when it changed. Its standing charge is the one SigenEnergyManager recorded for each day. SigenEnergyManager's older records have no standing charge, and for those days the plugin uses Octopus's figure for the tariff the row is named after or, failing that, 61.64p a day. The report says which days those were.

| Tariff | Unit price | Standing charge |
|---|---|---|
| **Your tariff (actual)** | The price SigenEnergyManager recorded for each half-hour | The one SigenEnergyManager recorded for each day |
| **Octopus Go** | 7.5p from 12:30am to 5:30am, 24p the rest of the day | Octopus's figure for your region |
| **Octopus Agile** | Octopus's published price for each half-hour in your region, capped at 100p | Octopus's figure for your region |
| **Octopus Cosy** | 12p from 4am to 7am and from 1pm to 4pm, 38p from 4pm to 7pm, 26p the rest of the day | Octopus's figure for your region |
| **Octopus Flux** | 7.01p from 2am to 5am, 33p from 4pm to 7pm, 21p the rest of the day | Octopus's figure for your region |
| **Economy 7 (typical)** | 15p from 12:30am to 7:30am, 30p the rest of the day | 61.64p a day |
| **Ofgem Price Cap (SVT)** | 24.5p at all times | 61.64p a day |
| **E.ON Next Fixed (typical)** | 24p at all times | 60p a day |
| **EDF Fixed (typical)** | 24p at all times | 60p a day |
| **Scottish Power Fixed (typical)** | 24p at all times | 60p a day |

The plugin fetches Octopus's standing charges from the same public price list as the Agile prices, which needs no account, and keeps them for a day. If it cannot reach Octopus, the Event Log says which tariff it could not fetch, and the plugin uses the figures it fetched last time or, failing that, its own. Its own are Octopus's figures for North East England on 27 September 2026 — Go 63.22p, Agile 70.05p, and Cosy and Flux 61.52p a day.

## Export tariffs

These are the tariffs you sell electricity on. You choose one in the settings, and the report applies it to every import tariff, so the ranking shows the difference the import prices make.

| Choice in the settings | Price |
|---|---|
| **Octopus Outgoing 12p flat (actual)** | 12p for every unit sold |
| **Octopus Agile Outgoing (variable)** | Octopus's published export price for each half-hour in your region |
| **SEG Minimum (Ofgem floor - 1.63p)** | 1.63p for every unit sold |
| **SEG Typical (7.5p)** | 7.5p for every unit sold |

SEG is the Smart Export Guarantee, the scheme that obliges larger suppliers to pay for the electricity you sell. The minimum and typical figures show what selling would earn away from Octopus.
