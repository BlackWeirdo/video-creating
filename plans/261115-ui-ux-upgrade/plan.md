# UI/UX upgrade (Jinja2 + plain CSS + plain JS)

Date: 2026-11-15. Scope: presentation layer only (`src/videocreator/web/`). No backend/API change,
no new library, no build step, works offline.

## Findings that shape the work

- All 20 templates are server-rendered; every action is a plain `<form method="post">` followed by
  a redirect with `?msg=` / `?err=` / `?saved=`. There is **no `fetch` call** in the app.
- A failing POST (HTTP 4xx/5xx) currently replaces the page with raw JSON (`{"detail": ...}`).
- Templates use classes that `style.css` never defined (`.grid-3`, `.alert-error`, `.alert-info`,
  `.checkbox-label`, `.status-*`, `.error-cell`, `.page-header`).

## Phases (one commit each)

| # | Phase | Approach | Status |
|---|-------|----------|--------|
| 1 | Design system | Semantic tokens in `:root`; `.btn/.input/.select/.textarea/.card/.badge/.table`; no raw colour outside the token blocks; classes applied to templates by script | done |
| 2 | Dark mode | `[data-theme="dark"]` token block; inline head script (localStorage, then OS); header toggle; 200 ms transition only while switching | done |
| 3 | Toasts | `static/toast.js` (`window.toast`), `static/forms.js` (`apiFetch`); POST forms are sent through `apiFetch`: redirect → follow it, flash message shown as toast; error → toast with FastAPI `detail`, page stays | done |
| 4 | Skeletons | `.skeleton` + shimmer; shown in `<main>` while the next list page is really loading (after 200 ms), never an artificial delay; `.empty-state` | done |
| 5 | Micro-interactions | hover/active transitions; staggered entrance via `--i` set by `:nth-child(-n+12)`; all inside `prefers-reduced-motion: no-preference` | done |
| 6 | Layout | Sidebar (4 groups, inline SVG icons, `aria-current`), thin header, only `<main>` scrolls, drawer below 900 px | done |
| 7 | Accessibility | Labels for every control, skip link, focus-visible ring, drawer focus handling, contrast table | done |

## Verification per phase

- `.venv/Scripts/python.exe -m pytest -m local` (`uv` and `ruff` are not installed on this machine).
- Real app served from a copy of the real database (role `client`, no worker) on port 8791;
  Edge headless screenshots, light/dark, 1366 px and 800 px.
- Contrast ratios computed from the tokens in `style.css`.

## Risks

- Five templates carried earlier uncommitted edits; each commit stages them without those edits
  where the two can be separated.
- `POST /settings/export` returns a file download and must stay a native form submit.
