# WildID installers (Windows and macOS)

One per-user installer per platform carries the engine (as a locked uv project, resolved on
the target machine) and the Lightroom Classic plugin: an Inno Setup `.exe` for Windows, a zip
with `install.sh` for macOS on Apple Silicon (its own section below). Unsigned: signing is
phase P of the plan (lightroom-plugin-plan.md L14, §6.6) — on the Windows SmartScreen prompt
use *More info → Run anyway*.

## Build (on Windows)

```powershell
cd installer\windows
powershell -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` downloads a pinned, checksum-verified `uv.exe`, stages `payload\`
(uv.exe + `app\` with pyproject/uv.lock/src + `wildid.lrplugin`), and compiles `wildid.iss`
with Inno Setup 6 into `output\WildID-Setup-<version>.exe`.

## What the installer does on a target machine

1. Installs to `%LOCALAPPDATA%\Programs\WildID` (per-user, no admin prompt):
   `uv.exe`, the project under `app\`, and the launchers `wildid.cmd`,
   `wildid-setup.cmd`, `wildid-server-start.cmd` (windowless server start via pythonw).
2. Runs `uv sync --frozen` — downloads the pinned wheels (PyTorch is several GB; network
   required) and the pinned Python itself: always uv's own, also on a PC that has a
   Python 3.14 (`python-preference = "only-managed"` in the shipped `pyproject.toml`; rule
   of 2026-11-15 for every system). The launchers self-heal: they re-sync if the
   environment is missing.
3. Copies the plugin into `%APPDATA%\Adobe\Lightroom\Modules\wildid.lrplugin` (Lightroom
   auto-loads it — no Plug-in Manager step) and writes `engine.json` there so the plugin can
   find, start and stop the engine.
4. Start-menu entries: **WildID Setup** (the first-run wizard: model download → offline
   verification; it offers an optional Hugging Face token first) and **WildID Server**.
5. Uninstall removes the program and the plugin but keeps the caches
   (`%LOCALAPPDATA%\wildid`, the Hugging Face cache), so a reinstall needs no re-download.

## Known Windows behaviour

- `RedirectionGuard=no` in `wildid.iss`: Inno Setup 6.7+ enables Windows' RedirectionGuard on
  Setup, `[Run]` children inherit it, and uv's managed-Python alias directory is a junction
  created by a non-elevated user — `uv sync` then fails with "The path cannot be traversed
  because it contains an untrusted mount point" (os error 448). Found on Windows 11 25H2 during
  acceptance (2026-10-25). Keep it off unless the installer becomes an elevated one.
- `wildid-server-start.cmd` starts the server through `Start-Process -WindowStyle Hidden`:
  uv's venv `pythonw.exe` is a console-subsystem trampoline (uv 0.11), so a plain `start`
  leaves a console window open for the server's lifetime. The launcher's own console still
  flashes briefly; that is expected.

## macOS (Apple Silicon)

One zip, `WildID-<version>-macos-arm64.zip`, carries what the Windows installer carries — a
pinned `uv`, the locked project, the launchers, the Lightroom plugin — plus `install.sh`,
which does on the target Mac what Inno Setup does on Windows. No `.pkg`, no `.dmg`, no root,
no password, nothing outside the user's home folder (ADR 0008).
Built on 2026-11-14; the acceptance on a Mac with Lightroom is `docs/acceptance-macos.md`.

### Build (on macOS or Linux)

```sh
bash installer/macos/build.sh
```

`build.sh` downloads the pinned `uv` for Apple Silicon and checks it against the release's
published `.sha256`, stages `payload/WildID-<version>-macos-arm64/` and writes the zip plus
`SHA256SUMS.txt` into `output/`. The zip is plain files, which is why CI builds it on
`ubuntu-latest`. The user's instructions travel inside it as `README-macOS.md`.

### What `install.sh` does on a target Mac

It is run from Terminal as `bash …/install.sh`, never by double-click (see below).

1. Refuses Intel Macs, macOS older than 14 (the floor of the locked torch wheel) and `sudo`.
2. Copies the payload to `~/Library/Application Support/WildID`: `uv`, `app/` (the project;
   its `.venv` appears with the first sync), `bin/` with `wildid`, `wildid-setup` and
   `wildid-server-start`, the plugin's copy source, `uninstall.sh`, `VERSION`, `install.log`.
   A server still running from a previous install is stopped first.
3. Clears `com.apple.quarantine` on what it copied.
4. Copies the plugin into `~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin`
   and writes `engine.json` there (`start`, `cli`, `cacheDir` as absolute paths).
5. Runs `uv sync --frozen` (about 1.2 GB on disk; network required). uv downloads its own
   CPython into `~/.local/share/uv` and never builds on a Python the Mac happens to have
   (Homebrew, python.org), which its default would do: `python-preference = "only-managed"`
   in the shipped `pyproject.toml`, the same rule as on Windows. The launchers self-heal:
   they re-sync if the environment is missing, so an install without network is not lost.
6. Offers one marker-guarded PATH line in `~/.zprofile` (and in `~/.bash_profile` where that
   file exists). `--path` / `--no-path` answer in advance; a non-interactive run leaves PATH
   alone. Nothing depends on PATH: `engine.json` and the closing message use full paths.
7. Names the next step: `wildid-setup`, the same first-run wizard as on Windows.

Running `install.sh` from a newer zip is the upgrade. `uninstall.sh` removes the program, the
plugin and the PATH line and keeps the caches; `--purge` also deletes
`~/Library/Caches/wildid` and WildID's three model folders in the Hugging Face cache, never
the whole cache.

### Known macOS behaviour

- Gatekeeper: everything unzipped from a browser download carries `com.apple.quarantine`.
  `bash install.sh` runs anyway, because the file being executed is `/bin/bash`; a
  double-click or `./install.sh` is blocked. The bundled `uv` is only ad-hoc signed, not
  notarized (`spctl` rejects it), so the flag has to come off the installed copy before first
  use: step 3. Checked on macOS 26.5 (2026-11-14): a fully quarantined folder installs and
  the installed files carry no flag. A real browser download on a fresh account is acceptance
  item D.
- No window trick is needed: `wildid-server-start` is `nohup … &` and returns at once (0.3 s
  from a shell). `WILDID_SERVER_LOG=<file>` keeps the server's output for debugging.
- The launchers find themselves through `/bin/realpath` (present since macOS 13), so a
  symlink to them works.
- The scripts are written for the bash 3.2 that macOS ships. `.gitattributes` pins them to LF
  line endings: a CRLF checkout would produce scripts that do not run, and `build.sh` refuses
  to package one.
- A photographer's Mac is assumed to have no Homebrew, no Python and no developer tools
  (owner, 2026-11-15). The scripts therefore call only what macOS ships: on such a Mac
  `python3`, `git` or `make` are stubs that open Apple's offer to install the developer
  tools. `tests/test_installer_macos.py` keeps this, and that every uv call of the installed
  scripts on both systems names the project, so the Python rule of step 5 is in force.

## Not automated here (deliberately)

- No code signing and no public release channel: phase P of the plan.
- CI (`.github/workflows/release.yml`) runs the Lua and Python suites, builds the installer on
  `windows-latest` with this same `build.ps1` and uploads installer + `SHA256SUMS.txt` (the
  installer carries the plugin; no separate plugin package). It builds the macOS zip on
  `ubuntu-latest` with `installer/macos/build.sh`, and a `macos-15` job runs the engine tests
  and then installs that zip for real as the runner user (quarantined unzip, `bash install.sh`,
  `wildid --version`, `uninstall.sh`), in a bare environment: stock PATH, none of the job's
  variables, an empty uv cache, so the bundled uv downloads Python and every wheel as it does
  on a Mac without Homebrew or Python. Pushing a tag `v<version>` also
  **publishes a GitHub Release on that tag** (since 2026-11-15; before, it made a draft to
  publish by hand) with both downloads and one `SHA256SUMS.txt`, once every build and test
  job is green. A version with an `aN`, `bN`, `rcN` or `.devN` suffix is published as a
  pre-release. If a release or a draft for that tag exists already, the step fails and says
  so. **The tag decides the version**:
  every job first runs `installer/set_version.py` to rewrite `pyproject.toml`,
  `src/wildid/__init__.py`, `Info.lua` and the root entry of `uv.lock` to it, so the sources
  need no bump before tagging (the repository stays as it was). A manual dispatch builds the
  version `pyproject.toml` says and uploads artifacts only unless `create_release` is ticked,
  which makes a *draft* release to publish by hand. `tests/test_release_workflow.py` runs the
  release step against a stand-in for `gh`, once per trigger.

## Bumping the version by hand

`python installer/set_version.py 0.3.1` (a leading `v` is fine) rewrites the four places the
version lives — `pyproject.toml`, `src/wildid/__init__.py`, `lrplugin/wildid.lrplugin/Info.lua`
and the root entry of `uv.lock` — and writes nothing unless all four match. It accepts
`X.Y.Z` with an optional `aN`/`bN`/`rcN`, `.postN` or `.devN` suffix (`1.2.3-rc1` is
normalised to `1.2.3rc1`); the plugin's `VERSION` takes the three numbers only. The lock edit
is the line `uv lock` would write, so `uv lock --check` passes afterwards and the engine
tests run `uv sync --locked`.
