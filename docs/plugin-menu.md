---
title: The plugin menu
nav_order: 8
---

# The plugin menu

These are under **Plugins → Tariff Analyser**.

| Menu item | What it does |
|---|---|
| **Energy Summary (today / yesterday / week / month / year)** | Makes the Energy Summary and opens it in your browser. [Your reports](what-it-shows.md) explains what it shows. |
| **Tariff Comparison (which tariff would be cheapest?)** | Asks for a **Comparison period** — the last 7, 14, 30, 60, 90, 180 or 365 days, ending yesterday — then, when you click **Run Comparison**, fetches any Agile prices it needs, makes the report and opens it in your browser. If your energy record starts later than the period, the report starts from the first day with data. |
| **Test Octopus API Connection** | Checks the plugin can reach Octopus's price list and find the Agile tariffs, for buying and for selling, in your region. It writes to the Event Log the tariff it found for each, the dates of the Agile prices it has saved, and whether your Octopus meter details are set, then finishes with **PASSED** or **issues found — see warnings above**. It starts with the same details as Show Plugin Info, so the whole result is ready to paste into a forum post. |
| **Toggle Timestamps in Log (on/off)** | Every line the plugin writes to the log starts with the time to the thousandth of a second. This turns that off or on. It stays as you leave it. |
| **Show Plugin Info** | Writes the plugin's version and details of your Mac and Indigo to the log, with where the plugin finds the energy database, where it keeps the Agile prices and saves the reports, your region, where your Octopus details came from, the time of the nightly collection, and whether timestamps are on. It is useful to include if you ask for help on the Indigo forum. |
