# AGENTS.md

Working notes for anyone — human or agent — changing this repository.

## What this is

A single-file CLI that downloads every image of a [picdrop](https://www.picdrop.com)
gallery into `./output`.

```bash
python3 picdrop.py <gallery-url> [password]
```

Design rules, in priority order:

1. **One command.** URL and optional password are the only things a user should
   have to supply. No config files, no per-gallery editing, no extra steps.
2. **Standard library by default.** Selenium is a fallback, not a requirement.
   Do not add dependencies for anything the stdlib can do.
3. **Resumable and idempotent.** Re-running must be safe: existing files are
   skipped, partial downloads go to `*.part` and are renamed only when complete.
4. **Single file.** `picdrop.py` stays self-contained and readable top to bottom.

## Layout

```
picdrop.py            the whole tool
requirements.txt      selenium (fallback route only)
output/               downloads land here — gitignored
AGENTS.md             this file
CLAUDE.md             pointer to this file
```

`picdrop.py` reads in four sections, in this order:

| section | what it does |
| --- | --- |
| helpers | URL → `(base, gallery id, password)`, thumbnail picking, dedup |
| route 1: http | stdlib `urllib` + cookie jar: login, then read the API |
| route 2: selenium | headless Chrome through the real password form, API read via in-page `fetch` |
| download | thread pool, retries, `*.part` staging, summary |

`main()` tries route 1, falls back to route 2 if it yields nothing, then downloads.

## How picdrop works

A gallery URL is `https://www.picdrop.com/<user>/<slug>`. Internally the ID is
`<user>:<slug>` — that colon form is what every API path wants.

| endpoint | purpose |
| --- | --- |
| `POST /api/galleries/<id>/login` | body `{"password": "..."}`; sets the session cookie |
| `GET /api/content/<id>` | `{key, name, numFiles}` |
| `GET /api/content/<id>/files?limit=500` | `{files, hasMore, lastSortKey}` |
| `GET /api/content/<id>/files/<key>` | one file record |
| `GET /api/navigation/<id>?depth=5` | sub-collections, `{nodes: [...]}` |

Auth is a plain session cookie. `?password=` in the URL is only read by the
frontend to prefill the form — the API ignores it, so a request without the
cookie gets a 404 with a "Forbidden" body. Note that picdrop returns **404 for
authorization failures**, so do not treat 404 as "wrong path".

Each file record carries a `thumbnails` array, largest first — typically
2048, 1600, 1200, 800, 600, 400, 200 px wide. Those URLs point at
`public.picdrop.com` and are **signed and time-limited** (the `?t=` token
embeds an expiry a few days out). They need no cookie, so downloading happens
over plain HTTP regardless of which route found them. Fetch them fresh each
run rather than caching them anywhere.

The record's `size` is the size of the file **as stored by picdrop**, not the
size of the largest thumbnail. A 2048 px preview of a 1.1 MB source is
typically ~220 KB — same pixel dimensions, heavier JPEG compression. That is
expected, not a bug, and the tool deliberately does not warn about it.

Selection galleries (client picks favourites) usually have downloads disabled
and expose no originals endpoint at all, so the largest thumbnail is the
ceiling. Galleries with downloads enabled do expose one — if you add support
for it, keep the thumbnail as the fallback.

## Pagination and nesting

`api_files()` follows `hasMore` using `lastSortKey` as `startSortKey`. The
parameter name is inferred, not documented — hence the guard that breaks when a
cursor repeats. If a gallery ever silently returns only the first 500 files,
that guard is the first place to look.

`api_subgalleries()` walks the navigation tree and picks up any string that
looks like a gallery id (contains `:`). It is best-effort: failures are
swallowed, and files are deduplicated by their `key`.

## Conventions

- Python 3.9+, no formatter enforced; match the surrounding style (4 spaces,
  ~95 column soft limit, `snake_case`, type hints on new functions).
- User-facing output goes through `log()` so ordering stays sane under threads.
- Errors the user can act on → `sys.exit("message")`. Errors that are merely a
  route failing → catch, print one line, fall through to the next route.
- Never print or log the password. Never commit a gallery URL with a live
  password in it.

## Testing

There is no test suite. Before shipping a change, at minimum:

```bash
python3 -m py_compile picdrop.py
python3 picdrop.py --help
```

The pure functions — `parse_gallery`, `safe_name`, `normalise`, `api_files` —
are importable and side-effect free; exercise them with a fake `get_json` (a
repeated cursor is the case worth checking). Anything touching the network
needs a real gallery.

## Gotchas

- Downloading someone's gallery is a matter between you and the photographer.
  This tool only automates what the browser already does with a valid link.
- Some corporate networks proxy-block `picdrop.com` and `public.picdrop.com`
  outright; a blanket `curl` failure there is a network policy, not a bug.
- Selenium needs Google Chrome installed. Selenium 4.6+ fetches the matching
  driver itself, so do not add webdriver-manager.
- `--headful` shows the browser; it is the fastest way to see why a login step
  broke.
