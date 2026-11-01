# Vendored front-end assets

No CDN at runtime and no JS build step (see CLAUDE.md). Third-party files are
committed here and updated by hand.

| File | Library | Version | Source | SHA-384 |
|---|---|---|---|---|
| `htmx.min.js` | htmx | 2.0.11 | `https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js` | `d8e6adcd0cb51fe65dfc822b8ebd5372e0c6a8b5de1e16e8a00c8963529d40c2a7af82d9db6937d4604b7582879958e0` |

Verified byte-identical against `https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js`.

To update:

```bash
V=2.0.12
curl -sSfL -o app/static/js/htmx.min.js "https://unpkg.com/htmx.org@$V/dist/htmx.min.js"
shasum -a 384 app/static/js/htmx.min.js
```

Then update the table above and bump `CACHE` in `app/static/js/sw.js`.
