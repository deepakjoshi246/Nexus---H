import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .agent import StrandsAdapter
from .fixtures import CASES, CONVERSATIONS, CUSTOMERS, POLICIES, SCENARIOS, TRANSACTIONS
from .guardrails import decide

DB_PATH = Path(os.getenv("NEXUS_H_DB_PATH") or (Path(__file__).resolve().parent.parent / "nexus_h.db"))

class NexusService:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self.agent = StrandsAdapter()
        self._init_db()

    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self):
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS handoffs (id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, case_id TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")

    def list_cases(self): return CASES
    def list_scenarios(self): return SCENARIOS
    def get_case(self, case_id): return next((c for c in CASES if c.id == case_id), None)

    def case_view(self, case):
        customer, conversation, _, _ = self._lookup(case)
        return {
            **case.to_dict(),
            "case_id": case.id,
            "customer_name": customer.name,
            "issue_type": case.scenario,
            "messages": [{"role": "customer", "content": message} for message in conversation.messages],
        }

    def health(self):
        return {"status": "ok", "service": "nexus-h", "deterministic": True, "agent": self.agent.status()}

    def _lookup(self, case):
        return (next(c for c in CUSTOMERS if c.id == case.customer_id),
                next(c for c in CONVERSATIONS if c.id == case.conversation_id),
                next(c for c in TRANSACTIONS if c.id == case.transaction_id),
                next(c for c in POLICIES if c.id == case.policy_id))

    def analyze_case(self, case_id, payload=None):
        case = self.get_case(case_id)
        if not case: return None
        customer, conversation, transaction, policy = self._lookup(case)
        decision = decide(case, customer, conversation, transaction, policy)
        result = {
            "case_id": case.id,
            "action": decision.action,
            "decision": {
                "decision": decision.action,
                "reason": decision.rationale,
                "reason_codes": decision.signals,
                "recommended_destination": self._destination(decision.action, case),
            },
            "signals": self._signal_details(decision.signals, transaction, conversation),
            "rationale": decision.rationale,
            "source": "deterministic_guardrails",
            "agent": self.agent.status(),
            "tool_calls": self._tool_activity(case, customer, conversation, transaction, policy),
        }
        result["audit"] = self._audit_events(case.id)
        self._audit(case.id, "analysis", result)
        result["audit"] = self._audit_events(case.id)
        if decision.action == "HANDOFF":
            result["handoff"] = self._handoff(case.id, result)
            result["brief"] = self._brief(case, customer, conversation, transaction, policy, decision)
            result["audit"] = self._audit_events(case.id)
        return result

    def _destination(self, action, case):
        if action == "HANDOFF" and case.scenario == "fraud-handoff":
            return "fraud_specialist"
        if action in ("HANDOFF", "APPROVAL"):
            return "billing_dispute_specialist"
        return "autonomous_resolution"

    def _signal_details(self, signals, transaction, conversation):
        values = {
            "risk": (0.91 if "high_risk_transaction" in signals else 0.22, "Transaction risk and verification signals."),
            "uncertainty": (0.82 if "insufficient_context" in signals else 0.18, "How much context is needed before a safe action."),
            "policy_boundary": (0.78 if "approval_threshold" in signals else 0.12, "Distance from autonomous policy authority."),
            "emotion": (0.25, "No protected attributes inferred; operational conversation signal only."),
            "complexity": (0.44 if len(conversation.messages) > 1 else 0.18, "Number of unresolved threads in the case."),
            "authority": (0.88 if "approval_threshold" in signals or "high_risk_transaction" in signals else 0.1, "Whether specialist or supervisor authority is required."),
        }
        return {key: {"score": score, "reason": reason} for key, (score, reason) in values.items()}

    def _tool_activity(self, case, customer, conversation, transaction, policy):
        return [
            {"tool": "get_case_data", "summary": f"Retrieved {case.id} from synthetic case store.", "evidence_ids": [case.id]},
            {"tool": "get_conversation", "summary": f"Retrieved {len(conversation.messages)} customer message(s).", "evidence_ids": [conversation.id]},
            {"tool": "get_customer_context", "summary": f"Customer verification status: {'verified' if customer.verified else 'needs review'}.", "evidence_ids": [customer.id]},
            {"tool": "get_transaction", "summary": f"{transaction.id}: {transaction.amount:.2f} {transaction.currency}, {transaction.status}.", "evidence_ids": [transaction.id]},
            {"tool": "search_policy", "summary": f"Matched policy {policy.id}; automatic refund limit is {policy.max_auto_refund:.2f}.", "evidence_ids": [policy.id]},
        ]

    def _brief(self, case, customer, conversation, transaction, policy, decision):
        destination = self._destination(decision.action, case)
        return {
            "title": case.title,
            "priority": case.priority,
            "customer_goal": conversation.messages[0],
            "one_line_summary": f"{customer.name} needs review of {transaction.id} ({transaction.amount:.2f} {transaction.currency}).",
            "what_happened": "The agent retrieved the case, customer, transaction, conversation, and policy records.",
            "financial_context": f"{transaction.id} is {transaction.status} for {transaction.amount:.2f} {transaction.currency}.",
            "policy_context": f"{policy.id} allows automatic refunds up to {policy.max_auto_refund:.2f}.",
            "actions_already_taken": ["Context retrieved", "Deterministic guardrails evaluated"],
            "escalation_reason": decision.rationale,
            "routing_reason": f"{destination} matches the unresolved case capability.",
            "recommended_next_step": "Review the retrieved evidence and decide the customer-facing resolution.",
            "evidence": [case.id, customer.id, transaction.id, policy.id],
            "confidence": 0.94,
        }

    def _audit(self, case_id, event, payload):
        now = datetime.now(timezone.utc).isoformat()
        event_id = hashlib.sha256(f"{case_id}:{event}:{json.dumps(payload, sort_keys=True)}".encode()).hexdigest()
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO audit(event_id,case_id,event,payload,created_at) VALUES(?,?,?,?,?)",
                       (event_id, case_id, event, json.dumps(payload, sort_keys=True), now))

    def _audit_events(self, case_id):
        with self._connect() as db:
            rows = db.execute("SELECT event, payload, created_at FROM audit WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
        return [{"action": row["event"].upper(), "timestamp": row["created_at"], "reason": "Evidence and decision recorded."} for row in rows]

    def _handoff(self, case_id, payload):
        handoff_id = "handoff-" + case_id
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO handoffs(id,case_id,action,payload,created_at) VALUES(?,?,?,?,?)",
                       (handoff_id, case_id, "HANDOFF", json.dumps(payload, sort_keys=True), now))
            row = db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
        self._audit(case_id, "handoff_created", {"handoff_id": handoff_id, "destination": payload["decision"]["recommended_destination"]})
        return {"id": row["id"], "case_id": row["case_id"], "action": row["action"], "created_at": row["created_at"]}

    def queue(self):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM handoffs ORDER BY created_at").fetchall()
        return [{"id": r["id"], "case_id": r["case_id"], "action": r["action"], "priority": "URGENT", "destination": "fraud_specialist" if r["case_id"] == "case-300" else "billing_dispute_specialist", "escalation_reason": "Mandatory specialist review based on retrieved evidence.", "created_at": r["created_at"]} for r in rows]

    def handoff_detail(self, handoff_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            if not row: return None
            audit = db.execute("SELECT event,payload,created_at FROM audit WHERE case_id=? ORDER BY id", (row["case_id"],)).fetchall()
        return {"id": row["id"], "case_id": row["case_id"], "action": row["action"],
                "payload": json.loads(row["payload"]), "created_at": row["created_at"],
                "audit": [{"event": a["event"], "payload": json.loads(a["payload"]), "created_at": a["created_at"]} for a in audit]}
