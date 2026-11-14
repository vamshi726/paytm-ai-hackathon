import uuid
from datetime import datetime,timedelta
from fastapi import APIRouter,HTTPException
from .agents import TriageAgent,InvestigationAgent,ResolutionAgent
from .database import database,utc_now
from .rag import vector_store
from .schemas import ChatRequest
from .email_service import send_approval_email
from .openai_responses import OpenAIResponseAgent
from .telegram_service import send_approval_telegram
from .workflow import build_support_workflow
router=APIRouter(prefix="/api")
triage_agent,investigation_agent,resolution_agent=TriageAgent(),InvestigationAgent(vector_store),ResolutionAgent()
response_agent=OpenAIResponseAgent()
support_workflow=build_support_workflow(triage_agent,investigation_agent,resolution_agent,response_agent,database)
@router.post("/chat/message")
def chat(request:ChatRequest):
    case_id=request.case_id or f"CASE-{uuid.uuid4().hex[:8].upper()}"
    approval=None
    with database.connection() as conn:
        if not conn.execute("SELECT id FROM support_tickets WHERE id=?",(case_id,)).fetchone():database.create_ticket(conn,case_id,request.customer_id,request.message)
        conn.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?)",(str(uuid.uuid4()),case_id,"customer",request.message,utc_now()))
        workflow_result=support_workflow.invoke({"message":request.message,"case_id":case_id,"customer_id":request.customer_id,"connection":conn})
        triage=workflow_result["triage"];evidence=workflow_result["evidence"];outcome=workflow_result["outcome"];tx=evidence["transaction"]
        conn.execute("UPDATE support_tickets SET category=?,issue_type=?,transaction_id=?,risk_level=?,status=?,updated_at=?,resolution=? WHERE id=?",(tx["service_category"] if tx else "Unclassified",triage.issue_type,tx["id"] if tx else None,outcome["risk"],outcome["status"],utc_now(),outcome["reply"],case_id))
        if outcome["approval_required"]:
            approval_id=f"APR-{uuid.uuid4().hex[:8].upper()}"
            requested_at=utc_now()
            expires_at=(datetime.fromisoformat(requested_at)+timedelta(minutes=20)).isoformat()
            conn.execute("INSERT INTO approval_requests VALUES(?,?,?,?,?,?,?,?,?,?)",(approval_id,case_id,outcome["action"],outcome["risk"],"PENDING",requested_at,None,None,None,expires_at));database.log_activity(conn,case_id,"APPROVAL_REQUESTED",f"Human review requested: {outcome['action']}")
            approval={"id":approval_id,"status":"PENDING","action":outcome["action"],"expires_at":expires_at}
        conn.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?)",(str(uuid.uuid4()),case_id,"assistant",outcome["reply"],utc_now()))
    if approval:
        email_delivered,email_detail=send_approval_email(case_id,approval["id"],approval["action"],outcome["risk"],approval["expires_at"])
        telegram_delivered,telegram_detail=send_approval_telegram(case_id,approval["id"],approval["action"],outcome["risk"],approval["expires_at"])
        with database.connection() as conn:
            database.log_activity(conn,case_id,"EMAIL_NOTIFICATION",email_detail)
            database.log_activity(conn,case_id,"TELEGRAM_NOTIFICATION",telegram_detail)
        approval.update({"notification_sent":email_delivered or telegram_delivered,"email_notification_sent":email_delivered,"telegram_notification_sent":telegram_delivered})
    return {"case_id":case_id,"message":outcome["reply"],"status":outcome["status"],"risk_level":outcome["risk"],"approval":approval,"transaction":tx,"rag_sources":[x["source"] for x in evidence["playbooks"]]}
@router.get("/chat/history/{case_id}")
def history(case_id:str):
    with database.connection() as conn:return database.serialise(conn.execute("SELECT sender_type,message,created_at FROM chat_messages WHERE case_id=? ORDER BY created_at",(case_id,)))
@router.get("/cases")
def cases():
    with database.connection() as conn:return database.serialise(conn.execute("SELECT * FROM support_tickets ORDER BY updated_at DESC"))
@router.get("/cases/{case_id}")
def case(case_id:str):
    with database.connection() as conn:
        ticket=conn.execute("SELECT * FROM support_tickets WHERE id=?",(case_id,)).fetchone()
        if not ticket:raise HTTPException(404,"Case not found")
        return {"case":dict(ticket),"messages":database.serialise(conn.execute("SELECT sender_type,message,created_at FROM chat_messages WHERE case_id=? ORDER BY created_at",(case_id,))),"activities":database.serialise(conn.execute("SELECT * FROM case_activities WHERE case_id=? ORDER BY created_at",(case_id,))),"investigation":database.serialise(conn.execute("SELECT agent_name,tool_name,sanitized_output,created_at FROM investigation_logs WHERE case_id=? ORDER BY created_at",(case_id,))),"approvals":database.serialise(conn.execute("SELECT * FROM approval_requests WHERE case_id=?",(case_id,)))}
@router.get("/approvals")
def approvals():
    with database.connection() as conn:return database.serialise(conn.execute("SELECT a.*,t.category,t.transaction_id FROM approval_requests a JOIN support_tickets t ON a.case_id=t.id ORDER BY requested_at DESC"))
@router.get("/dashboard/summary")
def summary():
    with database.connection() as conn:
        total=conn.execute("SELECT count(*) FROM support_tickets").fetchone()[0];grouped={row[0]:row[1] for row in conn.execute("SELECT status,count(*) FROM support_tickets GROUP BY status")}
        return {"total":total,"open":grouped.get("Understanding issue",0)+grouped.get("Under investigation",0),"pending_approvals":conn.execute("SELECT count(*) FROM approval_requests WHERE status='PENDING'").fetchone()[0],"resolved":grouped.get("Resolved",0),"escalated":grouped.get("Escalated",0),"auto_resolution_rate":round((grouped.get("Resolved",0)/total*100) if total else 0)}
