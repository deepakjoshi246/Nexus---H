from .models import Case, Conversation, Customer, Policy, Scenario, Transaction

SCENARIOS = [
    Scenario("refund-standard", "Standard refund", "Verified customer, low value transaction.", "CONTINUE"),
    Scenario("refund-approval", "Large refund", "Refund exceeds the automatic policy limit.", "APPROVAL"),
    Scenario("fraud-handoff", "Suspected fraud", "Risk signal requires a specialist.", "HANDOFF"),
    Scenario("missing-context", "Missing context", "Insufficient information to safely proceed.", "CLARIFY"),
]
CUSTOMERS = [
    Customer("cus-100", "Asha Rao", "standard"),
    Customer("cus-200", "Mateo Silva", "premium"),
    Customer("cus-300", "Noor Khan", "standard", verified=False),
]
TRANSACTIONS = [
    Transaction("txn-100", 42.50, "USD", "settled", 8),
    Transaction("txn-200", 275.00, "USD", "settled", 24),
    Transaction("txn-300", 89.00, "USD", "settled", 91),
    Transaction("txn-400", 18.00, "USD", "pending", 5),
]
CONVERSATIONS = [
    Conversation("conv-100", ["I would like a refund for my order."]),
    Conversation("conv-200", ["Please refund the full amount; it arrived damaged."]),
    Conversation("conv-300", ["I do not recognize this transaction."]),
    Conversation("conv-400", ["Can you help?"]),
]
POLICIES = [Policy("pol-std")]
CASES = [
    Case("case-100", "Small settled refund", "cus-100", "conv-100", "txn-100", "pol-std", "refund-standard", "normal", "open"),
    Case("case-200", "Large damaged-order refund", "cus-200", "conv-200", "txn-200", "pol-std", "refund-approval", "high", "open"),
    Case("case-300", "Unrecognized transaction", "cus-300", "conv-300", "txn-300", "pol-std", "fraud-handoff", "urgent", "open"),
    Case("case-400", "Vague support request", "cus-100", "conv-400", "txn-400", "pol-std", "missing-context", "normal", "open"),
]
