# Finance Tracker

Personal finance tracking for day-to-day income, expenses, and investments. Transaction amounts are stored in their Transaction currency; dashboard and statistics present them in each user's Default currency through Display conversion.

## Language

**Default currency**:
The unit of account a user thinks in for dashboard balances and statistics.
_Avoid_: Display currency, home currency, preferred currency

**Supported currency**:
A currency the app accepts for Default currency, Transaction currency, and currency conversion, from the rate source’s available set.
_Avoid_: Valid currency, allowed currency, known currency

**Common currencies**:
A fixed, product-curated subset of supported currencies shown first in currency pickers for quicker selection.
_Avoid_: Recommended currencies, popular currencies, weighted currencies, featured currencies

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

**Theme preference**:
The user's chosen appearance mode stored on their profile: Warm Ledger, Night Ledger, or System.
_Avoid_: Color scheme setting, UI mode, skin, dark mode toggle (as the only name for the whole feature)

**Warm Ledger**:
The light cream-paper appearance of the app.
_Avoid_: Light mode, default theme (unless describing the historical single look)

**Night Ledger**:
The same-family dark appearance companion to Warm Ledger.
_Avoid_: Dark mode (alone), inverted theme, generic slate dark

**System** (appearance):
Theme preference that resolves to Warm Ledger or Night Ledger from the operating system color scheme, including live updates while a tab is open.
_Avoid_: Auto theme, OS theme (as the stored preference value name — the stored value is `system`)

**IOU**:
A tracked lend or borrow arrangement between the user and a named counterparty, with an opening cash transaction and optional repayments.
_Avoid_: Loan record, debt entry, credit line

**Receivable**:
An IOU where the user lent money and is still owed the remaining amount.
_Avoid_: Lend IOU, money owed to me, asset IOU

**Payable**:
An IOU where the user borrowed money and still owes the remaining amount.
_Avoid_: Borrow IOU, money I owe, liability IOU

**Available balance**:
Cash position from all-time income minus expenses, display-converted to the user's default currency, including IOU-linked cash movements.
_Avoid_: Balance, net worth, total cash

**Total balance**:
Available balance plus open receivables minus open payables, each IOU amount display-converted to the user's default currency. Open IOU amounts use the latest exchange rate (same rate source as display conversion for today's date), not the opening or due date.
_Avoid_: Net worth, economic balance, adjusted balance

**Spending and income totals**:
Dashboard income and expense figures that exclude IOU-linked transactions; they reflect day-to-day earning and spending only.
_Avoid_: Real income, core expenses, non-IOU totals

**Finished IOU**:
A paid IOU — fully settled with zero remaining amount. Unpaid IOUs are closed but not finished.
_Avoid_: Closed IOU, completed loan, settled debt

**IOU start date**:
The date of the IOU opening transaction — when the lend or borrow cash movement was recorded.
_Avoid_: Created date, IOU opened at, inception timestamp

**IOU-linked transaction**:
A transaction tied to an IOU as its opening movement or a recorded repayment.
_Avoid_: Loan transaction, debt entry, IOU expense

**Spending statistics**:
Income, expense, and category breakdowns that exclude IOU-linked transactions, on both the dashboard pills and the statistics page.
_Avoid_: Core stats, non-IOU analytics, regular spending view
