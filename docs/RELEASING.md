# Cutting a release

A release is a version tag. Pushing one builds the installers and the Docker
image and publishes them; see `.github/workflows/release.yml`.

## Before the first release, once

1. **Make the repository public** (Settings → General → Danger Zone). The
   install script, the update check and the download links all read from it,
   and none of them work while it is private.
2. After the first tag has run, **make the Docker image public**: on GitHub,
   your profile → Packages → `zakvaska` → Package settings → Change
   visibility → Public. A new package starts private even when its repository
   is not, and `docker compose pull` fails for everyone else until this is
   done. It is needed once.

## Every release

1. Decide the number. Bug fixes: 1.0.1. New things: 1.1.0.
2. Write it in three places. `tests/test_release.py` fails if they disagree:
   - `app/__init__.py`: `__version__`
   - `desktop/src-tauri/Cargo.toml`: `version`, then run
     `cargo check --manifest-path desktop/src-tauri/Cargo.toml` so
     `Cargo.lock` follows
   - `CHANGELOG.md`: a new `## [x.y.z] - YYYY-MM-DD` section at the top.
     This section becomes the release notes, word for word.
3. Run the tests: `.venv/bin/python -m pytest`
4. Commit, and merge to `main`.
5. Optional but wise: on GitHub, Actions → Release → **Run workflow** on
   `main`. It builds everything and publishes nothing; the installers are
   attached to the run to try.
6. Tag and push:

   ```bash
   git checkout main && git pull
   git tag -a v1.0.0 -m "zakvaska 1.0.0"
   git push origin v1.0.0
   ```

7. Watch Actions → Release. About fifteen minutes later there is a GitHub
   Release with three installers and a checksum file, and
   `ghcr.io/scottmclesly/zakvaska` has the tags `1.0.0`, `1.0`, `1` and
   `latest`.

## If it goes wrong

A failed run publishes nothing: the release is only created by the last job,
after everything else has passed. Fix the problem, then move the tag:

```bash
git tag -d v1.0.0 && git push origin :refs/tags/v1.0.0
git tag -a v1.0.0 -m "zakvaska 1.0.0" && git push origin v1.0.0
```

Only do that for a tag whose release never appeared. Once people have
downloaded 1.0.0, a fix is 1.0.1.
