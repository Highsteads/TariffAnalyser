# Tariff Analyser for Indigo

**See what your own half-hourly electricity use would have cost on eleven UK tariffs, from inside Indigo.**

**Version:** 1.9.5 | **Author:** CliveS & Claude | **Needs:** Indigo 2022.1 or later and SigenEnergyManager 4.6 or later

**[Read the full guide](https://highsteads.github.io/TariffAnalyser/)** — setting up, what the reports show, and what to do when something goes wrong.

---

## What it does

This plugin lets [Indigo](https://www.indigodomo.com) price the energy your house really bought, sold and made, half an hour at a time, on each of eleven UK tariffs, and shows you the answer as a web page in your browser. It reads the record of your home's energy that my [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) plugin keeps for a Sigenergy solar and battery system.

- **Ranks the tariffs** — Octopus Tracker, Go, Go Faster, Agile, Cosy and Flux, Economy 7, the Ofgem price cap, and typical fixed deals from E.ON Next, EDF and Scottish Power — by what the last 7 to 365 days would have cost you on each, with a month-by-month breakdown.
- **Compares them fairly.** Every tariff is priced over the same half-hours, with the standing charge for those half-hours only, so a tariff with gaps in its prices cannot come out cheapest just because some of your use was never counted.
- **Prices your exports** at Octopus Outgoing 12p, Agile Outgoing, or the Smart Export Guarantee minimum or typical rate, whichever you choose.
- **Shows what your solar has saved** today, yesterday, this week, this month and this year, with a projection for a whole year.
- **Fetches Agile prices by itself** from Octopus's public price list, which needs no account.
- **Runs from a schedule** as well as the Plugins menu, so a report can be ready each morning.
- **Collects your Octopus meter readings each night** at 2am, if you give it your Octopus details, and keeps one line per day, gas included, in the energy database.

## What it works with

It needs [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) 4.6 or later, running on the same Mac, because that is where the half-hourly record of your energy comes from. The reports need no Octopus account. The nightly collection of meter readings needs an Octopus API key and your meter numbers.

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/TariffAnalyser/releases/latest) and download `TariffAnalyser.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `TariffAnalyser.indigoPlugin`
3. Double-click `TariffAnalyser.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. Open **Plugins → Tariff Analyser → Configure**, set **Octopus region (for Agile prices)** to your area's letter and **Export tariff to use in comparisons** to your export tariff, and click **Save**. The guide's [Settings](https://highsteads.github.io/TariffAnalyser/settings.html) page has the table of region letters.
2. Choose **Plugins → Tariff Analyser → Tariff Comparison (which tariff would be cheapest?)**, pick a period and click **Run Comparison**. The report opens in your browser.
3. If you want the nightly collection of your meter readings, fill in your Octopus API key and meter numbers in the same settings, or in `IndigoSecrets.py` as the guide explains.

The [full guide](https://highsteads.github.io/TariffAnalyser/) goes through each step, explains every setting and every figure in the reports, and covers what to do if something does not work.

## What's new

**v1.9.5** — The plugin no longer fails to start when Indigo's server is slow to answer, such as when several plugins restart at once. It now keeps trying until the server answers and logs one warning in the meantime.

**v1.9.4** — The note inside the plugin of where its code lives on GitHub uses the same spelling as other Indigo plugins. Nothing else changed.

**v1.9.3** — The **About** item in the Plugins menu opens this project's page. It went nowhere before.

Every version is listed in the [version history](https://highsteads.github.io/TariffAnalyser/changelog.html).

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
