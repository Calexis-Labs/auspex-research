import random

from lab.faults import GroundTruth, PrivilegedExec, fault, resolve
from lab.topo import TopoSpec


@fault("link_down_far_end")
class LinkDownFarEnd:
    """Rastgele bir switch-switch linkin KARSI ucunda shutdown: semptomun
    gozlendigi cihazda arayuz down/down (admin degil) gorunur, cunku tasiyici
    kaybi karsi taraftan gelir. GT cihazi kok nedenin oldugu cihazdir —
    shutdown'in yapildigi uc. Ajan LLDP kaybi + karsi uc kontroluyle oraya
    ulasmali.

    ETIKET = interface_admin_down (pilot dersi): arac ciktilarinda iki sinif
    AYNI gerceklige cozunur — kok cihazda 'administratively down'. Ayri etiket
    tutmak modelden ayirt edilemez bir ayrimi istemekti (0/7). Enjektor kalir
    (far-end bakis acili semptomlar degerli senaryo cesitliligi), etiket tek."""

    requires: dict = {}
    label = "interface_admin_down"

    def inject(self, pe: PrivilegedExec, topo: TopoSpec | None = None, rng: random.Random | None = None) -> GroundTruth:
        topo, rng = resolve(topo, rng)
        # Ayni cihaz cifti arasinda birden fazla trunk varsa (l2loop yedegi) STP
        # failover kesintiyi maskeler: o ciftin TUM trunk'lari aday disi.
        pair_trunk_count: dict[tuple, int] = {}
        for l in topo.links:
            if l["kind"] == "trunk":
                pair = tuple(sorted((l["a"][0], l["b"][0])))
                pair_trunk_count[pair] = pair_trunk_count.get(pair, 0) + 1

        # (kok_cihaz, kok_arayuz, semptom_cihazi, semptom_arayuzu) — iki yon de aday
        ends = []
        for l in topo.links:
            if l["kind"] not in ("routed", "trunk"):
                continue
            if l.get("redundant"):
                continue
            pair = tuple(sorted((l["a"][0], l["b"][0])))
            if l["kind"] == "trunk" and pair_trunk_count.get(pair, 0) > 1:
                continue
            a_dev, a_if = l["a"][0], f"Ethernet{l['a'][1]}"
            b_dev, b_if = l["b"][0], f"Ethernet{l['b'][1]}"
            ends.append((a_dev, a_if, b_dev, b_if))
            ends.append((b_dev, b_if, a_dev, a_if))
        culprit, culprit_if, victim, victim_if = rng.choice(ends)
        self._target = (culprit, culprit_if)
        pe.eos_config(culprit, f"interface {culprit_if}", "shutdown")
        return GroundTruth(
            device=culprit,
            fault_class=self.label,
            root_cause=(
                f"{culprit} {culprit_if} administratively down (shutdown); "
                f"far end {victim} {victim_if} shows down/down (not admin)"
            ),
            fix_commands=[f"interface {culprit_if}", "no shutdown"],
            key_terms=[culprit_if.lower()],
        )

    def revert(self, pe: PrivilegedExec, topo: TopoSpec | None = None) -> None:
        device, intf = self._target
        pe.eos_config(device, f"interface {intf}", "no shutdown")
