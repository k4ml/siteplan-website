# Siteplan website

Marketing site for the Siteplan concept, design and vision. Built with the Jekyll-style
static site generator at `ssg.py`.

## Build

```bash
cd ../siteplan-website
uv run ssg.py . _site
```

Requires `uv`; dependencies are declared inline in `ssg.py`.

## Preview

```bash
python3 -m http.server 8080 --directory _site
```

## Structure

| Path | Purpose |
| :--- | :--- |
| `_config.yml` | Site name, description, URL and language. |
| `_layouts/default.html` | The document shell: meta, fonts, header, footer, script. |
| `_includes/header.html` | Sticky header with primary navigation. |
| `_includes/footer.html` | Footer navigation and attribution. |
| `index.html` | Home: proposition, the problem, the workspace, the loop. |
| `concept.html` | Domain model: organization, team, room, topic, product layer, authority. |
| `architecture.html` | ASGI process, append path, projections, runtime and placement. |
| `design.html` | G-SDUI protocol, data binding, dynamic apps, reference scenario. |
| `vision.html` | Direction, principles and maturity. |
| `assets/css/site.css` | The design system. |
| `assets/js/site.js` | Mobile navigation and scroll reveal. |

Pages are root HTML with YAML front matter. `nav:` drives the active state in the header.

## Design language

Inspired by Red Hat / OpenShift marketing: flat white surfaces, sharp corners and no rounded
cards, one strong red (`#ee0000`) for emphasis and accents, hairline rules instead of shadows,
oversized display type, and technical diagrams drawn as line art with monospace labels.
