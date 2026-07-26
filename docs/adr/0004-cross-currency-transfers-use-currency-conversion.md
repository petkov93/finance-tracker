# Cross-currency Transfers use Currency conversion

Cross-currency Transfers between Bank accounts need a destination amount in the destination Bank account currency. We convert the source amount with the existing Currency conversion path (`convert` / exchange-rate snapshots), including unavailable and degraded-rate behaviour, rather than asking the user for a manual exchange rate or refusing cross-currency moves.

**Considered:** Manual rate entry per Transfer (more control, but a second FX UX and inconsistent with converter/display conversion). Rejected for v1 so Transfer FX stays one policy with the rest of the app.

**Consequences:** Destination credit equals the converted source amount (quantized to money precision). Same-currency Transfers skip conversion and credit the same amount.
