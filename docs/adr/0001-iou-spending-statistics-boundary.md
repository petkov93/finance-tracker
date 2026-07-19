# IOU-linked transactions excluded from spending statistics

Issue #37 originally specified no change to statistics in v1 beyond tagging IOU flows with **Lending** and **Borrowing** categories. During implementation we found that treating lend/borrow cash movements like ordinary income and expenses made dashboard pills and statistics charts misleading — a 500 lend looked like day-to-day spending, and repayments inflated income.

We split **cash position** from **spending view**:

- **Available balance** and **Total balance** still include all IOU-linked transactions (opening movements and repayments), because they reflect actual cash flow and open debt.
- **Spending and income totals** on the dashboard and **Spending statistics** on the statistics page exclude IOU-linked transactions via `exclude_iou_linked_transactions`.

**Lending** and **Borrowing** categories are created on first IOU use (`get_or_create`), not seeded with default categories, and are hidden from the manual add/edit transaction category picker so users cannot create orphan loan entries outside the IOU flows.

**Considered:** Keeping statistics unchanged per the grilled spec. Rejected because the first lend/repay cycle immediately broke the usefulness of category charts for personal spending.

**Consequences:** Glossary terms **Spending and income totals** and **Spending statistics** in `CONTEXT.md`. Future statistics filters may still tag Lending/Borrowing separately, but the default view is spending-only.
