# Flet UI design system

This foundation implements the shared visual language from reference theme 25, “Aurelian Clear 3.” Existing pages continue to use their current controls until the shell and page update work is scheduled.

## Tokens

`etf_cockpit.app.theme` preserves its existing public names and supplies theme-25 values. The palette uses dark navy (`#0b1424`), translucent navy surfaces, pale foreground text, and muted semantic colours: positive `#6fcfa6`, negative `#e8897c`, amber `#e6c27a`, and violet `#a99bf0`. The selected quail state uses the three stops `#47806b`, `#2a5645`, and `#21463a`; its `#f0c2ae` ink is reserved for selected controls.

The named tokens also include glass panel and recessed well treatments, raised controls, hairline borders, 30 px card and 22 px inner radii, a text shadow, the footer rail surface, and the cylinder bar palette. They are plain values for reusable Flet components; they do not change page layout or page behavior.

## Component kit

Import from `etf_cockpit.app.components.kit` or `etf_cockpit.app.components`:

- `glass_panel` and `card` build the shared glass surface and the title/note/insight/recessed-well anatomy.
- `kpi_tile`, `status_tag`, and `score_bar` render concise metrics and explicit status labels.
- `pill_group`, `toggle`, and `cta_button` provide keyed controls with tooltips and change/click callbacks.
- `table_style` places an existing table in a recessed plate.
- `cylinder_bar` draws horizontal three-stop bars with an axis title, endpoint labels, and units.
- `backdrop` uses `<DATA_DIR>/ui/backdrop.jpg` when present; otherwise it uses a deterministic navy-to-teal gradient. `DATA_DIR` is resolved by the existing `etf_cockpit.core.paths` module. Tests may pass a temporary `user_data_dir` without adding a setting.

Every factory accepts a stable `key`; the returned control has a tooltip that names its content or action. Status tags always display their text in addition to colour. Interactive factories accept callbacks so a page can own state and action behavior.

## Flet rendering notes

Flet 0.85.3 `Container.blur` blurs content behind the container. The local backdrop image is softened by a transparent blur layer above the image, while the gradient fallback needs no blur. Glass and selected controls use Flet linear gradients and rounded borders.

Flet `BoxShadow` has no inset mode. Recessed wells therefore use a darker gradient, an inner hairline border, and a restrained outer shadow. Raised/selected controls use a top border highlight and an offset outer shadow to approximate the CSS inset highlight and hard lower edge. No dependency, image, or font asset is added.

## Headless route renderer

From the repository root, render every route in `router.PAGES` with the default 1920×1200 viewport and a 15 second post-title settle period:

```powershell
python scripts/render_ui_pages.py
```

Select routes, output directory, viewport, settle time, browser executable, and per-route title timeout with `--routes`, `--out`, `--width`, `--height`, `--settle-ms`, `--browser`, and `--timeout-s`. For example:

```powershell
python scripts/render_ui_pages.py --routes / /portfolio --out artifacts/ui-render-check
```

The renderer starts the real app in web mode with browser auto-open disabled, launches a headless Chromium-family browser with a temporary profile and loopback-only DevTools port, and drives navigation, title checks, console capture, and PNG screenshots over the DevTools websocket. It writes one `<route-slug>.png` per route and `index.json` with each route, PNG name, success flag, error, and console errors. Failed routes remain in the index with `ok: false`. Missing browser or `websockets` exits with code 2.
