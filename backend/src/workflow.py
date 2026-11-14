"""LangGraph orchestration for deterministic support actions and grounded replies."""
from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import InvestigationAgent, ResolutionAgent, TriageAgent
from .database import SaathiDatabase
from .openai_responses import OpenAIResponseAgent


class SupportWorkflowState(TypedDict, total=False):
    message: str
    customer_id: str
    case_id: str
    connection: sqlite3.Connection
    triage: Any
    evidence: dict[str, Any]
    outcome: dict[str, Any]


def build_support_workflow(
    triage_agent: TriageAgent,
    investigation_agent: InvestigationAgent,
    resolution_agent: ResolutionAgent,
    response_agent: OpenAIResponseAgent,
    database: SaathiDatabase,
):
    def triage(state: SupportWorkflowState) -> dict[str, Any]:
        return {"triage": triage_agent.classify(state["message"])}

    def investigate(state: SupportWorkflowState) -> dict[str, Any]:
        evidence = investigation_agent.investigate(
            state["connection"],
            database,
            state["case_id"],
            state["customer_id"],
            state["message"],
            state["triage"],
        )
        return {"evidence": evidence}

    def resolve(state: SupportWorkflowState) -> dict[str, Any]:
        return {"outcome": resolution_agent.resolve(state["evidence"])}

    def respond(state: SupportWorkflowState) -> dict[str, Any]:
        outcome = dict(state["outcome"])
        outcome["reply"] = response_agent.respond(
            state["message"],
            outcome,
            state["evidence"]["playbooks"],
        )
        return {"outcome": outcome}

    graph = StateGraph(SupportWorkflowState)
    graph.add_node("triage", triage)
    graph.add_node("investigate_with_local_rag", investigate)
    graph.add_node("resolve_from_verified_evidence", resolve)
    graph.add_node("compose_grounded_reply", respond)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "investigate_with_local_rag")
    graph.add_edge("investigate_with_local_rag", "resolve_from_verified_evidence")
    graph.add_edge("resolve_from_verified_evidence", "compose_grounded_reply")
    graph.add_edge("compose_grounded_reply", END)
    return graph.compile()
