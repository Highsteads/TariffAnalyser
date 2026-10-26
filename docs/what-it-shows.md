---
title: Your reports
nav_order: 3
---

# Your reports

The plugin makes two reports. Each is a web page, saved in the output folder and opened in the default browser on the Mac that runs Indigo.

## The Tariff Comparison

This shows what the same recorded imports and exports would cost at different prices. It does not simulate a different battery schedule or recommend a tariff switch. It covers the period you choose, ending yesterday.

### The top of the page

The first lines give the dates, the number of days, the number of half-hours with data, and the export tariff used. Below them are the totals for the period:

| Shown as | What it means |
|---|---|
| **Grid import** | The electricity you bought from the grid. |
| **Grid export** | The electricity you sold to the grid. |
| **Solar generated** | What your panels made. |
| **Home load** | What the house used. |

### The tariff ranking

Non-illustrative tariffs appear in cost order, with the lowest modelled cost marked by a star. Illustrative fixed-supplier and price-cap examples follow without a rank. If no priced intervals are shared, no tariff is ranked.

| Column | What it means |
|---|---|
| **Total cost** | What the period would have cost on that tariff: what you bought, less what you sold, plus the standing charge. |
| **Import** | The cost of the electricity you bought. |
| **Export** | What the electricity you sold would have earned on that tariff. Your own row uses the export price recorded for each day, Flux uses Flux Export, and the rest use the export tariff chosen in the settings. |
| **Standing** | The standing charge for the period, day by day. |
| **vs actual** | How much cheaper or dearer the tariff is than the row for the prices you actually paid, which is marked **current** and named after the tariff you were on, such as **Octopus Flux (actual)**. |
| **Coverage** | How many of the stored readings have a price for this tariff. A separate note gives the calendar coverage of the readings themselves. |

A tariff with a price for less than half the period is not ranked. It appears greyed out below the others, marked **insufficient price data to rank**, with its coverage. This is usually Agile when its prices have not been fetched yet.

If your tariff changed during the period, a note above the table says what the recorded prices looked like and when they changed, such as one price a day to 17 September and time-of-use bands from 18 September.

If any tariff has gaps, a note above the table says what share of the period every tariff was compared over, and the pound figures are for that share. [How it works](how-it-works.md) explains why.

### The monthly breakdown

A second table gives the cost of energy on each non-illustrative tariff month by month, with the cheapest tariff each month highlighted. It leaves out standing charges, so it shows the difference the prices make on their own. A month with no half-hours that every tariff has a price for shows **no data**.

### The notes

The last section sets out the terms of the comparison: every tariff is given the same pattern of use; Agile, Go, Cosy, Flux and Economy 7 use Octopus's published prices, and if any half-hours had to use the plugin's own prices it says which tariff and the date of those prices; the Ofgem cap and fixed deals use typical prices with the date they were last checked; which export price each row used; how a half-hour that spans a price change is split; where each tariff's standing charge came from, including any days SigenEnergyManager had no figure for; and that all costs include VAT at 5%.

Because every tariff is given the same pattern of use, a tariff with a cheap night rate may do better in real life than the report shows, since you would likely charge the battery in the cheap hours. That could change the order of the tariffs. Intervals crossing a price boundary are estimates, especially during deliberate charging or export.

The file is named after the dates and the time it was made, such as `tariff_comparison_2026-08-27_2026-09-25_20260926_081500.html`, so each report is kept.

## The Energy Summary

This answers "what has my solar saved me?" It has five cards: **Today** (so far), **Yesterday**, **This week** (from Monday), **This month** and **This year**. Each card shows:

| Shown as | What it means |
|---|---|
| **total saved** | What the house's use would have cost if you had bought every unit from the grid, minus what you actually paid. It is the sum of the three lines below it. |
| **Solar generated** | What your panels made. |
| **Solar used at home** (kWh) | The solar the house used, straight from the panels or stored in the battery, and what share of the house's use that was. Solar stored on an earlier day counts on the day it is used. |
| **Exported** | What you sold to the grid. |
| **Battery charged from the grid** | The energy the battery took from the grid. |
| **Solar used at home** (pounds) | What that solar would have cost to buy at the price of each half-hour. |
| **Solar exported** | What you earned selling solar, leaving out grid-charged battery energy sold back. |
| **Time-shifting (battery charged from the grid)** | Battery energy bought from the grid, valued when it was used or sold, less what it cost to buy. It can be negative on a day the battery charges for the next day. [How it works](how-it-works.md) explains how the plugin tells solar from grid energy in the battery. |
| **Would have paid** | What the house's use would have cost if you had bought every unit from the grid. |
| **Actually paid** | What you paid for the electricity you bought, less what you earned. If you earned more than you paid, it says **Actually earned**. |
| **Daily average saving** | The total saved divided by the days with data. |
| **Projected annual** | The daily average times 365. If the period has fewer days of data than calendar days, it says how many days it is based on. |

The prices come from the half-hourly price SigenEnergyManager recorded, which is what you actually paid. The top of the page names that tariff, worked out as the [tariffs page](tariffs.md) explains, and says so if it changed this year. Where SigenEnergyManager recorded no price, the summary uses 24.5p, the Ofgem price cap rate in the plugin; a recorded price of 0p is kept. Export is priced at the export price SigenEnergyManager recorded for each day. A day with none uses the flat rate of your chosen export tariff, and the top of the page gives its name and price, such as SEG low rate at 1.63p. If you chose Agile Outgoing or Flux Export, which have no flat rate, those days are counted at 12p and the page says so.

A card with no data for its period says **No data available**.

The file is named after the day, such as `savings_summary_2026-09-26.html`, so running it again the same day replaces that day's page.
