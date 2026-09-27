---
title: Home
nav_order: 1
---

# Tariff Analyser for Indigo

This plugin lets [Indigo](https://www.indigodomo.com) work out what your electricity would have cost on each of eleven UK tariffs, using the energy your house really bought, sold and made, half an hour at a time. It writes the answer as a web page and opens it in your browser.

It reads the half-hourly record of your home's energy that my [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) plugin keeps for a Sigenergy solar and battery system, so you need that plugin running first.

## What it does for you

- **Ranks the tariffs** — the prices you actually paid, named after the tariff you were on, against Octopus Go, Go Faster, Agile, Cosy and Flux, Economy 7, the Ofgem price cap, and typical fixed deals from E.ON Next, EDF and Scottish Power — by what the last week, month or year would have cost you on each.
- **Compares them fairly.** Every tariff is priced over the same half-hours, so a tariff with gaps in its price data cannot come out cheapest just because some of your use was never counted.
- **Shows what your solar has saved** today, yesterday, this week, this month and this year, with a projection for a whole year.
- **Fetches Agile prices by itself** from Octopus's public price list, which needs no account.
- **Runs from a schedule** as well as the menu, so a report can be ready each morning.
- **Collects your Octopus meter readings each night** at 2am, if you give it your Octopus details, and keeps one line per day in the energy database.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and run your first report | [Getting started](getting-started.md) |
| Know what each report shows | [Your reports](what-it-shows.md) |
| See which tariffs it compares, and at what prices | [The tariffs it compares](tariffs.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Run reports from a schedule or an action group | [Actions](actions.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/TariffAnalyser/releases/latest).
