"""stdio MCP sunucusu — teacher'in (headless claude CLI) gordugu TEK arac yuzeyi.

Aciklamalar tools/schema.py'daki TOOLS'tan okunur (tek dogruluk kaynagi).
Butun cagrilar ToolExecutor.dispatch'ten, dolayisiyla allowlist'ten gecer.
Lab host'unda calisir: uv run python -m tools.mcp_server
"""

import os

from mcp.server.fastmcp import FastMCP

from lab import topo
from tools.schema import TOOLS, ToolExecutor
from tools.transport import HostExecTransport, ReadOnlyTransport

_DESC = {t["name"]: t["description"] for t in TOOLS}

# Lane motoru hangi dunyada kostugunu env ile soyler (datagen/lanes.py:lane_env);
# env yoksa varsayilan seed=0 dunyasi — eski davranis birebir.
_spec = topo.build_spec(
    int(os.environ.get("NETAGENT_TOPO_SEED", "0")),
    name=os.environ.get("NETAGENT_LAB_NAME", topo.LAB_NAME),
    mgmt_subnet=os.environ.get("NETAGENT_MGMT_SUBNET", topo.MGMT_SUBNET),
)
_inv = _spec.inventory()
_executor = ToolExecutor(_inv, eos=ReadOnlyTransport(_inv), host=HostExecTransport(_inv))

mcp = FastMCP("netagent")


@mcp.tool(description=_DESC["get_topology"])
def get_topology() -> str:
    return _executor.dispatch("get_topology", {})


@mcp.tool(description=_DESC["get_interfaces"])
def get_interfaces(device: str, interface: str | None = None) -> str:
    return _executor.dispatch("get_interfaces", {"device": device, "interface": interface})


@mcp.tool(description=_DESC["get_vlans"])
def get_vlans(device: str) -> str:
    return _executor.dispatch("get_vlans", {"device": device})


@mcp.tool(description=_DESC["get_ip_interfaces"])
def get_ip_interfaces(device: str) -> str:
    return _executor.dispatch("get_ip_interfaces", {"device": device})


@mcp.tool(description=_DESC["get_routes"])
def get_routes(device: str, prefix: str | None = None) -> str:
    return _executor.dispatch("get_routes", {"device": device, "prefix": prefix})


@mcp.tool(description=_DESC["get_ospf_neighbors"])
def get_ospf_neighbors(device: str) -> str:
    return _executor.dispatch("get_ospf_neighbors", {"device": device})


@mcp.tool(description=_DESC["ping_from_device"])
def ping_from_device(device: str, target: str, source: str | None = None, count: int = 3) -> str:
    return _executor.dispatch(
        "ping_from_device",
        {"device": device, "target": target, "source": source, "count": count},
    )


@mcp.tool(description=_DESC["get_config_section"])
def get_config_section(device: str, section: str) -> str:
    return _executor.dispatch("get_config_section", {"device": device, "section": section})


@mcp.tool(description=_DESC["submit_diagnosis"])
def submit_diagnosis(device: str, fault_class: str, root_cause: str, fix_commands: list[str]) -> str:
    return _executor.dispatch(
        "submit_diagnosis",
        {
            "device": device,
            "fault_class": fault_class,
            "root_cause": root_cause,
            "fix_commands": fix_commands,
        },
    )


if __name__ == "__main__":
    mcp.run()
