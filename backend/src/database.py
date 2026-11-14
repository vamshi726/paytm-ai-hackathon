"""SQLite storage and deterministic simulated payment-system tools."""
from __future__ import annotations
import sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "saathi.db"
def utc_now() -> str: return datetime.now(timezone.utc).isoformat()
class SaathiDatabase:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH): self.path = Path(path)
    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        try: yield conn; conn.commit()
        finally: conn.close()
    def initialise(self) -> None:
        with self.connection() as conn:
            conn.executescript("""CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,name TEXT,email TEXT,masked_phone TEXT,verification_status TEXT);CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY,customer_id TEXT,service_category TEXT,amount REAL,transaction_status TEXT,bank_status TEXT,gateway_status TEXT,refund_status TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS support_tickets(id TEXT PRIMARY KEY,customer_id TEXT,category TEXT,issue_type TEXT,description TEXT,transaction_id TEXT,risk_level TEXT,status TEXT,assigned_to TEXT,created_at TEXT,updated_at TEXT,resolution TEXT);CREATE TABLE IF NOT EXISTS chat_messages(id TEXT PRIMARY KEY,case_id TEXT,sender_type TEXT,message TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS investigation_logs(id TEXT PRIMARY KEY,case_id TEXT,agent_name TEXT,tool_name TEXT,sanitized_output TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS approval_requests(id TEXT PRIMARY KEY,case_id TEXT,proposed_action TEXT,risk_level TEXT,status TEXT,requested_at TEXT,reviewer_id TEXT,decision_at TEXT,reviewer_comments TEXT,expires_at TEXT);CREATE TABLE IF NOT EXISTS case_activities(id TEXT PRIMARY KEY,case_id TEXT,activity_type TEXT,actor_id TEXT,description TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS execution_records(id TEXT PRIMARY KEY,case_id TEXT,approval_id TEXT,action_type TEXT,idempotency_key TEXT UNIQUE,execution_status TEXT,external_reference TEXT,executed_at TEXT);CREATE TABLE IF NOT EXISTS notification_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);""")
            if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]: return
            conn.execute("INSERT INTO customers VALUES(?,?,?,?,?)", ("CUST-1001","Chetan Kumar","chetan@example.test","+91 ••••• 4821","VERIFIED"))
            for row in [("TXN-499-UPI","UPI & Money Transfers",499,"SUCCESS","SUCCESS","SUCCESS","NONE"),("TXN-799-REV","UPI & Money Transfers",799,"FAILED","DEBIT_SUCCESS","FAILED","PENDING"),("TXN-5000-DUP","UPI & Money Transfers",5000,"SUCCESS","SUCCESS","SUCCESS","NONE"),("TXN-20000-FRAUD","UPI & Money Transfers",20000,"SUCCESS","SUCCESS","SUCCESS","NONE"),("RCG-299","Mobile Recharge & Bill Payments",299,"PENDING","DEBIT_SUCCESS","PENDING","NONE")]:
                conn.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?)", (row[0],"CUST-1001",*row[1:],utc_now()))
    @staticmethod
    def serialise(cursor: sqlite3.Cursor) -> list[dict[str, Any]]: return [dict(row) for row in cursor.fetchall()]
    def log_activity(self, conn: sqlite3.Connection, case_id: str, kind: str, description: str, actor: str="Saathi AI") -> None: conn.execute("INSERT INTO case_activities VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),case_id,kind,actor,description,utc_now()))
    def customer_tool(self, conn: sqlite3.Connection, customer_id: str):
        row=conn.execute("SELECT id,name,masked_phone,verification_status FROM customers WHERE id=?",(customer_id,)).fetchone(); return dict(row) if row else None
    def transaction_tool(self, conn: sqlite3.Connection, transaction_id: str):
        row=conn.execute("SELECT * FROM transactions WHERE id=?",(transaction_id,)).fetchone(); return dict(row) if row else None
    def create_ticket(self, conn: sqlite3.Connection, case_id: str, customer_id: str, description: str) -> None:
        conn.execute("INSERT INTO support_tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(case_id,customer_id,"Unclassified","Unclassified",description,None,"LOW","Understanding issue",None,utc_now(),utc_now(),None)); self.log_activity(conn,case_id,"CASE_CREATED","Customer support case created")
database=SaathiDatabase()
