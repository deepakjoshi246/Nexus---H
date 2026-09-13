"""Required Strands Agents integration for the NEXUS-H runtime."""
import os

class StrandsAdapter:
    def __init__(self):
        import strands  # type: ignore
        from strands import Agent  # type: ignore
        from . import tools

        self._strands = strands
        self._agent_class = Agent
        self._tools = [
            tools.conversation,
            tools.case,
            tools.customer,
            tools.transaction,
            tools.policy,
        ]
        self.model_id = os.getenv("NEXUS_H_MODEL_ID", "amazon.nova-2-lite-v1:0")
        self.region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-south-1"))
        self._agent = Agent(
            model=self.model_id,
            system_prompt=(
                "You are the NEXUS-H operations agent. Use retrieval tools for case evidence "
                "and return concise advisory context. Deterministic guardrails remain authoritative."
            ),
            tools=self._tools,
        )

    def status(self):
        return {
            "enabled": True,
            "provider": "strands",
            "model": self.model_id,
            "region": self.region,
            "reason": "required_runtime",
        }

    def analyze(self, prompt):
        result = self._agent(prompt)
        return str(result)
