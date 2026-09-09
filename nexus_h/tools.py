"""Small deterministic tools used by the service and integrations."""
from .fixtures import CASES, CONVERSATIONS, CUSTOMERS, POLICIES, TRANSACTIONS
from .guardrails import decide

def conversation(conversation_id):
    return next((x for x in CONVERSATIONS if x.id == conversation_id), None)

def case(case_id):
    return next((x for x in CASES if x.id == case_id), None)

def customer(customer_id):
    return next((x for x in CUSTOMERS if x.id == customer_id), None)

def transaction(transaction_id):
    return next((x for x in TRANSACTIONS if x.id == transaction_id), None)

def policy(policy_id):
    return next((x for x in POLICIES if x.id == policy_id), None)

def routing(case_value):
    customer_value = customer(case_value.customer_id)
    conversation_value = conversation(case_value.conversation_id)
    transaction_value = transaction(case_value.transaction_id)
    policy_value = policy(case_value.policy_id)
    return decide(case_value, customer_value, conversation_value, transaction_value, policy_value)

def handoff(handoff_id, case_id, action="HANDOFF"):
    return {"id": handoff_id, "case_id": case_id, "action": action}

def audit(event, case_id, payload):
    return {"event": event, "case_id": case_id, "payload": payload}
