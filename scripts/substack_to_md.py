"""Substack article → local markdown + image archive, with optional Claude vision classification.

Use case: pull weekly research posts (Bracco's Sunday Scans, Diligence Stack,
Global Semi Research, etc.) into the local docs/research/ tree so the content
is searchable, screenshot-quotable, and image-classifiable.

Usage:
    # Basic: just download text + images, no classification
    python scripts/substack_to_md.py "https://example.substack.com/p/post-slug"

    # Full: also classify each image via Claude vision (requires ANTHROPIC_API_KEY)
    python scripts/substack_to_md.py "https://example.substack.com/p/post-slug" --classify

    # Limit images downloaded (useful for image-heavy posts)
    python scripts/substack_to_md.py "<url>" --classify --max-images 10

Output structure:
    docs/research/substack_<slug>_<date>/
        article.md                   — clean markdown of article body
        article_classified.md        — markdown with inline image descriptions (if --classify)
        manifest.json                — image URLs, local paths, captions, classifications
        images/
            img_001.png
            img_002.jpg
            ...

Cost estimate (with --classify):
    ~$0.003 per image (Claude Sonnet vision, 1 image @ ~1500 tokens out)
    Typical post = 15-25 images = $0.05-0.08 per run
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(".env")

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "docs" / "research"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GammaPulseSubstackBot/1.0"
REQUEST_TIMEOUT = 30.0

# Substack uses these class patterns for the main article body
ARTICLE_SELECTORS = [
    "div.body.markup",          # most common
    "div.available-content",    # alt
    "div.post-content",         # legacy
    "article",                  # fallback
]

# Skip images smaller than this (icons, avatars, decorative)
MIN_IMAGE_BYTES = 8_000

# Vision classification model
CLASSIFY_MODEL = "claude-sonnet-4-5"
CLASSIFY_MAX_TOKENS = 800
CLASSIFY_PROMPT = """You are analyzing an image from a financial markets research article.

Describe what's in this image in 2-4 sentences. Focus on:
- If it's a chart: ticker symbol, timeframe, key price levels, technical patterns visible, indicator readings shown
- If it's a heatmap/scanner: what's being ranked, top names visible, color signal direction
- If it's a screenshot of a tool/dashboard: what tool, what metric, key values
- If it's an annotated chart: what the annotations say

Use specific numbers and ticker symbols from the image. Do not editorialize or add market opinions — just describe what the image shows.

If you can't tell what the image is showing, say so plainly."""


def slugify(text: str) -> str:
    """Convert a URL slug to a safe filename component."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or "article"


def fetch_article(url: str) -> tuple[str, BeautifulSoup]:
    """Fetch the Substack article and return raw HTML + parsed soup."""
    print(f"[fetch] {url}", flush=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return resp.text, soup


def find_article_body(soup: BeautifulSoup) -> BeautifulSoup | None:
    """Locate the main article body using common Substack selectors."""
    for selector in ARTICLE_SELECTORS:
        node = soup.select_one(selector)
        if node:
            return node
    return None


def extract_metadata(soup: BeautifulSoup) -> dict[str, str]:
    """Pull title, author, publish date, subtitle from OG tags + page elements."""
    meta = {}
    og_title = soup.find("meta", property="og:title")
    if og_title:
        meta["title"] = og_title.get("content", "").strip()
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        meta["subtitle"] = og_desc.get("content", "").strip()
    og_url = soup.find("meta", property="og:url")
    if og_url:
        meta["url"] = og_url.get("content", "").strip()
    og_published = soup.find("meta", property="article:published_time")
    if og_published:
        meta["published"] = og_published.get("content", "").strip()
    author = soup.find("meta", attrs={"name": "author"})
    if author:
        meta["author"] = author.get("content", "").strip()
    return meta


def collect_images(body: BeautifulSoup, base_url: str) -> list[dict]:
    """Find all <img> tags in the article body. Returns deduped list of {src, alt, caption}."""
    images: list[dict] = []
    seen_urls: set[str] = set()
    for img in body.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        # Substack uses image proxy URLs; resolve relative paths
        full_url = urljoin(base_url, src)
        # Strip query strings for dedup (size variants of same image)
        url_key = full_url.split("?")[0]
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        alt = (img.get("alt") or "").strip()
        # Look for adjacent figcaption
        caption = ""
        parent_fig = img.find_parent("figure")
        if parent_fig:
            cap = parent_fig.find("figcaption")
            if cap:
                caption = cap.get_text(" ", strip=True)
        images.append({"src": full_url, "alt": alt, "caption": caption})
    return images


def download_image(url: str, out_path: Path) -> tuple[bool, int]:
    """Download an image to disk. Returns (success, size_bytes)."""
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
        size = len(resp.content)
        if size < MIN_IMAGE_BYTES:
            return False, size  # skip tiny images
        out_path.write_bytes(resp.content)
        return True, size
    except Exception as e:
        print(f"  [!] failed to download {url}: {e}", flush=True)
        return False, 0


def guess_extension(url: str, content_type: str = "") -> str:
    """Best-effort guess at file extension."""
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
        return path_ext
    if content_type:
        guess = mimetypes.guess_extension(content_type.split(";")[0])
        if guess:
            return guess
    return ".png"  # default


def html_to_markdown(body: BeautifulSoup, images: list[dict]) -> str:
    """Convert article body HTML to clean markdown, replacing image srcs with local refs."""
    try:
        from markdownify import markdownify as md
    except ImportError:
        # Fallback: text extraction only
        return body.get_text("\n\n", strip=True)

    # Build URL → local-ref map
    url_to_ref: dict[str, str] = {}
    for i, img in enumerate(images, 1):
        url_to_ref[img["src"]] = f"images/img_{i:03d}"

    # Replace img srcs in-place before conversion
    for img_tag in body.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src")
        if not src:
            continue
        full_url = src.split("?")[0] if src.startswith("http") else src
        for orig_url, ref in url_to_ref.items():
            if full_url.split("?")[0] == orig_url.split("?")[0]:
                img_tag["src"] = ref + ".png"  # extension set during download
                break

    markdown = md(str(body), heading_style="ATX", bullets="-")
    # Clean up excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown


def classify_image(image_path: Path, client) -> str:
    """Send an image to Claude vision and get a description."""
    img_bytes = image_path.read_bytes()
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    media_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    try:
        msg = client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=CLASSIFY_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": CLASSIFY_PROMPT},
                    ],
                }
            ],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"[classification error: {e}]"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Substack article URL")
    p.add_argument("--classify", action="store_true",
                   help="Run Claude vision on each downloaded image")
    p.add_argument("--max-images", type=int, default=30,
                   help="Cap on images to download (default: 30)")
    p.add_argument("--output-dir", default=None,
                   help="Override default output path under docs/research/")
    args = p.parse_args()

    # Build output dir from URL slug
    parsed = urlparse(args.url)
    path_parts = [p for p in parsed.path.split("/") if p]
    slug = slugify(path_parts[-1]) if path_parts else "article"
    date_tag = datetime.now().strftime("%Y-%m-%d")
    default_dir = RESEARCH_DIR / f"substack_{slug}_{date_tag}"
    out_dir = Path(args.output_dir) if args.output_dir else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"[output] {out_dir}", flush=True)

    # Fetch + parse
    raw_html, soup = fetch_article(args.url)
    meta = extract_metadata(soup)
    body = find_article_body(soup)
    if body is None:
        print("[!] could not locate article body — Substack layout may have changed",
              file=sys.stderr)
        # Save the raw HTML so we can inspect
        (out_dir / "raw.html").write_text(raw_html, encoding="utf-8")
        return 1

    # Find images
    images = collect_images(body, args.url)
    print(f"[parse] found {len(images)} unique images in article", flush=True)
    if args.max_images and len(images) > args.max_images:
        print(f"[parse] limiting to first {args.max_images}", flush=True)
        images = images[:args.max_images]

    # Download images
    manifest: list[dict] = []
    for i, img in enumerate(images, 1):
        ext = guess_extension(img["src"])
        local_name = f"img_{i:03d}{ext}"
        local_path = images_dir / local_name
        ok, size = download_image(img["src"], local_path)
        status = f"{size//1024} KB" if ok else "skipped/failed"
        print(f"  [{i:3d}] {local_name} ({status})", flush=True)
        manifest.append({
            "index": i,
            "url": img["src"],
            "local_path": f"images/{local_name}",
            "alt": img["alt"],
            "caption": img["caption"],
            "size_bytes": size,
            "downloaded": ok,
            "classification": None,
        })

    # Write base markdown
    md_text = html_to_markdown(body, images)
    front_matter = [
        f"# {meta.get('title', 'Untitled')}",
        "",
        f"*{meta.get('subtitle', '')}*" if meta.get("subtitle") else "",
        "",
        f"**Source:** {meta.get('url', args.url)}",
        f"**Published:** {meta.get('published', 'unknown')}",
        f"**Author:** {meta.get('author', 'unknown')}",
        f"**Fetched:** {datetime.now().isoformat()}",
        "",
        "---",
        "",
    ]
    full_md = "\n".join(front_matter) + md_text
    (out_dir / "article.md").write_text(full_md, encoding="utf-8")
    print(f"[write] article.md ({len(full_md):,} chars)", flush=True)

    # Optional: classify images via Claude vision
    if args.classify:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("[!] --classify requires ANTHROPIC_API_KEY in .env", file=sys.stderr)
            print("    skipping classification; basic outputs are still saved",
                  file=sys.stderr)
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            print(f"[classify] running Claude vision on {len(manifest)} images...",
                  flush=True)
            classified_count = 0
            for entry in manifest:
                if not entry["downloaded"]:
                    continue
                local_path = out_dir / entry["local_path"]
                desc = classify_image(local_path, client)
                entry["classification"] = desc
                classified_count += 1
                print(f"  [{entry['index']:3d}] {desc[:100]}...", flush=True)
                time.sleep(0.5)  # rate limit courtesy
            print(f"[classify] classified {classified_count} images", flush=True)

            # Write classified markdown (article + inline image descriptions)
            classified_md = full_md
            for entry in manifest:
                if entry.get("classification"):
                    placeholder = entry["local_path"].replace(".png", "")
                    description_block = (
                        f"\n\n> **Image {entry['index']}**: {entry['classification']}\n"
                    )
                    # Insert description after image reference
                    classified_md = classified_md.replace(
                        f"]({placeholder}",
                        f"]({placeholder}",
                    )
            # Also append a full image index at end
            classified_md += "\n\n---\n\n## Image Classifications\n\n"
            for entry in manifest:
                if entry.get("classification"):
                    classified_md += (
                        f"### Image {entry['index']} — `{entry['local_path']}`\n"
                        f"{entry['classification']}\n\n"
                    )
                    if entry.get("alt") or entry.get("caption"):
                        classified_md += (
                            f"*Alt/caption:* {entry.get('alt') or entry.get('caption')}\n\n"
                        )
            (out_dir / "article_classified.md").write_text(
                classified_md, encoding="utf-8"
            )
            print(f"[write] article_classified.md", flush=True)

    # Write manifest
    manifest_data = {
        "url": args.url,
        "fetched_at": datetime.now().isoformat(),
        "metadata": meta,
        "images_total": len(manifest),
        "images_downloaded": sum(1 for m in manifest if m["downloaded"]),
        "images_classified": sum(1 for m in manifest if m.get("classification")),
        "images": manifest,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest_data, indent=2), encoding="utf-8"
    )
    print(f"[write] manifest.json", flush=True)

    print(f"\nDone. Outputs in: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
