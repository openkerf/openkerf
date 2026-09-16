# Desktop review — 2026-09-16

Baseline: `385c7b2`. Implementation branch: `codex/desktop-uiux`.

The UI engineer implemented each finding; an independent senior UI/UX reviewer opened actual browser screenshots. Each finding had at most three attempts, stopping early on acceptance. Source inspection and automated checks were recorded separately from visual acceptance.

## Findings

| IDs | Change | Attempts used | Review |
| --- | --- | --- | --- |
| V01–02 | Honest offline preparation/execution and quieter warning hierarchy | 1, plus execution-guard review | Accepted in recorded states |
| V03–05, V07 | Desktop header fit, readable controls, stable Box footer, separate machine/server status | 2 | Accepted |
| V06, V08 | Box help/action summary and contextual canvas palette | 1 | Accepted |
| V09–14 | Search-first library, secondary disclosures, readable material names, explicit filter scope, single empty-state action | 1 | Accepted |
| V15–19 | Layer names, on-demand color/help, labelled numeric fields and compact inventory | 2 | Accepted |
| V20–24 | Repeat, arc text, hinge, QR/barcode and polygon guidance | 1 | Accepted |
| V25 | Complete preset operation name | 1 | Accepted |
| V26–29 | Series footer and concise test-grid prerequisites | 1 | Accepted |
| V30 | Both test-grid parameter ranges visible on short desktop | 2 | Accepted with/without material |
| V31 | Localized invalid-preview state, blocked placement and valid-input recovery | 1 | Accepted |
| V32–35 | Stable Save-as footer, local stencil feedback, concise help and correct text-edit title | 1 | Accepted |
| V36–39 | Rotary/setup guidance on demand, accurate controller scope, retained calibration and homing precautions | 1 | Accepted |
| V40–42 | Focus guidance, no unsupported alarm assurance, technical details on demand | 1 | Accepted |
| V43–44 | Relevant image inspector controls and translated effect labels | 1 | Accepted |
| V45 | Generator/layer labels react to live language changes | 1 | Accepted |

Independent code review also caught and resolved stale stencil-preview responses, an omitted offline check in direct test-grid execution, a hidden active series-repeat option, and a shared disclosure-style violation. Existing handbook quotations were updated; the obsolete promise of automatically starting after reconnection was removed.

## Evidence and verification

The local workshop evidence directory is `workshop/screenshots/desktop-overhaul-20260916/`, with a screenshot manifest and before/after profile hashes. It contains 79 captures; two early captures with incorrect dimensions are explicitly excluded from viewport acceptance. The private workshop ledger retains the detailed findings and review decisions.

- Main visual checks: Dutch/light at 1366×768 and 1440×900; English desktop at 1920×1080; dark Job smoke.
- Real interactions: material filtering (3 versus 16 presets), layer/DPI editing, palette discovery, raster scrolling, image-effect keyboard adjustment, modal Escape/focus return, language switching, invalid barcode recovery and disabled offline final Start.
- Simulated states: disconnected, running, paused and alarm. No physical execution was used.
- 258/260 pure/static application checks passed; two Python-parity checks skipped because their hardcoded interpreter path was absent. Eleven additional shared-style checks passed.
- One Node scratch-origin guard test and two Python scratch-isolation tests passed. Existing dependency/resource warnings were emitted by the Python checks.
- Production build passed; Svelte check reported zero errors and warnings.
- Sampled light-theme token contrast: secondary text/field 5.25:1, primary action 5.82:1, warning/white 6.30:1, alarm 5.60:1. This is not a complete contrast audit.
- The real Mac kernel configuration, operation defaults and library database had identical SHA-256 hashes before and after fixture testing.

## Coverage limits

Acceptance is for the recorded desktop scenarios, not exhaustive certification of every branch. Camera/photo acquisition, real rotary calibration and physical controller behavior require equipment validation. Full dark-theme/dialog coverage, comprehensive assistive-technology checks, mobile/tablet refinement and unreviewed advanced workflow variants remain outside this evidence set.

Carry forward the earlier Ruida checks: physical interruption/recovery and upload without starting. A simulated UI state does not validate transport or machinery.

## Repeat the workflow

Use the isolated server and origin guard in [README.md](README.md). Capture a representative baseline, give every observed issue an ID, and record each engineer attempt with a fresh screenshot and independent reviewer decision. An issue still failing after attempt three remains open; never relabel a skipped or unavailable state as a pass. Review failures locally first, then run the relevant pure tests and production build before integration.
