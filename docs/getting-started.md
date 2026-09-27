---
title: Getting started
nav_order: 2
---

# Getting started

This takes a few minutes, and you only do it once.

## What you need

- Indigo 2022.1 or later.
- My [SigenEnergyManager](https://github.com/Highsteads/SigenEnergyManager) plugin, version 4.6 or later, installed and running on the same Mac. It records your home's energy every half hour, and that record is what Tariff Analyser prices. It needs to have run for at least one half-hour before there is anything to compare.
- A web browser to read the reports. Any Mac already has one.

You do not need an Octopus account for the reports. The Octopus details in the plugin's settings are only for the nightly collection of your meter readings, which the [Settings](settings.md) page explains.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/TariffAnalyser/releases/latest) and download `TariffAnalyser.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `TariffAnalyser.indigoPlugin`
3. Double-click `TariffAnalyser.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes.

## 2. Choose your region

Open **Plugins → Tariff Analyser → Configure**.

Set **Octopus region (for Agile prices)** to the letter for your area, because Agile prices differ from one region to the next. The [Settings](settings.md) page has a table of the letters and how to find yours.

Set **Export tariff to use in comparisons** to the export tariff you are on, or the one you are thinking of. Leave everything else as it is to start with, and click **Save**.

## 3. Run your first comparison

1. Choose **Plugins → Tariff Analyser → Tariff Comparison (which tariff would be cheapest?)**.
2. Pick a **Comparison period**. Last 30 days is a good start.
3. Click **Run Comparison**.

The plugin fetches any Agile prices it does not already have, prices every tariff, and opens the report in your browser. The first run can take a little longer while it fetches the Agile prices.

## 4. Check it works

The report opens with your energy totals at the top and the tariffs ranked cheapest first. The Indigo Event Log has the same ranking in a short table, and a line saying where the report was saved.

Now choose **Plugins → Tariff Analyser → Energy Summary (today / yesterday / week / month / year)** to see what your solar has saved.

If the dialog shows a message instead of a report, the [When something goes wrong](troubleshooting.md) page goes through each one.
