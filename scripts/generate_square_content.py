import datetime as dt
import email.utils
import hashlib
import html
import io
import json
import math
import os
import random
import re
import socket
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODE = os.environ.get("CONTENT_MODE", "news").strip().lower()
NOW = dt.datetime.now(dt.timezone.utc)
NOW_PK = NOW + dt.timedelta(hours=5)

if not GEMINI_KEY:
    raise SystemExit("GEMINI_API_KEY is missing.")

if MODE not in {"news", "education", "article"}:
    raise SystemExit(f"Unsupported content mode: {MODE}")

# Current fallback chain used by the user's working V4.1 system.
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Blockworks", "https://blockworks.co/feed"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
]

COINS = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "binance": "BNB", "bnb": "BNB",
    "solana": "SOL", "sol": "SOL",
    "xrp": "XRP", "ripple": "XRP",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "chainlink": "LINK", "link": "LINK",
    "avalanche": "AVAX", "avax": "AVAX",
    "sui": "SUI",
    "toncoin": "TON", "ton": "TON",
    "tron": "TRX", "trx": "TRX",
    "polkadot": "DOT", "dot": "DOT",
    "litecoin": "LTC", "ltc": "LTC",
    "shiba": "SHIB", "shib": "SHIB",
    "pepe": "PEPE",
    "cosmos": "ATOM", "atom": "ATOM",
    "uniswap": "UNI", "uni": "UNI",
    "aave": "AAVE",
}

CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "LINK": "chainlink", "AVAX": "avalanche-2",
    "SUI": "sui", "TON": "the-open-network", "TRX": "tron",
    "DOT": "polkadot", "LTC": "litecoin", "SHIB": "shiba-inu",
    "PEPE": "pepe", "ATOM": "cosmos", "UNI": "uniswap", "AAVE": "aave",
}

# Dynamic visual system: theme is chosen from category/coin/sentiment.
THEMES = {
    "bitcoin": {
        "bg": (8, 12, 22), "panel": (9, 18, 34),
        "primary": (247, 181, 53), "secondary": (255, 115, 30),
        "highlight": (255, 225, 135), "grid": (78, 67, 42),
    },
    "ethereum": {
        "bg": (11, 10, 30), "panel": (17, 16, 43),
        "primary": (139, 118, 255), "secondary": (82, 173, 255),
        "highlight": (205, 196, 255), "grid": (58, 57, 86),
    },
    "solana": {
        "bg": (6, 18, 24), "panel": (7, 24, 31),
        "primary": (77, 239, 184), "secondary": (113, 103, 255),
        "highlight": (185, 255, 230), "grid": (39, 78, 78),
    },
    "security": {
        "bg": (25, 8, 15), "panel": (35, 12, 23),
        "primary": (255, 75, 90), "secondary": (255, 157, 66),
        "highlight": (255, 211, 205), "grid": (91, 46, 51),
    },
    "defi": {
        "bg": (15, 8, 28), "panel": (26, 12, 43),
        "primary": (182, 93, 255), "secondary": (56, 202, 255),
        "highlight": (228, 208, 255), "grid": (68, 48, 93),
    },
    "macro": {
        "bg": (5, 16, 28), "panel": (7, 27, 44),
        "primary": (52, 190, 255), "secondary": (54, 235, 186),
        "highlight": (203, 242, 255), "grid": (40, 77, 98),
    },
    "default": {
        "bg": (7, 13, 28), "panel": (9, 18, 34),
        "primary": (247, 188, 45), "secondary": (55, 181, 255),
        "highlight": (255, 232, 155), "grid": (57, 71, 94),
    },
}


def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def lname(tag):
    return tag.split("}", 1)[-1].lower()


def child_text(parent, wanted):
    for child in parent:
        if lname(child.tag) == wanted.lower():
            return clean(child.text or "")
    return ""


def parse_date(value):
    if not value:
        return NOW
    try:
        x = email.utils.parsedate_to_datetime(value)
        if x.tzinfo is None:
            x = x.replace(tzinfo=dt.timezone.utc)
        return x.astimezone(dt.timezone.utc)
    except Exception:
        return NOW


def feed_items(source, url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 BinanceSquareV5/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
        root = ET.fromstring(raw)
        out = []

        for item in root.iter():
            if lname(item.tag) != "item":
                continue
            title = child_text(item, "title")
            link = child_text(item, "link")
            summary = child_text(item, "description") or child_text(item, "summary")
            published = (
                child_text(item, "pubdate")
                or child_text(item, "published")
                or child_text(item, "updated")
            )
            if title and link:
                out.append({
                    "source": source,
                    "title": title,
                    "summary": summary[:1200],
                    "url": link,
                    "published": parse_date(published),
                })

        if not out:
            for entry in root.iter():
                if lname(entry.tag) != "entry":
                    continue
                title = child_text(entry, "title")
                summary = child_text(entry, "summary") or child_text(entry, "content")
                published = child_text(entry, "published") or child_text(entry, "updated")
                link = ""
                for child in entry:
                    if lname(child.tag) == "link":
                        link = child.attrib.get("href", "")
                        if link:
                            break
                if title and link:
                    out.append({
                        "source": source,
                        "title": title,
                        "summary": summary[:1200],
                        "url": link,
                        "published": parse_date(published),
                    })
        return out
    except Exception as exc:
        print(f"Feed failed: {source}: {type(exc).__name__}: {exc}")
        return []


def collect_news():
    all_items = []
    for source, url in FEEDS:
        all_items.extend(feed_items(source, url))

    cutoff = NOW - dt.timedelta(hours=72)
    items = [item for item in all_items if item["published"] >= cutoff]
    if not items:
        items = all_items

    seen_urls = set()
    unique = []
    for item in sorted(items, key=lambda z: z["published"], reverse=True):
        if item["url"] in seen_urls:
            continue
        seen_urls.add(item["url"])
        item["norm"] = re.sub(r"\W+", " ", item["title"].lower()).strip()
        unique.append(item)

    relevance_words = [
        "bitcoin", "ethereum", "binance", "bnb", "solana", "xrp",
        "stablecoin", "defi", "etf", "sec", "regulation", "blockchain",
        "crypto", "digital asset", "hack", "wallet", "exchange",
        "institutional", "treasury", "federal reserve", "fincen", "liquidity",
        "tokenization", "altcoin", "on-chain", "whale",
    ]

    for item in unique:
        blob = (item["title"] + " " + item["summary"]).lower()
        relevance = sum(3 for word in relevance_words if word in blob)
        freshness = max(0.0, 72 - (NOW - item["published"]).total_seconds() / 3600)
        item["score"] = relevance + freshness

    unique.sort(key=lambda z: z["score"], reverse=True)

    chosen = []
    for item in unique:
        current = set(item["norm"].split())
        duplicate = False
        for other in chosen:
            other_words = set(other["norm"].split())
            if current and other_words:
                overlap = len(current & other_words) / max(1, len(current | other_words))
                if overlap >= 0.72:
                    duplicate = True
                    break
        if not duplicate:
            chosen.append(item)
        if len(chosen) >= 12:
            break
    return chosen


def gemini_request(model, prompt, max_tokens):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": max_tokens,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=50) as response:
        data = json.load(response)

    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(
        part.get("text", "") for part in parts if isinstance(part, dict)
    ).strip()
    if not text:
        raise ValueError("Empty Gemini output.")
    return text


def gemini(prompt, max_tokens):
    errors = []
    for model in MODELS:
        print(f"Trying Gemini: {model}")
        try:
            result = gemini_request(model, prompt, max_tokens)
            print(f"SUCCESS with {model}")
            return result, model
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"{model}: HTTP {exc.code}: {detail[:600]}")
            errors.append(f"{model}: HTTP {exc.code}")
        except (TimeoutError, socket.timeout):
            print(f"{model}: timeout")
            errors.append(f"{model}: timeout")
        except Exception as exc:
            print(f"{model}: {type(exc).__name__}: {exc}")
            errors.append(f"{model}: {type(exc).__name__}")
    raise SystemExit("All Gemini models failed: " + ", ".join(errors))


def parse_json(text):
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("Gemini did not return JSON.")
    return json.loads(stripped[start:end + 1])


def infer_coin(text):
    upper = text.upper()
    for sym in re.findall(r"\$([A-Z]{2,10})\b", upper):
        return sym
    low = text.lower()
    for name, symbol in COINS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return symbol
    return ""


def normalize_hashtags(raw, must_have):
    tags = []
    for tag in raw if isinstance(raw, list) else []:
        tag = str(tag).strip()
        tag = re.sub(r"[^A-Za-z0-9_#]", "", tag)
        if tag and not tag.startswith("#"):
            tag = "#" + tag
        if tag and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)

    final = []
    for tag in list(must_have) + tags:
        if tag and tag.lower() not in {x.lower() for x in final}:
            final.append(tag)
        if len(final) >= 5:
            break
    return final


def trim_to(text, max_chars):
    text = clean(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.;:!?-")
    return cut + "…"


def generate_content(news):
    news_json = json.dumps([
        {
            "source": item["source"],
            "title": item["title"],
            "published_utc": item["published"].isoformat(),
            "summary": item["summary"],
            "url": item["url"],
        }
        for item in news[:12]
    ], ensure_ascii=False)

    common_rules = """
You are the senior editorial writer for a premium Binance Square account.
Use only facts supported by the candidate material supplied to you.
Do not invent facts, quotes, statistics, prices, dates or regulations.
Do not turn rumors into confirmed facts.
No financial advice, no buy/sell instructions, no guaranteed returns and no price predictions.
Keep the language natural and professional for crypto readers.
"""

    if MODE == "news":
        prompt = f"""
{common_rules}
Current Pakistan time: {NOW_PK.isoformat()}

Fresh candidate news:
{news_json}

Select the strongest timely story.
Write 700-1000 characters for the post, with a hook, what happened, why it matters,
and what readers should watch next.
Use a coin only when the story is truly coin-specific; otherwise use market_type=theme.
Also create a concise visual_subject describing what a professional crypto editorial image should show.
Return ONLY valid JSON:
{{
  "headline": "strong 1-2 line headline",
  "subheadline": "one concise context sentence",
  "post": "700-1000 character post",
  "market_type": "coin or theme",
  "coin": "BTC or empty",
  "pair": "BTC/USDT or empty",
  "category": "Regulation / Bitcoin / DeFi / Security / Macro / etc",
  "sentiment": "positive / negative / neutral",
  "key_fact": "one concise takeaway",
  "visual_subject": "one concise realistic visual description",
  "hashtags": ["#Bitcoin", "#BTC", "#CryptoNews"]
}}
"""
        raw, model = gemini(prompt, 1500)
        return parse_json(raw), model

    if MODE == "education":
        prompt = f"""
{common_rules}
Current Pakistan time: {NOW_PK.strftime('%d %B %Y')}

Create one premium educational Binance Square post about one useful crypto concept.
Teach clearly in 700-1000 characters using: hook -> explanation -> practical takeaway.
Use one relevant coin example when appropriate.
Also create a concise visual_subject for a realistic editorial education graphic.
Return ONLY valid JSON:
{{
  "headline": "strong educational headline",
  "subheadline": "context sentence",
  "post": "700-1000 character educational post",
  "market_type": "coin or theme",
  "coin": "BTC or empty",
  "pair": "BTC/USDT or empty",
  "category": "Crypto Education",
  "sentiment": "neutral",
  "key_fact": "one educational takeaway",
  "visual_subject": "one concise realistic visual description",
  "hashtags": ["#Bitcoin", "#CryptoEducation", "#Blockchain"]
}}
"""
        raw, model = gemini(prompt, 1500)
        return parse_json(raw), model

    prompt = f"""
{common_rules}
Current Pakistan time: {NOW_PK.isoformat()}

Candidate news:
{news_json}

Write one premium long-form Binance Square article based on the strongest current story.
Target 3000-5000 characters with:
1) Introduction
2) What happened
3) Why it matters
4) Market/industry context
5) What to watch next
6) Conclusion
Distinguish reports/proposals from confirmed facts.
Also create a concise visual_subject for a realistic editorial cover.
Return ONLY valid JSON:
{{
  "headline": "article title",
  "article": "3000-5000 character article",
  "market_type": "coin or theme",
  "coin": "BTC or empty",
  "pair": "BTC/USDT or empty",
  "category": "Market Analysis",
  "sentiment": "positive / negative / neutral",
  "key_fact": "one concise takeaway",
  "visual_subject": "one concise realistic visual description",
  "hashtags": ["#CryptoNews", "#Bitcoin", "#Blockchain"]
}}
"""
    raw, model = gemini(prompt, 3600)
    return parse_json(raw), model


def market_data(symbol):
    if not symbol:
        return {
            "available": False, "pair": "", "price": None,
            "change": None, "high": None, "low": None, "provider": "none",
        }

    symbol = symbol.upper().strip()
    coin_id = CG_IDS.get(symbol)
    if coin_id:
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?" + urllib.parse.urlencode({
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_high": "true",
                "include_24hr_low": "true",
            })
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 BinanceSquareV5"
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                row = json.load(response).get(coin_id, {})
            price = row.get("usd")
            if price is not None:
                return {
                    "available": True,
                    "pair": f"${symbol}/USDT",
                    "price": float(price),
                    "change": float(row.get("usd_24h_change")) if row.get("usd_24h_change") is not None else None,
                    "high": float(row.get("usd_24h_high")) if row.get("usd_24h_high") is not None else None,
                    "low": float(row.get("usd_24h_low")) if row.get("usd_24h_low") is not None else None,
                    "provider": "CoinGecko",
                }
        except Exception as exc:
            print("CoinGecko failed:", type(exc).__name__, exc)

    try:
        url = f"https://api.coinbase.com/v2/prices/{urllib.parse.quote(symbol)}-USD/spot"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BinanceSquareV5"})
        with urllib.request.urlopen(req, timeout=12) as response:
            row = json.load(response)
        return {
            "available": True,
            "pair": f"${symbol}/USDT",
            "price": float(row["data"]["amount"]),
            "change": None,
            "high": None,
            "low": None,
            "provider": "Coinbase",
        }
    except Exception as exc:
        print("Coinbase failed:", type(exc).__name__, exc)

    return {
        "available": False, "pair": f"${symbol}/USDT", "price": None,
        "change": None, "high": None, "low": None, "provider": "none",
    }


def commons_photo(query):
    try:
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": "10",
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "format": "json",
            "origin": "*",
        }
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 BinanceSquareV5"
        })
        with urllib.request.urlopen(req, timeout=18) as response:
            data = json.load(response)

        pages = data.get("query", {}).get("pages", {})
        candidates = []
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            mime = info.get("mime", "")
            meta = info.get("extmetadata", {})
            license_name = clean(meta.get("LicenseShortName", {}).get("value", "")).lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            if not ("cc by" in license_name or "public domain" in license_name):
                continue
            if not info.get("url"):
                continue
            candidates.append({
                "url": info["url"],
                "name": clean(page.get("title", "")).replace("File:", ""),
                "license": license_name or "free-license",
                "score": 0,
            })

        # Prefer filenames that look like editorial/crypto imagery.
        preferred = ("bitcoin", "cryptocurrency", "blockchain", "trading", "coin", "ethereum", "finance")
        for item in candidates:
            low = item["name"].lower()
            item["score"] = sum(4 for word in preferred if word in low)
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[0] if candidates else None
    except Exception as exc:
        print("Commons search failed:", type(exc).__name__, exc)
        return None


def download_image(background):
    if not background:
        return None
    try:
        req = urllib.request.Request(
            background["url"],
            headers={"User-Agent": "Mozilla/5.0 BinanceSquareV5"},
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        print("Background download failed:", type(exc).__name__, exc)
        return None


def theme_for(category, coin, sentiment):
    cat = str(category or "").lower()
    coin = str(coin or "").upper()
    if coin == "BTC" or "bitcoin" in cat:
        key = "bitcoin"
    elif coin == "ETH" or "ethereum" in cat:
        key = "ethereum"
    elif coin == "SOL" or "solana" in cat:
        key = "solana"
    elif any(word in cat for word in ("security", "hack", "exploit")):
        key = "security"
    elif any(word in cat for word in ("defi", "finance")):
        key = "defi"
    elif any(word in cat for word in ("regulation", "macro", "policy", "federal", "rate")):
        key = "macro"
    else:
        key = "default"

    theme = dict(THEMES[key])
    # Sentiment is a restrained accent modifier, not a complete recolor.
    if sentiment == "positive":
        theme["secondary"] = (70, 224, 150)
    elif sentiment == "negative":
        theme["secondary"] = (255, 82, 82)
    return key, theme


def find_font(candidates, size):
    search_roots = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation2",
        "/usr/share/fonts/truetype/lato",
        "/usr/share/fonts/truetype/noto",
    ]
    for name in candidates:
        for root in search_roots:
            path = os.path.join(root, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
    return ImageFont.load_default()


def fonts():
    return {
        "display": find_font([
            "DejaVuSansCondensed-Bold.ttf",
            "LiberationSans-Bold.ttf",
            "Lato-Bold.ttf",
        ], 76),
        "headline": find_font([
            "DejaVuSansCondensed-Bold.ttf",
            "LiberationSans-Bold.ttf",
            "Lato-Bold.ttf",
        ], 64),
        "body": find_font([
            "DejaVuSans.ttf",
            "LiberationSans-Regular.ttf",
            "Lato-Regular.ttf",
        ], 29),
        "body_bold": find_font([
            "DejaVuSansCondensed-Bold.ttf",
            "LiberationSans-Bold.ttf",
            "Lato-Bold.ttf",
        ], 33),
        "small": find_font([
            "DejaVuSans.ttf",
            "LiberationSans-Regular.ttf",
            "Lato-Regular.ttf",
        ], 21),
        "small_bold": find_font([
            "DejaVuSansCondensed-Bold.ttf",
            "LiberationSans-Bold.ttf",
            "Lato-Bold.ttf",
        ], 22),
    }


def font_at(base_candidates, size):
    return find_font(base_candidates, size)


def text_bbox(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def fit_text(draw, text, candidates, max_width, max_height, start_size, min_size, max_lines=3):
    text = clean(text)
    words = text.split()
    for size in range(start_size, min_size - 1, -2):
        font = font_at(candidates, size)
        lines = []
        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if text_bbox(draw, trial, font)[0] <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) <= max_lines:
            line_h = text_bbox(draw, "Ag", font)[1] + 10
            if line_h * len(lines) <= max_height:
                return font, lines, line_h
    font = font_at(candidates, min_size)
    return font, textwrap.wrap(text, width=max(10, int(max_width / max(1, min_size * 0.55))))[:max_lines], min_size + 10


def rounded_panel(base, box, fill, outline, radius=28, blur=18, alpha=225):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x1 + 8, y1 + 12, x2 + 8, y2 + 12), radius=radius, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)
    draw.rounded_rectangle(box, radius=radius, fill=(*fill, alpha), outline=(*outline, 195), width=2)
    draw.line((x1 + 18, y1 + 6, x2 - 18, y1 + 6), fill=(255, 255, 255, 32), width=1)
    base.alpha_composite(layer)


def gradient_background(size, theme):
    W, H = size
    img = Image.new("RGB", size, theme["bg"])
    px = img.load()
    bg = theme["bg"]
    p = theme["primary"]
    s = theme["secondary"]
    for y in range(H):
        for x in range(W):
            gx = x / max(1, W - 1)
            gy = y / max(1, H - 1)
            glow1 = max(0.0, 1.0 - math.hypot(x - 1510, y - 230) / 1400.0)
            glow2 = max(0.0, 1.0 - math.hypot(x - 360, y - 920) / 1200.0)
            vals = []
            for i in range(3):
                v = bg[i]
                v += (p[i] - bg[i]) * glow1 * 0.20
                v += (s[i] - bg[i]) * glow2 * 0.11
                v += 8 * gy + 4 * gx
                vals.append(int(max(0, min(255, v))))
            px[x, y] = tuple(vals)
    return img


def crop_cover(img, size):
    ratio = max(size[0] / img.width, size[1] / img.height)
    resized = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def color_grade_background(img, theme):
    # Enhancement #1: photo post-processing/color grade before typography.
    graded = img.filter(ImageFilter.GaussianBlur(0.45))
    graded = ImageEnhance.Contrast(graded).enhance(1.16)
    graded = ImageEnhance.Color(graded).enhance(1.30)
    graded = ImageEnhance.Brightness(graded).enhance(0.78)
    graded = ImageEnhance.Sharpness(graded).enhance(1.25)

    wash = Image.new("RGBA", graded.size, (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash)
    wd.rectangle((0, 0, graded.width, graded.height), fill=(*theme["bg"], 90))
    wd.ellipse((graded.width * 0.50, -graded.height * 0.20,
                graded.width * 1.15, graded.height * 0.55), fill=(*theme["primary"], 42))
    wd.ellipse((-graded.width * 0.15, graded.height * 0.55,
                graded.width * 0.55, graded.height * 1.15), fill=(*theme["secondary"], 28))
    return Image.alpha_composite(graded.convert("RGBA"), wash)


def add_vignette(img, strength=0.52):
    W, H = img.size
    vignette = Image.new("L", (W, H), 0)
    vp = vignette.load()
    cx, cy = W / 2, H / 2
    max_d = math.hypot(cx, cy)
    for y in range(H):
        for x in range(W):
            d = math.hypot(x - cx, y - cy) / max_d
            val = int(min(255, max(0, (d - 0.22) / 0.80 * 255 * strength)))
            vp[x, y] = val
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.putalpha(vignette)
    return Image.alpha_composite(img, overlay)


def draw_grid(draw, W, H, theme):
    # Subtle technical grid gives depth without pretending to be a real chart.
    grid = theme["grid"]
    for x in range(0, W, 80):
        draw.line((x, 150, x, H - 60), fill=(*grid, 70), width=1)
    for y in range(170, H - 60, 80):
        draw.line((0, y, W, y), fill=(*grid, 60), width=1)


def draw_market_motif(draw, box, theme, direction=1, seed=1):
    # Decorative/illustrative market motif; values are intentionally not labelled as live data.
    x1, y1, x2, y2 = box
    rng = random.Random(seed)
    points = []
    base_y = (y1 + y2) / 2
    span_y = max(20, (y2 - y1) * 0.33)
    for i in range(40):
        x = x1 + int((x2 - x1) * i / 39)
        wave = math.sin(i * 0.73 + rng.random() * 0.2) * span_y * 0.22
        drift = direction * span_y * 0.55 * i / 39
        jitter = rng.uniform(-span_y * 0.15, span_y * 0.15)
        y = int(base_y - wave - drift + jitter)
        points.append((x, y))
    line_color = (69, 224, 162) if direction >= 0 else (255, 84, 92)
    draw.line(points, fill=line_color, width=6)
    for i in range(7):
        px = x1 + int((x2 - x1) * (i + 1) / 8)
        py = y1 + 20 + int((y2 - y1 - 40) * rng.random())
        r = 5 + i % 3
        draw.ellipse((px - r, py - r, px + r, py + r), fill=(*theme["primary"], 170))


def draw_coin_icon(draw, center, coin, theme):
    cx, cy = center
    outer = 190
    for r in range(outer, 90, -4):
        t = (outer - r) / 100
        col = tuple(int(theme["primary"][i] * (0.50 + 0.50 * t)) for i in range(3))
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=col)
    draw.ellipse((cx-108, cy-108, cx+108, cy+108), outline=theme["highlight"], width=9)
    label = f"${coin}" if coin else "CRYPTO"
    bbox = draw.textbbox((0, 0), label, font=font_at(["DejaVuSansCondensed-Bold.ttf", "LiberationSans-Bold.ttf"], 68))
    f = font_at(["DejaVuSansCondensed-Bold.ttf", "LiberationSans-Bold.ttf"], 68)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw / 2, cy - th / 2 - 3), label, font=f, fill=(250, 250, 252))


def build_visual(data, market, news, background_img, model_used, background_meta=None):
    W, H = 1920, 1080
    sentiment = str(data.get("sentiment", "neutral")).lower()
    coin = str(data.get("coin", "")).upper().strip()
    category = clean(str(data.get("category", "Crypto")))
    theme_key, theme = theme_for(category, coin, sentiment)

    base = gradient_background((W, H), theme).convert("RGBA")

    if background_img:
        photo = crop_cover(background_img, (W, H))
        photo = color_grade_background(photo, theme)
        base.alpha_composite(photo)
    else:
        draw_grid(ImageDraw.Draw(base), W, H, theme)

    # Enhancement #1: unified post-processing stack.
    draw = ImageDraw.Draw(base)
    draw_grid(draw, W, H, theme)

    # Diagonal lighting streaks + circuit accents.
    for k in range(5):
        yy = 180 + k * 150
        draw.line((1140, yy, 1900, yy - 250), fill=(*theme["primary"], 22), width=4)
    for k in range(16):
        x = 1110 + k * 48
        y = 170 + (k % 5) * 105
        draw.ellipse((x, y, x + 8, y + 8), fill=(*theme["secondary"], 170))

    # Dark readability gradient.
    readability = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(readability)
    rd.rectangle((0, 0, W, H), fill=(0, 0, 0, 58))
    rd.rectangle((0, 130, 1030, 930), fill=(*theme["bg"], 212))
    rd.rectangle((0, 850, W, H), fill=(0, 0, 0, 140))
    base = Image.alpha_composite(base, readability)

    # Enhancement #3: dynamic glass/card palette.
    f = fonts()
    draw = ImageDraw.Draw(base)
    white = (248, 250, 254)
    muted = (184, 196, 214)

    # Brand bar.
    rounded_panel(base, (55, 40, 1865, 125), theme["panel"], theme["primary"], radius=24, blur=12, alpha=235)
    draw = ImageDraw.Draw(base)
    draw.ellipse((85, 66, 117, 98), fill=theme["primary"])
    draw.text((135, 55), "BINANCE SQUARE", font=f["small_bold"], fill=theme["highlight"])

    mode_label = {
        "news": "CRYPTO NEWS",
        "education": "CRYPTO EDUCATION",
        "article": "CRYPTO DEEP DIVE",
    }[MODE]
    draw.text((1505, 61), mode_label, font=f["small_bold"], fill=white)
    badge = "LIVE" if MODE == "news" else "LEARN" if MODE == "education" else "RESEARCH"
    bb = draw.textbbox((0, 0), badge, font=f["small_bold"])
    bw = bb[2] - bb[0] + 30
    draw.rounded_rectangle((1805 - bw, 55, 1805, 111), radius=18, fill=theme["primary"])
    draw.text((1820 - bw, 68), badge, font=f["small_bold"], fill=(6, 10, 16))

    # Enhancement #2: consistent text-template system.
    template_label = {
        "news": "BREAKING • MARKET INTELLIGENCE",
        "education": "LEARN • CRYPTO EDUCATION",
        "article": "RESEARCH • DEEP DIVE",
    }[MODE]
    label_w = draw.textbbox((0, 0), template_label, font=f["small_bold"])[2] + 48
    draw.rounded_rectangle((70, 165, 70 + label_w, 225), radius=18, fill=theme["primary"])
    draw.text((94, 182), template_label, font=f["small_bold"], fill=(7, 10, 17))

    headline = clean(str(data.get("headline", "Crypto Market Update")))
    headline_font, headline_lines, line_h = fit_text(
        draw,
        headline,
        ["DejaVuSansCondensed-Bold.ttf", "LiberationSans-Bold.ttf", "Lato-Bold.ttf"],
        max_width=965,
        max_height=290,
        start_size=68,
        min_size=44,
        max_lines=4,
    )
    y = 270
    for idx, line in enumerate(headline_lines):
        fill = white if idx < max(1, len(headline_lines) - 1) else theme["highlight"]
        draw.text((74, y), line, font=headline_font, fill=fill)
        y += line_h

    subheadline = clean(str(data.get("subheadline", "")))
    if not subheadline:
        subheadline = clean(str(data.get("key_fact", "Follow verified developments and primary sources.")))
    sub_font, sub_lines, sub_h = fit_text(
        draw,
        subheadline,
        ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Lato-Regular.ttf"],
        max_width=900,
        max_height=150,
        start_size=30,
        min_size=23,
        max_lines=3,
    )
    y += 12
    for line in sub_lines:
        draw.text((82, y), line, font=sub_font, fill=muted)
        y += sub_h

    # Right-side hero panel.
    rounded_panel(base, (1160, 160, 1845, 690), theme["panel"], theme["primary"], radius=34, blur=18, alpha=232)
    draw = ImageDraw.Draw(base)
    subject = clean(str(data.get("visual_subject", "premium cryptocurrency market scene")))
    subject_lines = textwrap.wrap(subject, width=31)[:3]
    draw.text((1210, 195), "EDITORIAL VISUAL", font=f["small_bold"], fill=theme["highlight"])
    sy = 230
    for line in subject_lines:
        draw.text((1210, sy), line, font=f["small"], fill=muted)
        sy += 29

    # Coin centerpiece + illustrative market motif.
    draw_coin_icon(draw, (1505, 380), coin or "CRYPTO", theme)
    direction = 1 if market.get("change") is None or market.get("change", 0) >= 0 else -1
    draw_market_motif(draw, (1225, 500, 1780, 625), theme, direction, seed=int(hashlib.sha256(headline.encode("utf-8")).hexdigest()[:8], 16))
    draw.text((1230, 635), "ILLUSTRATIVE MARKET MOTIF", font=f["small"], fill=(143, 156, 178))

    # Live market card.
    rounded_panel(base, (1160, 715, 1845, 865), theme["panel"], theme["secondary"], radius=24, blur=14, alpha=230)
    draw = ImageDraw.Draw(base)
    if market.get("available") and market.get("price") is not None:
        price = f"${market['price']:,.2f}"
        change = market.get("change")
        ch_text = f"{change:+.2f}% 24H" if change is not None else "SPOT PRICE"
        ch_col = (68, 224, 164) if change is None or change >= 0 else (255, 84, 92)
    else:
        price = "PRICE N/A"
        ch_text = "LIVE DATA UNAVAILABLE"
        ch_col = muted
    draw.text((1194, 745), "LIVE MARKET", font=f["small_bold"], fill=muted)
    draw.text((1194, 778), price, font=f["body_bold"], fill=white)
    draw.text((1570, 786), ch_text, font=f["small_bold"], fill=ch_col)

    # Lower information cards.
    key_fact = trim_to(str(data.get("key_fact", "Monitor verified developments.")), 82)
    cards = []
    if coin:
        cards.append((70, 470, "PAIR", f"${coin}/USDT", theme["primary"]))
    else:
        cards.append((70, 470, "FOCUS", trim_to(category, 26), theme["primary"]))
    cards.append((490, 890, "CATEGORY", trim_to(category, 28), theme["secondary"]))
    cards.append((910, 1375, "KEY FACT", key_fact, theme["primary"]))
    cards.append((1395, 1845, "SENTIMENT", sentiment.upper(), theme["secondary"]))

    card_y, card_h = 885, 122
    for x1, x2, label, value, col in cards:
        rounded_panel(base, (x1, card_y, x2, card_y + card_h), theme["panel"], col, radius=20, blur=10, alpha=235)
        draw = ImageDraw.Draw(base)
        draw.text((x1 + 20, card_y + 16), label, font=f["small"], fill=muted)
        value_font, value_lines, _ = fit_text(
            draw,
            str(value),
            ["DejaVuSansCondensed-Bold.ttf", "LiberationSans-Bold.ttf", "Lato-Bold.ttf"],
            x2 - x1 - 40,
            68,
            28,
            20,
            2,
        )
        vy = card_y + 46
        for line in value_lines:
            draw.text((x1 + 20, vy), line, font=value_font, fill=white)
            vy += 28

    # Hashtag strip - Binance-safe five maximum.
    tags = data.get("final_tags", [])
    draw.text((70, 1022), "TAGS", font=f["small_bold"], fill=theme["highlight"])
    tx = 150
    for tag in tags[:5]:
        width = draw.textbbox((0, 0), tag, font=f["small_bold"])[2] + 30
        if tx + width > 1685:
            break
        draw.rounded_rectangle((tx, 1016, tx + width, 1058), radius=14,
                               fill=(*theme["bg"], 225), outline=(*theme["secondary"], 190), width=2)
        draw.text((tx + 14, 1027), tag, font=f["small_bold"], fill=white)
        tx += width + 10

    source_names = []
    for item in news[:5]:
        if item["source"] not in source_names:
            source_names.append(item["source"])
    source_text = "Sources: " + " • ".join(source_names[:4]) if source_names else "Sources: Editorial / educational"
    draw.text((70, 1062), source_text[:150], font=f["small"], fill=(144, 158, 178))
    if background_meta:
        credit = f"Visual source: Wikimedia Commons • {background_meta.get('license', 'free-license')[:28]}"
    else:
        credit = "Visual source: deterministic graphic composition"
    cb = draw.textbbox((0, 0), credit, font=f["small"])
    draw.text((1845 - (cb[2] - cb[0]), 1062), credit[:110], font=f["small"], fill=(125, 141, 162))

    # Enhancement #1 continued: final finishing pass.
    base = add_vignette(base, strength=0.44)
    base = ImageEnhance.Contrast(base).enhance(1.04)
    base = ImageEnhance.Color(base).enhance(1.08)
    base = base.filter(ImageFilter.UnsharpMask(radius=1.15, percent=135, threshold=3))

    final = base.convert("RGB")
    final.save("square_visual.jpg", "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)
    final.save("article_cover.jpg", "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)

    with open("visual_theme.txt", "w", encoding="utf-8") as ftheme:
        ftheme.write(theme_key)

    print(f"Visual theme: {theme_key}")
    print("Visual size: 1920x1080")
    print("Gemini visual model/editor: ", model_used)
    return theme_key


def main():
    news = collect_news()
    print(f"Collected {len(news)} news candidates.")
    if not news and MODE in {"news", "article"}:
        print("Warning: no RSS candidates; Gemini will use a generic editorial prompt.")

    data, model_used = generate_content(news)
    if not isinstance(data, dict):
        raise SystemExit("Gemini JSON root must be an object.")

    market_type = str(data.get("market_type", "theme")).lower().strip()
    coin = str(data.get("coin", "")).upper().strip()
    if market_type == "coin":
        if not re.fullmatch(r"[A-Z0-9]{2,12}", coin):
            coin = infer_coin(clean(str(data.get("headline", "")) + " " + str(data.get("post", data.get("article", "")))))
        if not coin:
            coin = "BTC"
        pair = f"{coin}/USDT"
        must = [f"#{coin}"]
    else:
        coin = ""
        pair = ""
        must = []

    if MODE == "news":
        must.append("#CryptoNews")
    elif MODE == "education":
        must.append("#CryptoEducation")
    else:
        must.append("#CryptoAnalysis")

    tags = normalize_hashtags(data.get("hashtags", []), must)
    data["final_tags"] = tags
    data["coin"] = coin
    data["pair"] = pair

    if MODE == "article":
        body = clean(str(data.get("article", "")))
        if len(body) < 1800:
            raise SystemExit("Article body is too short.")
        footer = f"\n\n📊 Pair: ${pair}" if pair else f"\n\n🎯 Market Focus: {clean(str(data.get('category', 'Crypto')))}"
        footer += f"\n{' '.join(tags)}"
        content = trim_to(body, 5200) + footer
        title = trim_to(clean(str(data.get("headline", "Crypto Deep Dive"))), 130)
    else:
        body = clean(str(data.get("post", "")))
        if len(body) < 500:
            raise SystemExit("Generated post is too short.")
        footer = f"\n\n📊 Pair: ${pair}" if pair else f"\n\n🎯 Market Focus: {clean(str(data.get('category', 'Crypto')))}"
        footer += f"\n{' '.join(tags)}"
        content = trim_to(body, 1050) + footer
        title = ""

    market = market_data(coin)
    print("Market:", market)

    # Better background query: category -> coin -> visual subject -> generic crypto.
    search_terms = []
    if data.get("category"):
        search_terms.append(str(data["category"]))
    if coin:
        search_terms.append(f"{coin} cryptocurrency")
    if data.get("visual_subject"):
        search_terms.append(str(data["visual_subject"])[:120])
    search_terms.append("cryptocurrency blockchain finance")

    background = None
    bg_img = None
    for query in search_terms:
        background = commons_photo(query)
        if background:
            bg_img = download_image(background)
            if bg_img is not None:
                break
            background = None

    if background:
        print("Using Commons photo:", background["name"], background["license"])
    else:
        print("No suitable Commons photo found; using deterministic graphic background.")

    theme_key = build_visual(data, market, news, bg_img, model_used, background_meta=background)

    with open("content.txt", "w", encoding="utf-8") as f:
        f.write(content)
    with open("title.txt", "w", encoding="utf-8") as f:
        f.write(title)
    with open("mode.txt", "w", encoding="utf-8") as f:
        f.write(MODE)
    with open("model.txt", "w", encoding="utf-8") as f:
        f.write(model_used)
    with open("pair.txt", "w", encoding="utf-8") as f:
        f.write(f"${pair}" if pair else "")
    with open("visual_source.txt", "w", encoding="utf-8") as f:
        if background:
            f.write(f"Wikimedia Commons | {background['name']} | {background['license']}")
        else:
            f.write("Deterministic graphic composition")

    print("\n============================================")
    print("BINANCE SQUARE V5 READY")
    print("============================================")
    print("Mode:", MODE)
    print("Gemini:", model_used)
    print("Coin:", coin or "theme")
    print("Pair:", f"${pair}" if pair else "theme")
    print("Tags:", " ".join(tags))
    print("Content chars:", len(content))
    print("Visual:", "1920x1080")
    print("Theme:", theme_key)
    print("Background:", background["name"] if background else "deterministic")
    print("\n" + content)
    print("============================================")


if __name__ == "__main__":
    main()
