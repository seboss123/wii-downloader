"""Vimm's Lair Wii scraper — camoufox with fingerprint_preset (fpgen bypass).

Usage:
  python vimm_camoufox_scraper.py "Mario"              # search, print JSON
  python vimm_camoufox_scraper.py "Mario" --download    # search + fetch DL links
  python vimm_camoufox_scraper.py --id 63642            # single vault detail
"""
import asyncio, json, sys, re
from camoufox import AsyncCamoufox

async def search_vimm(query: str) -> list:
    results = []
    async with AsyncCamoufox(
        headless=True, fingerprint_preset=True,
        i_know_what_im_doing=True, canvas_noise=False,
    ) as browser:
        page = await browser.new_page()
        url = f"https://vimm.net/vault/?p=list&system=Wii&q={query.replace(' ', '+')}"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        rows = await page.query_selector_all("table.rounded tr")
        for row in rows:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 5:
                    continue
                title = (await cells[0].inner_text()).strip()
                version = (await cells[2].inner_text()).strip()
                languages = (await cells[3].inner_text()).strip()
                rating = (await cells[4].inner_text()).strip()

                link_el = await row.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                m = re.search(r'/vault/(\d+)', href or "")
                if not m:
                    continue
                vault_id = m.group(1)

                results.append({
                    "vault_id": vault_id,
                    "title": title,
                    "version": version,
                    "languages": languages,
                    "rating": rating,
                    "url": f"https://vimm.net/vault/{vault_id}",
                })
            except Exception:
                continue
    return results

async def get_vault_detail(vault_id: str) -> dict:
    """Fetch region, size, download URL from a vault detail page.
    
    Vimm uses a POST form to dl2.vimm.net with a time-limited token.
    Clicking Download triggers a browser download event that exposes
    the direct URL and filename.
    """
    detail = {"vault_id": vault_id}
    download_info = {}

    async with AsyncCamoufox(
        headless=True, fingerprint_preset=True,
        i_know_what_im_doing=True, canvas_noise=False,
    ) as browser:
        page = await browser.new_page()

        # Capture download events
        async def on_download(download):
            download_info["filename"] = download.suggested_filename
            download_info["url"] = download.url

        page.on("download", on_download)

        await page.goto(f"https://vimm.net/vault/{vault_id}", wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)

        body_text = await page.evaluate("document.body.innerText")

        m = re.search(r'RVL-\w+?-(\w+)', body_text)
        if m:
            detail["region"] = m.group(1)

        m = re.search(r'([\d.]+)\s*GB', body_text)
        if m:
            detail["size_gb"] = float(m.group(1))

        # Click download button to trigger the download event
        try:
            await page.click('button:has-text("Download")')
            await page.wait_for_timeout(5000)
        except Exception:
            pass

        if download_info:
            detail["download_url"] = download_info.get("url", "")
            detail["download_filename"] = download_info.get("filename", "")

        # Also extract form info as fallback
        form_info = await page.evaluate("""() => {
            const form = Array.from(document.querySelectorAll('form'))
                .find(f => f.action.includes('dl2.vimm.net'));
            if (!form) return null;
            const inputs = {};
            form.querySelectorAll('input').forEach(i => {
                if (i.name) inputs[i.name] = i.value;
            });
            return { action: form.action, method: form.method, inputs };
        }""")
        if form_info:
            detail["download_action"] = form_info["action"]
            detail["download_form"] = form_info["inputs"]

    return detail

async def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python vimm_camoufox_scraper.py <query> [--download]")
        print("       python vimm_camoufox_scraper.py --id <vault_id>")
        return

    if args[0] == "--id":
        vid = args[1]
        detail = await get_vault_detail(vid)
        print(json.dumps(detail, indent=2))
        return

    query = args[0]
    results = await search_vimm(query)
    print(json.dumps(results, indent=2))

    if "--download" in args and results:
        print("\n--- Fetching download links ---", file=sys.stderr)
        for r in results[:5]:
            detail = await get_vault_detail(r["vault_id"])
            r.update(detail)
            print(json.dumps(r, indent=2), file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())