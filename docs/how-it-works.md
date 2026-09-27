---
title: How it works
nav_order: 5
---

# How it works

You do not need to know any of this to use the plugin. It is here for anyone who likes to know what is going on.

## Where the numbers come from

SigenEnergyManager writes a line to its energy database every half hour: what the house bought from the grid, sold to it, made from the panels and used, and the Tracker price for that half-hour. Tariff Analyser reads those lines. It never talks to the inverter or the battery itself, and it changes nothing in your system.

For each tariff, it takes every half-hour in the period, works out that tariff's price for that half-hour, and multiplies it by what you bought. It does the same for what you sold, at your chosen export price, then adds the standing charge.

## Keeping the comparison fair

A tariff can only be priced for a half-hour if the plugin has a price for it. Agile prices might not have been fetched for part of the period, and SigenEnergyManager might not have recorded a Tracker price for a half-hour.

If each tariff were simply added up over the half-hours it has prices for, a tariff with gaps would look cheaper, because some of your use would never be counted. So the plugin prices every tariff over the same half-hours — the ones where every ranked tariff has a price — and charges the standing charge for those half-hours only, a forty-eighth of a day each.

- A tariff with prices for less than half the period is left out of the ranking and shown below it as **insufficient price data to rank**, so one tariff with few prices cannot shrink the comparison for all the others.
- When the half-hours compared are less than the whole period, the report says so and gives the share, and each tariff's **Coverage** column shows how much of the period it had prices for on its own.

## Agile prices

Octopus publishes Agile prices on its public price list, which needs no account or key. The plugin finds the current Agile tariff for your region, fetches the prices for the half-hours it does not already have, and keeps them in a small database in its own folder inside Indigo's Preferences folder. A published Agile price never changes, so a price once saved is kept, and later reports only fetch what is new.

Running a comparison from the Plugins menu fetches any missing Agile prices for that period first. The **Generate Tariff Comparison Report** action does not, so for a scheduled report, run **Update Octopus Agile Price Data** first, as the [Actions](actions.md) page explains.

## The nightly collection

If the plugin has an Octopus API key, then at 2am each night it collects the last seven days, ending yesterday, and writes one line per day into a daily summary in SigenEnergyManager's energy database. Octopus can take a few days to publish readings, particularly for export and gas, which is why it goes back a week each time. Each line holds:

- the day's energy from SigenEnergyManager's half-hourly record
- the readings from your Octopus meters, where you have given the plugin their details
- the day's cost on Tracker, and what it would have been on Go and Flux
- your gas use and its cost, if you have given it your gas meter's details

The two reports do not use this daily summary. It is there for anything else that reads the energy database. If you do not give the plugin an API key, it logs a warning at 2am and skips the collection, and the reports work as before.

## What goes in the log

Each comparison writes a short table of the ranking to the Indigo Event Log, along with the totals and where the report was saved. The nightly collection says when it starts and finishes, and a warning appears if it cannot find the energy database or an Octopus API key.

Every line the plugin writes starts with the time to the thousandth of a second, which helps when lining up events with other plugins. **Toggle Timestamps in Log (on/off)** in the plugin menu turns that off or on.
