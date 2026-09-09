"""Optional Strands Agents integration.

No model response is invented when Strands or credentials are absent.
"""
import os

class StrandsAdapter:
    def __init__(self):
        self.available = False
        self.reason = "strands_not_installed"
        try:
            import strands  # type: ignore
            from strands import Agent  # type: ignore
            from . import tools
            self.available = bool(os.getenv("NEXUS_H_MODEL_ID") or os.getenv("AWS_ACCESS_KEY_ID"))
            self.reason = "credentials_not_configured" if not self.available else "available"
            self._strands = strands
            self._agent_class = Agent
            self._tools = [
                tools.conversation,
                tools.case,
                tools.customer,
                tools.transaction,
                tools.policy,
            ]
        except ImportError:
            self._strands = None
            self._agent_class = None
            self._tools = []

    def status(self):
        return {"enabled": self.available, "provider": "strands" if self._strands else None, "reason": self.reason}

    def analyze(self, prompt):
        if not self.available:
            return None
        # This is the real Strands call path. Callers may use the text as
        # advisory context; guardrails remain authoritative.
        try:
            result = self._agent_class(
                model=os.getenv("NEXUS_H_MODEL_ID"),
                system_prompt="Use the provided retrieval tools for evidence. Return concise advisory context only.",
                tools=self._tools,
            )(prompt)
            return str(result)
        except Exception as exc:
            return {"error": "agent_unavailable", "detail": type(exc).__name__}
