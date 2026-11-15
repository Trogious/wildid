# 0008 — macOS on Apple Silicon: the engine on MPS, a zip with install.sh

**Status:** accepted 2026-11-14, when the owner said "build macOS version now". The engine
part of the acceptance ran the same day on the owner's sample photos (below). On 2026-11-15
decision 8 was added, decisions 4, 5 and 6 were amended and decision 7 was confirmed.
**Declared available by the owner on 2026-11-15 ("it's there now"):** the website presents
macOS as available, with an install guide and the figures measured on the one Mac, and the
READMEs follow. Until then the rule had been that nothing claims macOS works for a
photographer and no macOS figure is quoted before the acceptance has passed. The acceptance
itself is unchanged by the declaration and still open (`docs/acceptance-macos.md`): the
plug-in has not been run in Lightroom Classic on a Mac, the real install from a browser
download is to come, and no release carries the Mac zip yet.
**Context:** macOS was dropped from the backlog on 2026-10-25, reopened as a paper plan on
2026-10-28 (`docs/PLAN_MacOS.md`, decisions M1–M11) and built on 2026-11-14. The plan reserved
ADR number 0007 for this; that number went to the licence decision in the meantime. This ADR
records what was decided and what building found.
**The plan file is gone:** on 2026-11-15 the owner had `docs/PLAN_MacOS.md` removed, since it
had been executed, and with it the rule that every change to the app gets a row in the plan's
change log. Where this ADR, the acceptance documents and older log entries say "the plan",
"plan §…" or use its item numbers (M1–M11 decisions, E1–E10 engine, D1–D3 daemon, I1–I5
installer, V1–V11 plug-in checks), they mean that file. What is still open is tracked in
`docs/acceptance-macos.md`; what the website changes when macOS ships is in
`website/TODO_WEBSITE.md`.

## Decision

1. **Apple Silicon only (M1).** The lock's third environment is
   `sys_platform == 'darwin' and platform_machine == 'arm64'`, and `install.sh` refuses Intel
   Macs. PyTorch publishes no macOS x86_64 wheel for the locked version; supporting Intel
   would mean a second, old torch line.
2. **macOS 14 or newer (M2).** The locked torch and torchvision wheels are tagged
   `macosx_14_0_arm64`; `install.sh` refuses anything older and a test keeps the two equal.
   Lightroom Classic 15 has its own floor, which bounds the plug-in and not the engine: a
   search of Adobe's requirements page on 2026-11-14 named macOS 15 for it, but the page
   could not be opened to confirm, so it is a verify-item of the Mac acceptance.
3. **One torch version on all three platforms.** torch and torchvision come from the cu130
   index on Linux and Windows and from PyPI on macOS, held to the same versions by
   `constraint-dependencies` in `pyproject.toml`, so results on MPS and CUDA differ by backend
   only. Raise the two together. Re-lock with the uv version CI and the installers pin: a newer
   uv rewrites the lock's `revision`.
4. **Acceleration (M3).** `--device mps`; `auto` = cuda, then mps, then cpu. Precision on MPS
   is fp32: tf32 is a CUDA mode, and fp16 is not offered until it has been measured there
   (plan E8) — both warn and run fp32. `WILDID_MPS_FP16=1` turns the fp16 autocast on for that
   measurement and for nothing else. bf16 stays rejected. `PYTORCH_ENABLE_MPS_FALLBACK=1` is
   set before torch is imported, so an operator without a Metal kernel runs on the CPU instead
   of raising, and `-v` names it.
   *Amended 2026-11-15 (owner, after E8):* fp16 is offered on MPS as the opt-in it is on
   CUDA (`--precision fp16`, CLI and `wildid serve`); `auto` stays fp32, `tf32` still falls
   back, and the measurement switch is gone. The Lightroom plug-in's server stays on `auto`,
   so fp32 on a Mac (ADR 0003).
5. **Memory (M9).** `/health.vram` reports unified memory as what Metal recommends a process
   stays under (`torch.mps.recommended_max_memory()`, `kind: "unified"`). The plugin's 20 GB
   rule for keeping both models loaded applies to that figure unchanged until E8 has measured
   the footprint of both models on MPS.
   *Amended 2026-11-15 (owner, after E8):* unified memory has its own threshold. "Keep both
   models loaded" is offered from **30 GB** of that figure, not 20: both models hold 20.1 GB
   and Lightroom and macOS live in the same memory. The 20 GB rule for a graphics card is
   unchanged. On a Mac the Identify dialog quotes the footprint measured there (~12, ~13 and
   ~20 GB of memory) where it quotes VRAM on a graphics card, and on every platform the rule
   is applied again to the running server's report before the second model is loaded
   (ADR 0005).
6. **Distribution (M4–M8).** `WildID-<version>-macos-arm64.zip`, installed with
   `bash install.sh` from Terminal: per-user under `~/Library/Application Support/WildID`, the
   plugin into Lightroom's `Modules` folder with `engine.json`, a uv-managed Python, the server
   started on demand by `bin/wildid-server-start` (`nohup … &`) with the idle-exit model and no
   LaunchAgent. No `.pkg`, no `.dmg`, no root. Unsigned; signing and notarization are decided
   with Windows signing in phase P.
   *Amended 2026-11-15 (owner, after the first CI run):* a photographer's Mac is assumed to
   have no Homebrew, no Python and no developer tools. "A uv-managed Python" is therefore
   enforced and no longer left to uv's default, which builds on an installed Python 3.14 when
   it finds one. The scripts call only what macOS ships, and the CI smoke installs in a bare
   environment (stock PATH, none of the job's variables, an empty uv cache). First built as
   a setting in `install.sh` and the launchers; later the same day the owner made it the
   rule for every system, and it became one line in `pyproject.toml`,
   `python-preference = "only-managed"`, which both installers ship (ADR 0005, decision 6).
7. **CI and versioning (M10, M11).** The zip is plain files and builds on `ubuntu-latest`; a
   `macos-15` job runs the engine tests and installs the built zip for real. Tests fake MPS:
   hosted runners are not assumed to have a usable Metal device. The pushed tag decides the
   version, as on Windows.
   *Confirmed 2026-11-15 (owner):* the macOS job runs on both triggers, a pushed tag and a
   manual run, like the Linux tests, although the repository was private then and a private
   repository is billed at a higher rate for macOS runner minutes. The workflow has no switch
   that leaves it out, and `tests/test_installer_macos.py` fails if a condition is put on it
   or on a job it waits for.
8. **Requirements state only what was measured (owner, 2026-11-15).** One Mac has been
   measured, the owner's MacBook Pro with an M5 Pro and 48 GB of memory, and no smaller one
   is available for a run. Wherever macOS requirements are stated (`README.md`, the zip's
   `README-macOS.md`, the website), they give the floor the installer enforces (decisions 1
   and 2), name that machine and say that no other Mac has been tried. They do not say what
   a Mac with less memory needs or does: no minimum memory, no "should work", no "is tight"
   (the website's notes on smaller NVIDIA cards get no macOS twin). The figures measured on
   that machine join the requirement lines when macOS is accepted, not before.

## What building found (2026-11-14: M5 Pro, 48 GB, macOS 26.5, torch 2.14.1)

- Left alone, uv resolved torch 2.15.0 for macOS while the CUDA platforms stayed on 2.14.1.
  Hence decision 3.
- The local uv 0.13.6 bumped the lock's `revision` from 3 to 5; re-locking with the pinned uv
  0.11.32 kept it at 3. Compared entry by entry, no existing package lost a file or changed a
  hash.
- Both models classify the fixture photo on MPS with crop and second opinion, and **no
  operator fell back to the CPU** (bioclip-2, MegaDetector v6 YOLOv9-c, SpeciesNet 4.0.3a).
  For bioclip-2 on that one photo, MPS and CPU give the same top-3 scores to three decimals,
  the same crop box and the same SpeciesNet score. This is a smoke on one photo, not the E8
  measurement.
- `torch.mps.recommended_max_memory()` is 40.2 GB on the 48 GB machine, so the 20 GB rule
  leaves "keep both models loaded" on there. What a 16 GB or 24 GB Mac reports is not known.
- uv's release binary is ad-hoc signed and not notarized (`spctl` rejects it), so clearing the
  quarantine flag on the installed copy is required, not optional. `bash install.sh` runs from
  a folder in which every file is quarantined.
- The Python environment is about 1.2 GB on disk on macOS.

## What the measurement found (2026-11-14, same machine, the owner's sample photos)

Method and every figure: `docs/acceptance.md`.

- **MPS gives the reference answers.** Against CPU fp32 on the same Mac the top-1 is identical
  on 863 of 863 JPGs for both models (largest score difference 0.0003) and on 552 of 552
  through detector crop and place list; the detector's boxes are the same on MPS and CPU. The
  Kenya matrix of the Linux CUDA run reproduces: same mean score, same anomaly and review
  counts, all six second-opinion counts. The per-file comparison with CUDA followed on
  2026-11-15 (next point).
- **MPS against CUDA, file by file (2026-11-15).** Without the crop the Mac and the RTX 4090
  give the same top-1 on every file: 863 of 863 JPGs for both models, 157 of 157 RAW files.
  In fp32 on both the scores agree to 0.0002; CUDA's default TF32 moves them by up to 0.02.
  With the crop 2,003 of 2,040 answers agree (98.2 %): the detector's box differs between
  the machines, by a pixel or two on about a third of the JPGs and by another box on a
  few, and 31 of the 37 differing answers are review frames on both machines. Whether
  CUDA's TF32 moves the box or the backend does is not known yet. *(2026-11-15, the CUDA
  half of the answer: TF32 alone changes the crop on 30 of the 863 JPGs and 3 of the 157 RAW
  files, and 3 of 2,040 answers. That is too little to account for the difference between
  the machines; the comparison of CUDA in fp32 with the Mac is still to be run.
  `docs/acceptance.md`, "Linux: the CUDA crop runs in fp32".)* *(And on the Linux box the
  CPU gives CUDA's fp32 crops on every frame: the CUDA backend is not behind it either.
  `docs/acceptance.md`, "Linux: crop runs on the CPU".)* *(Compared on the Mac the same day:
  against CUDA in fp32 and against the Linux box's CPU the same 281 JPG crops and 38 answers
  differ. The two machines hand the detector different pixels; which step makes them differ
  is backlog item 12.)* *(The Linux box's part of item 12, the same day: with OpenCV's Intel
  IPP switched off the letterboxed image and the crop runs are the same as with it, to the
  last byte and digit. IPP's resize, the first suspect, is not the cause; the Mac's
  checksums are still to be compared. `docs/acceptance.md`, "Linux: what the detector
  sees, with Intel IPP and without".)* *(The Mac's part, the same day, and the cause: both
  machines hand the detector the same image; the resize before the detector differs. The
  Linux box computes OpenCV's portable `INTER_LINEAR`; the Mac's OpenCV, built with the
  Carotene and KleidiCV layers for Arm, gives values that differ by 1 on about a fifth of
  the pixels. `docs/acceptance.md`, "macOS: what the detector sees, and the step that
  differs".)*
- **Speed.** fp32: 33 images per second for bioclip-2 and 17 for bioclip-2.5 on 863 JPGs, 21
  and 14 with crop; the RTX 4090 does 139 and 98. The Mac is GPU-bound: batch size and loader
  threads change nothing.
- **fp16 on MPS** changes 12 of 863 answers for bioclip-2 and 1 for bioclip-2.5, every one a
  near-tie between low-scoring candidates, for 2.5 and 2.8 times the speed. That is the CUDA
  picture (8 and 6 of 863) with a far larger gain.
  Those speeds are bare classification. On the plug-in's path, measured on 2026-11-15 (crop,
  RAW files, the daemon in 24-photo requests), fp16 is worth 1.4 times with bioclip-2 and 1.6
  times with bioclip-2.5 and costs about 2 GB; every answer it changed on either day was a
  review frame in both precisions. Decided on 2026-11-15: opt-in, as on CUDA, and the
  plug-in's server stays on fp32 (decision 4, amended).
- **An installed copy gives the same answers (2026-11-15).** An installed WildID runs on the
  CPython 3.14.6 that uv downloads, not on the Homebrew Python of the checkout in which
  everything here was measured. Ten of the reference runs, repeated through a copy installed
  from the CI-built zip, are equal in every field of all 4,520 results, at the same speed.
- **Memory.** The daemon's process footprint is 11.7 GB with bioclip-2 under load, 13.4 GB
  with bioclip-2.5, 20.1 GB with both, flat over 1,256 photos. The CUDA figures were 6.8, 9.7
  and 14.1 GB of video memory; on a Mac the label table and the Metal cache come out of the
  same pool as everything else. Decision 5's 20 GB rule predates this: applied to Metal's
  recommended maximum it leaves a Mac that just passes it no room for Lightroom. The owner
  replaced it for unified memory with 30 GB on 2026-11-15 (decision 5, amended); only this
  48 GB machine has been measured.

## Consequences

- Changed: `pyproject.toml`, `uv.lock`, `model.py`, `cli.py`, `serve.py`, `env.py`,
  `detector.py`, `WildidModels.lua`; added `installer/macos/`, the macOS jobs in
  `release.yml`, `.gitattributes` (LF for shell scripts) and their tests.
- Open: everything inside Lightroom (V1–V11); an install from a browser download on a fresh
  account; and why the detector's box differs between the Mac and the Linux box. Neither
  CUDA's precision nor its backend is the cause (backlog items 10 and 11, done): the two
  machines hand the detector different pixels. The step is found (backlog item 12, done): the
  resize before the detector, where the Mac's OpenCV uses Arm-specific code and the Linux
  box the portable algorithm. Decided by the owner on 2026-11-15: the default stays, and a
  resize meant to be the same everywhere is an option, `--crop-exact` and a checkbox in the
  plug-in, off by default (ADR 0003 §1). Open: the measurement that the option makes the two
  systems agree (`species-id-mvp-plan.md` §10, item 13). *(The Linux box's half of item 13
  is made, 2026-11-15: what the option changes on a PC, in `docs/acceptance.md`. The Mac's
  half, which decides, is open.)* The three decisions the measurement
  left to the owner were all taken on 2026-11-15 (decisions 4, 5 and 8).
- Found by the first CI run and closed the same day (2026-11-15; `docs/acceptance.md`):
  decision 6 said "a uv-managed Python", but uv took an installed Python 3.14 when the Mac
  had one, as the CI runner and the owner's Mac both do (Homebrew), and downloaded its own
  only when there was none, so that download had never run. The installer now makes uv use
  its own Python always (decision 6, amended).
- Closed without a measurement (2026-11-15): what smaller Macs do. None is available, so the
  requirements name the one machine and stop there (decision 8).
- The website said "coming soon" for macOS until 2026-11-15, when the owner declared it
  available. What was changed on the site, and what a visitor still cannot rely on (a release
  with the Mac zip, the Lightroom steps seen on a Mac), is in `website/TODO_WEBSITE.md`.
- ADR 0003's precision decision gains an MPS amendment; `CLAUDE.md` carries the rule.
