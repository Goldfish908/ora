import pytest

from scripts.dvsa_reference_select import select_reference


def test_reference_selection_preserves_revision_provenance():
    assert select_reference("dev", "BWOR-001")["revision"] == "structural_r1"
    assert select_reference("dev", "BWOR-011")["revision"] == "initial"
    assert select_reference("dev", "BWOR-042")["revision"] == "syntax_r1"


def test_reference_selection_rejects_conflicts_and_out_of_split_ids():
    with pytest.raises(ValueError, match="no candidate reference"):
        select_reference("dev", "BWOR-046")
    with pytest.raises(ValueError, match="unauthorized problem ID"):
        select_reference("frozen", "BWOR-001")
    with pytest.raises(ValueError, match="restricted"):
        select_reference("sealed", "BWOR-001")
