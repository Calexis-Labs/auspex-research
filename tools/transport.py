"""Salt-okunur transport katmani.

ReadOnlyTransport  — cEOS'a scrapli/SSH ile; `| json` son ekini dogrulamadan
                     SONRA kendisi ekler, parse edilemezse ham metne duser.
HostExecTransport  — lab host'unda `docker exec` (shell YOK, argv listesi) ile
                     linux host ve FRR fallback node'lari.

Her iki yol da once tools.allowlist.validate_command'dan gecer; red durumunda
aga/subprocess'e hic dokunulmaz.
"""

import json
import subprocess
from dataclasses import dataclass

from tools.allowlist import validate_command


class UnknownDevice(Exception):
    """Envanterde olmayan ya da bu transport'un tasiyamayacagi cihaz."""


@dataclass(frozen=True)
class Node:
    name: str
    os: str                 # "eos" | "linux" | "frr_vtysh"
    host: str = ""          # mgmt IP (eos)
    container: str = ""     # docker container adi (linux / frr_vtysh)


def make_scrapli(node: Node):
    from scrapli import Scrapli

    return Scrapli(
        host=node.host,
        auth_username="admin",
        auth_password="admin",
        auth_strict_key=False,
        platform="arista_eos",
        transport="system",
        timeout_socket=15,
        timeout_ops=30,
    )


class ReadOnlyTransport:
    """cEOS icin scrapli tabanli, allowlist zorlamali transport."""

    def __init__(self, inventory: dict[str, Node], driver_factory=make_scrapli):
        self.inventory = inventory
        self._driver_factory = driver_factory
        self._conns: dict[str, object] = {}

    def _node(self, device: str) -> Node:
        node = self.inventory.get(device)
        if node is None or node.os != "eos":
            raise UnknownDevice(f"eos envanterinde yok: {device!r}")
        return node

    def _conn(self, node: Node):
        conn = self._conns.get(node.name)
        if conn is None:
            conn = self._driver_factory(node)
            conn.open()
            self._conns[node.name] = conn
        return conn

    def run(self, device: str, command: str, want_json: bool = True):
        node = self._node(device)
        cmd = validate_command(node.os, command)     # red → ag temasi yok
        conn = self._conn(node)
        if want_json:
            out = conn.send_command(f"{cmd.text} | json").result
            try:
                return json.loads(out)
            except ValueError:
                pass                                 # JSON'a cevrilemeyen komut → ham metin
        out = conn.send_command(cmd.text).result
        return {"raw": out}

    def close(self):
        for conn in self._conns.values():
            try:
                conn.close()
            except Exception:
                pass
        self._conns.clear()


def _run_argv(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return proc.stdout if proc.returncode == 0 else proc.stdout + proc.stderr


class HostExecTransport:
    """Linux host / FRR node'lari icin docker exec tabanli transport (lab host'unda calisir)."""

    def __init__(self, inventory: dict[str, Node], runner=_run_argv):
        self.inventory = inventory
        self._runner = runner

    def run(self, device: str, command: str):
        node = self.inventory.get(device)
        if node is None or node.os not in ("linux", "frr_vtysh"):
            raise UnknownDevice(f"host envanterinde yok: {device!r}")
        cmd = validate_command(node.os, command)     # red → subprocess yok
        if node.os == "frr_vtysh":
            argv = ["docker", "exec", node.container, "vtysh", "-c", f"{cmd.text} json"]
        else:
            argv = ["docker", "exec", node.container, *cmd.text.split()]
        out = self._runner(argv)
        try:
            return json.loads(out)
        except ValueError:
            return {"raw": out}
