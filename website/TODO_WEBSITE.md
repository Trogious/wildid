# Website: what is still needed

Open items for the project website in this folder before it can go live, as of 2026-11-13.
How to apply each one is described in [`README.md`](README.md). Tick an item when it is done.
File paths below are given from the repository root.

## Publishing on GitHub Pages

`.github/workflows/pages.yml` publishes this folder. Its job is skipped in a private
repository, and without the second step below it fails at its "Pages settings" step and
publishes nothing. Once, in this order:

- [x] Switch the repository to public. *(2026-11-15)*
- [x] Settings → Pages → Build and deployment → Source: **GitHub Actions**. *(2026-11-15)*
- [ ] The first publication: a push to `main` that changes `website/` runs the workflow by
      itself; otherwise Actions → website → Run workflow. The run's summary shows the address:
      `https://trogious.github.io/wildid`, unless a custom domain is set. Later changes under
      `website/` publish themselves.
- [ ] **Search engines.** Under the default address the site sits in a sub-path, where search
      engines do not read `robots.txt`. Submitting the sitemap in Google Search Console covers
      it: add the site there and submit `sitemap.xml`. A custom domain removes the limitation.
- [ ] Optional: a custom domain under Settings → Pages. The next run writes it into every
      page.

## URLs

- [x] **Site address.** Done by the workflow: at every run it puts the address GitHub Pages
      reports in place of the placeholder `https://WILDID-SITE-URL.invalid`. The placeholder
      stays in the repository on purpose.
- [ ] **Downloads, Windows and macOS.** The download buttons point to
      `https://github.com/Trogious/wildid/releases/latest`. Confirm, or name another location.
      The link works once a release is published; a draft is not enough. Since 2026-11-15 a
      pushed tag publishes the release itself, with both downloads. The repository has no
      release yet.
- [ ] **Source code.** The links point to `https://github.com/Trogious/wildid`. Confirm. The
      repository is public since 2026-11-15.
- [ ] **Problem reports.** "Report a problem" points to the repository's GitHub issues.
      Confirm, or name another channel.

## Screenshots

Overwrite the placeholder PNGs in `website/img/screenshots/` under the same file names. No
page needs editing. Any size works; about 16:10 looks best.

- [ ] `lightroom-after-run.png`: the whole Lightroom Classic window after a run, with the
      WildID collection tree on the left and the Keyword List on the right. Photos you are
      happy to publish.
- [ ] `win-smartscreen.png`: "Windows protected your PC" after More info, with Run anyway
      visible.
- [ ] `win-installer.png`: the installer on its Installing page, with the black download
      window.
- [ ] `win-installer-finish.png`: the installer's last page, with the setup wizard ticked.
- [ ] `win-wizard-questions.png`: the setup wizard with its questions answered.
- [ ] `win-wizard-done.png`: the setup wizard at "Setup complete".
- [ ] `lr-plugin-manager.png`: the Plug-in Manager with WildID installed and running.
- [ ] `lr-menu.png`: the Library menu at Plug-in Extras, showing the five WildID entries.
- [ ] `lr-identify-dialog.png`: the Identify dialog with default settings.
- [ ] `lr-summary.png`: the summary after a run.
- [ ] `lr-results-panels.png`: a close-up of Collections, Keyword List and Metadata after a
      run.
- [ ] `lr-prefetch-dialog.png`: the prefetch place list dialog with a country typed in.

Optional:

- [ ] `website/img/og-image.png`, the image shown when a link to the site is shared, is a
      finished typographic card. Replace it only if you want a photo-based one, 1200 × 630
      pixels.

## macOS on the site

Since 2026-11-15 the site presents macOS as available, on the owner's word ("it's there
now"): no "coming soon" is left anywhere. Done that day:

- [x] `index.html`, download cards: a real macOS card. Zip download from the release; "Apple
      Silicon, macOS 14 or newer, Lightroom Classic 15 or newer"; the one Mac it was tested
      on.
- [x] `index.html`, "Install on macOS, for Lightroom Classic": the guide from the download to
      the first Identify run. Unzip, Terminal, `bash install.sh`, why no double-click while
      unsigned, the PATH question, the wizard (`wildid-setup`), the Plug-in Manager check with
      the way to add the plugin by hand; from the first Identify run on it points to the
      Windows guide, whose steps are the same. Updating, uninstalling and its own "If
      something goes wrong".
- [x] `hardware.html`: the figures measured on the Mac (speed, memory per model, the rule for
      "keep both models loaded": offered from 30 GB reported as usable), given as what the one
      tested Mac did. `models.html`: the Mac's rows in the comparison table and the 30 GB
      sentence next to the 20 GB one.
- [x] Structured data, page descriptions, the hero line and the navigation of every page name
      macOS.
- [x] `command-line.html`: where the `wildid` command is after the macOS installation, and
      what the header line says on a Mac. `privacy.html` and `lightroom.html` name no path in
      a Windows form.

Still needed before a visitor can rely on it:

- [ ] **A release with the Mac download.** The macOS buttons point to
      `https://github.com/Trogious/wildid/releases/latest`, like the Windows ones. The
      repository has no release yet, so nothing carries `WildID-<version>-macos-arm64.zip`.
- [ ] **The Lightroom steps on a Mac.** They were written from the code and from the Windows
      run. Nobody has seen them on a Mac yet (`docs/acceptance-macos.md`, section B): the
      plugin loading by itself from the `Modules` folder, the Identify dialog's memory line
      ("Apple M5 Pro, unified memory: 40.2 GB usable"), the engine starting from the plugin.
      Correct the guide in `index.html` if one of them turns out differently.
- [ ] **The exact detector resize.** `hardware.html` and `command-line.html` say the option
      is "meant to" give the same pixels on every computer. Backlog item 13 in
      `species-id-mvp-plan.md` measures that on the Mac and the Linux box: afterwards say
      what was found.
- [ ] Optional: screenshots of the Mac installation, `mac-terminal-install.png` (the installer
      running in Terminal) and `mac-wizard-done.png` (the wizard at "Setup complete"). The
      guide has no pictures of its own so far; add the two `<figure>` blocks with them.

How the macOS requirements are worded (owner, 2026-11-15; ADR 0008 decision 8): they state
only what was measured. The site names the one Mac (a MacBook Pro with an M5 Pro and 48 GB of
memory), gives the figures measured on it and says that no other Mac has been tried. It states
no minimum memory and gives no advice for smaller Macs: the notes on smaller NVIDIA cards
("should be comfortable", "is tight") get no macOS twin. `README.md` and the zip's
`README-macOS.md` follow the same rule.

## Check while taking the screenshots

Three details in the Windows guide were written from the code, not from the screens. If one
of them is wrong, the text in `website/index.html` needs correcting.

- [ ] The installer's pages come in the order the guide describes: Install, the black
      download window, then a last page with "Run the WildID setup wizard now".
- [ ] The WildID fields appear in Lightroom's Metadata panel under "All Plug-in Metadata".
- [ ] Hugging Face labels the steps as the guide says: Settings, Access Tokens, "Create new
      token", token type "Read".
