"""Streamable HTTP MCP server for Alexa+ NEXUS-H support tools."""
import json
import os
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from nexus_h.service import NexusService


service = NexusService()
render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
default_allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if render_hostname:
    default_allowed_hosts.append(f"{render_hostname}:*")
allowed_hosts = [
    host.strip()
    for host in os.getenv(
        "MCP_ALLOWED_HOSTS", ",".join(default_allowed_hosts)
    ).split(",")
    if host.strip()
]
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "MCP_ALLOWED_ORIGINS",
        "http://127.0.0.1:*,http://localhost:*,http://[::1]:*",
    ).split(",")
    if origin.strip()
]
mcp = FastMCP(
    "NEXUS-H Support",
    instructions=(
        "Help support teams review synthetic billing cases. Use case evidence and "
        "deterministic guardrail decisions; never invent evidence or claim a payment "
        "action was executed. Escalations require human review."
    ),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", os.getenv("PORT", "8001"))),
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    ),
)


@mcp.tool()
def list_support_cases() -> list[dict]:
    """List available synthetic billing-support cases and their priority."""
    return [
        {
            "case_id": case.id,
            "title": case.title,
            "priority": case.priority,
            "scenario": case.scenario,
        }
        for case in service.list_cases()
    ]


@mcp.tool()
def get_case_context(case_id: str) -> dict:
    """Retrieve the conversation, customer, transaction, and policy context for a case."""
    case = service.get_case(case_id)
    if case is None:
        return {"error": "case_not_found", "case_id": case_id}
    return service.case_view(case)


@mcp.tool()
def analyze_support_case(case_id: str) -> dict:
    """Preview a deterministic case decision without creating a handoff or audit event."""
    result = service.evaluate_case(case_id)
    if result is None:
        return {"error": "case_not_found", "case_id": case_id}
    return result


@mcp.tool()
def get_human_queue() -> list[dict]:
    """List cases already waiting for specialist handoff."""
    api_base_url = os.getenv("NEXUS_H_API_BASE_URL")
    if api_base_url:
        request = Request(
            f"{api_base_url.rstrip('/')}/api/queue",
            headers={"Accept": "application/json"},
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("Dashboard queue API returned an invalid response.")
        return items
    return service.queue()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
