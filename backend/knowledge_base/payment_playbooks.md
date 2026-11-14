# Saathi local issue-resolution playbooks

This is the only RAG knowledge source. These are synthetic prototype procedures, not banking policy.

## Failed UPI payment with debit
**Customer issue:** UPI payment failed but money was debited.

**Resolution instructions:** Retrieve transaction, bank and gateway statuses. If bank is `DEBIT_SUCCESS`, gateway is `FAILED`, and refund is `PENDING`, explain that reversal is pending. Do not promise an exact settlement time or create a manual refund automatically. Mark conflicting records for investigation.

## Duplicate UPI charge
**Customer issue:** Customer was charged twice for one payment.

**Resolution instructions:** Verify payment records and existing refunds. A financial adjustment is high risk. Gather evidence and create a human approval request for a simulated refund. Never execute it until approval is recorded.

## Unauthorized transaction or fraud
**Customer issue:** Customer does not recognise a transfer.

**Resolution instructions:** Record a security case and give safe guidance: secure UPI PIN and never share OTPs. Do not disclose fraud heuristics. Financial compensation requires human review.

## Pending recharge
**Customer issue:** Recharge or bill payment is pending.

**Resolution instructions:** Retrieve fulfillment and payment status. If gateway is pending, tell the customer the case is under monitoring. Do not report success or refund without confirmed local transaction evidence.

## Successful transaction status
**Customer issue:** Customer asks what happened to a completed payment.

**Resolution instructions:** Verify customer ownership and status, then share confirmed status and transaction reference. This low-risk answer can be automatic.
