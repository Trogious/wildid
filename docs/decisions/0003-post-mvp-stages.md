# ADR 0003 — Post-MVP items 1–4: detector crop, RAW formats, precision, SpeciesNet second opinion

**Status:** accepted (2026-10-23)
**Context:** plan §10 backlog items 1–4 as reordered by the owner on 2026-10-23.

## 1. Detector-crop stage (`--crop`)

**Decision:** MegaDetector v6 (`MDV6-yolov9-c`, 25.5 M params, trained at 640 px; optional
`MDV6-yolov9-e-1280`, 58 M params, 1280 px) loaded through `ultralytics` (AGPL-3.0; fine for a
personal tool, worth knowing if this is ever distributed). The highest-confidence *animal* box
(class 0) is padded by 10 %, grown to at least 224 px per side, and cropped from an image decoded
at up to 2048 px (`CROP_DECODE_PX`, thumbnail-bounded so a chunk of 128 stays under ~1.6 GB).
No detection → the full frame is used and the block says so.

**Why not the alternatives:** MegaDetector 1000 ("redwood" etc., the newest from the MegaDetector
maintainer) ships as YOLOv5-format checkpoints that `ultralytics` refuses and that need the
`yolov5` package (which also drags in roboflow, tensorboard and an older typer). PytorchWildlife
wraps the same MDv6 weights but depends on gradio, lightning and a pinned supervision.
Running MDv6-c at 1280 px (not its training size) *lost* detections (bear, zebra), hence the
per-checkpoint `imgsz` in `DetectorSpec`.

**Measured** (RTX 4090, 1440×1800 frames): MDv6-c 133 img/s, MDv6-e 23 img/s. On the owner's
199 Kenya frames with the Kenya geo list: 10 top-1 changes, mean top-1 score 0.840 → 0.857,
frames below 0.50 from 23 to 19, and the frames that were wrong because the animal was small are
fixed: cheetah frame *Scleroptila shelleyi* 0.20 → *Acinonyx jubatus* 0.91, impala 0.46 → 0.84,
Jackson's hornbill 0.45 → 0.72. 16 of 199 frames had no detection above 0.2. Whole pipeline with
crop + second opinion + anomaly pass: 26 img/s.

**Amendment 2026-10-25 — detector batching.** `Detector.detect` passed the whole loader chunk
(4 × batch size = 128 frames) to one ultralytics `predict()` call, which runs a list as a single
batch, so GPU memory grew with the chunk: `--crop --model bioclip-2.5` on 863 JPGs ran out of
memory on the 24 GB card and bioclip-2 peaked at 24.6 GB. `DETECT_BATCH = 16` now bounds each
call: crop runs peak at 8.1–8.9 GB (bioclip-2) and 11.0–11.9 GB (2.5) whatever the folder size,
and the stage is 10–15 % faster. Letterbox padding depends on a frame's batch neighbours, so a
few boxes moved: top-1 unchanged on 845/863 JPGs and 154/157 ARWs. The daemon was never
affected (at most 32 photos per request). Re-measured on the Kenya folder with the GBIF-extended
candidate set: 11 top-1 changes, mean top-1 0.845 → 0.865, frames below 0.50 18 → 15, 16 frames
without a detection, 46.8 img/s (full pipeline with second opinion 33.2 img/s).

**Amendment 2026-11-15 — the resize before the detector, `--crop-exact` (owner).** ultralytics
reduces each photo to the detector's size with `cv2.resize` and `INTER_LINEAR`. OpenCV's x86-64
build computes that with its portable code; its Arm build, with the Carotene and KleidiCV
layers, computes values that differ by 1 on about a fifth of the pixels. On the owner's samples
the Mac and the Linux box then differ in the crop on about a third of the JPGs and, with fp32
on both, in 38 of 2,040 answers, 32 of them review frames on both; against the PC's default
TF32 it is 37 and 31 (`docs/acceptance.md`, backlog items 9 to 12). The owner's decision:
**the default stays as it is, and a resize meant to be the same everywhere is an option**:
`--crop-exact` on the command line, `crop_exact` in a `/classify` request, a checkbox in the
plug-in's Identify dialog, all off by default. With it the resize is OpenCV's
`INTER_LINEAR_EXACT` (0.30 ms per photo against 0.17 ms on the Mac). `detector.exact_resize()`
sets it by swapping, for the length of a `detect()` call, the `LetterBox` class that
ultralytics' predictor builds: the interpolation is an argument of that class which the
predictor never passes. A test runs the swap against the real ultralytics. Not done: making
it the default, which would change the accepted crop results on Windows and Linux, and
hand-written resize code. Still to be measured: that the two systems agree with it (backlog
item 13). Even then the PC's default TF32 leaves a few crops different. *(The Linux box's part
of item 13, the same day: on the PC the option is another resize on every photo, 11 % of the
detector's input values differ by 1, and it changes the crop on 231 of 863 JPGs and 57 of 157
RAW files and 43 of 2,040 answers, 37 of them review frames with and without it. So as a
default it would change the accepted results on a PC by about as much as the Mac differs from
the PC today. Under the option TF32 and fp32 differ on 31 crops and 5 answers. Whether the two
systems agree with it is the Mac's part, still open.)* *(The Mac's part of item 13, the same
day: **they agree.** With the option the detector computes on the same pixels on the Mac and
on the Linux box on all 1,020 photos, and with fp32 on both every crop and all 2,040 answers
are the same; scores agree to 0.0002, as without the crop. Against the PC's default TF32, 31
crops and 5 answers differ, which is the precision's own effect. On the Mac the option
changes the crop on 269 of 863 JPGs and 54 of 157 RAW files and 49 of 2,040 answers against
the default. It is not a gain in accuracy: against the folder names 1,035 of 1,448 scored
answers are right with it on both machines, 1,044 on the PC and 1,033 on the Mac without it.
The decision stands: the default stays, the option is for when two computers have to agree.
Windows was not part of the measurement.)*

**Weights and offline:** `wildid prefetch --crop [--detector …]` downloads the `.pt` from the
Zenodo record PytorchWildlife uses (sha256 pinned in `detector.py`) into
`<wildid cache>/models/`. ultralytics runs with `YOLO_OFFLINE=true` and `YOLO_VERBOSE=false`
(set in `env.py` before import): no update checks, no analytics. The checkpoint is a pickled
module, so `env.py` also sets `TORCH_FORCE_WEIGHTS_ONLY_LOAD=0` *before* pybioclip can set it
to true process-wide (pybioclip only sets it when unset); the call sites decide, and both
pickled files we load are checksummed downloads from their official sources.

## 2. RAW formats

`.nef`, `.cr3`, `.cr2`, `.orf`, `.raf`, `.rw2` and `.dng` join `.arw` in `RAW_EXTENSIONS` and in
the default `--ext` list; matching was already case-insensitive. Verified with CC0 samples from
raw.pixls.us (git-ignored under `tests/fixtures/raw/`): Nikon D7000 NEF (preview 2464×1632,
22 ms), Canon EOS 6D CR2 (2736×1824, 84 ms), Canon EOS M200 CR3 (3000×2000, 51 ms), OM System
OM-5 ORF (1600×1200), Fujifilm X-T20 RAF (1920×1280), Panasonic G9 RW2 (1920×1440), DJI FC7303
DNG (960×720), Pixel 6 Pro DNG (680×512), Leica M240 DNG. The Leica DNG embeds only a 160×120
preview, which motivated a new rule: a preview under 256 px (`RAW_PREVIEW_MIN_PX`) falls back to
the half-size demosaic (355 ms there), logged as before. No real wildlife frames in these formats
yet; the preview path is identical to ARW's.

## 3. Precision (`--precision`, default `auto` = TF32 on CUDA)

Measured on the owner's 863 sample JPGs, batch 32, RTX 4090, top-1 agreement against fp32:

| model | mode | predict img/s | encode-only img/s | top-1 agreement | max Δscore |
|---|---|---|---|---|---|
| bioclip-2 | fp32 | 77.3 | 210 | 863/863 | 0 |
| bioclip-2 | tf32 | 85.9 | 282 | 863/863 | 0.002 |
| bioclip-2 | fp16 autocast | 95.7 | 633 | 857/863 | 0.020 |
| bioclip-2 | bf16 autocast | 86.1 | 640 | 798/863 | 0.110 |
| bioclip-2.5 | fp32 | 48.6 | 103 | 863/863 | 0 |
| bioclip-2.5 | tf32 | 56.3 | 147 | 863/863 | 0.019 |
| bioclip-2.5 | fp16 autocast | 71.3 | 335 | 861/863 | 0.021 |
| bioclip-2.5 | bf16 autocast | 71.5 | 338 | 838/863 | 0.102 |

**Decisions:** TF32 is the default on CUDA (no top-1 change, +11–16 %). fp16 autocast is opt-in
(`--precision fp16`, +22–47 %, changes ~0.5 % of top-1 answers; CLI check on Kenya: 197/199).
bf16 is not offered (8-bit mantissa breaks the softmax over 867 k classes). The header prints
the effective mode. **Finding:** end-to-end throughput is CPU-bound in pybioclip's per-image
preprocessing (encode-only is 3–6× faster than predict); moving that work into the loader
threads is the next lever, not GPU precision.

*Amended 2026-11-14 (macOS, ADR 0008):* on Apple's Metal backend (MPS) everything runs fp32.
TF32 is a CUDA matmul mode and does not exist there, and fp16 autocast has not been measured
on MPS: `--precision tf32` and `--precision fp16` both warn and run fp32, and `auto` is fp32.
The fp16 autocast path is reachable for the measurement only, with `WILDID_MPS_FP16=1`. The
table above is CUDA and says nothing about MPS; the measurement is section E of
`docs/acceptance-macos.md`, and its outcome is recorded here.

*Measured 2026-11-14* (M5 Pro, the same 863 JPGs, batch 32; `docs/acceptance.md`): fp32 on MPS
gives the CPU reference's top-1 on 863/863 for both models (max |Δscore| 0.0003). fp16 on MPS
against that fp32: bioclip-2 851/863, max |Δscore| 0.017, 82.5 against 33.4 img/s; bioclip-2.5
862/863, 0.023, 48.4 against 17.3 img/s. Whether `--precision fp16` is offered on MPS was left
to the owner (decided on 2026-11-15, below); until then the mode stayed behind the measurement
switch.

*Measured 2026-11-15 on the Lightroom plug-in's path* (crop, RAW files, the daemon in 24-photo
requests; `docs/acceptance.md`): there fp16 is worth 1.4 times with bioclip-2 (15.4 → 21.4
img/s) and 1.6 times with bioclip-2.5, not the 2.5 and 2.8 times of bare classification,
because the detector and the image decoding take the same time in either precision. It costs
1.6 to 2.2 GB of memory under load. Over both days every answer fp16 changed was a review
frame in both precisions (top score at most 0.43); the review flag itself moved on 5 of 1,726
results, each within 0.01 of the threshold.

*Decided 2026-11-15 (owner):* `--precision fp16` is offered on MPS as the opt-in it is on
CUDA, for `wildid classify` and `wildid serve` alike. `auto` stays fp32 there, and `tf32`
still warns and runs fp32. The Lightroom plug-in's server stays on `auto` on every platform,
so on a Mac it runs fp32: on the plug-in's path fp16 would buy 1.4 to 1.6 times for about
2 GB and for answers that leave the reference on about 1 % of frames. The measurement switch
`WILDID_MPS_FP16` is gone. The flag alone reproduces the measured fp16 runs frame for frame
(863/863 for both models, Δ 0).

## 4. Second opinion (`--second-opinion`, implies `--crop`)

**Decision:** Google's SpeciesNet v4.0.3a crop classifier (EfficientNetV2-M, 2,498 labels,
Apache-2.0), loaded directly from the files Google publishes on Kaggle (`info.json`,
onnx2torch-converted `.pt`, labels). The `speciesnet` package is *not* a dependency: it pins
`yolov5` and pulls roboflow, tensorboard, sahi and a downgrade of typer. Our loader mirrors its
preprocessing exactly (float resize to 480×480 without antialias, back to uint8, HWC, /255) and
needs only `onnx2torch` (+ `onnx`). `wildid prefetch --second-opinion` fetches the Kaggle
tarball (direct link, no account needed, sha256 pinned) into `<wildid cache>/models/`.

Each block gets `speciesnet: <taxon> (<score>) <verdict>` where the verdict compares SpeciesNet's
label with BioCLIP's top-1 at species, genus, family, order and class rank; only a real conflict
is marked `⚠ disagrees`. SpeciesNet often stops at "Aves" for birds it does not know — that is
"same class", not a dispute.

**Measured on the Kenya frames** (crop + geo): see `docs/acceptance.md` for the verdict tally.
SpeciesNet agrees on the big mammals (hyena, zebra, hippo, elephant, cats) and is weak on
DSLR bird portraits and on reptiles (it answers "blank" or iguana for Madagascar lizards), which
matches its camera-trap training. It is a second opinion for mammals, as the backlog said.

## 5. Loader-thread pre-shrink (follow-up to §3; 2026-10-23)

**Problem.** pybioclip's `predict()` resizes every image on the main thread, one at a time,
before batching. The GPU idled: encode-only ran 3–6× faster than end to end.

**Decision.** The loader threads apply the model's *own* resize/crop objects to each PIL image
right after decoding (`model.make_preshrink`), so the image pybioclip receives is already
224 px and its transform becomes an identity. Scoring still goes through pybioclip unchanged.
- open_clip-style transform (bioclip-2.5: `Resize(224, bicubic)` → `CenterCrop`): the same ops on
  the same PIL image, then PIL short-circuits the same-size resize — **bit-exact** (863/863
  identical top-1, max |Δscore| 0).
- pybioclip's squash transform (bioclip-2: `ToTensor` → `Resize((224, 224), antialias)`): PIL's
  antialiased bilinear resize to 224×224, which torchvision's `antialias=True` was designed to
  match; the tensor resize on the result is an identity. Not bit-exact: 847/863 identical top-1,
  max |Δscore| 0.044, and every flipped frame was a near-tie (top-1 ≤ 0.44, top-1/top-2 gap
  ≤ 0.02, e.g. *Egretta dimorpha* 0.440 ↔ *Egretta garzetta* 0.456). The exact tensor path was
  tried first (850/863) but ran at 164 img/s across 16 threads versus 2,028 img/s for PIL.
- With `--crop` the detector needs the full frame, so crops are shrunk afterwards in a small
  thread pool (`Classifier.prepare_inputs`); SpeciesNet still sees the full-resolution crop.
- `WILDID_NO_PRESHRINK=1` disables the shortcut for bit-exact reproduction of the old path.

**Measured** (863 sample JPGs, RTX 4090, TF32):

| | predict on full frames | predict on pre-shrunk | end to end before | end to end after |
|---|---|---|---|---|
| bioclip-2 | 87.7 img/s | 171.6 img/s | 60.8 img/s | **144.0 img/s** |
| bioclip-2.5 | 55.8 img/s | 113.9 img/s | 47.0 img/s | **98.1 img/s** |

Loader threads: 16 contend with the main thread (104 / 75.8 img/s), 8 is best (143 / 99.3),
4 slightly lower (139 / 95.9); the default cap is 8 (`--workers` overrides). The Kenya geo run
went from 56–59 to 145 img/s; the crop + second-opinion pipeline only from 27 to 30 img/s
because the detector, SpeciesNet and the anomaly pass dominate there.
