# WildID website

The project's public website: plain HTML, one stylesheet, no JavaScript, no build step, and
nothing loaded from other servers. The pages are served as they are; the one thing the deploy
workflow changes is the site's own address (see Hosting).

| File | Content |
|---|---|
| `index.html` | Pitch, the three download cards, how it works (with the cards that link to the detail pages), the Windows setup for Lightroom Classic, the macOS setup for Lightroom Classic, the Linux setup |
| `models.html`, `hardware.html`, `accuracy.html`, `places.html`, `lightroom.html`, `privacy.html`, `command-line.html`, `licence.html` | The detail pages, one click from the start page |
| `404.html`, `robots.txt`, `sitemap.xml`, `favicon.svg`, `.nojekyll` | Housekeeping |
| `css/site.css` | The only stylesheet; light and dark theme follow the visitor's system |
| `fonts/` | Newsreader 500 roman and italic (headings, species names), self-hosted; `OFL.txt` is its licence |
| `img/og-image.png` | The 1200 × 630 image shown when a link to the site is shared |
| `img/screenshots/` | Twelve screenshots, placeholders until replaced (below) |
| `README.md`, `TODO_WEBSITE.md` | Notes for whoever maintains the site: this file, and the checklist of what is still missing |

## Look at it

```
python3 -m http.server 8000 -d website      # then open http://localhost:8000
```

Opening `website/index.html` directly in a browser works too.

## Before it goes live

[`TODO_WEBSITE.md`](TODO_WEBSITE.md) is the checklist to tick off; the steps below say how.

1. **The site's address.** Every page, `sitemap.xml` and `robots.txt` carry the placeholder
   `https://WILDID-SITE-URL.invalid` (canonical link, sharing tags, structured data). On
   GitHub Pages nothing needs doing: at every run the deploy workflow puts the address that
   Pages reports in its place, and the files in the repository keep the placeholder on
   purpose. For any other host, replace it yourself with the real address, without a trailing
   slash. From the repository root, in any shell:

   ```
   python -c "import pathlib,sys;[p.write_text(p.read_text(encoding='utf-8').replace('https://WILDID-SITE-URL.invalid',sys.argv[1]),encoding='utf-8',newline='\n') for p in pathlib.Path('website').rglob('*') if p.suffix in('.html','.xml','.txt')]" https://your.address
   ```

   (`uv run python -c …` where `python` is not on the PATH.) Afterwards
   `grep -rn WILDID-SITE-URL website --include=*.html --include=*.xml --include=*.txt` must
   print nothing.
2. **Screenshots.** Overwrite the placeholder PNGs in `img/screenshots/` with real ones under
   the same file names; nothing else needs editing. Any size works, about 16:10 looks best,
   and the width should be at least 1600 pixels for the two Lightroom overviews.

   | File | What to capture |
   |---|---|
   | `lightroom-after-run.png` | The whole Lightroom Classic window in the Library grid after an Identify run: the WildID collection tree opened down to a species (with `_review`) on the left, the Keyword List with the WildID branch on the right. Photos you are happy to publish. |
   | `win-smartscreen.png` | The blue "Windows protected your PC" window after clicking More info, with Run anyway visible |
   | `win-installer.png` | The installer on its Installing page together with the black text window that shows the download progress |
   | `win-installer-finish.png` | The installer's last page with "Run the WildID setup wizard now" ticked |
   | `win-wizard-questions.png` | The setup wizard after its questions: token skipped, model `all`, crop stage yes, one country |
   | `win-wizard-done.png` | The same window at the end: the offline check and "Setup complete" |
   | `lr-plugin-manager.png` | File → Plug-in Manager with WildID selected, "Installed and running" |
   | `lr-menu.png` | Library → Plug-in Extras opened, the five WildID entries |
   | `lr-identify-dialog.png` | The "WildID: identify species" dialog with default settings |
   | `lr-summary.png` | The summary message after a run |
   | `lr-results-panels.png` | Close-up after a run: Collections panel with the WildID tree, Keyword List with the WildID branch, Metadata panel on All Plug-in Metadata |
   | `lr-prefetch-dialog.png` | The "WildID: prefetch place list" dialog with a country typed in |

3. **Links that assume the public repository.** The download buttons point to
   `https://github.com/Trogious/wildid/releases/latest`, "Source code" to the repository and
   "Report a problem" to its issues. The repository is public since 2026-11-15, so the last
   two work; the download buttons work once a release (not a draft) is published. Change them
   in the pages if downloads or support live elsewhere.
4. **Optional.** `img/og-image.png` is a finished typographic card; replace it with a photo-based
   one of the same size if you prefer.

## Hosting

**GitHub Pages** is set up. `.github/workflows/pages.yml` publishes this folder whenever a push
to `main` changes it, and on manual dispatch. The workflow

- copies the folder, leaving out `README.md` and `TODO_WEBSITE.md`, which are notes for
  maintainers;
- puts the site's address, as the Pages settings report it, wherever the placeholder stands;
- deploys the result. The address is `https://trogious.github.io/wildid` unless a custom domain
  is set under Settings → Pages. A custom domain reaches every page with the next run.

The job is skipped in a private repository, because GitHub Pages on the free plan needs a
public one. This repository is public, and "GitHub Actions" is the source under Settings →
Pages, since 2026-11-15: the owner's one-time steps, listed in `TODO_WEBSITE.md`. Without
that source the job fails at its "Pages settings" step and publishes nothing.

Under the default address the site sits in a sub-path, where crawlers do not look for
`robots.txt`. Submit `sitemap.xml` in Google Search Console instead. With a custom domain both
work as usual.

Any other static host works as well: replace the address placeholder as described above and
upload the contents of this folder, without the two Markdown files if they should not be
public.

## Keeping it true

The site repeats facts from the repository. When one changes, change the page in the same
commit (`CLAUDE.md` has the rule):

| On the site | Source |
|---|---|
| Requirements, download sizes, command-line examples | `README.md` |
| Menu names, dialog options, keywords, collections, VRAM figures in the dialog | `lrplugin/README.md`, `lrplugin/wildid.lrplugin/WildidModels.lua` |
| Speed, graphics memory, accuracy tables, test machines | `docs/acceptance.md` |
| Installer steps, wizard questions | `installer/README.md`, `src/wildid/cli.py` (`setup`) |
| Licences and credits | `README.md` (Licence), `docs/decisions/0007-free-open-source-agpl.md` |

The pages are hand-maintained: the header, the footer and the `<head>` block are repeated in
all ten HTML files, so a change there goes into each of them. Update `<lastmod>` in
`sitemap.xml` when a page changes.
