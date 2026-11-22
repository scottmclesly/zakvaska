# zakvaska v1 plan

Work phase by phase. Each phase ends with its acceptance checks passing, tests green, and a commit.

## Data model (v1)

| Table | Key fields |
|---|---|
| `jar` | name, origin (homemade / purchased), culture_name, flour_type, state (active / fridge / dormant / dried), feed_interval_room_h (default 12), feed_interval_fridge_h (default 168), parent_jar_id (lineage), is_control (bool), notes, archived, created_at |
| `jar_state_change` | jar_id, from_state, to_state, changed_at, note |
| `feeding` | jar_id, fed_at, starter_g, flour_g, flour_type, water_g, water_temp_c, ambient_temp_c, notes → derived ratio (e.g. 1:2:2) and hydration % |
| `observation` | jar_id, observed_at, height_mm, start_height_mm, rise_pct (derived), bubbles, smell, texture, notes. Captured now; charted in v2. |
| `recipe` | name, category (rye / wheat / enriched / other), archived |
| `recipe_version` | recipe_id, version (int), notes, created_at |
| `recipe_ingredient` | version_id, name, role (flour / water / levain / salt / sweetener / fat / other), baker_pct, notes |
| `recipe_stage` | version_id, seq, name (e.g. scald/zavarka, sponge, final dough, proof, bake), duration_min, temp_c, notes |
| `equipment_program` | name (e.g. West Bend "Basic", "Whole Wheat"), device, total_min, notes. User-entered from the manual. |
| `bake` | recipe_version_id, jar_id (nullable), started_at, finished_at, method (oven / dutch oven / bread maker), equipment_program_id, crust_setting, loaf_size, oven_temp_c, bake_min, total_flour_g, status (planned / in progress / done / failed) |
| `bake_stage_log` | bake_id, stage name, planned_start, actual_start, actual_end, notes |
| `bake_result` | bake_id, rating (1–5), crust, crumb, taste, rise, next_time |
| `photo` | owner_type (jar / feeding / observation / bake), owner_id, path, thumb_path, taken_at, caption |
| `alert` | jar_id, kind (feed_due), due_at, fired_at, acknowledged_at, snoozed_until |
| `setting` | key, value (display temp unit, etc.) |

## Phase 0: scaffold and environment
- [x] Repo layout: `app/` (main.py, config.py, db.py, models/, routes/, services/, templates/, static/), `migrations/`, `tests/`, `scripts/`, `docs/`
- [x] `requirements.txt` with pinned versions; `.env.example`; `.gitignore` (.venv, data/, .env, __pycache__)
- [x] `scripts/setup.sh` (check Python ≥3.12, create .venv, install, `alembic upgrade head`) and `scripts/run.sh`
- [x] Base layout template, HTMX vendored, mobile-first CSS, PWA manifest and icon
- [x] `/health` endpoint
- **Accept:** fresh clone → `setup.sh` → `run.sh` → home page loads at 127.0.0.1:8420 on desktop and phone width; `pytest` passes.

## Phase 1: jars, feedings, observations
- [x] Jar CRUD (archive, not delete), state changes logged, parent/child lineage, control flag
- [x] Quick "Fed it" form: defaults pre-filled from that jar's last feeding, one tap to log
- [x] Derived ratio and hydration display
- [x] Observation form (height before/after → rise %)
- [x] Jar detail page: timeline of feedings, observations and state changes, newest first
- [x] Dashboard: one card per active jar with state, time since last feed, next due, overdue highlight
- **Accept:** create both jars (homemade + Soviet control), log feedings and observations, see them on the timeline; derived values are correct (unit-tested).

## Phase 2: alerts
- [x] Next-due computed from last feeding + interval for the current state (dormant/dried: no alerts)
- [x] APScheduler job every minute creates or fires `alert` rows; state recomputed from DB on startup (no lost alerts after restart)
- [x] In-app banner/badge plus browser Notification API while a tab is open (permission requested on user action)
- [x] Acknowledge and snooze (30 min / 2 h / custom); logging a feeding auto-acknowledges
- **Accept:** with a 1-minute test interval, an alert fires, shows in-app and as a browser notification, snooze delays it, and a feeding clears it; restart mid-countdown still fires.

## Phase 3: recipes
- [x] Recipe CRUD with ingredients in baker's % and ordered stages
- [x] Edit → new version; previous versions viewable read-only; diff between versions (ingredient and stage changes)
- [x] Scale-to view: enter total flour or target dough weight → grams per ingredient
- [x] Equipment programs CRUD (enter West Bend programs from the manual)
- **Accept:** create a Borodinsky recipe with scald/sponge/final/proof/bake stages, edit it to v2, scale to 500 g flour with correct grams (unit-tested).

## Phase 4: bakes and results
- [x] Start a bake from a recipe version: pick jar, method, equipment program, flour total; stages copied into `bake_stage_log` as the plan
- [x] Log actual stage start/end times on the fly (big buttons, phone-friendly)
- [x] Results form: rating, crust, crumb, taste, rise, next-time notes
- [x] Bake list filterable by recipe, jar and rating; recipe page shows its bakes
- **Accept:** run a full bake end-to-end on a phone-width screen; it appears on the recipe, the jar and the bake list.

## Phase 5: photos
- [x] Upload from phone camera (`accept="image/*" capture`), attach to jar, feeding, observation or bake
- [x] Thumbnails via Pillow; respect EXIF orientation; store under `data/photos/YYYY/MM/`
- [x] Gallery on each detail page; side-by-side compare of two bake crumb photos
- **Accept:** photo shot on phone uploads, displays correctly rotated, and survives restart.

## Phase 6: backup and polish
- [x] Export all data to JSON plus CSV per table; zip with photos
- [x] `scripts/backup.sh` (SQLite online backup + photos tarball)
- [x] README: setup, run, LAN access (`ZAKVASKA_HOST=0.0.0.0`), backup
- **Accept:** export → wipe data dir → import (or restore backup) brings everything back.

## After v1
- [x] Renamed jar-log → zakvaska (old env keys and database name still adopted)
- [x] Weight display cycles grams → US cups/spoons → oz/lb, with per-ingredient densities
- [x] Bread maker 2 / 2.5 / 3 lb loaf buttons on the start-a-bake form
- [x] Drawn jars that fill to the measured rise, and ingredient role glyphs
- [x] A shelf for the jars, archived ones on a dustier shelf below
- [x] Drawn loaves per recipe category and the bread maker on the equipment page
- [x] Rise-curve charts, homemade and control overlaid on the dashboard
      (pulled forward out of the v2 backlog, 2026-11-02)
- [x] Programs and recipe stages drawn to scale as bars of elapsed time
- [x] Weight *entry* in the unit on display, not only reading: every weight
      field takes "250 g", "8 oz", "1 lb 2 oz" or "1 ½ cups", and a recipe
      can be typed as the amounts it is written in — the baker's percentages
      are worked out from them and the batch is kept on the version, so it
      reads back in cups (2026-11-08)

## v2 backlog (do not build in v1)
- Back-scheduling from a target "bread out" time through recipe stages
- `POST /api/readings` sensor ingest (ESP32: temp/humidity + ToF height)
- ntfy push to phone
- Raspberry Pi deploy (systemd unit, data dir on persistent storage)
