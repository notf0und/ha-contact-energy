<p align="center">
  <img src="custom_components/contact_energy/brand/logo@2x.png" alt="Contact Energy" height="96">
</p>

# Contact Energy for Home Assistant

Brings your [Contact Energy](https://contact.co.nz) (New Zealand) account into Home Assistant:

- **Hourly electricity usage and cost in the Energy dashboard**, including the free hours of plans such as *Good Nights*, with all the history your account has.
- **Billing-period totals**: paid, free and total kWh plus cost since the last meter reading.
- **Account details**: balance, next bill amount and date, payment due, plan name, meter reading dates.
- **Gas** (when the account has a gas connection): monthly gas usage in the Energy dashboard, meter reading (with its history), reading dates and last month's usage.

It uses the same API as the Contact Energy app, signing in with your app email and password.

It is developed and tested on a *Good Nights* plan. If your plan (EV, time-of-use, prepay, ...) gives odd values, please [report it](#reporting-issues) with a diagnostics file.

## Installation

### HACS (recommended)

1. Make sure [HACS](https://hacs.xyz) is installed.
2. Open the repository in HACS:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=notf0und&repository=ha-contact-energy&category=integration)

3. Download **Contact Energy** and restart Home Assistant.

### Manual

Copy `custom_components/contact_energy` into your Home Assistant `config/custom_components/` folder and restart Home Assistant.

## Setup

1. **Settings → Devices & services → Add integration → Contact Energy**.
2. Enter the email and password you use for the Contact Energy app.
3. Choose whether to **fetch all historical usage** (default) or only the last 35 days.
4. If the login has several electricity connections (ICPs), pick one. Add the integration again for each other connection.

If the password changes, Home Assistant asks you to sign in again. **Reconfigure** on the integration lets you turn full history on or off.

## Energy dashboard

Usage is imported as hourly long-term statistics. It is not tied to an entity, so add it in **Settings → Dashboards → Energy → Electricity grid → Add consumption**:

| Statistic | Use as |
|-----------|--------|
| `Contact Energy - Electricity (<ICP>)` | Grid consumption; for costs choose *Use an entity tracking the total costs* → `Contact Energy - Electricity Cost (<ICP>)` |
| `Contact Energy - Free Electricity (<ICP>)` | A second grid consumption (free hours, no cost) |
| `Contact Energy - Gas (<gas ICP>)` | **Gas consumption** section → Add gas source; for costs choose *Use an entity tracking the total costs* → `Contact Energy - Gas Cost (<gas ICP>)` (needs gas rates, below) |

Gas usage is only available **per month**, so the whole month appears on the first day of the month in the dashboard. It is in **kWh**, the energy Contact bills you for, not the m³ the meter counts: natural gas carries about 10.5–11 kWh per m³, so e.g. 52 m³ ≈ 555 kWh. A month appears once it has ended.

### Gas cost

Home Assistant only offers *Use a static price* for sensors, not for imported statistics, and Contact Energy's API has no gas prices. So enter your rates in the integration's **Configure** (Settings → Devices & services → Contact Energy → ⚙): the **gas price** per kWh and, optionally, the **daily charge**, both including GST, from your bill. For example, a bill with *Living Smart 11.362 cents per kWh (incl. GST)*, a daily charge of *2.678 dollars per day* and Gas Industry Company fees of *3.243 cents per day* gives a price of `0.11362` and a daily charge of `2.71043`.

The integration then imports `Contact Energy - Gas Cost (<gas ICP>)`: each month's kWh × price, plus the days in the month × the daily charge. When your prices change, enter the new ones: they apply from the current month, and earlier months keep the rate they had (the first rate you enter also covers all earlier history). Clearing both fields stops the gas cost.

> [!NOTE]
> Contact Energy publishes usage 1–3 days late. Right after a meter reading the billing-period sensors (*Usage*, *Usage (free)*, *Total usage*, *Usage cost*) read 0 until the first day of the new period arrives; *Latest day usage* always shows the last day with data, and the *Previous period* sensors the last complete billing period.

The integration remembers each meter reading date as it changes. Until it has seen two, the previous period's start is estimated as the same day one month before the last reading (`estimated_start: true`). Today's and yesterday's bars stay empty until the data arrives, so look a few days back to see the latest usage. The **Usage data until** sensor shows the latest day available.

History is fetched gradually in the background: about 48 days per hour, newest first, until the start of your account's data. The **Fetch usage now** button fetches the next batch straight away.

## Entities

| Device | Entity | Notes |
|--------|--------|-------|
| Account | Account balance, Next bill amount, Payment due | NZD. *Payment due* lists recent payments as an attribute |
| Account | Next bill date, Payment due date | |
| Account | Plan | e.g. `Good Nights (Monday - Friday)` |
| Electricity | Usage, Usage (free), Total usage | kWh since the last meter reading (the billing period), with `period_start` and `data_until` attributes |
| Electricity | Usage cost | NZD since the last meter reading |
| Electricity | Previous period usage, Previous period usage (free), Previous period total usage, Previous period cost | The last complete billing period (previous reading date → day before the last reading), with `period_start`, `period_end`, `data_until`, `estimated_start` attributes |
| Electricity | Latest day usage, Latest day cost | The last day with data (`date`, `paid_kwh`, `free_kwh` attributes) |
| Electricity | Usage data until | Latest day with usage data |
| Electricity | Previous reading date, Next reading date | |
| Electricity | Meter reading | Disabled by default: only updated when the meter is read |
| Electricity | Fetch usage now | Button: fetch the next batch of usage |
| Gas | Meter reading, Previous reading date, Next reading date | Only with a gas connection |
| Gas | Usage last month | kWh (energy, not m³) for the last full month — the API has no daily gas data; `month` attribute |

Account details are refreshed hourly; usage is checked hourly.

## Upgrading from 1.0.x

1.1.0 is a rewrite. Upgrading needs no action:

- Entity ids and the statistic ids used by the Energy dashboard stay the same.
- The usage history moves from the *Usage* sensor's attributes (which bloated the database) to `.storage/contact_energy.<entry_id>`. The daily totals are migrated, and the hourly detail is re-fetched in the background.
- Monetary sensors now use `NZD` instead of `$`. Home Assistant may raise a repair about the unit change for their long-term statistics; accept it to update the unit.
- Gas entities are only created when the account has a gas connection.
- The gas meter reading changed from a *measurement* to a *total increasing* sensor, so its 1.0.x long-term statistics (stored as averages) no longer show in its history graph. They can be converted in the database: for each old row set `state = max` and `sum = state - <first reading>`.

## Reporting issues

Wrong numbers, errors, or a plan that isn't handled correctly (for example night or EV rates showing up as *free*)? **Please [open an issue on GitHub](https://github.com/notf0und/ha-contact-energy/issues/new/choose)** rather than sending a message on Reddit, the forums or email. Issues are the only place I track problems, and others with the same plan can find the answer there.

Attach a **diagnostics file**; it is usually all that is needed:

1. **Settings → Devices & services → Contact Energy**.
2. Open the **Electricity** device (or **Gas**, for a gas problem).
3. In the device's **⋮** menu, choose **Download diagnostics**. The same download is also in the integration entry's ⋮ menu.
4. Drag the downloaded `.json` file into the issue.

The file contains the integration's state plus fresh, unmodified responses from the Contact Energy API: your plan, the hourly usage of the latest day, two weeks of daily usage and recent gas months. That is how plans I don't have myself can be supported. Your email, password, addresses, ICP numbers and meter serial numbers are removed; the usage figures, costs and balances remain. Have a look before you upload it if you want to check.

For errors, debug logs help too:

```yaml
logger:
  logs:
    custom_components.contact_energy: debug
```

## Development

```bash
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
```

## Credits

Originally developed by [@codyc1515](https://github.com/codyc1515) — huge thanks for laying the foundation.

This project is not affiliated with Contact Energy. The Contact Energy name and logo are trademarks of Contact Energy Ltd.
