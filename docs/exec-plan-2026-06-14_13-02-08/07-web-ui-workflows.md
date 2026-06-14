# 07-web-ui-workflows

## Goal
Implement the lightweight vanilla web UI for submitting jobs, managing voice presets, polling progress, and browsing history.

## Depends on
- `06-api-integration-boundaries`

## Do
1. Add `templates/index.html`, `static/app.js`, and `static/styles.css` matching the planned single-page layout.
2. Update `web.py`/`main.py` to serve templates and static assets.
3. Implement config loading, voice preset dropdown/upload/delete, job submit via JSON/form, progress polling, event rendering, artifact links, cancellation, and history loading.
4. Keep advanced settings collapsed by default and support responsive single-column layout on mobile.

## Verify
Run immediately after this step:
1. `uv run python -m compileall src`.
2. FastAPI TestClient smoke for `/` and static assets.
3. Lightweight HTML/JS observable checks for expected form IDs, API endpoints, and artifact link rendering code.

## Notes
- Added `templates/index.html` with planned single-page two-column layout, voice controls, text/parameter form, progress/events/artifacts, and history table.
- Added `static/app.js` with config loading, voice preset list/delete/save, JSON and multipart job submit, polling, cancel, artifact links, and history loading.
- Added `static/styles.css` with desktop two-column layout, status badges, progress/events/history styling, advanced settings support, and mobile responsive layout.
- Updated `web.py` to serve the template and `main.py` to mount `/static`.
- Verification `uv run python -m compileall src` passed.
- Verification FastAPI TestClient smoke passed for `/`, `/static/app.js`, `/static/styles.css`, expected form IDs, API endpoint references, artifact link rendering references, and responsive CSS marker.
