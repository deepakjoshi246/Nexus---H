"""Pure, deterministic guardrail and routing logic."""
from dataclasses import dataclass
from .models import Case, Conversation, Customer, Policy, Transaction

ACTIONS = ("CONTINUE", "CLARIFY", "APPROVAL", "HANDOFF")

@dataclass(frozen=True)
class Decision:
    action: str
    signals: list[str]
    rationale: str

def decide(case: Case, customer: Customer, conversation: Conversation,
           transaction: Transaction, policy: Policy) -> Decision:
    signals = []
    scenario_rules = {
        "duplicate-charge": ("duplicate_charge", "HANDOFF", "Two settled charges require billing dispute investigation."),
        "refund-missing": ("prior_refund_commitment", "HANDOFF", "A previously promised refund is not resolved in the payment evidence."),
        "policy-exception": ("policy_exception", "APPROVAL", "A policy exception requires authorized approval."),
        "account-action": ("privileged_account_action", "APPROVAL", "Account closure and payment-method changes require supervisor authority."),
        "conflicting-records": ("conflicting_records", "HANDOFF", "Conflicting financial records require reconciliation by a specialist."),
    }
    if case.scenario in scenario_rules:
        code, action, rationale = scenario_rules[case.scenario]
        signals.append(code)
        return Decision(action, signals, rationale)
    if not conversation.messages or len(" ".join(conversation.messages).strip()) < 15:
        signals.append("insufficient_context")
    if not customer.verified:
        signals.append("customer_unverified")
    if transaction.status != "settled":
        signals.append("transaction_not_settled")
    if transaction.risk_score >= 80:
        signals.append("high_risk_transaction")
    if "high_risk_transaction" in signals or "customer_unverified" in signals:
        return Decision("HANDOFF", signals, "A specialist must review identity or transaction risk.")
    if "insufficient_context" in signals:
        return Decision("CLARIFY", signals, "Ask for the order and the requested action before proceeding.")
    if transaction.amount > policy.max_auto_refund or transaction.risk_score >= policy.approval_threshold:
        signals.append("approval_threshold")
        return Decision("APPROVAL", signals, "The requested operation exceeds automatic authority.")
    return Decision("CONTINUE", signals, "All deterministic policy checks passed.")
