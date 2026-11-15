# WildID for macOS

Species identification for wildlife photos, with a plug-in for Lightroom Classic. Everything
runs on your Mac: no photo leaves it.

**Needs:** a Mac with Apple Silicon (a chip of the M series) and macOS 14 or newer: the
installer accepts nothing else, and Intel Macs are not supported. The Lightroom plug-in needs
Lightroom Classic 15 or newer; the command line works without Lightroom. Nothing else has to
be installed first, no Python and no developer tools: WildID downloads its own Python and
never uses one your Mac may already have.

**Tested on exactly one Mac:** a MacBook Pro with an M5 Pro chip and 48 GB of memory, running
macOS 26.5. On it WildID identifies about 16 photos per second from RAW files with the crop
on, and its engine holds about 12 GB of memory with the default model, about 13 GB with
the larger one and about 20 GB with both. No other Mac has been tried, so nothing is known
about how WildID runs on a Mac with less memory.

## Install

1. Unzip the download (double-click it in Finder).
2. Open Terminal (Applications → Utilities → Terminal) and run, with the folder name of your
   download:

   ```
   bash ~/Downloads/WildID-<version>-macos-arm64/install.sh
   ```

   Type `bash` in front as shown. WildID is not signed with an Apple developer certificate, so
   macOS refuses to start `install.sh` by double-click. Handing the script to `bash` is not
   subject to that check. No password is asked for and nothing outside your home folder is
   touched.
3. The installer copies WildID into your home folder, downloads its own Python and the
   libraries it needs (about 1.2 GB on disk, needs the network), installs the Lightroom
   plug-in and asks whether to put the `wildid` commands on your PATH. Say yes unless you have
   a reason not to.
4. Open a **new** Terminal window and run the setup wizard:

   ```
   wildid-setup
   ```

   It downloads the model (4.4 GB for the default one) and checks that WildID then works
   without the network. A Hugging Face account is not needed.
5. Start Lightroom Classic (restart it if it was open). File → Plug-in Manager lists
   **WildID** as installed and running. Select photos, then Library → Plug-in Extras →
   **Identify species with WildID…**

If Lightroom does not list the plug-in, add it by hand: Plug-in Manager → Add → the folder
`~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin`.

## What goes where

| Folder | Content |
|---|---|
| `~/Library/Application Support/WildID` | the program: `uv`, the Python project and its environment, the `wildid` commands in `bin`, `uninstall.sh`, `install.log` |
| `~/Library/Application Support/Adobe/Lightroom/Modules/wildid.lrplugin` | the Lightroom plug-in and `engine.json`, which tells it where the program is |
| `~/Library/Caches/wildid` | detector and SpeciesNet files, species lists, the server's `serve.json` |
| `~/.cache/huggingface` | the models (shared Hugging Face cache) |
| `~/.local/share/uv` | the Python that WildID runs on, downloaded by `uv` |
| `~/.cache/uv` | `uv`'s download cache |
| `~/.zprofile` | one line that puts the `wildid` commands on your PATH, if you said yes |

The commands, also usable by their full path in `~/Library/Application Support/WildID/bin`:

- `wildid` — the command line (`wildid --help`)
- `wildid-setup` — the setup wizard; run it again before a trip to fetch a species list
- `wildid-server-start` — starts the server Lightroom talks to; the plug-in does this itself

## Upgrade

Download the newer zip and run its `install.sh` the same way. Models and species lists are
kept.

## Uninstall

```
bash "$HOME/Library/Application Support/WildID/uninstall.sh"
```

This removes the program, the plug-in and the PATH line. The downloaded models and species
lists are kept, so a reinstall needs no new download; add `--purge` to delete them too.
`uv`'s two folders, `~/.local/share/uv` and `~/.cache/uv`, stay in either case: delete them by
hand if nothing else on your Mac uses `uv`.

## If something goes wrong

- **macOS says a WildID file "cannot be opened" or "is damaged".** The download quarantine
  flag is still on it. Clear it and try again:

  ```
  xattr -dr com.apple.quarantine "$HOME/Library/Application Support/WildID"
  ```

- **The Python environment did not download** (no network during install). Run
  `wildid --version` once you are online: the command downloads what is missing.
- **Lightroom says the server did not start.** Start it by hand with a log, then look at the
  file:

  ```
  WILDID_SERVER_LOG=~/wildid-server.log wildid-server-start
  ```

- `~/Library/Application Support/WildID/install.log` records what the installer did.

## Licence and source

WildID is free software under the GNU Affero General Public License, version 3 or later (see
`LICENSE` in this folder). The source code is at <https://github.com/Trogious/wildid>.
