"""Required Strands Agents integration for the NEXUS-H runtime."""
import os
from dataclasses import asdict


class StrandsAnalysisError(RuntimeError):
    """Raised when the optional Strands advisory cannot be generated."""


class StrandsAdapter:
    def __init__(self):
        import strands  # type: ignore
        from strands import Agent, tool  # type: ignore
        from . import tools

        self._strands = strands
        self._agent_class = Agent

        @tool
        def get_conversation(conversation_id: str) -> dict:
            """Retrieve a synthetic customer conversation by its ID."""
            value = tools.conversation(conversation_id)
            return asdict(value) if value else {"error": "conversation_not_found"}

        @tool
        def get_case(case_id: str) -> dict:
            """Retrieve a synthetic billing-support case by its ID."""
            value = tools.case(case_id)
            return value.to_dict() if value else {"error": "case_not_found"}

        @tool
        def get_customer(customer_id: str) -> dict:
            """Retrieve the synthetic customer context for a case."""
            value = tools.customer(customer_id)
            return asdict(value) if value else {"error": "customer_not_found"}

        @tool
        def get_transaction(transaction_id: str) -> dict:
            """Retrieve the synthetic transaction details for a case."""
            value = tools.transaction(transaction_id)
            return asdict(value) if value else {"error": "transaction_not_found"}

        @tool
        def get_policy(policy_id: str) -> dict:
            """Retrieve the policy limits and approval thresholds for a case."""
            value = tools.policy(policy_id)
            return asdict(value) if value else {"error": "policy_not_found"}

        self._tools = [
            get_conversation,
            get_case,
            get_customer,
            get_transaction,
            get_policy,
        ]
        self.model_id = os.getenv("NEXUS_H_MODEL_ID", "amazon.nova-2-lite-v1:0")
        self.region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-south-1"))
        self.advisory_enabled = os.getenv(
            "NEXUS_H_ENABLE_MODEL_ADVISORY", "false"
        ).lower() in {"1", "true", "yes"}
        self._agent = Agent(
            model=self.model_id,
            system_prompt=(
                "You are the NEXUS-H operations agent. Use retrieval tools for case evidence "
                "and return a concise factual advisory only. Do not reveal chain-of-thought, "
                "invent evidence, execute actions, or override deterministic guardrails."
            ),
            tools=self._tools,
        )

    def status(self):
        return {
            "enabled": self.advisory_enabled,
            "provider": "strands",
            "model": self.model_id,
            "region": self.region,
            "reason": (
                "opt_in_advisory"
                if self.advisory_enabled
                else "disabled_deterministic_mode"
            ),
        }

    def analyze(self, prompt):
        if not self.advisory_enabled:
            raise StrandsAnalysisError("Strands model advisory is disabled.")
        try:
            return str(self._agent(prompt))
        except Exception as error:
            raise StrandsAnalysisError(
                "Strands model advisory failed; deterministic decision was not recorded."
            ) from error
