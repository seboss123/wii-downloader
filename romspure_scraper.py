"""
romspure.cc scraper — gets direct download URLs for Wii hacks/mods.

Flow (reverse-engineered):
  1. GET /download/<slug>-<post_id>/<index>  → page with data-download-ajax
  2. POST admin-ajax.php action=romspure_get_nonce        → nonce
  3. POST admin-ajax.php action=app_get_download_link     → signed sto.romsfast.com URL
  4. GET signed URL                                        → the file

Cloudflare blocks plain HTTP; camoufox passes it. All AJAX runs inside the
browser via page.evaluate (same-origin, carries cf_clearance).

Usage:
  python romspure_scraper.py <hack-page-url> [--download] [--index N]
"""
import argparse
import asyncio
import json
import re
import sys

from camoufox.async_api import AsyncCamoufox

LAUNCH = dict(headless=True, fingerprint_preset=True,
              i_know_what_im_doing=True, canvas_noise=False)


async def get_post_ids(page, hack_url):
    """Return [(post_id, [indexes...])] from the hack page's download links."""
    await page.goto(hack_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    hrefs = await page.eval_on_selector_all(
        "a[href*='/download/']", "els => els.map(e => e.href)")
    out = {}
    for h in hrefs:
        m = re.search(r"/download/(.+)-(\d+)(?:/(\d+))?$", h)
        if m:
            out.setdefault(m.group(2), set()).add(int(m.group(3) or 1))
    return [(pid, sorted(v)) for pid, v in out.items()]


async def get_download_link(page, post_id, index):
    """Run the nonce + link AJAX inside the browser. Returns {url,name,size}."""
    return await page.evaluate(
        """async ([postId, idx]) => {
            const base = 'https://romspure.cc/wp-admin/admin-ajax.php';
            const enc = new URLSearchParams();
            enc.append('action', 'romspure_get_nonce');
            const n = await (await fetch(base, {method:'POST', body:enc,
                          headers:{'Content-Type':'application/x-www-form-urlencoded'}})).json();
            if (!n.success) return {error: 'nonce failed: ' + JSON.stringify(n)};
            const b = new URLSearchParams();
            b.append('action', 'app_get_download_link');
            b.append('post_id', postId);
            b.append('index', idx);
            b.append('nonce', n.data.nonce);
            const r = await (await fetch(base, {method:'POST', body:b,
                         headers:{'Content-Type':'application/x-www-form-urlencoded'}})).json();
            return r.success ? r.data : {error: JSON.stringify(r)};
        }""", [str(post_id), str(index)])


async def scrape(hack_url, do_download, want_index):
    async with AsyncCamoufox(**LAUNCH) as browser:
        page = await browser.new_page()
        results = []
        for post_id, indexes in await get_post_ids(page, hack_url):
            for index in (want_index and [want_index] or indexes):
                data = await get_download_link(page, post_id, index)
                entry = {"post_id": post_id, "index": index, **data}
                if do_download and data.get("url"):
                    fname = data.get("name") or f"romspure-{post_id}-{index}.zip"
                    async with page.expect_download(timeout=300000) as dl_info:
                        await page.evaluate("u => { location.href = u }", data["url"])
                    dl = await dl_info.value
                    path = f"C:/Users/Christian/Downloads/{fname}"
                    await dl.save_as(path)
                    entry["saved"] = path
                results.append(entry)
        return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="hack page URL, e.g. https://romspure.cc/hacks/wii/mario-kart-wii-deluxe/")
    ap.add_argument("--download", action="store_true", help="actually download the file(s)")
    ap.add_argument("--index", type=int, default=None, help="only this file index")
    args = ap.parse_args()
    res = asyncio.run(scrape(args.url, args.download, args.index))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()