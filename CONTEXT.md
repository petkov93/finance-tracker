# Finance Tracker

Personal finance tracking for day-to-day income, expenses, and investments. Transaction amounts are stored in their native currency; dashboard and statistics present them in each user's default currency through display conversion.

## Language

**Default currency**:
The unit of account a user thinks in for dashboard balances and statistics.
_Avoid_: Display currency, home currency, preferred currency

**Transaction currency**:
The currency in which a transaction amount was actually paid or received.
_Avoid_: Native currency, native code, source currency, original currency field

**Display conversion**:
Presenting stored transaction amounts in a user's default currency without changing stored values.
_Avoid_: Display transform, UI conversion, reporting FX

**Statistics aggregation**:
Month and category series for the statistics charts, derived from display-converted transaction amounts.
_Avoid_: Chart building, analytics, reporting rollup, stats pipeline

**Currency conversion**:
Converting a monetary amount from one currency to another using a latest exchange rate.
_Avoid_: FX calc, money transform

**Conversion pair**:
The from-currency and to-currency chosen for a conversion.
_Avoid_: Currency tuple, pair settings

**Exchange rate**:
How many units of the to-currency equal one unit of the from-currency.
_Avoid_: FX rate, multiplier

**Default pair**:
The conversion pair shown when a user has no last-used pair stored (CZK → EUR).
_Avoid_: Initial pair, startup currencies

**Last-used pair**:
The conversion pair remembered after the user's most recent successful convert on the converter page.
_Avoid_: Recent pair, saved currencies
