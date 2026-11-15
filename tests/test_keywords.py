"""Keyword policy: the single source of truth shared by JSON output, XMP and the server."""

from __future__ import annotations

from wildid.keywords import Keyword, suggest
from wildid.output import Prediction


def pred(score=0.9, species="Panthera onca", common="Jaguar", cls="Mammalia", genus="Panthera"):
    return Prediction(
        species=species,
        common_name=common,
        score=score,
        taxon_class=cls,
        genus=genus,
        family="Felidae",  # carried by the prediction, not part of the hierarchy
    )


def test_top1_full_hierarchy_with_synonym_and_presence_tags():
    s = suggest([pred(), pred(score=0.01, species="Puma concolor")], None)
    assert s.keywords == (
        Keyword(path=("WildID", "Mammalia", "Panthera", "Panthera onca"), synonyms=("Jaguar",)),
        Keyword(path=("animals",)),
        Keyword(path=("wildlife",)),
    )
    assert s.review is False and s.review_reasons == ()


def test_empty_class_is_skipped():
    s = suggest([pred(cls="")], None)
    assert s.keywords[0].path == ("WildID", "Panthera", "Panthera onca")
    assert s.keywords[0].hierarchical == "WildID|Panthera|Panthera onca"


def test_missing_genus_is_read_off_the_binomial():
    full = suggest([pred(genus="")], None).keywords[0].path
    assert full == ("WildID", "Mammalia", "Panthera", "Panthera onca")
    sub = suggest([pred(genus="", species="Charis Sarota acanthoides")], None)
    assert sub.keywords[0].path == ("WildID", "Mammalia", "Charis", "Charis Sarota acanthoides")
    single = suggest([pred(cls="", genus="", species="Incertae")], None)
    assert single.keywords[0].path == ("WildID", "Incertae")  # no level repeated


def test_missing_common_name_means_no_synonym():
    s = suggest([pred(common="")], None)
    assert s.keywords[0].synonyms == ()


def test_low_score_flags_review():
    s = suggest([pred(score=0.3)], None, min_score=0.5)
    assert s.review is True
    assert any("below 0.5" in r for r in s.review_reasons)
    assert s.keywords[-1] == Keyword(path=("WildID", "review"))
    assert s.keywords[0].leaf == "Panthera onca"  # the species keyword is still suggested
    leaves = [kw.leaf for kw in s.keywords]
    assert "animals" not in leaves  # without a detector, presence follows the score


def test_detector_verdict_overrides_the_score_heuristic():
    confident = suggest([pred(score=0.9)], None, detected=False)  # detector saw no animal
    assert [kw.leaf for kw in confident.keywords] == ["Panthera onca"]
    unsure = suggest([pred(score=0.2)], None, detected=True)  # detector saw one anyway
    leaves = [kw.leaf for kw in unsure.keywords]
    assert "animals" in leaves and "wildlife" in leaves and leaves[-1] == "review"


def test_domestic_species_get_animals_but_not_wildlife():
    for name in ("Felis catus", "Canis lupus familiaris", "Gallus gallus domesticus"):
        s = suggest([pred(species=name)], None)
        leaves = [kw.leaf for kw in s.keywords]
        assert "animals" in leaves, name
        assert "wildlife" not in leaves, name
    wild = suggest([pred(species="Sus scrofa")], None)  # wild boar stays wildlife
    assert "wildlife" in [kw.leaf for kw in wild.keywords]


def test_out_of_place_list_flags_review():
    s = suggest([pred()], False)
    assert s.review is True
    assert s.review_reasons == ("unconstrained top-1 is not in the place list",)


def test_in_place_list_or_unknown_does_not_flag():
    assert suggest([pred()], True).review is False
    assert suggest([pred()], None).review is False


def test_no_predictions_is_review_only():
    s = suggest([], None)
    assert s.review is True
    assert s.keywords == (Keyword(path=("WildID", "review")),)


def test_extra_reasons_flag_review():
    s = suggest([pred()], None, extra_reasons=("GPS cell not prefetched",))
    assert s.review is True and "GPS cell not prefetched" in s.review_reasons
    assert s.keywords[-1].path == ("WildID", "review")
    assert suggest([pred()], None, extra_reasons=("",)).review is False


def test_custom_root_and_threshold():
    s = suggest([pred(score=0.6)], None, root="Fauna", min_score=0.75)
    assert s.keywords[0].path[0] == "Fauna"
    assert s.keywords[-1].path == ("Fauna", "review")
