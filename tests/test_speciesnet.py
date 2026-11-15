from __future__ import annotations

import numpy as np
from PIL import Image

from wildid.output import Prediction
from wildid.speciesnet import IMG_SIZE, Label, SpeciesNet, compare, opinion_line

CHEETAH = Label.parse("5a9b1344;mammalia;carnivora;felidae;acinonyx;jubatus;cheetah")
FELIDAE = Label.parse("df8514b0;mammalia;carnivora;felidae;;;cat family")
BLANK = Label.parse("f1856211;;;;;;blank")
LEOPARD = Prediction(
    "Panthera pardus", "Leopard", 0.9, genus="Panthera", family="Felidae", taxon_class="Mammalia"
)
ROLLER = Prediction(
    "Coracias caudatus", "Roller", 0.9, genus="Coracias", family="Coraciidae", taxon_class="Aves"
)


def test_label_parsing_and_names():
    assert CHEETAH.binomial == "Acinonyx jubatus" and CHEETAH.rank == "species"
    assert CHEETAH.name == "Acinonyx jubatus"
    assert FELIDAE.binomial is None and FELIDAE.rank == "family"
    assert FELIDAE.name == "Felidae (family)"
    assert BLANK.rank == "none" and BLANK.name == "blank"
    short = Label.parse("abc;mammalia")  # tolerate short lines
    assert short.rank == "class" and short.name == "Mammalia (class)"


def test_compare_verdicts():
    assert (
        compare(LEOPARD, Label.parse("x;mammalia;carnivora;felidae;panthera;pardus;leopard"))
        == "agrees"
    )
    assert (
        compare(LEOPARD, Label.parse("x;mammalia;carnivora;felidae;panthera;leo;lion"))
        == "same genus"
    )
    assert compare(LEOPARD, FELIDAE) == "same family"
    assert compare(LEOPARD, CHEETAH) == "same family"  # cheetah is a felid too
    assert (
        compare(LEOPARD, Label.parse("x;mammalia;carnivora;hyaenidae;crocuta;crocuta;hyaena"))
        == "disagrees"
    )
    assert compare(LEOPARD, BLANK) == "no taxon"
    aves = Label.parse("x;aves;;;;;bird")
    assert compare(ROLLER, aves) == "same class"  # class-level answer for a bird: consistent
    assert compare(LEOPARD, aves) == "disagrees"  # a bird for a leopard is a dispute
    assert compare(ROLLER, Label.parse("x;aves;coraciiformes;;;;")) == "same order"


def test_opinion_line_marks_disagreement():
    hyaena = Label.parse("x;mammalia;carnivora;hyaenidae;crocuta;crocuta;spotted hyaena")
    assert opinion_line(LEOPARD, (hyaena, 0.8123)) == (
        "  speciesnet: Crocuta crocuta — spotted hyaena (0.812)  ⚠ disagrees"
    )
    assert (
        opinion_line(LEOPARD, (FELIDAE, 0.5))
        == "  speciesnet: Felidae (family) (0.500)  same family"
    )
    assert opinion_line(LEOPARD, (BLANK, 0.9)) == "  speciesnet: blank (0.900)  no taxon"


def test_preprocess_matches_speciesnet_contract():
    arr = SpeciesNet.preprocess(Image.new("RGB", (300, 200), (255, 128, 0)))
    assert arr.shape == (IMG_SIZE, IMG_SIZE, 3) and arr.dtype == np.float64
    assert 0.0 <= arr.min() and arr.max() <= 1.0
    assert abs(arr[0, 0, 0] - 1.0) < 1e-6 and abs(arr[0, 0, 1] - 128 / 255) < 1e-6
