"""Shared constants: taxa, places, extensions, cache locations, network policy."""

from __future__ import annotations

import os
from pathlib import Path

from wildid import __version__

APP_NAME = "wildid"
USER_AGENT = f"wildid/{__version__} (personal wildlife photo tool)"

# --- images -----------------------------------------------------------------
# RAW formats go through rawpy's embedded-preview path (plan D10); matching is case-insensitive.
RAW_EXTENSIONS: frozenset[str] = frozenset({"arw", "nef", "cr3", "cr2", "orf", "raf", "rw2", "dng"})
DEFAULT_EXTENSIONS: tuple[str, ...] = ("jpg", "jpeg", *sorted(RAW_EXTENSIONS))
# JPEG decode target for the long side. The model input is 224 px, so decoding a 61 MP file at
# full size is pure waste; PIL's draft mode decodes at 1/2, 1/4 or 1/8 scale straight from the DCT.
MAX_DECODE_PX = 1024
# With the detector-crop stage the crop needs detail: decode larger, bounded by a thumbnail.
CROP_DECODE_PX = 2048
# An embedded RAW preview smaller than this is useless for a 224 px model: demosaic instead.
RAW_PREVIEW_MIN_PX = 256
SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {"__MACOSX", "@eaDir", "$RECYCLE.BIN", "System Volume Information", "lost+found"}
)

# --- detector crop (post-MVP item 1) ------------------------------------------
CROP_MARGIN = 0.10  # fraction of the box size added on each side
CROP_MIN_PX = 224  # crops are grown (centred) to at least this many pixels per side

# --- top-k --------------------------------------------------------------------
TOP_K_FILE = 5
TOP_K_DIRECTORY = 3
DEFAULT_BATCH_SIZE = 32

# --- geo ----------------------------------------------------------------------
DEFAULT_TAXA: tuple[str, ...] = ("Mammalia", "Reptilia", "Amphibia", "Aves")
# iNaturalist "iconic taxa" accepted by observations/species_counts?iconic_taxa=...
INAT_ICONIC_TAXA: frozenset[str] = frozenset(
    {
        "Actinopterygii",
        "Amphibia",
        "Animalia",
        "Arachnida",
        "Aves",
        "Chromista",
        "Fungi",
        "Insecta",
        "Mammalia",
        "Mollusca",
        "Plantae",
        "Protozoa",
        "Reptilia",
    }
)
CONTINENTS: tuple[str, ...] = (
    "Africa",
    "Antarctica",
    "Asia",
    "Europe",
    "North America",
    "Oceania",
    "South America",
)
CONTINENT_ALIASES: dict[str, str] = {"australia": "Oceania", "australasia": "Oceania"}
# iNaturalist place ids for the continents, verified 2026-10-23 against /v1/places/<id>
# (admin_level -10, place_type 29; see docs/decisions/0002-geo-source.md). iNaturalist has no
# continent-level place for Antarctica: use --place-id with a regional place there.
CONTINENT_PLACE_IDS: dict[str, int] = {
    "Africa": 97392,
    "Asia": 97395,
    "Europe": 97391,
    "North America": 97394,
    "Oceania": 97393,
    "South America": 97389,
}

INAT_API = "https://api.inaturalist.org/v1"
INAT_CONNECT_TIMEOUT_S = 5.0
INAT_READ_TIMEOUT_S = 30.0
INAT_REQUEST_INTERVAL_S = 1.0
INAT_PER_PAGE = 500
INAT_RESULT_CAP = 10_000
GEO_CACHE_MAX_AGE_DAYS = 30
GEO_MIN_MATCHED_SPECIES = 50  # below this the filter is probably wrong; warn loudly

# --- taxonomy normalisation ---------------------------------------------------
# The TreeOfLife label tables follow the GBIF backbone, which has no class Reptilia: the
# reptile orders sit in the *class* column with an empty order (bioclip-2 table, measured
# 2026-10-27: Squamata 8,475 rows, Testudines 459, Crocodylia 66, Sphenodontia 7). iNaturalist,
# the keyword hierarchy and the plugin's class collections all expect "Reptilia", so
# predictions are normalised at the source (model.normalise_class). Ray-finned fish have no
# class at all in that table (23,700 Chordata rows) and are left as they are.
REPTILE_CLASS_ALIASES: dict[str, str] = {
    "Squamata": "Reptilia",
    "Testudines": "Reptilia",
    "Crocodylia": "Reptilia",
    "Sphenodontia": "Reptilia",
    "Rhynchocephalia": "Reptilia",
}

# --- keywords (Lightroom integration; see lightroom-plugin-plan.md L5/L6) -------
KEYWORD_ROOT = "WildID"
REVIEW_KEYWORD = "review"
# Scores are a softmax over the candidate set, so this is a review heuristic, not a probability.
DEFAULT_MIN_SCORE = 0.5
# Flat, top-level tags (deliberately outside KEYWORD_ROOT): "animals" when a photo is judged
# to contain an animal (detector verdict when the crop stage ran, else the score threshold),
# plus "wildlife" unless the species is domesticated.
ANIMALS_KEYWORD = "animals"
WILDLIFE_KEYWORD = "wildlife"
# Domesticated taxa that withhold the "wildlife" tag. Matched after collapsing trinomials to
# genus + last epithet ("Canis lupus familiaris" -> "Canis familiaris"), so the common
# TreeOfLife spellings of domestic forms land here. Pragmatic list — extend as photos demand.
DOMESTIC_SPECIES: frozenset[str] = frozenset(
    {
        "Canis familiaris",
        "Felis catus",
        "Bos taurus",
        "Bos indicus",
        "Equus caballus",
        "Equus asinus",
        "Ovis aries",
        "Capra hircus",
        "Sus domesticus",
        "Gallus domesticus",
        "Lama glama",
        "Vicugna pacos",
        "Camelus dromedarius",
        "Camelus bactrianus",
        "Bubalus bubalis",
        "Cavia porcellus",
        "Mustela furo",
        "Anser domesticus",
    }
)

# --- models -------------------------------------------------------------------
PRECISION_MODES: tuple[str, ...] = ("auto", "fp32", "tf32", "fp16")
# auto = tf32 on CUDA (measured: identical top-1 on 863 frames, +11 % throughput), fp32 on CPU
# and on Apple's Metal backend (MPS), where tf32 does not exist. fp16 is opt-in on CUDA and MPS.
DEFAULT_PRECISION = "auto"
TOL_REPO = "imageomics/TreeOfLife-200M"
HF_MODEL_IDS: dict[str, str] = {
    "bioclip-2.5": "imageomics/bioclip-2.5-vith14",
    "bioclip-2": "imageomics/bioclip-2",
}
# bioclip-2 is the default: the BioCLIP 2.5 TreeOfLife-200M text embeddings published today
# contain no reptiles at all (see docs/decisions/0001-bioclip-25.md). 2.5 stays selectable.
DEFAULT_MODEL = "bioclip-2"


# --- cache paths --------------------------------------------------------------
def cache_dir() -> Path:
    """wildid's own cache (geo lists, place resolution). Override with WILDID_CACHE_DIR."""
    override = os.environ.get("WILDID_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    from platformdirs import user_cache_dir

    return Path(user_cache_dir(APP_NAME, appauthor=False))


def geo_cache_dir() -> Path:
    return cache_dir() / "geo"


def models_dir() -> Path:
    """Detector and SpeciesNet weights (the BioCLIP models live in the Hugging Face cache)."""
    return cache_dir() / "models"
