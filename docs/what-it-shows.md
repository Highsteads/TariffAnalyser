---
title: Your reports
nav_order: 3
---

# Your reports

The plugin makes two reports. Each is a web page, saved in the output folder and opened in the default browser on the Mac that runs Indigo.

## The Tariff Comparison

This answers "which tariff would have been cheapest for the way my house really uses energy?" It covers the period you choose, ending yesterday.

### The top of the page

The first lines give the dates, the number of days, the number of half-hours with data, and the export tariff used. Below them are the totals for the period:

| Shown as | What it means |
|---|---|
| **Grid import** | The electricity you bought from the grid. |
| **Grid export** | The electricity you sold to the grid. |
| **Solar generated** | What your panels made. |
| **Home load** | What the house used. |
| **Self-sufficiency** | How much of what the house used did not come from the grid, as a percentage. |

### The tariff ranking

Each tariff has one row, cheapest at the top, marked ★, and dearest at the bottom, marked ✘.

| Column | What it means |
|---|---|
| **Total cost** | What the period would have cost on that tariff: what you bought, less what you sold, plus the standing charge. |
| **Import** | The cost of the electricity you bought. |
| **Export** | What the electricity you sold would have earned, at the export tariff chosen in the settings. It is the same for every tariff. |
| **Standing** | The daily standing charge for the period. |
| **vs actual** | How much cheaper or dearer the tariff is than the row for the prices you actually paid, which is marked **current** and named after the tariff you were on, such as **Octopus Flux (actual)**. |
| **Coverage** | How much of the period that tariff has a price for. |

A tariff with a price for less than half the period is not ranked. It appears greyed out below the others, marked **insufficient price data to rank**, with its coverage. This is usually Agile when its prices have not been fetched yet.

If your tariff changed during the period, a note above the table says what the recorded prices looked like and when they changed, such as one price a day to 17 September and time-of-use bands from 18 September.

If any tariff has gaps, a note above the table says what share of the period every tariff was compared over, and the pound figures are for that share. [How it works](how-it-works.md) explains why.

### The monthly breakdown

A second table gives the cost of energy on each tariff month by month, with the cheapest tariff each month highlighted. It leaves out standing charges, so it shows the difference the prices make on their own. A month with no half-hours that every tariff has a price for shows **no data**.

### The notes

The last section sets out the terms of the comparison: every tariff is given the same pattern of use, the prices other than yours and Agile are typical published prices with the date they were last checked, standing charges may differ from your contract, and all costs include VAT at 5%.

Because every tariff is given the same pattern of use, a tariff with a cheap night rate may do better in real life than the report shows, since you would likely charge the battery in the cheap hours.

The file is named after the dates and the time it was made, such as `tariff_comparison_2026-08-27_2026-09-25_20260926_081500.html`, so each report is kept.

## The Energy Summary

This answers "what has my solar saved me?" It has five cards: **Today** (so far), **Yesterday**, **This week** (from Monday), **This month** and **This year**. Each card shows:

| Shown as | What it means |
|---|---|
| **total saved** | What the solar and battery saved in that period — the electricity you did not have to buy, plus what you earned from selling. |
| **Solar generated** | What your panels made. |
| **Used at home** | The solar you kept rather than sold, and what share of the solar that was. |
| **Exported** | What you sold to the grid. |
| **Avoided import** | What you would have paid for the electricity your solar and battery supplied instead of the grid. |
| **Export revenue** | What you earned from selling. |
| **Would have paid** | What the house's use would have cost if you had bought every unit from the grid. |
| **Actually paid** | What you paid for the electricity you bought, less what you earned. If you earned more than you paid, it shows £0.00. |
| **Daily average saving** | The total saved divided by the days with data. |
| **Projected annual** | The daily average times 365. If the period has fewer days of data than calendar days, it says how many days it is based on. |

The prices come from the half-hourly price SigenEnergyManager recorded, which is what you actually paid. The top of the page names that tariff, worked out as the [tariffs page](tariffs.md) explains, and says so if it changed this year. Where SigenEnergyManager recorded no price, the summary uses 24.5p, the Ofgem price cap rate in the plugin. Export is priced at the flat rate of your chosen export tariff, and the top of the page gives its name and price, such as SEG Minimum at 1.63p. If you chose Agile Outgoing, which has no flat rate, it is counted at 12p and the page says so.

A card with no data for its period says **No data available**.

The file is named after the day, such as `savings_summary_2026-09-26.html`, so running it again the same day replaces that day's page.
