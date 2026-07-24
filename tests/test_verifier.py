"""Verifier karar tablosu:
- tekil gt: pass / partial / fail mevcut davranisla birebir
- tek elemanli liste tekil gibi davranir
- no_fault / insufficient_info: fault_class eslesmesi yeterli (device serbest)
- coklu gt: her iki kok neden bulunursa pass, biri bulunursa partial,
  hicbiri bulunmazsa fail; ikinci kok neden serbest metinden de sayilir
"""

from datagen.verifier import Verdict, verify
from lab.faults import GroundTruth

GT_IF = GroundTruth(
    device="leaf1",
    fault_class="interface_admin_down",
    root_cause="leaf1 Ethernet2 administratively down",
    fix_commands=["interface Ethernet2", "no shutdown"],
    key_terms=["ethernet2"],
)
GT_ACL = GroundTruth(
    device="spine1",
    fault_class="acl_blocking_traffic",
    root_cause="ACL SEC-EDGE-IN on spine1 Ethernet1 denies icmp",
    fix_commands=["interface Ethernet1", "no ip access-group SEC-EDGE-IN in"],
    key_terms=["sec-edge-in"],
)
GT_NONE = GroundTruth(
    device="none", fault_class="no_fault",
    root_cause="ag sagliklidir; bildirilen sorun ag kaynakli degil",
    fix_commands=[], key_terms=[],
)
GT_INSUF = GroundTruth(
    device="none", fault_class="insufficient_info",
    root_cause="bilgi yetersiz; net teshis icin ek bilgi gerekli",
    fix_commands=[], key_terms=[],
)


def _diag(**kw) -> dict:
    d = {"device": "leaf1", "fault_class": "interface_admin_down",
         "root_cause": "Ethernet2 kapali", "fix_commands": ["interface Ethernet2", "no shutdown"]}
    d.update(kw)
    return d


# ---------------------------------------------------------------- tekil

def test_single_pass():
    v = verify(_diag(), GT_IF)
    assert v == Verdict("pass")
    assert v.passed


def test_single_partial_when_key_term_missing():
    v = verify(_diag(root_cause="port kapali", fix_commands=[]), GT_IF)
    assert v.level == "partial"
    assert "anahtar terim eksik" in v.reasons[0]


def test_single_fail_wrong_class():
    v = verify(_diag(fault_class="ospf_mtu_mismatch"), GT_IF)
    assert v.level == "fail"
    assert any("fault_class" in r for r in v.reasons)


def test_single_fail_wrong_device():
    v = verify(_diag(device="leaf2"), GT_IF)
    assert v.level == "fail"
    assert any("device" in r for r in v.reasons)


def test_single_fail_no_diagnosis():
    assert verify(None, GT_IF).level == "fail"
    assert verify({}, GT_IF).level == "fail"


def test_single_device_normalization_and_case():
    v = verify(_diag(device="CLAB-NETAGENT-LEAF1", fault_class="Interface_Admin_Down"), GT_IF)
    assert v.passed


def test_single_element_list_behaves_like_scalar():
    assert verify(_diag(), [GT_IF]) == verify(_diag(), GT_IF)
    assert verify(_diag(device="leaf2"), [GT_IF]).level == "fail"


# ---------------------------------------------------------------- no_fault / insufficient_info

def test_no_fault_class_match_is_enough_device_free():
    v = verify({"device": "leaf1", "fault_class": "no_fault",
                "root_cause": "ag temiz", "fix_commands": []}, GT_NONE)
    assert v.passed


def test_no_fault_wrong_class_fails():
    assert verify(_diag(), GT_NONE).level == "fail"


def test_insufficient_info_class_match_is_enough():
    v = verify({"device": "", "fault_class": "insufficient_info",
                "root_cause": "hangi kullanici etkilendi bilmem lazim", "fix_commands": []},
               [GT_INSUF])
    assert v.passed


def test_insufficient_info_fabricated_fault_fails():
    v = verify(_diag(fault_class="interface_admin_down"), GT_INSUF)
    assert v.level == "fail"


# ---------------------------------------------------------------- coklu (multi_fault)

def test_multi_pass_when_both_root_causes_found():
    diag = _diag(
        root_cause=(
            "iki ayri ariza var: leaf1 Ethernet2 kapatilmis (interface_admin_down) "
            "ve spine1 uzerinde acl_blocking_traffic icmp'yi kesiyor"
        ),
    )
    assert verify(diag, [GT_IF, GT_ACL]).passed


def test_multi_pass_via_primary_fields_plus_free_text():
    # birincil alanlar GT_ACL'i, serbest metin GT_IF'i karsilar
    diag = {
        "device": "spine1",
        "fault_class": "acl_blocking_traffic",
        "root_cause": "spine1 ACL icmp kesiyor; ayrica leaf1 tarafinda interface_admin_down var",
        "fix_commands": [],
    }
    assert verify(diag, [GT_IF, GT_ACL]).passed


def test_multi_partial_when_only_one_found():
    v = verify(_diag(), [GT_IF, GT_ACL])
    assert v.level == "partial"
    assert "acl_blocking_traffic@spine1" in v.reasons[0]


def test_multi_fail_when_none_found():
    diag = {"device": "leaf2", "fault_class": "wrong_host_gateway",
            "root_cause": "gateway yanlis", "fix_commands": []}
    v = verify(diag, [GT_IF, GT_ACL])
    assert v.level == "fail"
    assert "hicbir kok neden eslesmedi" in v.reasons[0]


def test_multi_no_diagnosis_fails():
    assert verify(None, [GT_IF, GT_ACL]).level == "fail"


def test_empty_gt_list_fails_loudly():
    assert verify(_diag(), []).level == "fail"
