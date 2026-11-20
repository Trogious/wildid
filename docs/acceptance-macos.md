# macOS (Apple Silicon) — acceptance run

Runnable checklist for the owner's Mac, to accept what was built on 2026-11-14 (ADR 0008).
It mirrors `docs/acceptance-lightroom.md`, the Windows run. The build plan,
`docs/PLAN_MacOS.md`, was removed on 2026-11-15 once it had been executed and is in git
history: the numbers used below (V1–V11, E8, D2, M9 and the like) are its item numbers, and
each item is described here in full.
Ticked boxes carry a 2026-11-14 note. Those marked *build* were checked while building, on
that Mac (M5 Pro, 48 GB, macOS 26.5.1) with the bear fixture and with the installer exercised
in a throwaway home folder. Those marked *samples* were checked the same day once the owner's
`sample-jpg/` and `sample-arw/` were in place: **sections 0, A, the file steps of C, and E are
done**; the figures are in `docs/acceptance.md`. **Everything unticked is still open**: it
needs Lightroom Classic on the Mac (B, the rest of C) or a real install (D). The two boxes
that waited for the CUDA run's files, one in 0 and one in E, were closed on 2026-11-15
(backlog item 9 in `species-id-mvp-plan.md` §10). The owner took the decisions at the end
of E on 2026-11-15. The six macOS-specific boxes of section B (V1 to V5, V8 and V11) were
ticked on 2026-11-20: the owner reported them done. On that day this Mac holds Lightroom
Classic 16.0 and WildID 0.3.2, both installed on 2026-11-16.

On 2026-11-15 the owner declared macOS available ("it's there now"): the website and the
READMEs present it so and quote the figures measured here. That changes nothing in this
checklist: everything unticked is still to be run, and the site's Lightroom steps for macOS
are to be corrected if section B shows something different (`website/TODO_WEBSITE.md`).

Suggested order: **0 → A → E → C → D → B**. E and C need only the sample folders; B needs
Lightroom Classic.

---

## 0. Session setup

- [x] Machine recorded: Apple M5 Pro, 48 GB, macOS 26.5.1. *(2026-11-14.)* Lightroom Classic
      16.0, installed on 2026-11-16. *(2026-11-20: version read from the installed
      application, whose bundle declares macOS 14.0 as its minimum. Adobe's requirements
      page, which ADR 0008 decision 2 could not open, was not read again. The build number
      shown in Help → System Info is still to be noted here.)*
- [x] `git pull` on `main`; `uv sync --locked` (the lock's macOS arm64 wheels, torch 2.14.1).
      *(2026-11-14: uv 0.13.6 from Homebrew; `.venv` 1.2 GB; MPS built and available.)*
- [x] `uv run pytest -q` and `uv run ruff check .` *(2026-11-14: 188 passed, 5 skipped —
      the RAW-fixture and live-model skips; ruff clean.)* The ARW-fixture skips un-skip when
      `tests/fixtures/*.ARW` are present.
- [x] The eight plain-Lua suites: `for t in cleanup collections geo json keywords models photos
      reviewed; do luajit lrplugin/tests/${t}_test.lua lrplugin/wildid.lrplugin; done`
      *(2026-11-14: all pass under LuaJIT.)*
- [x] Models and stages: `uv run wildid prefetch --model all --crop --second-opinion`.
      *(2026-11-14: bioclip-2 4.47 GB, bioclip-2.5 7.28 GB, detector 52 MB, SpeciesNet
      209 MB, no Hugging Face account; the offline verification passed for both models on
      `--device auto`, which is `mps` here.)*
- [x] Cache dir: `uv run python -c "from wildid.constants import cache_dir; print(cache_dir())"`
      → `~/Library/Caches/wildid`, the path the plugin's macOS default and `install.sh`
      assume. *(2026-11-14: `Library/Caches/wildid` under the home folder, as expected.)*
- [x] Sample folders in the repository root (git-ignored): `sample-jpg/`, `sample-arw/`.
      *(2026-11-14, samples: 863 JPG in 43 folders; 152 ARW + 5 DNG + 3 TIF with 152
      sidecars. Fingerprinted before and after the run: untouched.)*
- [x] Trip lists for the samples, online once:
      `uv run wildid prefetch --country Kenya --country Madagascar` (add what the folders need).
      *(2026-11-14, samples: Kenya 1,505 species → 1,421 candidates; Madagascar 995 → 862 for
      bioclip-2 and 576 for 2.5; Thailand › Nakhon Ratchasima 589 → 557; plus the GPS cells of
      `mg-baobab4` and `sample-arw/lion` with `--gps-from`, country and region level. The lists
      have grown since the Linux run of 2026-11-03: 1,416, 860 / 575, 511.)*
- [x] The CUDA reference for section E: the JSON files of the same sample runs on the
      RTX 4090 box. *(2026-11-15: the nine run documents of backlog item 9, made on the
      Linux box, are in `~/.cache/wildid-acceptance/cuda-reference/` on this
      Mac, with a manifest. Its SHA-256 list of the 1,020 classified photos matches this
      Mac's sample files on every one.)*

## A. Daemon with the real model

- [x] `uv run wildid serve -v` logs the port and the serve.json path and reports the model
      ready on `mps`. *(2026-11-14: ready 4.1 s after launch; `loaded bioclip-2 on mps`.)*
- [x] Health and auth, in Terminal:

```sh
S=~/Library/Caches/wildid/serve.json
PORT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$S")
TOKEN=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['token'])" "$S")
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/health" | python3 -m json.tool
# ready true, protocol 1, device "mps", vram.kind "unified". Then without -H: HTTP 401.
```

      *(2026-11-14: `vram` = Apple M5 Pro, 40.2 GB total, `kind: unified`; a missing and a
      wrong token both give 401; serve.json is mode 600.)*
- [x] Classify a frame through the daemon:

```sh
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"paths": ["/full/path/to/photo.ARW"], "k": 3, "crop": true}' \
  "http://127.0.0.1:$PORT/classify" | python3 -m json.tool
# sane species; suggested_keywords with the WildID|class|genus|species path.
```

      *(2026-11-14, bear fixture without crop: Ursus arctos 0.826 in 1.1 s; keywords
      `WildID|Mammalia|Ursus|Ursus arctos` + `animals` + `wildlife`; `device: mps`,
      `precision: fp32`.)* *(2026-11-14, samples: three lion ARWs with crop, Panthera leo
      0.882 / 0.915 / 0.942 in 1.3 s, as on Linux.)*
- [x] Geo request against a cached place (`"geo": {"country": "Kenya"}` in the body):
      candidates reflect the place; an uncached place returns 400 naming prefetch.
      *(2026-11-14, samples: Kenya → 1,421 candidates, the lions at 0.970–0.990, all
      `in_candidates`; `Peru` → 400 naming `POST /prefetch`.)*
- [x] Throughput and stability: a few hundred photos in 16–32-photo requests (or section B's
      big run). Memory flat across requests: Activity Monitor → Memory for the `python`
      process, and `/health.vram.free_gb` before and after. *(2026-11-14, samples: 1,256
      photos in 56 crop requests of 24, 0 failed, 15.6 img/s; the process footprint holds at
      11.5–11.7 GB from the third pass on, Metal at 9.3 GB.)*
- [x] Idle exit: `uv run wildid serve --idle-exit 20`. *(2026-11-14: exited after 26 s quiet,
      serve.json removed, process gone 3 s later.)* Repeat with 60 and confirm in Activity
      Monitor that the memory is released.
- [x] Second-server refusal: a second `wildid serve` while one runs. *(2026-11-14: exit 1,
      "a wildid server is already running (pid …, port …)".)*
- [x] `POST /shutdown` → `{"ok": true}`, the process ends within a few seconds.
      *(2026-11-14.)*
- [ ] V9, firewall: with the macOS firewall on (System Settings → Network → Firewall), the
      first `wildid serve` raises no "accept incoming connections" prompt (loopback only).
- [ ] V10, sleep and wake: sleep the Mac with the server running; after wake `/health`
      answers, or the plugin starts a new server on the next Identify.

## B. Plugin inside Lightroom Classic

Setup: the installed plugin from section D, or by hand (File → Plug-in Manager → Add →
`lrplugin/wildid.lrplugin`, with an `engine.json` written by hand, see `lrplugin/README.md`).
Use a **test catalog** for the first pass.

macOS-specific items (V1–V11 of the build plan):

- [x] V1: after `install.sh` the plugin is listed in Plug-in Manager as installed and running
      **without** "Add" (the `Modules` folder auto-loads on macOS). If not, note it: the
      fallback is Add → `~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin`.
      *(2026-11-20: reported done by the owner.)*
- [x] V2, V5: with no server running, Identify starts it through `engine.json` →
      `bin/wildid-server-start`: Lightroom does not freeze, no Terminal window opens, the
      progress reaches "identifying". Afterwards `pgrep -fl "wildid serve"` shows one process.
      *(2026-11-20: reported done by the owner.)*
- [x] V3: hand-install route. Remove `engine.json` from the plugin folder, start a server by
      hand (`wildid serve`) and run Identify: the plugin finds it through
      `~/Library/Caches/wildid/serve.json` (`io.open` and `os.getenv('HOME')` work in
      Lightroom's Lua on macOS). Put `engine.json` back.
      *(2026-11-20: reported done by the owner.)*
- [x] V8: the Identify dialog's memory line reads "Apple M5 Pro, unified memory: 40.2 GB
      usable" and "Keep both models loaded" is enabled on this Mac (40.2 GB passes the 30 GB
      rule for unified memory). The two subscripts end on "~12 GB memory" and "~13 GB memory"
      and the checkbox reads "Keep both models loaded (~20 GB memory)": no "VRAM" anywhere.
      With both loaded, "WildID: server status…" lists both models; note `vram.free_gb`.
      Negative case (cannot be shown on this Mac): below 30 GB usable the checkbox is
      disabled with the note "below the 30 GB needed for both models", and a tick made
      before the server was running is not honoured once the server reports its memory. The
      rule is covered by `lrplugin/tests/models_test.lua`; the second half is one line in
      `WildidIdentify.lua` that no test reaches.
      *(2026-11-20: reported done by the owner; no `vram.free_gb` figure is recorded.)*
- [x] V11: no Gatekeeper dialog at any point; `xattr -l "$HOME/Library/Application Support/WildID/uv"`
      shows no `com.apple.quarantine`. *(2026-11-20: reported done by the owner. The command,
      run that day, lists `com.apple.provenance` only.)*
- [x] V4: Smart Preview fallback with originals on an external drive
      (`/Volumes/<drive>/…`), drive ejected: those photos are identified from the Smart
      Preview and counted in the summary; offline originals without one are skipped and counted.
      *(2026-11-20: reported done by the owner.)*

The Windows items, once each on the Mac (V7; details and expected results are in
`docs/acceptance-lightroom.md` §B, read paths in their macOS form):

- [ ] Plugin loads with no Plug-in Manager errors; the five entries appear in the Library
      menu and File → Plug-in Extras; "Identify" is greyed without a selection.
- [ ] "WildID: server status…" shows ready, model and uptime; Stop works.
- [ ] Small run (5 mixed photos, crop on, no geo): dialog values persist; progress and summary
      correct; keyword tree `WildID → class → genus → species` with the common name as
      synonym; flat `animals` and `wildlife`; Metadata panel → "All Plug-in Metadata" shows
      species, class, score, status, model, run; collections
      `WildID/<class>/<genus>/<species — common name>`; a low-confidence frame in `_review`
      with `WildID|review`.
- [ ] Model choice: both radios with their subscripts; a run with bioclip-2.5 shows the model
      loading and names it in the summary; with "keep both loaded" the switch is instant.
- [ ] Geo run: "WildID: prefetch place list…" (online) for a trip place, then Identify with
      the place set: out-of-place frames are flagged for review.
- [ ] Auto-geo from GPS: prefetch the selection's GPS cells, then Identify with "each photo's
      GPS position"; a photo without GPS runs unfiltered, one in a cell not prefetched is
      flagged, the summary counts both.
- [ ] Move-on-rerun: a species change moves the photo between species collections, the
      summary counts it; keywords under `WildID` are replaced and stale `animals` /
      `wildlife` come off.
- [ ] Big run (200+ photos): smooth progress; cancel mid-run commits whole chunks only; a
      re-run is idempotent.
- [ ] Kill the server mid-run (`pkill -f "wildid serve"`): clean error dialog naming how many
      photos were already tagged.
- [ ] Edge cases: a folder with diacritics and spaces in its path round-trips; a virtual copy
      is skipped and counted; dry run writes nothing but reports counts.
- [ ] "WildID: delete empty collections…" lists and deletes empty collections and the genus
      and class sets a move emptied; smart collections and the chosen set stay.
- [ ] "WildID: mark as reviewed": the selected flagged photos leave `_review`, lose
      `WildID|review` and show status `reviewed`; Edit → Undo puts keyword and membership back.
- [ ] Exact detector resize *(added 2026-11-15)*: the checkbox "Exact detector resize (the
      same on a Mac and a PC)" under the crop row is off the first time, greyed while the
      crop and the second opinion are both off, and keeps its state between runs. Its title
      is not clipped. A run with it on finishes as usual.
- [ ] Dialogs, the bezel message and combo boxes look right on macOS (fonts, widths, no
      clipped text). Note anything that reads badly.

## C. Sidecars on real ARWs

Copies only; use a test catalog. The same twelve steps as the Windows run
(`docs/acceptance-lightroom.md` §C), on a copy of `sample-arw/`:

*2026-11-14, samples: steps 1–4 and 10 done outside Lightroom on copies of 12 ARW + 1 DNG +
1 TIF (lion, fossa, landscape), and the merge of step 11 on wildid's own sidecars; numbers in
`docs/acceptance.md`. Steps 5–9, 11 on a Lightroom-written sidecar, and 12 need Lightroom.*

1. - [x] Copy 20–50 ARWs (mammals, a reptile, a bird, an empty frame) to `~/xmp-test`.
2. - [x] Dry run: `uv run wildid ~/xmp-test --write-xmp --dry-run --crop [--country …]`
         → "xmp dry run … N written", no file on disk.
3. - [x] Real run with `--format json --output run.json`: one `.xmp` per ARW; note the
         number of `"review": true` results. *(12 sidecars; 3 of 13 results `review`.)*
4. - [x] One sidecar in a text editor: `dc:subject`, `lr:hierarchicalSubject`
         (`WildID|class|genus|species` plus the flat tags), the `wildid:*` provenance.
5. - [ ] Import with **Add**: no "metadata changed" badges.
6. - [ ] Keyword List: a real nested `WildID` tree; `review` count ≈ run.json's; `animals` /
         `wildlife` as plain top-level keywords, absent on the empty frames.
7. - [ ] Species keyword appears once; the common name is a separate flat keyword (designed).
8. - [ ] The review set is the genuinely ambiguous frames.
9. - [ ] WildID plugin metadata fields stay empty for sidecar-imported photos (expected).
10. - [x] Idempotence: the same command again → "0 written … N skipped", files untouched.
11. - [ ] Merge on a genuine Lightroom sidecar **(Cmd+S first)**: develop-edit one photo,
          Cmd+S, `uv run wildid <file> --write-xmp --xmp-mode merge --keyword-root WildID2`,
          then Metadata → Read Metadata from File: develop edits intact, old keywords intact,
          `WildID2` added. **Any lost develop edit is a hard fail: keep the sidecar.**
12. - [ ] After Lightroom's own rewrite the sidecar still contains the `wildid:*` block.

## D. Installer

- [x] Build: `bash installer/macos/build.sh` → `installer/macos/output/WildID-<version>-macos-arm64.zip`
      and `SHA256SUMS.txt`. *(2026-11-14: 22.6 MB; uv 0.11.32 checked against its published
      `.sha256`.)*
- [x] Install into a throwaway home folder (`HOME=<scratch> bash …/install.sh --no-path`).
      *(2026-11-14: `uv sync --frozen` through the bundled uv, 77 packages; payload, plugin
      copy and a valid `engine.json` with executable `start` and `cli`; `wildid --version`;
      a classification on MPS through the installed launcher; `wildid-server-start` returned
      in 0.3 s and the detached server answered `/health`, `/classify`, `/shutdown`; a second
      run added the PATH line once; from a folder with every file quarantined the install ran
      and left no quarantine flag; `uninstall.sh` removed program, plugin and PATH line and
      kept the cache; `--purge` removed only WildID's folders.)*
      *(2026-11-15, repeated after the installer was made to use uv's own Python, with
      Homebrew's Python 3.14.7 on PATH: uv downloaded CPython 3.14.6 and built the
      environment on it, not on Homebrew's; 77 packages, 8 s in all; no quarantine flag left;
      `wildid --version`; the bear fixture through the installed launcher gives the checkout's
      answers, crop and second opinion included; the server through `wildid-server-start`
      was ready in 3.7 s on `mps` and answered `/health`, `/classify`, `/shutdown`; a second
      `install.sh` kept the environment; `uninstall.sh` left only uv's two folders. Figures in
      `docs/acceptance.md`.)*
- [ ] Real install, as a user would: a fresh user account (or this one) → download the zip
      **in Safari**, so it is quarantined → unzip in Finder → Terminal:
      `bash ~/Downloads/WildID-<version>-macos-arm64/install.sh`. Expected: the environment
      download with visible progress, the plugin copied, `engine.json` correct, the PATH
      question asked. `~/Library/Application Support/WildID/install.log` records it.
      The download starts with uv's own Python ("Downloading cpython-3.14…") although this
      Mac has Homebrew's; afterwards
      `readlink "$HOME/Library/Application Support/WildID/app/.venv/bin/python"` points into
      `~/.local/share/uv/python/`.
- [ ] The documented claim: double-clicking `install.sh` in Finder does **not** install
      (blocked, or opened in an editor), and `bash install.sh` does. If macOS behaves
      otherwise, `README-macOS.md` needs correcting.
- [ ] A **new** Terminal window: `wildid-setup` runs the wizard to "Setup complete".
- [ ] Lightroom: the plugin auto-loaded (V1), Identify works, no Gatekeeper dialog (V11).
- [ ] `bash "$HOME/Library/Application Support/WildID/uninstall.sh"`: program, plugin and the
      PATH line gone; `~/Library/Caches/wildid` and the Hugging Face cache intact.
- [ ] Upgrade: run `install.sh` from a newer zip over an existing install; a running server is
      stopped, models are kept.
- [x] CI: Actions → *release* → Run workflow with `create_release` **off**. Expected: the Lua
      job, the engine tests on Linux and on `macos-15`, and both builds green; artifacts
      `wildid-<version>-windows` and `wildid-<version>-macos-arm64`; the macOS job's install
      smoke passes. Install the CI-built zip once the same way as the local one.
      *(2026-11-15: the first run, started by the owner. Everything expected
      is green, in 2 min 29 s; the macOS job ran on macOS 15.8.2. The smoke's log showed two
      gaps in what it proved, see `docs/acceptance.md`: uv built the environment on the
      runner's Homebrew Python 3.14 and not on a managed one, and the bundled uv downloaded
      nothing because the job's uv cache was warm. Both were closed the same day: the
      installer makes uv use its own Python, and the smoke installs in a bare environment.
      Second run: green in 2 min 34 s, and in the smoke the bundled
      uv downloaded CPython 3.14.6 and every wheel itself. The zip of that run, downloaded
      and checked against the logged SHA-256, holds the same 49 files as the Mac-built one,
      byte for byte; installed by hand into a throwaway home folder as the local one was:
      7 s, on uv's Python, no quarantine flag left, `wildid --version`, the bear fixture as
      in the checkout, a second `install.sh` and `uninstall.sh` as expected.)*
- [x] The engine through an installed copy, on the Python a user gets *(added and done
      2026-11-15, on the owner's go)*: an installed WildID runs on the CPython 3.14.6 that uv
      downloads; everything in section E was measured in the checkout on Homebrew's 3.14.7.
      Ten of the reference runs repeated through the copy installed from the CI-built zip
      (`sample-jpg` and `sample-arw` with both models, with and without crop; the Kenya rows
      with place list, anomaly check and second opinion): all 4,520 results equal in every
      field, every score difference 0, at the checkout's speed. Through
      `wildid-server-start`, a 24-photo crop request on RAW files gives the command line's
      answers. Sample folders and real caches untouched. Table in `docs/acceptance.md`.

## E. Measurement — MPS against CUDA, speed, memory (E8 of the build plan)

Purpose: the repository has **no macOS figure**. The build only showed that one photo gives
the same answer on MPS and on CPU. This section decides whether MPS-fp32 answers match the
accepted Windows CUDA-tf32 run, what the Mac's speed and memory use are, whether fp16 may be
offered on MPS, and whether the 20 GB "keep both models loaded" rule fits unified memory.

*2026-11-14, samples: measured; table and readings in `docs/acceptance.md`. In short: MPS
gives the CPU reference's answer on 863 of 863 frames for both models and on 552 of 552
through crop and place list; the Kenya matrix reproduces the Linux CUDA run; 33 and 17 images
per second in fp32, 82 and 48 with fp16; 11.7 GB footprint for the daemon with bioclip-2 under
load, 20.1 GB with both models.*

- [x] The same command on both machines, per model, no geo filter, no crop (the plainest
      comparison of the two backends): *(the Mac half; outputs in
      `~/.cache/wildid-acceptance/2026-11-14-macos/`)*

```sh
mkdir -p out
uv run wildid sample-jpg --model bioclip-2   --k 1 --format json --output out/mac-b2.json
uv run wildid sample-jpg --model bioclip-2.5 --k 1 --format json --output out/mac-b25.json
# on the Windows box the same two commands write out\win-b2.json and out\win-b25.json
```

- [x] Top-1 agreement, MPS-fp32 against CUDA-tf32 (expected: at least 99.5 % identical).
      *(2026-11-15, per file: 863 of 863 for bioclip-2 and for bioclip-2.5 on `sample-jpg`,
      157 of 157 on `sample-arw`; largest score difference 0.0069, 0.0185 and 0.0080, all of
      it TF32: against CUDA in fp32 the scores agree to 0.0002. Compared with `compare.py`
      and `deep_compare.py` in `~/.cache/wildid-acceptance/2026-11-15-macos-installed/`,
      which do what the script below does, and more.)* *(Beyond this box: with `--crop` the
      two machines agree on 2,003 of 2,040 answers, 98.2 %. The detector's box differs, by
      a pixel or two on about a third of the JPGs. Whether CUDA's TF32 is behind that is
      backlog item 10. Figures in `docs/acceptance.md`.)* *(2026-11-15, from the Linux box:
      TF32 alone changes the crop on 30 of the 863 JPGs, too few to be behind it. The four
      CUDA runs in fp32 have still to come to this Mac for the comparison that decides. The
      Linux box's CPU gives CUDA's fp32 crops on every frame, so the CUDA backend is not
      behind it either; those four CPU runs are to be compared here as well, backlog item
      11.)* *(2026-11-15, compared here: against CUDA in fp32 and against the Linux box's CPU
      the Mac's crop differs on the same 281 JPGs and 10 RAW files, and 38 of 2,040 answers
      differ. Neither the precision nor the backend: the two machines hand the detector
      different pixels. Which step makes them differ is backlog item 12.)* *(2026-11-15,
      from the Linux box, its part of item 12: switching OpenCV's Intel IPP off changes
      nothing there, neither the letterboxed image nor a crop. IPP is not it. This Mac's
      checksums against the Linux box's `.tsv` files are still to be made.)* *(2026-11-15,
      made: both machines hand the detector the same image, on all 1,020 photos. What
      differs is the resize before the detector: the Linux box computes OpenCV's portable
      `INTER_LINEAR`, this Mac's OpenCV uses Arm-specific code that differs by 1 in about a
      fifth of the pixel values. Cause found; whether to make the crop the same on both
      is the owner's decision. `docs/acceptance.md`, last section.)*

```sh
uv run python - <<'PY'
import json, pathlib

def top1(path, flavour):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    out = {}
    for r in doc["results"]:
        if r["ok"] and r["predictions"]:
            parts = flavour(r["path"]).parts
            out["/".join(parts[-2:])] = (r["predictions"][0]["species"], r["predictions"][0]["score"])
    return doc["device"], doc["precision"], out

for tag in ("b2", "b25"):
    mdev, mprec, mac = top1(f"out/mac-{tag}.json", pathlib.PurePosixPath)
    wdev, wprec, win = top1(f"out/win-{tag}.json", pathlib.PureWindowsPath)
    both = sorted(set(mac) & set(win))
    diff = [k for k in both if mac[k][0] != win[k][0]]
    print(f"{tag}: {mdev}/{mprec} vs {wdev}/{wprec}: {len(both) - len(diff)}/{len(both)} identical top-1, "
          f"max |dscore| {max((abs(mac[k][1] - win[k][1]) for k in both), default=0):.4f}")
    for k in diff:
        print("   ", k, "mac:", mac[k], "win:", win[k])
PY
```

- [x] The same comparison on the Mac alone, `--device cpu` against the default `mps`
      (separates the backend from the platform), at least for bioclip-2. *(Both models:
      863/863, max |Δscore| 0.0003 and 0.0002; with crop and the Madagascar list 552/552,
      0.0000.)*
- [x] Speed: images per second for bioclip-2 and bioclip-2.5, with and without `--crop`
      (`time uv run wildid sample-jpg --model … --k 1 > /dev/null`, frames divided by the
      seconds after the model load; `-v` prints the load time, the cold-load figure to note).
      *(33.4 and 17.3; with crop 21.0 and 13.5; load 3.1 s and 5.2 s.)*
- [x] Memory: `/health.vram.free_gb` and Activity Monitor's figure for the `python` process
      with one model, with both (`POST /warmup` for the other), idle and under 24-photo crop
      requests (the plugin's chunk). *(Footprint idle / under load: bioclip-2 9.4 / 11.7 GB,
      bioclip-2.5 12.9 / 13.4 GB, both 19.2 / 20.1 GB.)*
- [x] fp16 on MPS, the measurement switch:
      `WILDID_MPS_FP16=1 uv run wildid sample-jpg --precision fp16 --k 1 --format json --output out/mac-b2-fp16.json`
      (and the same for 2.5) → top-1 agreement against `out/mac-b2.json` and the speed.
      *(bioclip-2 851/863 same top-1 at 2.5 times the speed, bioclip-2.5 862/863 at 2.8
      times; every changed frame is a near-tie between low-scoring candidates.)* *(Since
      2026-11-15 the switch is gone: `--precision fp16` alone does this on a Mac, and gives
      these runs' answers on 863 of 863 frames for both models.)*
- [x] fp16 on the plug-in's path, added 2026-11-15: the same switch with `--crop` on both
      sample folders, and through the daemon in 24-photo crop requests on the RAW files,
      against fp32 baselines of the same session (`driver.sh` in
      `~/.cache/wildid-acceptance/2026-11-15-macos/`). *(Daemon: 15.4 → 21.4 img/s with
      bioclip-2, 10.2–10.7 → 16.4–17.5 with bioclip-2.5. 13 of 2,040 CLI results and 4 of 314
      daemon results change, every one a review frame in both precisions. About 2 GB more
      memory.)*
- [x] Decisions, the owner's to take; the figures are in `docs/acceptance.md`. *(All taken
      on 2026-11-15 and built the same day.)*
      1. *Do MPS answers match?* Settled by the data, nothing to decide: identical to the CPU
         reference on every frame, and the Kenya matrix reproduces the CUDA run.
      2. *fp16 on MPS: offered or not?* **Decided 2026-11-15 (owner): offered as the opt-in
         it is on CUDA; the plug-in's server stays on fp32.** It behaves like fp16 on CUDA
         (13 of 1,726 answers change, all near-ties) and is worth much more here for bare
         classification: 2.5 to 2.8 times the speed against 1.5 to 1.9 on CUDA. Until the
         decision `--precision fp16` on a Mac warned and ran fp32. The options were to keep
         it off, to offer it as the opt-in it is on CUDA, or also to start the plug-in's
         server with it on Macs. Measured for that third option on 2026-11-15: on the
         plug-in's path (crop, RAW, the daemon) fp16 is worth 1.4 times with bioclip-2 and
         1.6 times with bioclip-2.5, costs about 2 GB, and every answer it changes is a
         review frame in both precisions.
      3. *"Keep both models loaded" on unified memory.* **Decided 2026-11-15 (owner): 30 GB
         on a Mac.** Both models take 20.1 GB under load and Lightroom needs its own share of
         the same memory; the 20 GB rule, applied to Metal's recommended maximum, would pass
         a Mac with nothing left over. Built the same day: `kind: unified` has its own
         threshold, 30 GB of that figure (ADR 0008 decision 5). Only this 48 GB machine
         (40.2 GB recommended) has been measured.
      4. *Detector batch size.* No change needed: memory is flat and nothing ran out.
      5. *What to say about smaller Macs.* **Decided 2026-11-15 (owner): "the requirements
         state only what was measured - I cannot get a smaller Mac".** The requirement lines
         name this one machine and say that no other Mac has been tried; they state no
         minimum memory and give no advice for smaller Macs (ADR 0008 decision 8). What was
         measured here: the daemon holds 11.7 GB with bioclip-2 under load and the CLI peaks
         at 15.8 GB with crop. Nothing was measured on a 16 GB or 24 GB Mac.
      The outcome is recorded in ADR 0003 (precision on MPS) and ADR 0008. The macOS figures
      went onto the website and into the READMEs on 2026-11-15, on the owner's word, before
      B, C and D had passed (`website/TODO_WEBSITE.md`, "macOS on the site", which also says
      how the requirements are worded). The Lightroom Classic version used on the Mac joins
      the "Tested on exactly one Mac" paragraph of `README-macOS.md` once B has run.

## When something fails

Fix-or-file per deviation with the step number, the artifact (sidecar file, server log,
screenshot of the dialog or the Keyword List) and the macOS and Lightroom versions. Levers
that exist without code changes:

- `engine.json` (`start`, `cli`, `cacheDir`) next to `Info.lua` in the plugin folder;
- `WILDID_SERVER_LOG=~/wildid-server.log wildid-server-start` keeps the server's output;
- `~/Library/Application Support/WildID/install.log` records what the installer did;
- `wildid classify <photo> -v` names any operator that fell back from MPS to the CPU;
- `--device cpu` takes MPS out of the picture when a result looks wrong;
- `xattr -dr com.apple.quarantine "$HOME/Library/Application Support/WildID"` if macOS
  refuses to run an installed file.
