# Clear finished IOUs removes linked ledger rows

Issue #37 specified no cascade deletes between IOUs and transactions, and that closing or reopening tracking must never erase cash events. During polish we added an explicit user-initiated cleanup path for **finished** IOUs (status **paid**, zero remaining).

**Clear finished IOUs** (settings) deletes each paid IOU and every transaction linked to it (opening movement and all repayments). **Unpaid** and **active** IOUs are never removed by this action. **Clear all transactions** skips IOU-linked rows so bulk ledger wipe cannot silently break open IOUs.

Normal IOU operations still preserve history: closing as unpaid, reopening, and deleting individual repayments adjust IOU state without cascade-deleting unrelated rows. The deliberate exception is the opt-in “clear finished” bulk cleanup when the user no longer wants paid IOU records or their ledger entries.

**Considered:** Keeping all IOU-linked transactions forever (original spec). Rejected for paid IOUs because users asked for a way to tidy settled arrangements without manual per-transaction deletion, which active IOU guards block.

**Consequences:** Glossary term **Finished IOU** in `CONTEXT.md`. Paid IOU history is recoverable only from backups, not from in-app undo.
