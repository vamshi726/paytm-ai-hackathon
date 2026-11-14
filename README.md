# Saathi

Paytm-inspired customer support prototype with simulated financial investigation and human approval workflows. It intentionally has **no sign-in, authentication, or authorization layer**, as requested; do not expose this prototype publicly.

The backend now lives in `backend/src`: `workflow.py` orchestrates deterministic triage, investigation, resolution, and response nodes with LangGraph. `rag.py` uses LangChain documents, text splitting, and a local retriever over Markdown in `backend/knowledge_base/*.md`; it uses local Chroma when available and an offline cosine-similarity fallback otherwise. `openai_responses.py` uses a LangChain prompt/model chain with the retrieved excerpts to phrase customer-facing replies. OpenAI does not decide transaction outcomes or approvals, and no web content or external RAG source is queried.

Approval decisions are accepted only from authorized approver email replies or the configured private Telegram bot chat; the dashboard is read-only for approvals. The background poller checks enabled channels every 10 seconds, processes replies using their server-received timestamp, and expires still-pending approvals only after checking for replies. A reply received before the 20-minute deadline remains valid even if a polling cycle processes it slightly later. Keep the backend running during the approval window.

## Run locally

1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` to your own key. `OPENAI_MODEL` selects the model (defaults to `gpt-4o-mini`). Keep `.env` private; chat messages sent for response phrasing are processed by OpenAI.
2. Create and activate a Python 3.11+ virtual environment, then run `pip install -r requirements.txt`.
3. Start the API from the project root: `uvicorn backend.src.main:app --reload --port 8000`.

   If your terminal is already inside the `backend` directory, use: `uvicorn src.main:app --reload --port 8000`.
4. Run `npm install`, then `npm run dev`.
5. Visit the Vite URL (normally `http://localhost:5173`).

Try these support messages:

- `Where is my ₹799 UPI reversal?`
- `I was charged twice ₹5,000`
- `I don’t recognize a ₹20,000 UPI transfer`

The generated SQLite database is `saathi.db`. The prototype makes no real financial changes.

Run the backend tests with `pytest backend/tests -q`.

## Email and Telegram approvals

The backend sends each approval request to email and Telegram, then polls for a reply for up to 20 minutes. A valid reply requires the approval ID and an explicit APPROVED or REJECTED decision; comments are optional. Only a sender listed in `HITL_APPROVER_EMAILS` (or `HITL_APPROVER_EMAIL`) can decide by email. Telegram decisions are accepted only from the configured private chat; group chats are not accepted. The operations dashboard displays status but cannot approve or reject.

For Gmail, enable IMAP in the mailbox settings and configure `IMAP_HOST=imap.gmail.com` and `IMAP_PORT=993`. The IMAP reader defaults to `SMTP_USERNAME` and `SMTP_PASSWORD`; Gmail commonly requires an app password when two-step verification is enabled. `smtp.gmail.com:587` is for sending only, not inbox polling. For Telegram, the approver must open the bot’s private chat and send `/start` before the bot can message them. After changing `.env`, restart the backend.

```env
HITL_EMAIL=true
HITL_TELEGRAM=true
HITL_APPROVER_EMAILS=lead@example.com,finance@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=approver@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=approver@example.com
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-private-chat-id
```

Reply to the email request with its approval ID in the subject and put `APPROVED` or `REJECTED` (optionally followed by a comment) at the top of the reply. In Telegram, send `APPROVED APR-...` or `REJECTED APR-...`, optionally followed by comments. Replies without a matching pending ID, a clear decision, or an authorized sender are ignored. Requests expire after 20 minutes; expiration never executes an action.
