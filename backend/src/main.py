import asyncio
from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .approval_poller import ApprovalReplyPoller
from .api import router
from .database import database
load_dotenv()
database.initialise()


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = threading.Event()
    worker = threading.Thread(
        target=ApprovalReplyPoller(stop_event).run,
        name="approval-reply-poller",
        daemon=True,
    )
    worker.start()
    try:
        yield
    finally:
        stop_event.set()
        await asyncio.to_thread(worker.join, 15)


app=FastAPI(title="Saathi Prototype API",version="0.2.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router)
@app.get("/api/health")
def health(): return {"status":"ok","service":"saathi-prototype","rag_source":"local Markdown knowledge base"}
