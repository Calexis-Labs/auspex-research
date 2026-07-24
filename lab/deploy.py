"""Lab yasam dongusu: deploy / destroy / wait_ready / health_check — spec'ten turetilir.

Lab host'unda (Dell) calisir. containerlab'i sudo -n ile cagirir
(/etc/sudoers.d/containerlab yalnizca bu binary'ye izin verir).
Saglik kontrol listesi TopoSpec'ten TURETILIR:
  - l3=ospf ise her cihazda beklenen FULL adjacency sayisi routed_links'ten
  - her host -> kendi gateway'i ping
  - her host -> her loopback ping
  - ayni VLAN'daki host ciftleri arasi ping
Kontroller arac katmaninin KENDISIYLE yapilir — dogfooding.
"""

import argparse
import itertools
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

from lab import generator, topo
from lab.topo import TopoSpec
from tools.transport import HostExecTransport, ReadOnlyTransport


def _clab(*args: str) -> subprocess.CompletedProcess:
    cmd = ["sudo", "-n", "containerlab", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def deploy(spec: TopoSpec | None = None, ceos_image: str = generator.CEOS_IMAGE_DEFAULT) -> None:
    spec = spec or topo.default_spec()
    clab_yml = generator.build(spec, ceos_image)
    print(f"deploy: {clab_yml}")
    proc = _clab("deploy", "-t", str(clab_yml), "--reconfigure")
    if proc.returncode != 0:
        sys.exit(f"containerlab deploy basarisiz:\n{proc.stdout}\n{proc.stderr}")
    print(proc.stdout[-2000:])


def destroy(spec: TopoSpec | None = None) -> None:
    spec = spec or topo.default_spec()
    clab_yml = generator.clab_file(spec)
    if not clab_yml.exists():
        clab_yml = generator.build(spec)         # yml yoksa saf uretimle tekrar yaz
    proc = _clab("destroy", "-t", str(clab_yml), "--cleanup")
    print(proc.stdout[-1000:] or proc.stderr[-1000:])


def wait_ready(spec: TopoSpec | None = None, timeout_s: int = 300) -> ReadOnlyTransport:
    """Tum cEOS node'lari SSH+CLI cevap verene kadar bekler; acik transport dondurur."""
    spec = spec or topo.default_spec()
    inv = spec.inventory()
    eos = ReadOnlyTransport(inv)
    deadline = time.monotonic() + timeout_s
    pending = [n for n, node in inv.items() if node.os == "eos"]
    while pending:
        name = pending[0]
        try:
            eos.run(name, "show version")
            print(f"  hazir: {name}")
            pending.pop(0)
        except Exception:
            if time.monotonic() > deadline:
                raise TimeoutError(f"cEOS {timeout_s}s icinde hazir olmadi: {pending}")
            time.sleep(10)
    return eos


# ---------------------------------------------------------------- health

@dataclass
class HealthReport:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def render(self) -> str:
        lines = [
            f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else "")
            for name, ok, detail in self.checks
        ]
        return "\n".join(lines)


def _walk(obj, key):
    """JSON agacinda key'in tum degerlerini getir — EOS sema surprizlerine dayanikli."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, key)


def _ping_ok(out) -> bool:
    text = out.get("raw", "") if isinstance(out, dict) else json.dumps(out)
    return re.search(r"(?<![\d.])0(\.0+)?% packet loss", text) is not None


def expected_adjacencies(spec: TopoSpec) -> dict[str, int]:
    """Cihaz basina beklenen FULL OSPF komsu sayisi — routed_links'ten turetilir."""
    counts: dict[str, int] = {}
    for a_dev, _, b_dev, _ in spec.routed_links():
        counts[a_dev] = counts.get(a_dev, 0) + 1
        counts[b_dev] = counts.get(b_dev, 0) + 1
    return counts


def health_check(
    spec: TopoSpec | None = None,
    eos: ReadOnlyTransport | None = None,
    attempts: int = 6,
    wait_s: int = 15,
) -> HealthReport:
    """Spec'ten turetilen kontrol listesi; yakinsama icin attempts kez dener."""
    spec = spec or topo.default_spec()
    inv = spec.inventory()
    eos = eos or ReadOnlyTransport(inv)
    host = HostExecTransport(inv)

    loopbacks = {dev: nd["loopback_ip"] for dev, nd in spec.ceos_nodes.items()}

    report = HealthReport()
    for attempt in range(1, attempts + 1):
        report = HealthReport()

        if spec.l3 == "ospf":
            for dev, want in expected_adjacencies(spec).items():
                neighbors = eos.run(dev, "show ip ospf neighbor")
                states = [str(s).lower() for s in _walk(neighbors, "adjacencyState")]
                full = states.count("full")
                report.add(f"{dev} OSPF {want}x FULL", full == want, f"full={full} states={states}")

        for hname, h in spec.hosts.items():
            report.add(f"{hname} -> gw {h['gw']}", _ping_ok(host.run(hname, f"ping -c 3 -w 2 {h['gw']}")))
            for dev, lb in loopbacks.items():
                report.add(f"{hname} -> {lb} ({dev})", _ping_ok(host.run(hname, f"ping -c 3 -w 2 {lb}")))

        for h1, h2 in itertools.combinations(sorted(spec.hosts), 2):
            if spec.hosts[h1]["vlan"] != spec.hosts[h2]["vlan"]:
                continue
            target = spec.hosts[h2]["ip_cidr"].split("/")[0]
            report.add(f"{h1} -> {h2} (vlan {spec.hosts[h1]['vlan']})",
                       _ping_ok(host.run(h1, f"ping -c 3 -w 2 {target}")))

        if report.ok:
            break
        if attempt < attempts:
            print(f"  yakinsama bekleniyor ({attempt}/{attempts})...\n{report.render()}")
            time.sleep(wait_s)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="lab yasam dongusu")
    ap.add_argument("cmd", nargs="?", default="health", choices=["deploy", "destroy", "wait", "health"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default=topo.LAB_NAME)
    ap.add_argument("--image", default=generator.CEOS_IMAGE_DEFAULT)
    args = ap.parse_args()

    spec = topo.build_spec(args.seed, name=args.name)
    if args.cmd == "deploy":
        deploy(spec, args.image)
        eos = wait_ready(spec)
        report = health_check(spec, eos)
        print(report.render())
        sys.exit(0 if report.ok else 1)
    elif args.cmd == "destroy":
        destroy(spec)
    elif args.cmd == "wait":
        wait_ready(spec)
    elif args.cmd == "health":
        report = health_check(spec)
        print(report.render())
        sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
