from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(frozen=True)
class Conversation:
    id: str
    messages: list[str]

@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    segment: str
    verified: bool = True

@dataclass(frozen=True)
class Transaction:
    id: str
    amount: float
    currency: str
    status: str
    risk_score: int = 0

@dataclass(frozen=True)
class Policy:
    id: str
    max_auto_refund: float = 100.0
    approval_threshold: int = 60

@dataclass(frozen=True)
class Case:
    id: str
    title: str
    customer_id: str
    conversation_id: str
    transaction_id: str
    policy_id: str
    scenario: str
    priority: str
    status: str
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    expected_action: str

    def to_dict(self):
        return asdict(self)
