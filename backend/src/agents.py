import re,sqlite3,uuid
from dataclasses import dataclass
from typing import Any
from .database import SaathiDatabase,utc_now
from .rag import MarkdownVectorStore
@dataclass
class TriageResult: issue_type:str; transaction_id:str|None
class TriageAgent:
    def classify(self,message:str)->TriageResult:
        upper=message.upper(); ids=re.findall(r"(?:TXN|RCG)-[A-Z0-9-]+",upper); lower=message.lower()
        issue="Unauthorized transaction" if any(x in lower for x in ["fraud","don't recognize","dont recognize","unauthorised","unauthorized"]) else "Duplicate charge" if any(x in lower for x in ["twice","duplicate"]) else "Recharge or bill payment status" if any(x in lower for x in ["recharge","bill"]) else "Failed payment with debit" if any(x in lower for x in ["failed","deduct","debited","reversal"]) else "Payment status inquiry"
        return TriageResult(issue,ids[0] if ids else None)
class InvestigationAgent:
    def __init__(self,store:MarkdownVectorStore): self.store=store
    def find_transaction(self,message,explicit):
        if explicit:return explicit
        text=message.lower()
        if any(x in text for x in ["20,000","20000","fraud","recognize"]):return "TXN-20000-FRAUD"
        if any(x in text for x in ["5,000","5000","twice","duplicate"]):return "TXN-5000-DUP"
        if any(x in text for x in ["799","deduct","debited","reversal","failed"]):return "TXN-799-REV"
        if "499" in text:return "TXN-499-UPI"
        if "recharge" in text:return "RCG-299"
        return None
    def investigate(self,conn:sqlite3.Connection,database:SaathiDatabase,case_id,customer_id,message,triage):
        playbooks=self.store.search(f"{triage.issue_type} {message}")
        for item in playbooks: conn.execute("INSERT INTO investigation_logs VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),case_id,"Investigation Agent","Local Markdown RAG",f"{item['source']} (relevance {item['score']})",utc_now()))
        txid=self.find_transaction(message,triage.transaction_id); customer=database.customer_tool(conn,customer_id); tx=database.transaction_tool(conn,txid) if txid else None
        checks=[("Customer Database Tool","Customer record verified" if customer else "Customer not found")]
        if tx: checks += [("Transaction History Tool",f"{tx['id']} is {tx['transaction_status']}"),("Bank Status Tool",f"Bank: {tx['bank_status']}"),("Payment Gateway Tool",f"Gateway: {tx['gateway_status']}")]
        for tool,output in checks:
            conn.execute("INSERT INTO investigation_logs VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),case_id,"Investigation Agent",tool,output,utc_now()));database.log_activity(conn,case_id,"TOOL_CHECK",f"{tool}: {output}")
        return {"transaction":tx,"playbooks":playbooks}
class ResolutionAgent:
    def resolve(self,evidence:dict[str,Any]):
        tx=evidence["transaction"]
        if not tx:return {"status":"More details needed","risk":"LOW","approval_required":False,"reply":"I can investigate this. Please share the transaction ID or choose the payment you mean.","action":None}
        if tx["id"]=="TXN-499-UPI":return {"status":"Resolved","risk":"LOW","approval_required":False,"reply":"Your ₹499 UPI transaction was completed successfully. Reference: TXN-499-UPI.","action":None}
        if tx["id"]=="TXN-799-REV":return {"status":"Resolved","risk":"LOW","approval_required":False,"reply":"The ₹799 payment failed while the bank debit succeeded. The reversal is already pending; no further action is needed from you.","action":None}
        if tx["id"]=="TXN-5000-DUP":return {"status":"Awaiting approval","risk":"HIGH","approval_required":True,"reply":"I found a potential duplicate ₹5,000 charge. A human review is required. The request will remain pending for up to 20 minutes while I wait for the approver’s email or Telegram reply; I’ll update you when they respond.","action":"Initiate simulated ₹5,000 refund"}
        if tx["id"]=="TXN-20000-FRAUD":return {"status":"Escalated","risk":"HIGH","approval_required":True,"reply":"I registered your suspected unauthorized ₹20,000 transfer and flagged it for security review. A human review is required, and the request will remain pending for up to 20 minutes while I wait for the approver’s email or Telegram reply. I’ll update you when they respond. Secure your UPI PIN and never share OTPs.","action":"Security investigation"}
        return {"status":"Under investigation","risk":"MEDIUM","approval_required":False,"reply":"Your recharge is still pending with the payment system. We will update this case after its final status is available.","action":None}
