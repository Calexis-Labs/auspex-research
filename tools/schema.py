"""Arac semalari + dispatch.

TOOLS deterministik (alfabetik) siralidir — prompt cache byte-stabil kalsin.
ToolExecutor.dispatch hata durumunda exception firlatmaz; ajana JSON icinde
{"error": ...} dondurur (teshis dongusu kirilmasin, model kendini duzeltsin).
"""

import json

from tools.allowlist import CommandNotAllowed
from tools.transport import HostExecTransport, Node, ReadOnlyTransport, UnknownDevice


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_DEVICE = {"type": "string", "description": "Device name from the topology, e.g. leaf1"}

TOOLS = [
    {
        "name": "get_config_section",
        "description": "Return one section of the running config as raw text (e.g. section='router ospf', 'vlan', 'interface ethernet2', 'access-list'). Full config is never available.",
        "input_schema": _schema(
            {"device": _DEVICE, "section": {"type": "string", "description": "Section filter, e.g. 'router ospf'"}},
            ["device", "section"],
        ),
    },
    {
        "name": "get_interfaces",
        "description": "Interface status summary for a device (link state, vlan, speed, duplex). Pass 'interface' (e.g. ethernet2) for full detail on one interface.",
        "input_schema": _schema(
            {"device": _DEVICE, "interface": {"type": "string", "description": "Optional single interface, e.g. ethernet2"}},
            ["device"],
        ),
    },
    {
        "name": "get_ip_interfaces",
        "description": "L3 interfaces with IP/mask. On switches: SVIs and routed ports. On Linux hosts: addresses AND the routing table incl. default gateway.",
        "input_schema": _schema({"device": _DEVICE}, ["device"]),
    },
    {
        "name": "get_ospf_neighbors",
        "description": "OSPF neighbor table of a device: neighbor id, state (FULL/EXSTART/...), interface.",
        "input_schema": _schema({"device": _DEVICE}, ["device"]),
    },
    {
        "name": "get_routes",
        "description": "IP routing table of a device. Optionally filter by destination prefix or address.",
        "input_schema": _schema(
            {"device": _DEVICE, "prefix": {"type": "string", "description": "Optional, e.g. 10.10.0.0/24 or 3.3.3.3"}},
            ["device"],
        ),
    },
    {
        "name": "get_topology",
        "description": "Discovered LLDP neighbor map of the whole network — which port connects to which device. Good first call.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "get_vlans",
        "description": "VLAN database and trunk status (allowed/native VLANs per trunk) of a switch.",
        "input_schema": _schema({"device": _DEVICE}, ["device"]),
    },
    {
        "name": "ping_from_device",
        "description": "Ping an IPv4 address FROM the given device (switch or host). Returns raw ping output. count is capped at 5.",
        "input_schema": _schema(
            {
                "device": _DEVICE,
                "target": {"type": "string", "description": "IPv4 address to ping"},
                "source": {"type": "string", "description": "Optional source interface (switches only), e.g. vlan10"},
                "count": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Packet count, default 3"},
            },
            ["device", "target"],
        ),
    },
    {
        "name": "submit_diagnosis",
        "description": "Submit your FINAL diagnosis and end the session. Call exactly once, only when confident. fix_commands are proposed to a human — they are never executed automatically.",
        "input_schema": _schema(
            {
                "device": {"type": "string", "description": "Device where the root cause lives"},
                "fault_class": {"type": "string", "description": "One of the known fault class names"},
                "root_cause": {"type": "string", "description": "One-sentence root cause, specific (interface, VLAN id, IP...)"},
                "fix_commands": {"type": "array", "items": {"type": "string"}, "description": "Commands a human would apply to fix it"},
            },
            ["device", "fault_class", "root_cause", "fix_commands"],
        ),
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]
assert TOOL_NAMES == sorted(TOOL_NAMES), "TOOLS alfabetik kalmali (cache stabilitesi)"


class ToolExecutor:
    """Arac cagrilarini transport'lara dagitir. Lab host'unda calisir."""

    def __init__(self, inventory: dict[str, Node], eos: ReadOnlyTransport, host: HostExecTransport):
        self.inventory = inventory
        self.eos = eos
        self.host = host

    # ------------------------------------------------------------- yardimcilar

    def _transport_for(self, device: str):
        node = self.inventory.get(device)
        if node is None:
            raise UnknownDevice(f"envanterde yok: {device!r}")
        return self.eos if node.os == "eos" else self.host

    def _eos_nodes(self) -> list[str]:
        return [n.name for n in self.inventory.values() if n.os == "eos"]

    # ------------------------------------------------------------- aracların gövdeleri

    def _get_topology(self) -> dict:
        return {name: self.eos.run(name, "show lldp neighbors") for name in self._eos_nodes()}

    def _get_interfaces(self, device: str, interface: str | None = None):
        cmd = f"show interfaces {interface}" if interface else "show interfaces status"
        return self._transport_for(device).run(device, cmd)

    def _get_vlans(self, device: str) -> dict:
        return {
            "vlans": self.eos.run(device, "show vlan"),
            "trunks": self.eos.run(device, "show interfaces trunk"),
        }

    def _get_ip_interfaces(self, device: str):
        node = self.inventory.get(device)
        if node is None:
            raise UnknownDevice(f"envanterde yok: {device!r}")
        if node.os == "eos":
            return self.eos.run(device, "show ip interface brief")
        return {
            "addresses": self.host.run(device, "ip -j addr show"),
            "routes": self.host.run(device, "ip -j route show"),
        }

    def _get_routes(self, device: str, prefix: str | None = None):
        cmd = f"show ip route {prefix}" if prefix else "show ip route"
        return self.eos.run(device, cmd)

    def _get_ospf_neighbors(self, device: str):
        return self.eos.run(device, "show ip ospf neighbor")

    def _ping(self, device: str, target: str, source: str | None = None, count: int = 3):
        node = self.inventory.get(device)
        if node is None:
            raise UnknownDevice(f"envanterde yok: {device!r}")
        count = max(1, min(int(count), 5))
        if node.os == "eos":
            cmd = f"ping {target} repeat {count}"
            if source:
                cmd += f" source {source}"
            return self.eos.run(device, cmd, want_json=False)
        return self.host.run(device, f"ping -c {count} -w 2 {target}")

    def _get_config_section(self, device: str, section: str):
        return self.eos.run(device, f"show running-config section {section}", want_json=False)

    # ------------------------------------------------------------- dispatch

    def dispatch(self, name: str, args: dict) -> str:
        try:
            result = self._dispatch(name, args or {})
        except (CommandNotAllowed, UnknownDevice, KeyError, TypeError, ValueError) as e:
            result = {"error": f"{type(e).__name__}: {e}"}
        return json.dumps(result, ensure_ascii=False, default=str)

    def _dispatch(self, name: str, args: dict):
        match name:
            case "get_topology":
                return self._get_topology()
            case "get_interfaces":
                return self._get_interfaces(args["device"], args.get("interface"))
            case "get_vlans":
                return self._get_vlans(args["device"])
            case "get_ip_interfaces":
                return self._get_ip_interfaces(args["device"])
            case "get_routes":
                return self._get_routes(args["device"], args.get("prefix"))
            case "get_ospf_neighbors":
                return self._get_ospf_neighbors(args["device"])
            case "ping_from_device":
                return self._ping(args["device"], args["target"], args.get("source"), args.get("count", 3))
            case "get_config_section":
                return self._get_config_section(args["device"], args["section"])
            case "submit_diagnosis":
                return {"status": "diagnosis_recorded", "diagnosis": args}
            case _:
                return {"error": f"bilinmeyen arac: {name!r}"}
