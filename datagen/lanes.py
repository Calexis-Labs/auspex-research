"""Cok-seritli datagen motoru: N lane, her biri KENDI containerlab topolojisinde
kuyruktaki senaryo gruplarini kosar.

Lane i -> lab adi "netagent{i}", mgmt subnet "192.168.{121+i}.0/24" — lane'ler
ayni host'ta yan yana yasar. Kuyruk (traces/queue.jsonl) topo_seed'e gore
ardisik gruplanmistir; lane bir grubu fcntl kilitli cursor dosyasindan atomik
claim eder, topolojiyi bir kez kurar, grubun tum senaryolarini kosar, yikar.

Dongu (senaryo basina): health -> inject -> teacher rollout -> verify ->
revert -> health. Rollout hatasi lane'i oldurmez (satir kaydedilir, devam).
Health geri gelmezse lane destroy+redeploy eder; MAX_INFRA_FAILURES ardisik
altyapi hatasinda lane durur ve log'a FATAL yazar.

Teacher'in MCP sunucusu lane'in dunyasini NETAGENT_LAB_NAME / NETAGENT_TOPO_SEED /
NETAGENT_MGMT_SUBNET env degiskenlerinden kurar (tools/mcp_server.py entegrasyon
notu: final rapora bakin) — lane'ler ayri process oldugu icin os.environ cakismaz.

Lab host'unda: uv run python -m datagen.lanes --lanes 2
"""

import argparse
import fcntl
import json
import multiprocessing
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from datagen.symptoms import fill as symptoms_fill
from datagen.teacher import run_rollout
from datagen.verifier import verify
from lab import deploy as lab_deploy
from lab import topo
from lab.faults import FAULTS, PrivilegedExec
from lab.topo import TopoSpec, build_spec

TRACES_DIR = Path(__file__).parents[1] / "traces"
DEFAULT_QUEUE = TRACES_DIR / "queue.jsonl"

MAX_LANES = 3                 # abonelik rate limit — ust sinir
BASE_MGMT_OCTET = 124         # lane i -> 192.168.(124+i).0/24 (121 varsayilan lab'in — cakisma yasak)
MAX_INFRA_FAILURES = 3
SETTLE_S = 5                  # inject sonrasi oturma payi


class InfraError(RuntimeError):
    """Altyapi hatasi: baseline/revert saglik kaybi ya da deploy sorunu.

    row varsa senaryo kismen tamamlanmistir — cagiran yine de kaydeder.
    """

    def __init__(self, msg: str, row: dict | None = None):
        super().__init__(msg)
        self.row = row


class LimitError(RuntimeError):
    """Abonelik/oran limiti: senaryo kaydedilmez, beklenip AYNI senaryo tekrar
    denenir (limit penceresinde kuyruk cop 'error' satiriyla tukenmesin)."""


LIMIT_WAIT_S = 300            # limitte bekleme (limit penceresi ~5 saat, ama
                             # kismi resetler icin sik dene)


# ---------------------------------------------------------------- lane kimligi

def lane_lab_name(lane_id: int) -> str:
    return f"{topo.LAB_NAME}{lane_id}"


def lane_mgmt_subnet(lane_id: int) -> str:
    return f"192.168.{BASE_MGMT_OCTET + lane_id}.0/24"


def lane_spec(lane_id: int, seed: int) -> TopoSpec:
    return build_spec(seed, name=lane_lab_name(lane_id), mgmt_subnet=lane_mgmt_subnet(lane_id))


def lane_env(spec: TopoSpec) -> dict[str, str]:
    """Teacher'in MCP sunucusuna lane dunyasini anlatan env degiskenleri."""
    return {
        "NETAGENT_LAB_NAME": spec.name,
        "NETAGENT_TOPO_SEED": str(spec.seed),
        "NETAGENT_MGMT_SUBNET": spec.mgmt_subnet,
    }


# ---------------------------------------------------------------- kuyruk

def load_queue(path: Path) -> list[dict]:
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def group_by_seed(entries: list[dict]) -> list[list[dict]]:
    """Ardisik ayni-topo_seed kosulari tek grup — lane bir grupta tek deploy yapar."""
    groups: list[list[dict]] = []
    for e in entries:
        if groups and groups[-1][0]["topo_seed"] == e["topo_seed"]:
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups


@dataclass(frozen=True)
class Claim:
    index: int
    group: list[dict]


class GroupClaimer:
    """fcntl kilitli cursor dosyasiyla grup dagitimi — lane'ler ayri process
    olsa da ayni grup iki kez verilmez. Cursor: siradaki grup indeksi."""

    def __init__(self, queue_path: Path, groups: list[list[dict]]):
        self.cursor_path = queue_path.with_suffix(".cursor")
        self.groups = groups

    def claim(self) -> Claim | None:
        fd = os.open(self.cursor_path, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                raw = f.read().strip()
                idx = int(raw) if raw else 0
                if idx >= len(self.groups):
                    return None
                f.seek(0)
                f.truncate()
                f.write(str(idx + 1))
                f.flush()
                return Claim(idx, self.groups[idx])
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def remaining(self) -> int:
        """Henuz claim edilmemis satir sayisi (kaba gosterge, monitor icin)."""
        try:
            raw = self.cursor_path.read_text().strip()
        except FileNotFoundError:
            raw = ""
        idx = int(raw) if raw else 0
        return sum(len(g) for g in self.groups[idx:])


# ---------------------------------------------------------------- senaryo dongusu

def make_row(entry: dict, lane: int | None, gt, trace, verdict) -> dict:
    """Mevcut batch satir semasi + scenario_id/lane/topo_seed/k_index/ts."""
    gts = gt if isinstance(gt, list) else [gt]
    return {
        "rollout_id": f"{entry['scenario_id']}#{entry.get('k_index', 0) + 1}",
        "fault": entry["fault_class"],
        "ground_truth": [asdict(g) for g in gts] if isinstance(gt, list) else asdict(gt),
        "symptom": entry["symptom"],
        "diagnosis": trace.diagnosis,
        "verdict": verdict.level,
        "verdict_reasons": list(verdict.reasons),
        "n_tool_calls": trace.n_tool_calls,
        "num_turns": trace.num_turns,
        "usage": trace.usage,
        "cost_usd": trace.cost_usd,
        "duration_s": round(trace.duration_s, 1),
        "error": trace.error,
        "model": trace.model,
        "events": trace.events,
        "scenario_id": entry["scenario_id"],
        "lane": lane,
        "topo_seed": entry["topo_seed"],
        "k_index": entry.get("k_index", 0),
        "ts": time.time(),
    }


def error_row(entry: dict, lane: int | None, message: str, model: str = "?") -> dict:
    """Rollout hic olusamadan kaydedilen satir — sema alanlari bos/notr doldurulur."""
    return {
        "rollout_id": f"{entry['scenario_id']}#{entry.get('k_index', 0) + 1}",
        "fault": entry["fault_class"],
        "ground_truth": None,
        "symptom": entry["symptom"],
        "diagnosis": None,
        "verdict": "error",
        "verdict_reasons": [message[:300]],
        "n_tool_calls": 0,
        "num_turns": 0,
        "usage": {},
        "cost_usd": 0.0,
        "duration_s": 0.0,
        "error": message[:500],
        "model": model,
        "events": [],
        "scenario_id": entry["scenario_id"],
        "lane": lane,
        "topo_seed": entry["topo_seed"],
        "k_index": entry.get("k_index", 0),
        "ts": time.time(),
    }


def run_scenario(
    entry: dict,
    spec: TopoSpec,
    pe: PrivilegedExec,
    model: str = "sonnet",
    lane: int | None = None,
    health=None,
    rollout=None,
    verifier=None,
    sleep=None,
) -> dict:
    """Tek senaryo: health -> inject -> rollout -> verify -> revert -> health.

    Altyapi bozuksa InfraError firlatir (row varsa icinde tasinir); rollout
    hatalari satira yazilir, exception olmaz. health/rollout/verifier/sleep
    parametreleri test enjeksiyonu icindir; None ise cagri aninda gercekler
    cozulur (monkeypatch edilebilir kalsin diye def aninda baglanmaz).
    """
    health = health or lab_deploy.health_check
    rollout = rollout or run_rollout
    verifier = verifier or verify
    sleep = sleep or time.sleep
    fault = FAULTS[entry["fault_class"]]

    base = health(spec, attempts=8)
    if not base.ok:
        raise InfraError(f"baseline saglikli degil:\n{base.render()}")

    rng = random.Random(f"{entry['scenario_id']}:{entry.get('k_index', 0)}")
    try:
        gt = fault.inject(pe, spec, rng)
    except LookupError as e:
        # bu dunyada uygun hedef yok (orn. tum vlanlar vrrp'li) — senaryo atlanir,
        # altyapi hatasi DEGILDIR
        return {**error_row(entry, lane, f"uygun hedef yok: {e}", model), "verdict": "skipped"}
    except Exception as e:
        # kismi enjeksiyon olabilir (cok satirli config'in ilk satirlari uygulanmis)
        # — best-effort revert dene, sonra InfraError olarak yukari at ki lane
        # redeploy yolunu kullansin ve hata DOGRU senaryoya atfedilsin
        try:
            fault.revert(pe, spec)
        except Exception:
            pass
        raise InfraError(f"inject basarisiz ({entry['fault_class']}): {e}") from e
    sleep(SETTLE_S)
    # placeholder'lar ENJEKSIYONDAN SONRA doldurulur — semptom gercek etkiyle celismesin
    entry = {**entry, "symptom": symptoms_fill(entry["symptom"], spec, gt, rng)}
    try:
        trace = rollout(entry["symptom"], model=model)
        if getattr(trace, "limited", False):
            # limit: arizayi geri al (finally), kaydetme, cagiran beklesin ve
            # ayni senaryoyu tekrar denesin
            raise LimitError(trace.error or "abonelik/oran limiti")
        verdict = verifier(trace.diagnosis, gt)     # verifier tekil VE liste gt destekler
    finally:
        fault.revert(pe, spec)

    row = make_row(entry, lane, gt, trace, verdict)
    healed = health(spec, attempts=8)
    if not healed.ok:
        raise InfraError(f"revert sonrasi saglik geri gelmedi:\n{healed.render()}", row=row)
    return row


# ---------------------------------------------------------------- lane process

def _write_status(path: Path, **fields) -> None:
    fields["updated"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fields, ensure_ascii=False))
    tmp.replace(path)


def _log(path: Path, msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a") as f:
        f.write(f"{stamp} {msg}\n")
    print(msg, flush=True)


def _deploy_lane(spec: TopoSpec) -> None:
    """deploy + wait_ready + health; her asamadaki sorun InfraError olur."""
    try:
        lab_deploy.deploy(spec)
        lab_deploy.wait_ready(spec)
        report = lab_deploy.health_check(spec, attempts=8)
    except (Exception, SystemExit) as e:              # deploy() sys.exit kullanir
        raise InfraError(f"deploy/wait_ready basarisiz: {e}") from e
    if not report.ok:
        raise InfraError(f"deploy sonrasi saglik yok:\n{report.render()}")


def run_lane(
    lane_id: int,
    queue_path: Path,
    model: str = "sonnet",
    max_infra: int = MAX_INFRA_FAILURES,
    traces_dir: Path = TRACES_DIR,
    rollout=None,
) -> int:
    """Lane ana dongusu: grup claim -> deploy -> senaryolar -> destroy; 0/1 doner."""
    entries = load_queue(queue_path)
    groups = group_by_seed(entries)
    claimer = GroupClaimer(queue_path, groups)

    traces_dir.mkdir(exist_ok=True)
    out_path = traces_dir / f"batch_lane{lane_id}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    log_path = traces_dir / f"lane{lane_id}.log"
    status_path = traces_dir / f"lane{lane_id}_status.json"

    infra_streak = 0
    rows_done = 0
    last_verdict = "-"

    def status(state: str, **kw) -> None:
        _write_status(
            status_path, lane=lane_id, state=state, rows_done=rows_done,
            last_verdict=last_verdict, infra_streak=infra_streak,
            queue_remaining=claimer.remaining(), out_file=out_path.name, **kw,
        )

    _log(log_path, f"lane{lane_id}: basladi — kuyruk {len(entries)} satir / {len(groups)} grup")
    with out_path.open("w") as out:

        def emit(row: dict) -> None:
            nonlocal rows_done, last_verdict
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            rows_done += 1
            last_verdict = row["verdict"]

        while True:
            claim = claimer.claim()
            if claim is None:
                break
            group = claim.group
            seed = group[0]["topo_seed"]
            spec = lane_spec(lane_id, seed)
            os.environ.update(lane_env(spec))
            pe = PrivilegedExec(spec)

            status("deploying", topo_seed=seed, active_scenario=None)
            try:
                _deploy_lane(spec)
            except InfraError as e:
                infra_streak += 1
                _log(log_path, f"lane{lane_id}: deploy hatasi (streak {infra_streak}): {e}")
                for entry in group:
                    emit(error_row(entry, lane_id, f"deploy hatasi: {e}", model))
                lab_deploy.destroy(spec)
                if infra_streak >= max_infra:
                    _log(log_path, f"lane{lane_id}: FATAL — {max_infra} ardisik altyapi hatasi, duruldu")
                    status("fatal", topo_seed=seed, active_scenario=None)
                    return 1
                continue
            infra_streak = 0

            def _scenario_with_limit_retry(entry: dict, rid: str) -> dict:
                # LimitError'da AYNI senaryoyu bekle-tekrar dene (kuyrugu cop
                # 'error' satiriyla tuketme); InfraError/digerleri disari cikar
                while True:
                    try:
                        return run_scenario(entry, spec, pe, model=model, lane=lane_id, rollout=rollout)
                    except LimitError as e:
                        _log(log_path, f"lane{lane_id}: LIMIT — {LIMIT_WAIT_S}s bekleniyor, sonra {rid} tekrar: {e}")
                        status("limit_bekliyor", topo_seed=seed, active_scenario=rid)
                        time.sleep(LIMIT_WAIT_S)
                        status("running", topo_seed=seed, active_scenario=rid)

            for entry in group:
                rid = f"{entry['scenario_id']}#{entry.get('k_index', 0) + 1}"
                status("running", topo_seed=seed, active_scenario=rid)
                try:
                    emit(_scenario_with_limit_retry(entry, rid))
                    infra_streak = 0
                except InfraError as e:
                    infra_streak += 1
                    _log(log_path, f"lane{lane_id}: altyapi hatasi (streak {infra_streak}) {rid}: {e}")
                    emit(e.row or error_row(entry, lane_id, str(e), model))
                    if infra_streak >= max_infra:
                        _log(log_path, f"lane{lane_id}: FATAL — {max_infra} ardisik altyapi hatasi, duruldu")
                        status("fatal", topo_seed=seed, active_scenario=rid)
                        lab_deploy.destroy(spec)
                        return 1
                    status("redeploying", topo_seed=seed, active_scenario=rid)
                    lab_deploy.destroy(spec)
                    try:
                        _deploy_lane(spec)
                    except InfraError as e2:
                        infra_streak += 1
                        _log(log_path, f"lane{lane_id}: redeploy hatasi (streak {infra_streak}): {e2}")
                        if infra_streak >= max_infra:
                            _log(log_path, f"lane{lane_id}: FATAL — {max_infra} ardisik altyapi hatasi, duruldu")
                            status("fatal", topo_seed=seed, active_scenario=rid)
                            lab_deploy.destroy(spec)   # yarim kalkmis lab asili kalmasin
                            return 1
                        # bu gruptan vazgec; kosulmamis kalan entry'ler sessizce
                        # kaybolmasin — cursor grubu 'bitti' sayacak
                        for skipped in group[group.index(entry) + 1:]:
                            emit(error_row(skipped, lane_id, "redeploy sonrasi grup atlandi", model))
                        break                          # sonraki grubu dene
                except Exception as e:                 # beklenmedik rollout hatasi — kaydet, devam
                    _log(log_path, f"lane{lane_id}: rollout hatasi {rid}: {e}")
                    emit(error_row(entry, lane_id, f"rollout hatasi: {e}", model))

            status("destroying", topo_seed=seed, active_scenario=None)
            lab_deploy.destroy(spec)

    _log(log_path, f"lane{lane_id}: bitti — {rows_done} satir -> {out_path.name}")
    status("done", topo_seed=None, active_scenario=None)
    return 0


def _lane_proc(lane_id: int, queue_path: str, model: str, max_infra: int) -> None:
    sys.exit(run_lane(lane_id, Path(queue_path), model=model, max_infra=max_infra))


def main() -> int:
    ap = argparse.ArgumentParser(description="cok-seritli datagen kosucusu")
    ap.add_argument("--lanes", type=int, default=2, help=f"lane sayisi (1..{MAX_LANES})")
    ap.add_argument("--queue", default=str(DEFAULT_QUEUE))
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--max-infra", type=int, default=MAX_INFRA_FAILURES)
    args = ap.parse_args()

    n = max(1, min(args.lanes, MAX_LANES))
    queue_path = Path(args.queue)
    if not queue_path.exists():
        sys.exit(f"kuyruk yok: {queue_path} — once: uv run python -m datagen.queue_build")

    procs = [
        multiprocessing.Process(target=_lane_proc, args=(i, str(queue_path), args.model, args.max_infra))
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    return 0 if all(p.exitcode == 0 for p in procs) else 1


if __name__ == "__main__":
    sys.exit(main())
