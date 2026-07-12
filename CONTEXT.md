# Finance Tracker

Personal finance tracking for day-to-day income, expenses, and investments, with amounts stored in CZK.

## Language

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
