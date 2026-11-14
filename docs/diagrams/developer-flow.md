# Saathi developer flow

## Request, LangGraph, and RAG

```mermaid
flowchart TD
    START([Customer submits message]) --> HTTP[POST /api/chat/message]
    HTTP --> DB1[Open SQLite transaction<br/>create or load case and save customer message]
    DB1 --> GRAPH[Invoke support_workflow]

    subgraph LANGGRAPH["LangGraph support graph"]
        TRIAGE[TriageAgent.classify]
        INVESTIGATE[InvestigationAgent.investigate]
        RESOLVE[ResolutionAgent.resolve]
        PHRASE[OpenAIResponseAgent.respond]
        TRIAGE --> INVESTIGATE --> RESOLVE --> PHRASE
    end

    GRAPH --> TRIAGE
    INVESTIGATE --> TOOLS[Verify customer and transaction records]
    INVESTIGATE --> RETRIEVE[MarkdownVectorStore retriever]

    subgraph RAG["Local LangChain RAG"]
        MD[backend/knowledge_base/*.md]
        DOC[LangChain Document]
        SPLIT[RecursiveCharacterTextSplitter]
        INDEX[Local Chroma index<br/>or offline cosine fallback]
        SEARCH[Retrieve relevant chunks and sources]
        MD --> DOC --> SPLIT --> INDEX --> SEARCH
    end

    RETRIEVE --> SEARCH
    SEARCH --> PHRASE
    TOOLS --> RESOLVE
    RESOLVE --> PHRASE
    PHRASE --> PROMPT[LangChain prompt plus verified outcome<br/>and retrieved excerpts]
    PROMPT --> DB2[Update case and save assistant reply]
    DB2 --> APPROVAL{approval_required?}
    APPROVAL -- No --> RETURN[Return response to chat]
    APPROVAL -- Yes --> SAVE[Create APR ID and persist PENDING<br/>requested_at and 20-minute expires_at]
    SAVE --> SMTP[Send approval email using SMTP]
    SMTP --> LOG[Log email delivery result]
    LOG --> RETURN_PENDING[Return pending status and approval ID]
```

## Email decision and timeout

```mermaid
flowchart TD
    START([FastAPI lifespan starts]) --> WORKER[ApprovalReplyPoller thread]
    WORKER --> TICK[Poll cycle every 10 seconds]
    TICK --> PENDING{Any PENDING approval?}
    PENDING -- No --> WAIT[Wait for next cycle]
    PENDING -- Yes --> ENABLED{HITL_EMAIL enabled?}
    ENABLED -- No --> EXPIRE_CHECK
    ENABLED -- Yes --> IMAP[Fetch new inbox UIDs over IMAP]
    IMAP --> FILTER[Check sender against configured approver addresses]
    FILTER --> PARSE[Parse approval ID, decision, and optional comments]
    PARSE --> VALID{One matching ID and clear decision?}
    VALID -- No --> IGNORE[Log ignored reply; keep waiting]
    VALID -- Yes --> TIME[Use IMAP INTERNALDATE as received_at]
    TIME --> WINDOW{Pending and received_at in approval window?}
    WINDOW -- No --> IGNORE
    WINDOW -- Approved --> APPROVE[Store APPROVED, reviewer, and comments]
    APPROVE --> EXEC[Write one simulated execution record]
    EXEC --> UPDATE[Update ticket, chat history, and activity]
    WINDOW -- Rejected --> REJECT[Store REJECTED and reviewer comments]
    REJECT --> ESCALATE[Escalate ticket; do not execute action]
    IGNORE --> EXPIRE_CHECK
    UPDATE --> EXPIRE_CHECK
    ESCALATE --> EXPIRE_CHECK
    EXPIRE_CHECK{Still pending and deadline reached?}
    EXPIRE_CHECK -- Yes --> EXPIRE[Mark EXPIRED; no action]
    EXPIRE_CHECK -- No --> WAIT
    EXPIRE --> WAIT
    WAIT --> TICK
```

### Key implementation points

- The backend worker polls email before expiring approvals. A reply received before `expires_at` can still be applied if IMAP returns it shortly after the deadline.
- Email authorization uses the configured approver address list. The approval ID must match a pending request, and the decision must be explicit.
- `approval_service.apply_channel_decision` stores reviewer comments in `approval_requests`, includes them in the resulting case/chat message, and uses the approval ID as the execution idempotency key.
- Rejections and timeouts never create execution records. Approved actions are simulated in SQLite; no external payment operation is performed.
- The chat and operations UI refresh case state while an approval is pending so the final decision and comments become visible without a manual page reload.
