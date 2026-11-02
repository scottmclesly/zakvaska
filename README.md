# zakvaska

A local, single-user **baking lab notebook**: sourdough starter jars, feedings,
feeding alerts, recipes (versioned, baker's %), bakes and their results, with photos.

Built to compare a homemade whole-rye starter against a purchased Soviet rye
culture (the control) on the way to a decent Borodinsky.

> Renamed from **jar-log**. An existing install needs nothing done to it: the old
> `JARLOG_*` environment keys are still read, and a `jarlog.db` is renamed to
> `zakvaska.db` the first time the app or a migration opens it. The git repository
> and its folder still say `jar-log`; rename those yourself if you want to.

## Requirements

- Python 3.12 or newer
- Nothing else — no Node, no build step, no external services

## Setup

```bash
./scripts/setup.sh    # creates .venv, installs pinned deps, runs migrations
./scripts/run.sh      # http://127.0.0.1:8420
```

`setup.sh` copies `.env.example` to `.env` on first run. Both scripts are safe
to re-run.

## Configuration

Set in `.env` (see `.env.example`):

| Key | Default | Notes |
|---|---|---|
| `ZAKVASKA_DATA_DIR` | `./data` | SQLite database and photos. Gitignored. |
| `ZAKVASKA_HOST` | `127.0.0.1` | Use `0.0.0.0` to reach it from a phone. |
| `ZAKVASKA_PORT` | `8420` | |
| `ZAKVASKA_TZ` | `America/New_York` | Timestamps are stored in UTC, shown in this zone. |

## Using it from your phone

Set `ZAKVASKA_HOST=0.0.0.0` in `.env`, restart, then open
`http://<this-machine's-IP>:8420` on a phone on the same network. It is an
installable PWA — "Add to Home Screen" gives it an icon and a standalone window.

## Units

Weights are stored in grams, always. The chip in the header cycles what you
*read* them as:

| Shown as | Good for |
|---|---|
| `grams` | the rye recipes, and the scale on the counter |
| `cups` | an American recipe written in cups and spoons |
| `oz / lb` | a bread-maker manual, or a scale set to imperial |

Cups and spoons are volume, so they need a density per ingredient — a cup of
rye flour is 103 g and a cup of water is 237 g. Those live in
`app/services/measures.py`, keyed by ingredient name with a fallback per role.
They are approximate on purpose: how hard you pack a cup of flour moves it by
a fifth, which is exactly why grams are what gets stored. Totals never show as
cups, because cups of mixed dough would be a made-up number.

The `°F` chip beside it does the same for temperatures.

Typing a weight in is still grams — that is what a kitchen scale reads.

## Feeding alerts

A job runs once a minute and marks a jar's feed as due, based on its last
feeding and the interval for its current state. Dormant and dried jars are
never chased. Alerts show as a banner on every page; you can snooze one
(30 min, 2 h, or any number of minutes) or dismiss it, and **feeding the jar
clears it automatically**.

Alert state lives entirely in the database and is recomputed on startup, so
restarting the app never loses one — anything that came due while it was down
fires immediately on the next start. Set `ZAKVASKA_SCHEDULER=0` to run without
the job.

### Browser notifications only work on this machine

While a tab is open, the page can also raise a desktop notification. The
browser Notification API is restricted to *secure contexts*, and
`http://localhost` counts as one but `http://192.168.x.x` does not — so
notifications work on the machine running the app and **not** on a phone over
the LAN. The in-app banner works everywhere.

Getting phone notifications means either serving over HTTPS or the ntfy push
planned for v2 (`docs/TODO-v1.md`).

## Recipes

Ingredients are stored as **baker's percentages**: total flour is 100%, and
everything else is a percentage of the flour weight. The scale-to box on a
recipe page turns those into grams — give it either a total flour weight or
a target dough weight and it works the other out.

Levain is kept as its own line rather than being broken back into the flour
and water inside it, so the grams match what you actually weigh. That does
mean the hydration figure shown is the dough's *added* water, not its true
total.

Editing a recipe never changes it in place: every save writes a new version,
and old versions stay readable so a bake recorded against v1 still describes
what was made. The compare page shows what changed between any two versions,
matching lines by name rather than by position.

Equipment programs are the bread maker's programs, typed in from its manual,
so a bake can record which one was used.

## Bakes

A bake starts from a recipe *version*, never from the recipe, and the
version's stages are copied into it as a plan. Editing the recipe afterwards
leaves every bake alone — last month's loaf still means what it meant.

The bake page is a running sheet: tap a stage started, tap it done, and it
records the real times beside the planned ones with the difference. Notes go
in per stage. If the flour total is set, the page also shows the grams to
weigh out for that loaf.

The result is a rating out of five plus crust, crumb, taste, rise and — the
part that matters — what to change next time. Saving one marks the bake done.

A bread maker is sold by the pound its pan takes, so the start form has hot
buttons for the 2, 2.5 and 3 lb settings. Each one works backwards through the
recipe's percentages to the flour that fills that pan, and fills in the loaf
size too. The rating is the *dough* the pan holds; the baked loaf comes out
about a tenth lighter.

The bake list filters by recipe, jar, rating and status, and each bake also
shows up on the recipe version it came from and on the jar that raised it.

## Photos

A photo can hang off a jar, a feeding, an observation or a bake. The feeding
and observation forms take one as you log, so a jar gets photographed at the
moment it is worth photographing; everything else uploads from the gallery on
the detail page. On a phone the file field opens the camera directly.

Every upload is re-encoded to JPEG on the way in, which does three things at
once: the EXIF rotation is applied to the pixels, so the photo is the right
way up in any browser; the rest of the EXIF block, GPS included, is dropped;
and a 12-megapixel phone photo stops being a 12-megapixel file. Files land in
`data/photos/YYYY/MM/` by the date the photo was *taken*, not uploaded, with a
480 px thumbnail beside each one.

`/photos/compare` puts two bake photos side by side with their ratings and
their "next time" notes, which is the only honest way to see a change in
crumb.

Photos are the one thing here that really deletes — a blurry shot of a jar lid
is not lab-notebook history, and a misfired upload needs an undo. Jars,
recipes and bakes are still archived, never deleted.

## Backup

Two ways out, for two different jobs.

**The export**, from the Backup page in the footer, is one zip holding every
table as JSON, the same rows again as CSV, and the photo files. The JSON is
what restores; the CSV is for whoever opens this in ten years without the app.
The same page reads an export back, which replaces everything currently in the
notebook — rows and photos alike. An export only restores into the schema it
came from, so run the migrations that match it first; it says so if they do not
agree.

**The script** takes a straight snapshot instead, and is the one to put on a
timer:

```bash
./scripts/backup.sh                 # into ./backups
./scripts/backup.sh /Volumes/stick  # somewhere else
./scripts/backup.sh --keep 14       # and prune to the newest 14
```

It copies the database through SQLite's online-backup API, so it is safe to run
while zakvaska is serving, and tars it up with the photos. To put one back, stop
zakvaska and untar it over the data directory:

```bash
tar -xzf backups/zakvaska-backup-20261101-1930.tar.gz -C data
```

Everything worth keeping is in `ZAKVASKA_DATA_DIR` (`./data` by default): back up
that directory and you have backed up the notebook.

## Development

```bash
.venv/bin/python -m pytest              # tests
.venv/bin/alembic upgrade head          # apply migrations
.venv/bin/alembic revision --autogenerate -m "what changed"
./scripts/run.sh --reload               # needs: .venv/bin/pip install watchfiles
```

`GET /health` reports database connectivity and data-dir writability.

Conventions and the stack decision live in [CLAUDE.md](CLAUDE.md); the build
plan is in [docs/TODO-v1.md](docs/TODO-v1.md).
