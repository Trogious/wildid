# 0007 — Free app, open source under AGPL-3.0, public GitHub repository

**Status:** accepted 2026-11-04. The repository is public since 2026-11-15 (owner).
**Context:** The app has been free since 2026-10-24 (plan L13) and private-first (L14). Going
public raised closed vs open source. The detector crop and the second opinion import
`ultralytics`, which is AGPL-3.0: a closed-source release would need either an Ultralytics
Enterprise licence or a re-implementation of the YOLO inference without `ultralytics` (ONNX
export plus `onnxruntime`), and closed source also forfeits the free code-signing routes
(SignPath Foundation, Certum's open-source certificate) **[L]**. Open source removes all of
that. The one cost weighed: a public GitHub repository cannot be unlisted — not promoting it
keeps it low-profile, nothing keeps it private.

## Decision

1. **Free, open source.** The whole repository — engine, `wildid serve`, the Lightroom plugin,
   installer scripts, documentation — is licensed under the GNU Affero General Public License,
   version 3 or later (`LICENSE`, verbatim GNU text; SPDX `AGPL-3.0-or-later`). One licence for
   everything keeps the combination with `ultralytics` compliant by construction and puts the
   plugin under the same terms as the engine it ships with.
2. **Public GitHub repository; no promotion required.** Releases are GitHub Releases of that
   same repository, so the installer and its Corresponding Source — the tag together with
   `release.yml` and `installer/set_version.py`, which regenerate the build exactly — sit in
   the same place, which is what AGPL §6(d) asks for. If a download is ever hosted elsewhere,
   that page must carry the repository link.
3. **Notices.** The installer README and the plugin's info text carry the licence notice and
   the repository URL; `pyproject.toml` declares the licence. `THIRD_PARTY_LICENSES` (notices
   for what the installer bundles, uv included) is produced in phase P together with the rest
   of the public-release checklist (signing, channels), which stays parked.
4. **Not decided here:** when to go public (the phase-P tripwire stands: before the installer
   is handed to anyone), signing, channels.
   *2026-11-15 (owner):* the repository is public since this day. Signing and channels are
   still open.

## Consequences

- `LICENSE` added; `pyproject.toml` gains `license = "AGPL-3.0-or-later"`; README gets a
  licence section; `CLAUDE.md` gains the rule that every new dependency must be
  redistributable alongside AGPL code.
- No per-file licence headers (optional under the GNU text); the `LICENSE` file and the README
  notice are the notice.
- AGPL §13 (network use) does not reach the owner: the daemon binds 127.0.0.1 for the same
  person who received the program. Anyone who later hosts `wildid serve` for third parties
  takes on that obligation themselves.
- Model weights and reference data are not covered by this licence and keep their publishers'
  terms (checked against the primary sources on 2026-11-04): BioCLIP 2 / 2.5 weights MIT; the
  TreeOfLife-200M text embeddings CC0-1.0 and **not gated** (the earlier "gated, accept the
  terms" belief was wrong; `prefetch` still downloads them per user because they are 2.7–3.3
  GB); MegaDetector v6 weights CC-BY 4.0 on Zenodo (attribution owed in the notices; the
  PyTorch-Wildlife code is MIT); SpeciesNet code Apache-2.0 (the Kaggle page's licence line
  for the weights still to be read in a browser); GBIF Backbone CC-BY 4.0; iNaturalist API
  under its Terms of Service (100 requests/minute hard limit, 60 asked, 10,000/day). The
  remaining checks stay a phase-P item.
- Signing at phase P can use the open-source routes **[L]**, subject to their eligibility
  rules; macOS notarization still needs the Apple Developer Program.
