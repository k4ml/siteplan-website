# Siteplan website

Marketing site for the Siteplan concept, design and vision. Built with the Jekyll-style
static site generator at `ssg.py`.

## Build

```bash
cd ../siteplan-website
uv run ssg.py . _site
```

Requires `uv`; dependencies are declared inline in `ssg.py`.

## Validate

The build must pass a check before it is published. It verifies that every expected page
exists, that every internal link and anchor resolves, that all referenced assets are
present, that ids are unique and tags are balanced, and that no placeholder domain
leaked into the output.

```bash
python3 scripts/check_site.py _site
```

## Continuous integration

`.github/workflows/build.yml` runs on every push and pull request to `main`. It builds
the site with `uv`, runs the checker, and uploads `_site` as a workflow artifact
(`site`, kept 14 days). The workflow fails if the build or any check fails.

## Deploy

On a push to `main`, the `deploy` job downloads the artifact that CI built and validated,
then publishes it with Wrangler to the `siteplan-website` Worker as static assets. The
custom domain `siteplan.koditi.my` is declared in `wrangler.jsonc`.

The deploy is skipped, and the run still succeeds, when `CLOUDFLARE_API_TOKEN` is not
set. Pull requests never deploy.

### Required repository secrets

| Secret | Purpose |
| :--- | :--- |
| `CLOUDFLARE_API_TOKEN` | Token with **Workers Scripts: Edit** and **Zone: Edit** (plus **DNS: Edit** so the custom domain can be created) for the `koditi.my` zone. |
| `CLOUDFLARE_ACCOUNT_ID` | The Cloudflare account id that owns the Worker. |

Set them under *Settings → Secrets and variables → Actions*. The first successful run
creates the Worker and attaches the domain; no manual DNS record is needed, because
`custom_domain: true` lets Cloudflare manage it.

To deploy from a workstation instead, build and then run Wrangler yourself:

```bash
uv run ssg.py . _site
npx wrangler deploy
```

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
| `assets/js/site.js` | Mobile navigation. |
| `scripts/check_site.py` | Post-build validation used by CI. |
| `.github/workflows/build.yml` | Build, validate, upload and deploy the site. |
| `wrangler.jsonc` | Cloudflare Worker config: assets directory and custom domain. |

Pages are root HTML with YAML front matter. `nav:` drives the active state in the header.

## Design language

Inspired by Red Hat / OpenShift marketing: flat white surfaces, sharp corners and no rounded
cards, one strong red (`#ee0000`) for emphasis and accents, hairline rules instead of shadows,
oversized display type, and technical diagrams drawn as line art with monospace labels.
