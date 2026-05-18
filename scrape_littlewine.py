#!/usr/bin/env python3
"""Scrape littlewine.com.tw advanced search results for red wine markets."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.request import urlretrieve
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, TimeoutError, async_playwright


BASE_URL = "https://littlewine.com.tw/"
OUTPUT_DIR = Path("docs")
DATA_DIR = OUTPUT_DIR / "data"
HTML_OUTPUT = OUTPUT_DIR / "index.html"
CSV_OUTPUT = DATA_DIR / "littlewine_red_pxmart_links.csv"
JSON_OUTPUT = DATA_DIR / "littlewine_red_pxmart_links.json"
IMAGE_DIR = OUTPUT_DIR / "images"
IMAGE_WEB_PREFIX = "images"
ALL_MARKETS = ["大全聯", "全聯", "好市多", "家樂福", "美廉社", "大潤發", "愛買"]


@dataclass(frozen=True)
class WineLink:
    market: str
    title: str
    url: str
    region: str = ""
    country: str = ""
    grape: str = ""
    abv: str = ""
    vintage: str = ""
    winery: str = ""
    sweetness: str = ""
    acidity: str = ""
    body: str = ""
    rating: str = ""
    reference_price: str = ""
    image_url: str = ""
    image_path: str = ""


async def try_click_by_text(page: Page, labels: Iterable[str], timeout: int = 3000) -> bool:
    for label in labels:
        loc = page.get_by_role("link", name=label)
        if await loc.count() > 0:
            try:
                await loc.first.click(timeout=timeout)
                return True
            except TimeoutError:
                pass

        btn = page.get_by_role("button", name=label)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=timeout)
                return True
            except TimeoutError:
                pass
    return False


async def open_advanced_search(page: Page) -> None:
    await page.goto(BASE_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)

    opened = await try_click_by_text(page, ["進階搜尋", "進階查詢", "Advanced Search"], timeout=4000)
    if not opened:
        selector_candidates = [
            "text=進階搜尋",
            "a:has-text('進階搜尋')",
            "button:has-text('進階搜尋')",
            ".advanced-search",
        ]
        for sel in selector_candidates:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                opened = True
                break

    if not opened:
        raise RuntimeError("找不到『進階搜尋』按鈕，請檢查網站版面是否改版。")

    await page.wait_for_timeout(1200)


async def select_filters(page: Page, market: str) -> None:
    async def click_filter(label: str) -> None:
        candidates = [
            page.get_by_label(label),
            page.get_by_text(label, exact=True),
            page.locator(f"label:has-text('{label}')"),
            page.locator(f"button:has-text('{label}')"),
            page.locator(f"span:has-text('{label}')"),
            page.locator(f"li:has-text('{label}')"),
        ]
        for loc in candidates:
            if await loc.count() > 0:
                try:
                    await loc.first.click(timeout=3000)
                    return
                except TimeoutError:
                    continue
        raise RuntimeError(f"無法點選篩選條件: {label}")

    await click_filter("紅酒")
    await page.wait_for_timeout(500)
    await click_filter(market)
    await page.wait_for_timeout(500)

    confirmed = await try_click_by_text(page, ["確認搜尋", "搜尋", "查詢"], timeout=5000)
    if not confirmed:
        confirm_selectors = [
            "button:has-text('確認搜尋')",
            "a:has-text('確認搜尋')",
            "input[type='submit']",
        ]
        for sel in confirm_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                confirmed = True
                break
    if not confirmed:
        raise RuntimeError("找不到『確認搜尋』按鈕。")

    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1200)


async def collect_links_from_current_page(page: Page, market: str) -> list[WineLink]:
    link_elements = page.locator("a[href]")
    count = await link_elements.count()
    results: list[WineLink] = []

    for i in range(count):
        link = link_elements.nth(i)
        href = (await link.get_attribute("href")) or ""
        if not href.strip():
            continue

        full_url = urljoin(BASE_URL, href)
        if "littlewine.com.tw" not in full_url:
            continue

        title = (await link.inner_text()).strip()
        if not title:
            continue

        lower_url = full_url.lower()

        excluded_tokens = [
            "/search",
            "?s=",
            "/tag/",
            "/category/",
            "/shop/",
            "/news",
            "/about",
            "/contact",
            "/author/",
            "facebook.com",
            "instagram.com",
            "line.me",
        ]
        if any(token in lower_url for token in excluded_tokens):
            continue

        # 只保留「商品詳細頁」型態 URL，避免把分類/搜尋頁混進來。
        detail_tokens = ["/product/", "/wine/", "/item/", "?p="]
        if any(token in lower_url for token in detail_tokens):
            results.append(WineLink(market=market, title=title, url=full_url))

    unique: dict[str, WineLink] = {}
    for r in results:
        unique[r.url] = r

    return sorted(unique.values(), key=lambda x: x.title)


async def goto_next_page(page: Page) -> bool:
    candidates = [
        page.get_by_role("link", name="下一頁"),
        page.get_by_role("link", name="Next"),
        page.locator("a.next"),
        page.locator(".pagination a:has-text('>')"),
        page.locator(".page-numbers.next"),
    ]
    for loc in candidates:
        if await loc.count() > 0:
            try:
                await loc.first.click(timeout=2500)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(800)
                return True
            except TimeoutError:
                continue
    return False


async def expand_lazy_results(
    page: Page,
    market: str,
    max_rounds: int = 6,
    wait_ms: int = 10000,
    target_count: int | None = None,
) -> None:
    """Scroll to bottom and wait for delayed/infinite-loaded results."""
    previous_count = -1

    for _ in range(max_rounds):
        current_count = len(await collect_links_from_current_page(page, market))
        if target_count is not None and current_count >= target_count:
            break
        if current_count == previous_count:
            break
        previous_count = current_count

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except TimeoutError:
            pass
        await page.wait_for_timeout(wait_ms)


async def scrape_all_results(
    page: Page,
    market: str,
    max_pages: int = 30,
    limit: int | None = None,
) -> list[WineLink]:
    all_links: dict[str, WineLink] = {}

    for page_index in range(1, max_pages + 1):
        print(f"[{market}] Processing page {page_index}...")
        if limit is None:
            await expand_lazy_results(page, market)
        else:
            await expand_lazy_results(page, market, max_rounds=2, wait_ms=1200, target_count=limit)
        current_links = await collect_links_from_current_page(page, market)

        new_count = 0
        for item in current_links:
            if item.url not in all_links:
                all_links[item.url] = item
                new_count += 1
                print(f"[{market}] + {item.url}")

        print(
            f"[{market}] Page {page_index}: {new_count} new links, total {len(all_links)}"
        )

        if limit is not None and len(all_links) >= limit:
            print(f"[{market}] Reached limit {limit}, stop early.")
            break

        moved = await goto_next_page(page)
        if not moved:
            print(f"[{market}] No next page, stop pagination.")
            break

    collected = sorted(all_links.values(), key=lambda x: x.title)
    if limit is not None:
        return collected[:limit]
    return collected


def normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :：\n\t")


def extract_by_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return normalize_value(match.group(1))
    return ""


def extract_by_labels(text: str, labels: list[str]) -> str:
    lines = [normalize_value(line) for line in text.splitlines() if normalize_value(line)]

    for i, line in enumerate(lines):
        for label in labels:
            if line.startswith(label + "：") or line.startswith(label + ":"):
                value = normalize_value(re.split(r"[：:]", line, maxsplit=1)[1])
                if value:
                    return value

            if line == label and i + 1 < len(lines):
                next_line = normalize_value(lines[i + 1])
                if next_line and next_line not in labels:
                    return next_line
    return ""


def rating_from_score_classes(classes: str) -> str:
    """Convert score class to rating text, e.g. score3half -> 3.5/5."""
    if not classes:
        return ""

    match = re.search(r"\bscore([0-5])(half)?\b", classes)
    if not match:
        return ""

    base = int(match.group(1))
    value = base + (0.5 if match.group(2) else 0.0)
    return f"{value:g}/5"


async def extract_score_from_area(page: Page, area_selectors: list[str]) -> str:
    """Find score class under area selectors, e.g. .starArea/.sweetArea."""
    for selector in area_selectors:
        area = page.locator(selector)
        area_count = await area.count()
        if area_count == 0:
            continue

        for idx in range(area_count):
            cls = (await area.nth(idx).get_attribute("class")) or ""
            rating = rating_from_score_classes(cls)
            if rating:
                return rating

            score_nodes = area.nth(idx).locator("[class*='score']")
            for j in range(await score_nodes.count()):
                inner_cls = (await score_nodes.nth(j).get_attribute("class")) or ""
                rating = rating_from_score_classes(inner_cls)
                if rating:
                    return rating

    return ""


def extract_score_near_labels_from_html(html: str, labels: list[str], window: int = 500) -> str:
    """Extract score class near a text label from raw HTML."""
    if not html:
        return ""

    for label in labels:
        for m in re.finditer(re.escape(label), html, flags=re.IGNORECASE):
            start = max(0, m.start() - window)
            end = min(len(html), m.end() + window)
            snippet = html[start:end]
            score_match = re.search(r"\bscore([0-5])(half)?\b", snippet, flags=re.IGNORECASE)
            if score_match:
                base = int(score_match.group(1))
                value = base + (0.5 if score_match.group(2) else 0.0)
                return f"{value:g}/5"
    return ""


def extract_degree_score_by_label(html: str, label: str) -> str:
    """Extract scoreN/scoreNhalf from detail block like: <span>甜度</span> ... <section class='degreeArea score1'>."""
    if not html or not label:
        return ""

    pattern = (
        rf"<span[^>]*>\s*{re.escape(label)}\s*</span>"
        rf"[\s\S]{{0,500}}?"
        rf"<section[^>]*class=[\"'][^\"']*degreeArea[^\"']*\b(score[0-5](?:half)?)\b[^\"']*[\"']"
    )
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if not match:
        return ""
    return rating_from_score_classes(match.group(1))


def parse_wine_meta_from_text(text: str) -> dict[str, str]:
    region = extract_by_patterns(
        text,
        [
            r"產區\s*[：:]\s*([^\n]+)",
            r"產地\s*[：:]\s*([^\n]+)",
            r"Region\s*[：:]\s*([^\n]+)",
        ],
    )
    if not region:
        region = extract_by_labels(text, ["產區", "產地", "Region"])

    country = extract_by_patterns(
        text,
        [
            r"國家\s*[：:]\s*([^\n]+)",
            r"Country\s*[：:]\s*([^\n]+)",
        ],
    )
    if not country:
        country = extract_by_labels(text, ["國家", "Country"])

    grape = extract_by_patterns(
        text,
        [
            r"葡萄品種\s*[：:]\s*([^\n]+)",
            r"品種\s*[：:]\s*([^\n]+)",
            r"葡萄\s*[：:]\s*([^\n]+)",
            r"Grape(?:\s+Variet(?:y|ies))?\s*[：:]\s*([^\n]+)",
        ],
    )
    if not grape:
        grape = extract_by_labels(text, ["葡萄品種", "品種", "葡萄", "Grape Variety", "Grape Varieties"])

    abv = extract_by_patterns(
        text,
        [
            r"酒精濃度\s*[：:]\s*([^\n]+)",
            r"酒精度\s*[：:]\s*([^\n]+)",
            r"酒精\s*[：:]\s*([^\n]+)",
            r"ABV\s*[：:]\s*([^\n]+)",
            r"Alcohol\s*[：:]\s*([^\n]+)",
            r"\b(\d{1,2}(?:\.\d)?\s?%)\b",
        ],
    )
    if not abv:
        abv = extract_by_labels(text, ["酒精濃度", "酒精度", "酒精", "ABV", "Alcohol"])

    vintage = extract_by_patterns(
        text,
        [
            r"年份\s*[：:]\s*([^\n]+)",
            r"年分\s*[：:]\s*([^\n]+)",
            r"Vintage\s*[：:]\s*([^\n]+)",
            r"\b(19\d{2}|20\d{2})\b",
        ],
    )
    if not vintage:
        vintage = extract_by_labels(text, ["年份", "年分", "Vintage"])

    winery = extract_by_patterns(
        text,
        [
            r"酒莊\(廠\)\s*[：:]\s*([^\n]+)",
            r"酒莊\s*[：:]\s*([^\n]+)",
            r"酒廠\s*[：:]\s*([^\n]+)",
            r"Winery\s*[：:]\s*([^\n]+)",
        ],
    )
    if not winery:
        winery = extract_by_labels(text, ["酒莊(廠)", "酒莊", "酒廠", "Winery"])

    sweetness = extract_by_patterns(text, [r"甜度\s*[：:]\s*([^\n]+)"])
    if not sweetness:
        sweetness = extract_by_labels(text, ["甜度"])

    acidity = extract_by_patterns(text, [r"酸度\s*[：:]\s*([^\n]+)"])
    if not acidity:
        acidity = extract_by_labels(text, ["酸度"])

    body = extract_by_patterns(text, [r"飽滿度\s*[：:]\s*([^\n]+)", r"Body\s*[：:]\s*([^\n]+)"])
    if not body:
        body = extract_by_labels(text, ["飽滿度", "Body"])

    rating = extract_by_patterns(
        text,
        [
            r"星等\s*[：:]\s*([^\n]+)",
            r"評分\s*[：:]\s*([^\n]+)",
            r"(★{1,5}(?:☆{0,5})?)",
            r"([1-5](?:\.\d)?\s*/\s*5)",
        ],
    )
    if not rating:
        rating = extract_by_labels(text, ["星等", "評分"])

    reference_price = extract_by_patterns(
        text,
        [
            r"參考價\s*[：:]\s*([^\n]+)",
            r"建議售價\s*[：:]\s*([^\n]+)",
            r"價格\s*[：:]\s*([^\n]+)",
            r"(NT\$\s?[\d,]+)",
            r"(\$\s?[\d,]+)",
        ],
    )
    if not reference_price:
        reference_price = extract_by_labels(text, ["參考價", "建議售價", "價格"])

    return {
        "region": region,
        "country": country,
        "grape": grape,
        "abv": abv,
        "vintage": vintage,
        "winery": winery,
        "sweetness": sweetness,
        "acidity": acidity,
        "body": body,
        "rating": rating,
        "reference_price": reference_price,
    }


def pick_first_non_empty(values: list[str]) -> str:
    for v in values:
        if v and v.strip():
            return v.strip()
    return ""


def first_src_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    first = srcset.split(",")[0].strip()
    if not first:
        return ""
    return first.split(" ")[0].strip()


def score_image_candidate(url: str) -> int:
    lower = url.lower()
    score = 0
    if any(token in lower for token in ["wine", "product", "upload", "uploads", "detail"]):
        score += 3
    if any(token in lower for token in [".jpg", ".jpeg", ".png", ".webp"]):
        score += 2
    if any(token in lower for token in ["logo", "icon", "banner", "line", "facebook", "instagram"]):
        score -= 5
    return score


async def enrich_wine_details(browser: Browser, items: list[WineLink]) -> list[WineLink]:
    enriched: list[WineLink] = []
    page = await browser.new_page(viewport={"width": 1366, "height": 900})
    try:
        total = len(items)
        for idx, item in enumerate(items, start=1):
            print(f"[DETAIL] ({idx}/{total}) {item.url}")
            try:
                await page.goto(item.url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except TimeoutError:
                    pass
                await page.wait_for_timeout(800)
                body_text = await page.inner_text("body")
                page_html = await page.content()
                image_url = ""
                image_loc = page.locator("#body_UI_img, #body_UI_img img, .body_UI_img img, .body_UI_img source")
                if await image_loc.count() > 0:
                    el = image_loc.first
                    src = (await el.get_attribute("src")) or ""
                    data_src = (await el.get_attribute("data-src")) or ""
                    data_original = (await el.get_attribute("data-original")) or ""
                    data_lazy = (await el.get_attribute("data-lazy-src")) or ""
                    srcset = (await el.get_attribute("srcset")) or ""
                    data_srcset = (await el.get_attribute("data-srcset")) or ""
                    image_url = pick_first_non_empty(
                        [
                            src,
                            data_src,
                            data_original,
                            data_lazy,
                            first_src_from_srcset(srcset),
                            first_src_from_srcset(data_srcset),
                        ]
                    )

                if not image_url:
                    bg_loc = page.locator("#body_UI_img, .body_UI_img")
                    if await bg_loc.count() > 0:
                        style_attr = (await bg_loc.first.get_attribute("style")) or ""
                        bg_match = re.search(r"url\((['\"]?)(.*?)\1\)", style_attr)
                        if bg_match:
                            image_url = bg_match.group(2)

                if not image_url:
                    og_image = page.locator("meta[property='og:image']")
                    if await og_image.count() > 0:
                        image_url = (await og_image.first.get_attribute("content")) or ""

                if not image_url:
                    candidates: list[str] = []

                    img_loc = page.locator("img")
                    img_count = await img_loc.count()
                    for i in range(min(img_count, 120)):
                        el = img_loc.nth(i)
                        src = (await el.get_attribute("src")) or ""
                        data_src = (await el.get_attribute("data-src")) or ""
                        data_original = (await el.get_attribute("data-original")) or ""
                        data_lazy = (await el.get_attribute("data-lazy-src")) or ""
                        srcset = first_src_from_srcset((await el.get_attribute("srcset")) or "")
                        data_srcset = first_src_from_srcset((await el.get_attribute("data-srcset")) or "")
                        for raw in [src, data_src, data_original, data_lazy, srcset, data_srcset]:
                            if raw:
                                candidates.append(urljoin(BASE_URL, raw))

                    # 選分數最高的圖片 URL，避免抓到 logo/icon。
                    if candidates:
                        candidates = sorted(set(candidates), key=lambda u: score_image_candidate(u), reverse=True)
                        if score_image_candidate(candidates[0]) > 0:
                            image_url = candidates[0]

                if not image_url:
                    html_candidates = re.findall(r"https?://[^\"'\s>]+\.(?:jpg|jpeg|png|webp)", page_html, flags=re.IGNORECASE)
                    if html_candidates:
                        html_candidates = sorted(set(html_candidates), key=lambda u: score_image_candidate(u), reverse=True)
                        if score_image_candidate(html_candidates[0]) > 0:
                            image_url = html_candidates[0]
                if image_url:
                    image_url = urljoin(BASE_URL, image_url)

                # 星等/甜度/酸度/飽滿度優先從各區塊的 score class 解析。
                dom_rating = await extract_score_from_area(page, [".starArea"])
                dom_sweetness = await extract_score_from_area(page, [".sweetArea", ".sweetnessArea"])
                dom_acidity = await extract_score_from_area(page, [".acidArea", ".acidityArea"])
                dom_body = await extract_score_from_area(page, [".bodyArea", ".fullArea"])

                # 優先抓商品屬性區塊的 degreeArea score。
                if not dom_sweetness:
                    dom_sweetness = extract_degree_score_by_label(page_html, "甜度")
                if not dom_acidity:
                    dom_acidity = extract_degree_score_by_label(page_html, "酸度")
                if not dom_body:
                    dom_body = extract_degree_score_by_label(page_html, "飽滿度")

                # 後備：若站台 class 名稱不同，從標籤附近 HTML 補抓 score* class。
                if not dom_sweetness:
                    dom_sweetness = extract_score_near_labels_from_html(page_html, ["甜度", "Sweetness"])
                if not dom_acidity:
                    dom_acidity = extract_score_near_labels_from_html(page_html, ["酸度", "Acidity"])
                if not dom_body:
                    dom_body = extract_score_near_labels_from_html(page_html, ["飽滿度", "Body"])

                # 後備：若沒有 score class，再用 icon-star 數量推估
                if not dom_rating:
                    star_count = await page.locator(".icon-star").count()
                    dom_rating = f"{star_count}/5" if star_count > 0 else ""
            except Exception:
                body_text = ""
                image_url = ""
                dom_rating = ""
                dom_sweetness = ""
                dom_acidity = ""
                dom_body = ""

            meta = parse_wine_meta_from_text(body_text)
            if dom_rating:
                meta["rating"] = dom_rating
            if dom_sweetness:
                meta["sweetness"] = dom_sweetness
            if dom_acidity:
                meta["acidity"] = dom_acidity
            if dom_body:
                meta["body"] = dom_body
            print(
                "[DETAIL]"
                f" region={meta['region'] or '-'}"
                f", country={meta['country'] or '-'}"
                f", grape={meta['grape'] or '-'}"
                f", abv={meta['abv'] or '-'}"
                f", vintage={meta['vintage'] or '-'}"
                f", winery={meta['winery'] or '-'}"
                f", sweetness={meta['sweetness'] or '-'}"
                f", acidity={meta['acidity'] or '-'}"
                f", body={meta['body'] or '-'}"
                f", rating={meta['rating'] or '-'}"
                f", ref_price={meta['reference_price'] or '-'}"
            )
            enriched.append(
                WineLink(
                    market=item.market,
                    title=item.title,
                    url=item.url,
                    region=meta["region"],
                    country=meta["country"],
                    grape=meta["grape"],
                    abv=meta["abv"],
                    vintage=meta["vintage"],
                    winery=meta["winery"],
                    sweetness=meta["sweetness"],
                    acidity=meta["acidity"],
                    body=meta["body"],
                    rating=meta["rating"],
                    reference_price=meta["reference_price"],
                    image_url=image_url,
                )
            )
    finally:
        await page.close()

    return enriched


def load_cached_items(output_path: Path) -> dict[tuple[str, str], WineLink]:
    """Load previously parsed items from JSON output as a cache."""
    if not output_path.exists():
        return {}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, list):
        return {}

    cache: dict[tuple[str, str], WineLink] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market", "") or "").strip()
        url = str(row.get("url", "") or "").strip()
        if not market or not url:
            continue

        cache[(market, url)] = WineLink(
            market=market,
            title=str(row.get("title", "") or "").strip(),
            url=url,
            region=str(row.get("region", "") or "").strip(),
            country=str(row.get("country", "") or "").strip(),
            grape=str(row.get("grape", "") or "").strip(),
            abv=str(row.get("abv", "") or "").strip(),
            vintage=str(row.get("vintage", "") or "").strip(),
            winery=str(row.get("winery", "") or "").strip(),
            sweetness=str(row.get("sweetness", "") or "").strip(),
            acidity=str(row.get("acidity", "") or "").strip(),
            body=str(row.get("body", "") or "").strip(),
            rating=str(row.get("rating", "") or "").strip(),
            reference_price=str(row.get("reference_price", "") or "").strip(),
            image_url=str(row.get("image_url", "") or "").strip(),
            image_path=str(row.get("image_path", "") or "").strip(),
        )

    return cache


def load_items_from_json(input_path: Path) -> list[WineLink]:
    """Load full item list from JSON output for render-only mode."""
    cache = load_cached_items(input_path)
    items = list(cache.values())
    return sorted(items, key=lambda x: (x.market, x.title))


def merge_with_current_item(current: WineLink, cached: WineLink) -> WineLink:
    """Keep current market/title/url, reuse parsed detail fields from cache."""
    return WineLink(
        market=current.market,
        title=current.title or cached.title,
        url=current.url,
        region=cached.region,
        country=cached.country,
        grape=cached.grape,
        abv=cached.abv,
        vintage=cached.vintage,
        winery=cached.winery,
        sweetness=cached.sweetness,
        acidity=cached.acidity,
        body=cached.body,
        rating=cached.rating,
        reference_price=cached.reference_price,
        image_url=cached.image_url,
        image_path=cached.image_path,
    )


def write_csv(items: list[WineLink], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "market",
                "title",
                "url",
                "region",
                "country",
                "grape",
                "abv",
                "vintage",
                "winery",
                "sweetness",
                "acidity",
                "body",
                "rating",
                "reference_price",
                "image_url",
                "image_path",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "market": item.market,
                    "title": item.title,
                    "url": item.url,
                    "region": item.region,
                    "country": item.country,
                    "grape": item.grape,
                    "abv": item.abv,
                    "vintage": item.vintage,
                    "winery": item.winery,
                    "sweetness": item.sweetness,
                    "acidity": item.acidity,
                    "body": item.body,
                    "rating": item.rating,
                    "reference_price": item.reference_price,
                    "image_url": item.image_url,
                    "image_path": item.image_path,
                }
            )


def write_json(items: list[WineLink], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "market": item.market,
            "title": item.title,
            "url": item.url,
            "region": item.region,
            "country": item.country,
            "grape": item.grape,
            "abv": item.abv,
            "vintage": item.vintage,
            "winery": item.winery,
            "sweetness": item.sweetness,
            "acidity": item.acidity,
            "body": item.body,
            "rating": item.rating,
            "reference_price": item.reference_price,
            "image_url": item.image_url,
            "image_path": item.image_path,
        }
        for item in items
    ]
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_html(items: list[WineLink], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _is_valid_country(raw: str) -> bool:
        value = (raw or "").strip()
        if not value:
            return False
        if re.fullmatch(r"\d{4}", value):
            return False
        return True

    def _rating_value(raw: str) -> float:
        m = re.search(r"([0-5](?:\.\d+)?)", raw or "")
        return float(m.group(1)) if m else -1.0

    def _price_value(raw: str) -> int:
        digits = re.sub(r"\D", "", raw or "")
        return int(digits) if digits else -1

    # 預設先依星等高到低（同星等再依參考價高到低）輸出。
    items = sorted(items, key=lambda x: (_rating_value(x.rating), _price_value(x.reference_price), x.title), reverse=True)

    markets = sorted({item.market for item in items})
    countries = sorted({item.country for item in items if _is_valid_country(item.country)})
    chips = "\n".join(
        f'      <button class="chip market-chip" data-market="{market}">{market}</button>' for market in markets
    )
    country_chips = "\n".join(
        f'      <button class="chip country-chip" data-country="{country}">{country}</button>' for country in countries
    )
    rows = "\n".join(
        (
            f'        <tr data-market="{item.market}" data-country="{item.country if _is_valid_country(item.country) else ""}" data-rating="{item.rating or ""}" data-price="{item.reference_price or ""}">'
            f'<td><span class="tag">{item.market}</span></td>'
            f'<td><a href="{item.url}" target="_blank" rel="noopener noreferrer">{item.title}</a></td>'
            f'<td>{item.country if _is_valid_country(item.country) else "-"}</td>'
            f'<td>{item.region or "-"}</td>'
            f'<td>{item.grape or "-"}</td>'
            f'<td>{item.abv or "-"}</td>'
            f'<td>{item.winery or "-"}</td>'
            f'<td>{item.sweetness or "-"}</td>'
            f'<td>{item.acidity or "-"}</td>'
            f'<td>{item.body or "-"}</td>'
            f'<td>{item.rating or "-"}</td>'
            f'<td>{item.reference_price or "-"}</td>'
            + (
                f'<td><a href="{item.image_url}" target="_blank" rel="noopener noreferrer">'
                f'<img class="thumb" src="{item.image_path}" alt="{item.title}" loading="lazy" /></a></td>'
                if item.image_path
                else "<td>-</td>"
            )
            + "</tr>"
        )
        for item in items
    )
    html = f"""<!doctype html>
<html lang=\"zh-Hant\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>littlewine 紅酒連結清單</title>
    <style>
      body {{
        font-family: "Noto Sans TC", "PingFang TC", sans-serif;
        margin: 24px;
        line-height: 1.6;
      }}
      h1 {{ margin-bottom: 0.25rem; }}
      p.meta {{ color: #555; margin-top: 0; }}
      .toolbar {{ margin: 10px 0 16px; display: flex; gap: 8px; flex-wrap: wrap; justify-content: space-between; align-items: center; }}
      .toolbar-left, .toolbar-right {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
      .toolbar-stack {{ display: flex; flex-direction: column; gap: 8px; width: 100%; }}
      .chip {{ border: 1px solid #114488; background: #fff; color: #114488; border-radius: 16px; padding: 4px 10px; cursor: pointer; }}
      .chip.active {{ background: #114488; color: #fff; }}
      .country-chip {{ border-color: #e9b980; color: #9a5e1a; background: #fff9f2; }}
      .country-chip.active {{ background: #f3c48a; border-color: #e2ad68; color: #5e3a10; }}
      .table-wrap {{ overflow-x: auto; border: 1px solid #dbe5f3; border-radius: 10px; }}
      table {{ width: 100%; border-collapse: collapse; min-width: 1400px; }}
      th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #e9eef7; vertical-align: top; }}
      th {{ background: #f4f8ff; font-weight: 600; }}
      tr:hover td {{ background: #fafcff; }}
      .thumb {{ width: 96px; height: 96px; object-fit: cover; border-radius: 8px; border: 1px solid #dbe5f3; background: #fff; }}
      .tag {{ display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 12px; background: #eef5ff; color: #114488; font-size: 0.85rem; }}
      a {{ color: #114488; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
    </style>
  </head>
  <body>
    <h1>littlewine 紅酒連結清單</h1>
    <p class=\"meta\">目前顯示 <span id=\"visible-count\">{len(items)}</span> / 全部 <span id=\"total-count\">{len(items)}</span> 筆</p>
    <div class=\"toolbar-stack\">
      <div class=\"toolbar\">
        <div class=\"toolbar-left\">
          <button class=\"chip market-chip active\" data-market=\"ALL\">全部</button>
{chips}
        </div>
        <div class=\"toolbar-right\">
          <button class=\"chip sort-chip active\" data-sort=\"rating\">星等高到低</button>
          <button class=\"chip sort-chip\" data-sort=\"price\">參考價高到低</button>
        </div>
      </div>
      <div class=\"toolbar\">
        <div class=\"toolbar-left\">
          <button class=\"chip country-chip active\" data-country=\"ALL\">全部</button>
{country_chips}
        </div>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>賣場</th>
            <th>酒款</th>
            <th>國家</th>
            <th>產區</th>
            <th>葡萄品種</th>
            <th>酒精濃度</th>
            <th>酒莊(廠)</th>
            <th>甜度</th>
            <th>酸度</th>
            <th>飽滿度</th>
            <th>星等</th>
            <th>參考價</th>
            <th>圖片</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
    <script>
      const marketChips = Array.from(document.querySelectorAll('.market-chip'));
      const countryChips = Array.from(document.querySelectorAll('.country-chip'));
      const sortChips = Array.from(document.querySelectorAll('.sort-chip'));
      const items = Array.from(document.querySelectorAll('tr[data-market]'));
      const tbody = document.querySelector('tbody');
      const visibleCountEl = document.getElementById('visible-count');
      let currentMarket = 'ALL';
      let currentCountry = 'ALL';

      function parseRating(text) {{
        const match = (text || '').match(/([0-5](?:\.\d+)?)/);
        return match ? Number(match[1]) : -1;
      }}

      function parsePrice(text) {{
        const digits = (text || '').replace(/[^\d]/g, '');
        return digits ? Number(digits) : -1;
      }}

      function sortRows(mode) {{
        const sorted = [...items].sort((a, b) => {{
          const aCells = a.querySelectorAll('td');
          const bCells = b.querySelectorAll('td');
          const aTitle = aCells[1]?.innerText || '';
          const bTitle = bCells[1]?.innerText || '';

          if (mode === 'price') {{
            const aPrice = parsePrice(a.dataset.price || '');
            const bPrice = parsePrice(b.dataset.price || '');
            if (aPrice !== bPrice) return bPrice - aPrice;
            return aTitle.localeCompare(bTitle, 'zh-Hant');
          }}

          const aRating = parseRating(a.dataset.rating || '');
          const bRating = parseRating(b.dataset.rating || '');
          if (aRating !== bRating) return bRating - aRating;

          const aPrice = parsePrice(a.dataset.price || '');
          const bPrice = parsePrice(b.dataset.price || '');
          if (aPrice !== bPrice) return bPrice - aPrice;

          return aTitle.localeCompare(bTitle, 'zh-Hant');
        }});

        if (tbody) sorted.forEach((row) => tbody.appendChild(row));
      }}

      function filterBy(market, country) {{
        currentMarket = market;
        currentCountry = country;
        let visible = 0;
        items.forEach((item) => {{
          const marketOk = market === 'ALL' || item.dataset.market === market;
          const countryOk = country === 'ALL' || item.dataset.country === country;
          const show = marketOk && countryOk;
          item.style.display = show ? '' : 'none';
          if (show) visible += 1;
        }});
        if (visibleCountEl) visibleCountEl.textContent = String(visible);
      }}

      marketChips.forEach((chip) => {{
        chip.addEventListener('click', () => {{
          marketChips.forEach((c) => c.classList.remove('active'));
          chip.classList.add('active');
          filterBy(chip.dataset.market || 'ALL', currentCountry);
        }});
      }});

      countryChips.forEach((chip) => {{
        chip.addEventListener('click', () => {{
          countryChips.forEach((c) => c.classList.remove('active'));
          chip.classList.add('active');
          filterBy(currentMarket, chip.dataset.country || 'ALL');
        }});
      }});

      sortChips.forEach((chip) => {{
        chip.addEventListener('click', () => {{
          sortChips.forEach((c) => c.classList.remove('active'));
          chip.classList.add('active');
          sortRows(chip.dataset.sort || 'rating');
          filterBy(currentMarket, currentCountry);
        }});
      }});

      sortRows('rating');
      filterBy('ALL', 'ALL');
    </script>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


async def scrape_market(page: Page, market: str, limit: int | None = None) -> list[WineLink]:
    await open_advanced_search(page)
    await select_filters(page, market)
    return await scrape_all_results(page, market, limit=limit)


def parse_markets_arg(markets_arg: str | None) -> list[str]:
    if not markets_arg or not markets_arg.strip():
        return list(ALL_MARKETS)

    requested = [m.strip() for m in markets_arg.split(",") if m.strip()]
    if not requested:
        return list(ALL_MARKETS)

    invalid = [m for m in requested if m not in ALL_MARKETS]
    if invalid:
        raise ValueError(
            f"Unknown markets: {', '.join(invalid)}. Supported: {', '.join(ALL_MARKETS)}"
        )

    seen: set[str] = set()
    ordered_unique: list[str] = []
    for m in requested:
        if m not in seen:
            ordered_unique.append(m)
            seen.add(m)
    return ordered_unique


async def run(headed: bool, limit: int | None, markets: list[str], refresh: bool) -> list[WineLink]:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=not headed)
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        try:
            merged: dict[tuple[str, str], WineLink] = {}

            for market in markets:
                links = await scrape_market(page, market, limit=limit)
                if limit is not None:
                    print(f"[INFO] {market}: keep first {len(links)} links")
                for item in links:
                    merged[(item.market, item.url)] = item

            merged_items = sorted(merged.values(), key=lambda x: (x.market, x.title))
            print(f"[DETAIL] Start detail scraping for {len(merged_items)} links...")

            cache = {} if refresh else load_cached_items(JSON_OUTPUT)
            to_parse: list[WineLink] = []
            reused: list[WineLink] = []
            for item in merged_items:
                key = (item.market, item.url)
                cached = cache.get(key)
                if cached is None:
                    to_parse.append(item)
                    continue
                reused.append(merge_with_current_item(item, cached))

            if refresh:
                print("[CACHE] Refresh mode on, skip cache reuse")
            elif reused:
                print(f"[CACHE] Reused {len(reused)} parsed items from {JSON_OUTPUT.as_posix()}")
            if to_parse:
                print(f"[DETAIL] Need to parse {len(to_parse)} new items...")

            enriched_new = await enrich_wine_details(browser, to_parse) if to_parse else []
            enriched = sorted([*reused, *enriched_new], key=lambda x: (x.market, x.title))
            return enriched
        finally:
            await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape littlewine red wine links from PXMart")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode for debugging",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only keep first N links before scraping details",
    )
    parser.add_argument(
        "--markets",
        type=str,
        default=None,
        help="Comma-separated markets, e.g. '全聯,家樂福'. Default: all markets",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-parse all detail pages and ignore JSON cache",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Only render HTML from existing JSON cache, do not scrape or download",
    )
    parser.add_argument(
        "--input-json",
        type=str,
        default=JSON_OUTPUT.as_posix(),
        help="JSON file used by --render-only (default: docs/data/littlewine_red_pxmart_links.json)",
    )
    return parser.parse_args()


def download_images(items: list[WineLink], output_dir: Path) -> list[WineLink]:
    output_dir.mkdir(parents=True, exist_ok=True)
    updated: list[WineLink] = []

    for item in items:
        image_path = ""
        if item.image_url:
            digest = hashlib.md5(item.image_url.encode("utf-8")).hexdigest()[:12]
            suffix = Path(item.image_url.split("?")[0]).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".jpg"
            file_name = f"{digest}{suffix}"
            file_path = output_dir / file_name
            try:
                if not file_path.exists():
                    urlretrieve(item.image_url, file_path)
                image_path = str((Path(IMAGE_WEB_PREFIX) / file_name).as_posix())
            except Exception:
                image_path = ""

        updated.append(
            WineLink(
                market=item.market,
                title=item.title,
                url=item.url,
                region=item.region,
                country=item.country,
                grape=item.grape,
                abv=item.abv,
                vintage=item.vintage,
                winery=item.winery,
                sweetness=item.sweetness,
                acidity=item.acidity,
                body=item.body,
                rating=item.rating,
                reference_price=item.reference_price,
                image_url=item.image_url,
                image_path=image_path,
            )
        )

    return updated


def main() -> None:
    args = parse_args()

    if args.render_only:
        input_path = Path(args.input_json)
        items = load_items_from_json(input_path)
        if not items:
            raise SystemExit(f"No items found in {input_path}. Run scraping first or provide a valid JSON file.")
        write_html(items, HTML_OUTPUT)
        print(f"Done. Rendered {len(items)} items to {HTML_OUTPUT.as_posix()} from {input_path}")
        return

    try:
        markets = parse_markets_arg(args.markets)
    except ValueError as exc:
        raise SystemExit(str(exc))

    links = asyncio.run(run(headed=args.headed, limit=args.limit, markets=markets, refresh=args.refresh))
    links = download_images(links, IMAGE_DIR)

    write_html(links, HTML_OUTPUT)
    write_csv(links, CSV_OUTPUT)
    write_json(links, JSON_OUTPUT)

    print(f"Done. Collected {len(links)} links.")
    print(f"- {HTML_OUTPUT.as_posix()}")
    print(f"- {CSV_OUTPUT.as_posix()}")
    print(f"- {JSON_OUTPUT.as_posix()}")


if __name__ == "__main__":
    main()
