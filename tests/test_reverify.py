"""reverify: v2 kurallarin geriye donuk uygulanmasi.

- link_down_far_end satiri: GT etiketi interface_admin_down olur; model dogru
  cihazda interface_admin_down dediyse fail -> pass.
- eski insufficient_info satiri: GT no_fault olur; model no_fault dediyse pass.
- error/skipped satirlar ve coklu-GT icindeki alias bilesenleri de ele alinir.
"""

from datagen.reverify import reverify_row


def _row(fault, gt, diagnosis, verdict="fail"):
    return {
        "fault": fault, "ground_truth": gt, "diagnosis": diagnosis,
        "verdict": verdict, "verdict_reasons": ["x"],
    }


def _gt(fault_class, device="leaf1", key_terms=None):
    return {
        "device": device, "fault_class": fault_class, "root_cause": "rc",
        "fix_commands": ["interface Ethernet2", "no shutdown"],
        "key_terms": key_terms if key_terms is not None else ["ethernet2"],
    }


def test_link_down_far_end_becomes_pass():
    row = _row("link_down_far_end", _gt("link_down_far_end"), {
        "device": "leaf1", "fault_class": "interface_admin_down",
        "root_cause": "leaf1 Ethernet2 admin down", "fix_commands": ["no shutdown"],
    })
    new = reverify_row(row)
    assert new["verdict"] == "pass"
    assert new["orig_verdict"] == "fail"
    assert new["ground_truth"]["fault_class"] == "interface_admin_down"
    assert new["fault"] == "link_down_far_end"  # kayit adi kalir (izlenebilirlik)


def test_legacy_insufficient_info_becomes_no_fault():
    row = _row("insufficient_info", _gt("insufficient_info", device="none", key_terms=[]), {
        "device": "", "fault_class": "no_fault", "root_cause": "ag saglikli",
    })
    new = reverify_row(row)
    assert new["verdict"] == "pass"
    assert new["fault"] == "no_fault"
    assert new["ground_truth"]["fault_class"] == "no_fault"


def test_wrong_diagnosis_still_fails():
    row = _row("insufficient_info", _gt("insufficient_info", device="none", key_terms=[]), {
        "device": "leaf1", "fault_class": "acl_blocking_traffic", "root_cause": "uydurma",
    })
    assert reverify_row(row)["verdict"] == "fail"


def test_error_rows_untouched():
    row = {"fault": "svi_down", "ground_truth": None, "diagnosis": None,
           "verdict": "error", "verdict_reasons": ["timeout"]}
    assert reverify_row(row) == row


def test_multi_gt_alias_component_relabeled():
    gts = [_gt("link_down_far_end", device="spine1"),
           _gt("svi_down", device="leaf2", key_terms=["vlan10"])]
    row = _row("multi_fault", gts, {
        "device": "spine1", "fault_class": "interface_admin_down",
        "root_cause": "spine1 admin down; ayrica leaf2 svi_down vlan10",
        "fix_commands": [],
    })
    new = reverify_row(row)
    assert new["ground_truth"][0]["fault_class"] == "interface_admin_down"
    assert new["verdict"] in ("pass", "partial")


def test_unchanged_pass_row_stays_pass():
    row = _row("svi_down", _gt("svi_down", device="leaf2", key_terms=[]), {
        "device": "leaf2", "fault_class": "svi_down", "root_cause": "svi kapali",
    }, verdict="pass")
    new = reverify_row(row)
    assert new["verdict"] == "pass" and new["orig_verdict"] == "pass"
