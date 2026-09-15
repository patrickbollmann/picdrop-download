#!/usr/bin/env python3
"""picdrop gallery downloader.

    python3 picdrop.py <gallery-url> [password]

Downloads every image of a picdrop gallery, at the largest size picdrop
serves, into ./output (created if missing).

The password is optional: if the gallery URL already carries ?password=...,
that value is used.

How it works
------------
picdrop galleries are a Vue app talking to a JSON API. A password-protected
gallery needs a session cookie, which is handed out when the password form is
submitted. This script tries two ways to get that far, in order:

  1. plain HTTP -- POST the password to /api/galleries/<id>/login, then read
     /api/content/<id>/files. Fast, no browser.
  2. Selenium -- drive a headless Chrome through the real password form and
     read the same API from inside the page. Slower, but survives changes to
     the login endpoint, bot checks and JS-side tokens.

Whichever succeeds yields a list of files with pre-signed CDN URLs. Those are
public, so the actual downloading is done with plain HTTP either way.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
RETRIES = 3
TIMEOUT = 60


# ----------------------------------------------------------------- helpers ---

def log(msg: str = "") -> None:
    print(msg, flush=True)


def parse_gallery(url: str) -> tuple[str, str, str | None]:
    """-> (base url, gallery id 'user:slug', password from the query string)."""
    if "://" not in url:
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    parts = [seg for seg in p.path.strip("/").split("/") if seg]
    if len(parts) < 2:
        sys.exit("Cannot read a gallery id from %s\n"
                 "Expected something like https://www.picdrop.com/<user>/<gallery>" % url)
    base = "%s://%s" % (p.scheme, p.netloc)
    password = urllib.parse.parse_qs(p.query).get("password", [None])[0]
    return base, "%s:%s" % (parts[0], parts[1]), password


def best_thumbnail(rec: dict) -> str | None:
    thumbs = rec.get("thumbnails") or []
    if not thumbs:
        return None
    return max(thumbs, key=lambda t: t.get("width") or 0).get("url")


def normalise(records: list[dict]) -> list[dict]:
    """API records -> [{name, size, url}], deduplicated, order preserved."""
    out, seen = [], set()
    for rec in records:
        key = rec.get("key") or rec.get("id")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        url = best_thumbnail(rec)
        if not url:
            continue
        out.append({"name": rec.get("name") or ("%s.jpg" % key),
                    "size": rec.get("size") or 0,
                    "url": url})
    return out


# ------------------------------------------------------------ route 1: http ---

def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def api_files(get_json, base: str, gid: str) -> list[dict]:
    """Page through /api/content/<gid>/files. `get_json` takes a URL."""
    records, cursor, seen_cursors = [], None, set()
    while True:
        url = "%s/api/content/%s/files?limit=500" % (base, gid)
        if cursor:
            url += "&startSortKey=" + urllib.parse.quote(str(cursor))
        data = get_json(url)
        batch = data.get("files") or []
        records.extend(batch)
        cursor = data.get("lastSortKey")
        if not data.get("hasMore") or not batch or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    return records


def api_subgalleries(get_json, base: str, gid: str) -> list[str]:
    """Gallery ids of any sub-collections, so nested galleries are included."""
    try:
        nav = get_json("%s/api/navigation/%s?depth=5&teaserImage=0" % (base, gid))
    except Exception:
        return []
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for field in ("id", "key", "collectionId", "path"):
                value = node.get(field)
                if isinstance(value, str) and ":" in value and value != gid:
                    found.append(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(nav)
    return list(dict.fromkeys(found))


def collect_via_http(base: str, gid: str, password: str | None) -> list[dict]:
    opener = make_opener()

    def get_json(url: str) -> dict:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "Referer": "%s/" % base})
        with opener.open(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())

    gallery_url = "%s/%s" % (base, gid.replace(":", "/", 1))
    opener.open(urllib.request.Request(gallery_url), timeout=TIMEOUT).read()

    if password:
        req = urllib.request.Request(
            "%s/api/galleries/%s/login" % (base, gid),
            data=json.dumps({"password": password}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Referer": gallery_url, "Origin": base})
        opener.open(req, timeout=TIMEOUT).read()

    records = api_files(get_json, base, gid)
    for sub in api_subgalleries(get_json, base, gid):
        try:
            records.extend(api_files(get_json, base, sub))
        except Exception:
            pass
    return normalise(records)


# -------------------------------------------------------- route 2: selenium ---

FETCH_JS = """
const done = arguments[arguments.length - 1];
const urls = arguments[0];
(async () => {
  const out = [];
  for (const u of urls) {
    try {
      const r = await fetch(u, {credentials: 'include',
                               headers: {'Accept': 'application/json'}});
      out.push(r.ok ? await r.json() : null);
    } catch (e) { out.push(null); }
  }
  done(out);
})();
"""


def _password_form_visible(driver, By, wait_seconds: float) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        fields = [f for f in driver.find_elements(By.CSS_SELECTOR, "input[type=password]")
                  if f.is_displayed()]
        if not fields:
            return False
        time.sleep(0.25)
    return True


def _click_submit_button(driver, By) -> None:
    """The password form is not always a <form>; click whatever submits it."""
    for selector in ("button[type=submit]", "input[type=submit]", "form button"):
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            if element.is_displayed() and element.is_enabled():
                element.click()
                return
    # Last resort: the first visible button that carries a label (skips icon
    # toggles such as the show/hide-password eye).
    for element in driver.find_elements(By.TAG_NAME, "button"):
        if element.is_displayed() and element.is_enabled() and element.text.strip():
            element.click()
            return


def collect_via_selenium(base: str, gid: str, password: str | None,
                         headful: bool = False) -> list[dict]:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        sys.exit("Selenium is needed for this gallery but is not installed.\n"
                 "    pip3 install selenium")

    options = webdriver.ChromeOptions()
    if not headful:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--user-agent=%s" % UA)
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        sys.exit("Could not start Chrome via Selenium: %s\n"
                 "Google Chrome must be installed; Selenium fetches the driver itself." % e)

    try:
        gallery_url = "%s/%s" % (base, gid.replace(":", "/", 1))
        if password:
            gallery_url += "?password=" + urllib.parse.quote(password)
        driver.get(gallery_url)

        # The gallery either renders straight away or shows a password form.
        try:
            field = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type=password]")))
        except Exception:
            field = None

        if field is not None:
            if not password:
                sys.exit("This gallery is password protected -- pass the password:\n"
                         "    python3 picdrop.py <url> <password>")
            from selenium.webdriver.common.keys import Keys
            field.clear()
            field.send_keys(password)
            field.send_keys(Keys.RETURN)          # works whenever it is a real form
            if _password_form_visible(driver, By, 3):
                _click_submit_button(driver, By)  # otherwise find the button ourselves
            try:
                WebDriverWait(driver, 20).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "input[type=password]")))
            except Exception:
                sys.exit("The password form is still there after submitting -- "
                         "is the password correct?\n"
                         "Re-run with --headful to watch what happens.")

        time.sleep(1.5)  # let the app settle and set its cookie
        driver.set_script_timeout(120)

        def get_json_batch(urls: list[str]) -> list[dict | None]:
            return driver.execute_async_script(FETCH_JS, urls)

        def get_json(url: str) -> dict:
            result = get_json_batch([url])[0]
            if result is None:
                raise RuntimeError("request failed: %s" % url)
            return result

        records = api_files(get_json, base, gid)
        for sub in api_subgalleries(get_json, base, gid):
            try:
                records.extend(api_files(get_json, base, sub))
            except Exception:
                pass
        return normalise(records)
    finally:
        driver.quit()


# ---------------------------------------------------------------- download ---

def safe_name(name: str, used: set[str], index: int) -> str:
    name = re.sub(r"[/\\\0]", "_", name or "").strip() or ("image_%04d.jpg" % index)
    stem, ext = os.path.splitext(name)
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = "%s_%d%s" % (stem, n, ext)
        n += 1
    used.add(candidate.lower())
    return candidate


def download_one(item: dict, dest: str) -> tuple[str, int, str | None]:
    """-> (status, bytes, error). status is 'ok', 'skip' or 'fail'."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip", os.path.getsize(dest), None
    tmp = dest + ".part"
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(item["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as fh:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
            os.replace(tmp, dest)
            return "ok", os.path.getsize(dest), None
        except Exception as e:  # noqa: BLE001
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                break  # an expired or invalid link -- retrying will not help
            time.sleep(2 * attempt)
    if os.path.exists(tmp):
        os.remove(tmp)
    return "fail", 0, str(last)


def download_all(items: list[dict], outdir: str, jobs: int) -> int:
    os.makedirs(outdir, exist_ok=True)
    used: set[str] = set()
    for i, item in enumerate(items, 1):
        item["path"] = os.path.join(outdir, safe_name(item["name"], used, i))

    total = len(items)
    counts = {"ok": 0, "skip": 0, "fail": 0}
    failures: list[tuple[str, str]] = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(download_one, it, it["path"]): it for it in items}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            status, size, err = future.result()
            counts[status] += 1
            done += 1
            name = os.path.basename(item["path"])
            if status == "ok":
                log("[%3d/%3d] ok     %7.2f MB  %s" % (done, total, size / 1e6, name))
            elif status == "skip":
                log("[%3d/%3d] exists           %s" % (done, total, name))
            else:
                log("[%3d/%3d] FAILED           %s -- %s" % (done, total, name, err))
                failures.append((name, err or ""))

    log("\nDone. downloaded=%d  already there=%d  failed=%d  ->  %s"
        % (counts["ok"], counts["skip"], counts["fail"], outdir))
    for name, err in failures:
        log("  failed: %s (%s)" % (name, err))
    if any("403" in e or "404" in e for _, e in failures):
        log("\n403/404 means the signed links expired mid-run. Just run the "
            "command again -- finished files are skipped.")
    return 1 if failures else 0


# -------------------------------------------------------------------- main ---

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Download every image of a picdrop gallery into ./output",
        epilog="example: python3 picdrop.py https://www.picdrop.com/someone/AbCdEf hunter2")
    ap.add_argument("url", help="gallery URL")
    ap.add_argument("password", nargs="?", default=None,
                    help="gallery password (optional; also read from ?password= in the URL)")
    ap.add_argument("-o", "--output", default="output", help="output folder (default: ./output)")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="parallel downloads (default: 4)")
    ap.add_argument("--browser", action="store_true",
                    help="skip the plain-HTTP attempt and go straight to Selenium")
    ap.add_argument("--headful", action="store_true",
                    help="show the Selenium browser window (useful for debugging)")
    args = ap.parse_args()

    base, gid, url_password = parse_gallery(args.url)
    password = args.password or url_password
    log("Gallery : %s" % gid)
    log("Password: %s" % ("(none)" if not password else "*" * len(password)))

    items: list[dict] = []
    if not args.browser:
        log("Reading the gallery over plain HTTP ...")
        try:
            items = collect_via_http(base, gid, password)
        except Exception as e:  # noqa: BLE001
            log("  plain HTTP did not work (%s)" % e)

    if not items:
        log("Falling back to a headless browser ...")
        items = collect_via_selenium(base, gid, password, headful=args.headful)

    if not items:
        sys.exit("No images found. Check the URL and the password.")

    size = sum(it["size"] for it in items)
    log("Found %d image(s), %.1f MB total.\n" % (len(items), size / 1e6))

    outdir = os.path.abspath(args.output)
    return download_all(items, outdir, max(1, args.jobs))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\nInterrupted. Re-run the same command to resume.")
        sys.exit(130)
