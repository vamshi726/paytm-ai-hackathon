# Saathi AI Support — 9-Slide Presentation

> **Presentation note:** Saathi is a local prototype. Its transaction actions are simulated, and it has not been measured on a production support workload. The impact estimate on Slide 9 is an explicit example scenario, not a measured result.

## Slide 1 — Saathi: Faster, Safer Payment Support

**On-slide**
- AI-assisted support for payment and recharge issues
- Evidence-grounded answers with clear case tracking
- Human review by email for high-risk actions

**Speaker notes**
Saathi is a Paytm-inspired support prototype. It combines deterministic checks against local customer and transaction records with retrieval from support playbooks. AI helps phrase the response, but it does not decide transaction outcomes or approve financial actions.

**Visual suggestion:** Product name, support chat mock-up, and a simple “Investigate → Explain → Escalate safely” tagline.

## Slide 2 — The Support Challenge

**On-slide**
- Routine questions can consume staff time when every case is handled manually.
- Important facts may be spread across customer, transaction, bank, and gateway records.
- High-risk requests need controlled human review—not an automatic action.
- Customers need a clear status and next step while review is pending.

**Speaker notes**
The goal is not to remove human judgment. It is to automate safe, repeatable investigation and communication, while reserving human attention for ambiguous or high-risk cases.

**Visual suggestion:** A support queue with repetitive routine cases alongside a few high-risk cases.

## Slide 3 — What Saathi Does

**On-slide**
- Classifies the customer’s issue.
- Checks local customer and transaction evidence.
- Retrieves relevant procedures from the local Markdown playbooks.
- Explains verified outcomes in customer-friendly language.
- Requests an email decision for configured high-risk cases.

**Speaker notes**
Example prototype routes include a completed transaction, a failed payment with reversal already pending, a pending recharge, a possible duplicate charge, and a suspected unauthorized transaction. Unsupported or unclear issues request more details rather than inventing a resolution.

**Visual suggestion:** Five issue cards grouped into “automated response,” “need more details,” and “human review.”

## Slide 4 — Customer-to-Resolution Flow

**On-slide**
1. Customer describes the issue in chat.
2. Saathi investigates records and retrieves relevant playbook guidance.
3. Low-risk cases receive a grounded response.
4. High-risk cases create a pending approval and send an email.
5. The case and chat update when the approver replies—or when the 20-minute window expires.

**Speaker notes**
The customer sees the pending state while the service polls the inbox. The operations dashboard is for monitoring; approval and rejection happen through an authorized email reply, not dashboard controls.

**Visual suggestion:** Use the quick flowchart in [overview.md](../diagrams/overview.md).

## Slide 5 — Technology Stack

**On-slide**
- **Frontend:** React, TypeScript, Vite
- **API and storage:** Python, FastAPI, SQLite
- **Workflow orchestration:** LangGraph
- **RAG:** LangChain documents and text splitters; local Markdown retriever with Chroma or an offline similarity fallback
- **Response phrasing:** LangChain OpenAI integration
- **Approval channel:** SMTP for sending and IMAP for reading email replies
- **Validation:** pytest and TypeScript/Vite build

**Speaker notes**
The knowledge source is the project’s local Markdown playbooks. OpenAI is used to phrase a response from the verified outcome and retrieved text; deterministic code handles classification, transaction lookups, approval policy, and execution records.

**Visual suggestion:** Layered stack diagram: Chat UI → FastAPI/LangGraph → local records + playbooks → email.

## Slide 6 — How LangGraph and RAG Work Together

**On-slide**
- **LangGraph:** Triage → investigate → resolve from evidence → compose response.
- **LangChain RAG:** Markdown → `Document` chunks → retriever → relevant excerpts.
- **Grounding:** The response prompt receives the verified outcome and retrieved excerpts.
- **Decision boundary:** The deterministic resolution agent—not the language model—decides whether human approval is required.

**Speaker notes**
The retriever uses the local playbooks only. Chroma can persist the local vector index; an offline similarity fallback keeps retrieval available without it. OpenAI does not receive authority to approve a refund or change transaction state.

**Visual suggestion:** Show LangGraph nodes, with the retrieval branch feeding evidence to the investigation and response steps.

## Slide 7 — Email Approval and Safety

**On-slide**
- Request email includes a unique approval ID and a 20-minute deadline.
- Only configured approver email addresses can decide.
- Reply with the ID and `APPROVED` or `REJECTED`; a comment is optional.
- Inbox polling runs every 10 seconds and checks the mail server’s received time.
- Approval records the reviewer and comment; rejection or timeout performs no action.

**Speaker notes**
The poller checks for email before expiring an approval. A reply received before the deadline can still be applied if a polling cycle reads it just afterward. The dashboard and chat refresh to show the final decision and any reviewer comment.

**Visual suggestion:** Email request → approver reply → validated decision → case update, with “20 minutes” shown above the timeline.

## Slide 8 — How to Run and Demo

**On-slide**
1. Configure `.env` with an OpenAI key and email/IMAP settings; enable `HITL_EMAIL`.
2. Install Python dependencies and start the API.
3. Install frontend dependencies and start Vite.
4. Try a routine issue, then try “I was charged twice ₹5,000.”
5. Reply to the approval email with its approval ID, decision, and optional comment.
6. Observe the updated case status, simulated execution record, and comment.

**Speaker notes**
Run from the repository root:

```powershell
pip install -r requirements.txt
uvicorn backend.src.main:app --reload --port 8000
```

In another terminal:

```powershell
npm install
npm run dev
```

For Gmail, IMAP must be enabled and the backend must remain running during the approval window. Do not put credentials in the presentation or share the `.env` file.

**Visual suggestion:** A short demo sequence with chat, approval email, and updated operations view.

## Slide 9 — Manual-Intervention Impact and Measurement

**On-slide**
- Routine, supported cases can be investigated and answered without a staff touch.
- Duplicate, fraud, ambiguous, or unsupported cases still need human attention or customer information.
- **Illustrative scenario:** If 60 of 100 cases qualify for safe automation, manual-handled case volume falls from 100 to 40—a **60% reduction** for that assumed case mix.
- This is a scenario, **not a measured Saathi result**. Actual reduction depends on the real mix of support cases.
- Measure: auto-resolution rate, human-review rate, clarification rate, reply latency, and incorrect-resolution rate.

**Speaker notes**
Use this formula for a pilot:

`Manual-intervention reduction = (baseline human-touch cases − post-launch human-touch cases) / baseline human-touch cases × 100%`

In the example, the baseline is 100 human-touch cases and 40 still require attention after automation: `(100 − 40) / 100 = 60%`. High-risk approvals remain human-reviewed; automation reduces investigation and handling effort but does not remove that approval step. Establish the baseline and validate the rate on a representative, audited case sample before making a real-world claim.

**Visual suggestion:** A 100-case bar split into 60 routine cases handled automatically and 40 cases still requiring attention, labeled “illustrative only.”
