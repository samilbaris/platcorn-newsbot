# -*- coding: utf-8 -*-
"""
Platcorn NewsBot – tek dosya (anti-duplicate hardened)
- Sadece anahtar kelime eşleşen haberleri yollar (başlık + opsiyonel gövde araması).
- Eski haberleri atlar (MAX_AGE_HOURS).
- Tekrar göndermez: canonical URL + normalize_link + sqlite 'seen' + 'seen_link'
  + koşu içi set'ler + 72 saatlik başlık-parmakizi (recent_title).
- Başlık/özet Türkçeleştirme (GoogleTranslator) + özet (sumy LSA).
- HTML güvenliği (escape) + Telegram HTML parse_mode.
- healthchecks.io pingi Python’dan atar (/start, /fail, başarı).

Gereken paketler: feedparser requests deep-translator sumy newspaper3k nltk
"""

import os, re, time, sqlite3, html
from datetime import datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser, requests
from deep_translator import GoogleTranslator

# Özetleme & NLTK
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer
import nltk
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")

# Makale gövdesi
from newspaper import Article

# =======================
# KULLANICI AYARLARI
# =======================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()

INTERVAL_SECONDS     = 300         # 5 dk
MAX_ITEMS_PER_FEED   = 6
SUMMARY_SENTENCES    = 4
TRANSLATE_TITLES     = True
TRANSLATE_SUMMARIES  = True

STRICT_KEYWORDS   = True       # sadece filtreye uyanlar
SEARCH_IN_SUMMARY = False      # gövde araması (gürültü için kapalı)
MAX_AGE_HOURS     = 24

# --- tekrar/yenilik kontrolleri ---
FRESH_ONLY_MINUTES   = 15   # SADECE son 15 dk’da yayınlananlar
RECENT_TITLE_TTL_HRS = 72   # Aynı başlık-parmakizi 72 saat içinde tekrar gönderilmez

APP_DIR = os.path.join(os.path.expanduser("~"), ".newsbot")
DB_PATH = os.path.join(APP_DIR, "seen.db")

# =======================
# ANAHTAR KELİMELER
# =======================

GLOBAL_KEYWORDS = [
    "youtube","twitch","kick","tiktok","instagram","x.com","threads","rumble",
    "livestream","stream","streamer","creator","influencer","content creator",
    "broadcast","subscriber","followers","viewers","shorts","clip","ban","partner",
    "community","platform","streaming","upload","algorithm","monetization","feature",
    "viral","trend","controversy","backlash","criticism","tepki","tepki çekti","linç",
    "drama","reaksiyon","yayın yasağı","trend oldu","viral oldu",
    "mrbeast","ishowspeed","hasanabi","asmongold","xqc","kai cenat",
    "ludwig","ninja","pokimane","amouranth","valkyrae","shroud","drdisrespect",
    "ice poseidon","adin ross","nickmercs","summit1g","tfue","sykkuno","myth",
    "pewdiepie","dream","tommyinnit","markiplier","jacksepticeye","logan paul","ksi",
    "jake paul","moistcr1tikal","charli d’amelio","bella poarch",
    "reaction","drama","controversy","leak","clip","highlight","rage quit",
    "cancelled","apology","comeback","announcement","collab","partnership",
    "reveal","exclusive","interview","livestream fail","viral clip","top moment",
    "trending","memes","internet reaction","eleştirildi","skandal","tartışma",
    "gündem oldu","sosyal medya tepki","yayıncı kavgası","clash","fued","debate",
    "sponsorship","deal","brand","agency","marketing","ads","revenue",
    "creator economy","influencer marketing","merch","startup","partnership",
    "brand deal","promotion","sponsorluk","işbirliği","ajans","kampanya","kazan",
    "income","platform change","exclusive deal","collaboration","network",
    "marka anlaşması","kampanya","tanıtım videosu","sponsorlu içerik",
    "yayıncı","influencer","içerik üretici","dijital kültür","sosyal medya",
    "akım","banlandı","yasaklandı","abonelik","yayın kazancı","platform değişikliği",
    "komik video","reaksiyon","twitch draması","kick yayını","youtube videosu","sızdırıldı",
    "takipçi","izlenme","tıklanma","algoritma","yayın yasağı","tepki gördü","eleştirildi",
    "gündem oldu","linç yedi"
]

CORE_KEYWORDS = [
    "youtube","twitch","kick","tiktok","instagram","x","threads","rumble",
    "livestream","streamer","stream","mrbeast","ishowspeed","hasanabi","asmongold",
    "xqc","kai cenat","ludwig","ninja","pokimane","amouranth","valkyrae","shroud",
    "drdisrespect","pewdiepie","adin ross","nickmercs","tfue","sykkuno","markiplier",
]

PROPER_NOUNS = [
    "YouTube","Twitch","Kick","Rumble",
    "MrBeast","iShowSpeed","HasanAbi","Asmongold","xQc",
    "Kai Cenat","Ludwig","Ninja","Pokimane","Amouranth",
    "Valkyrae","Shroud","Dr Disrespect","Platcorn"
]

PUBLISHER_MAP = {
    "www.dexerto.com": "Dexerto",
    "www.theverge.com": "The Verge",
    "www.ign.com": "IGN",
    "www.vulture.com": "Vulture",
    "www.hollywoodreporter.com": "Hollywood Reporter",
    "www.variety.com": "Variety",
    "www.gamespot.com": "GameSpot",
    "www.pcgamer.com": "PC Gamer",
    "www.kotaku.com": "Kotaku",
    "www.gamerbraves.com": "Gamer Braves",
    "www.hypebeast.com": "Hypebeast",
    "www.onedio.com": "Onedio",
    "www.sportskeeda.com": "Sportskeeda",
    "www.complex.com": "Complex",
    "www.gamingbible.com": "GamingBible",
    "www.reddit.com": "Reddit / LivestreamFail",
}

CATEGORIES = {
    "🟢 Platcorn & Creator": {
        "feeds": [
            "https://www.dexerto.com/feed",
            "https://www.dexerto.com/streaming/feed",
            "https://www.dexerto.com/entertainment/feed",
            "https://www.dexerto.com/esports/feed",
            "https://www.theverge.com/creator-economy/rss/index.xml",
            "https://www.ign.com/rss",
            "https://www.kotaku.com/rss",
            "https://www.pcgamer.com/rss",
            "https://www.gamespot.com/feeds/news",
            "https://www.gamerbraves.com/feed/",
            "https://variety.com/feed/",
            "https://www.hollywoodreporter.com/feed/",
            "https://www.vulture.com/rss/all.xml",
            "https://screenrant.com/feed/",
            "https://www.hypebeast.com/feed",
            "https://www.tubefilter.com/feed/",
            "https://www.socialmediatoday.com/rss",
            "https://creatorhook.com/feed/",
            "https://passionfroot.me/blog/rss.xml",
            "https://www.reddit.com/r/LivestreamFail/new/.rss",
            "https://onedio.com/rss",
            "https://www.webtekno.com/rss",
            "https://shiftdelete.net/feed",
            "https://www.technopat.net/feed/",
            "https://www.log.com.tr/feed/",
            "https://www.donanimhaber.com/rss/tum/",
            "https://rss.app/feeds/x6S2Zp6JUwCH1v0z.xml",
            "https://rss.app/feeds/U6QgNNMArHLnllsz.xml",
            "https://rss.app/feeds/ouzFl9q7fiqQ8kWC.xml",
            "https://rss.app/feeds/XxJ66s4xwq9qU2FW.xml",
            "https://rss.app/feeds/KutuqpKql1oBN51M.xml",
            "https://rss.app/feeds/uT33Zn9imAtSHeFb.xml",
            "https://rss.app/feeds/RQSjNahESu5puTnP.xml",
            "https://rss.app/feeds/we2ENM1QjscyHS6V.xml",
        ],
        "keywords": GLOBAL_KEYWORDS,
    }
}

# =======================
# ARAÇLAR
# =======================

def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def ensure_app_dir():
    os.makedirs(APP_DIR, exist_ok=True)

def init_db():
    ensure_app_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            title TEXT,
            link TEXT,
            category TEXT,
            ts   INTEGER
        )
    """)
    # link tabanlı dedupe (kanonik veya normalize link)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_link (
            link TEXT PRIMARY KEY,
            ts   INTEGER
        )
    """)
    # 72 saatlik başlık parmakizi
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recent_title (
            pk  TEXT PRIMARY KEY,  -- pub::t_fp2
            ts  INTEGER
        )
    """)
    conn.commit()
    return conn

def escape_html(s: str) -> str:
    return html.escape(s or "", quote=False)

def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""

def publisher_of(url: str) -> str:
    host = host_of(url).lower()
    return PUBLISHER_MAP.get(host, host)

def normalize_link(url: str) -> str:
    if not url:
        return url
    try:
        p = urlparse(url.strip())
        scheme = "https" if p.scheme in ("http", "https") else p.scheme
        q = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
        return urlunparse((scheme, p.netloc.lower(), p.path, "", q, ""))  # fragment'i at
    except Exception:
        return url

def entry_unix_ts(e):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            try:
                return int(time.mktime(t))
            except Exception:
                pass
    return None

def is_too_old(e) -> bool:
    ts = entry_unix_ts(e)
    if not ts:
        return True
    return (time.time() - ts) > MAX_AGE_HOURS * 3600

def is_new_enough(e) -> bool:
    """Sadece son FRESH_ONLY_MINUTES dakikada yayınlananları kabul et."""
    ts = entry_unix_ts(e)
    if not ts:
        return False
    return (time.time() - ts) <= FRESH_ONLY_MINUTES * 60

# --- Makale çek: (text, canonical_link) ---
def fetch_article(url: str):
    try:
        art = Article(url)
        art.download(); art.parse()
        txt   = (art.text or "").strip()
        canon = (art.canonical_link or "").strip()
        return txt, canon
    except Exception:
        return "", ""

# --- Dedupe yardımcıları ---
def link_seen(conn, link: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen_link WHERE link=?", (link,))
    return cur.fetchone() is not None

def mark_link_seen(conn, link: str):
    if not link:
        return
    conn.execute("INSERT OR IGNORE INTO seen_link (link, ts) VALUES (?, strftime('%s','now'))", (link,))
    conn.commit()

def already_seen(conn, _id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen WHERE id=?", (_id,))
    return cur.fetchone() is not None

def mark_seen(conn, _id: str, title: str, link: str, category: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen (id,title,link,category,ts) VALUES (?,?,?,?, strftime('%s','now'))",
        (_id, title, link, category)
    )
    conn.commit()

# --- Başlık parmakizi (hafif ve agresif) ---
def title_fp(title: str) -> str:
    """Hafif fingerprint: harf/rakam dışını sil, trim."""
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9çğıöşü]+", " ", t)
    return t.strip()

def title_fp2(title: str) -> str:
    """
    Agresif fingerprint:
    - harf/rakam dışını boşluğa çevir
    - sayıları at
    - kısa kelimeleri (<=2) at
    - tekilleştir, alfabetik sırala
    """
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9çğıöşü]+", " ", t)
    toks = [w for w in t.split() if len(w) > 2 and not w.isdigit()]
    toks = sorted(set(toks))
    return " ".join(toks)

def recent_title_seen(conn, pub: str, t_fp2: str) -> bool:
    pk = f"{pub}::{t_fp2}"
    row = conn.execute("SELECT ts FROM recent_title WHERE pk=?", (pk,)).fetchone()
    if not row:
        return False
    last = int(row[0])
    return (time.time() - last) < RECENT_TITLE_TTL_HRS * 3600

def mark_recent_title(conn, pub: str, t_fp2: str):
    pk = f"{pub}::{t_fp2}"
    conn.execute(
        "INSERT OR REPLACE INTO recent_title (pk, ts) VALUES (?, strftime('%s','now'))",
        (pk,)
    )
    conn.commit()

# ----- Çeviri yardımcıları -----

def pretranslate_en(s: str) -> str:
    if not s: return s
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?B\b", r"\1 billion", s, flags=re.IGNORECASE)
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?M\b", r"\1 million", s, flags=re.IGNORECASE)
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?K\b", r"\1 thousand", s, flags=re.IGNORECASE)
    s = s.replace("’","'").replace("“","\"").replace("”","\"")
    return s

def postprocess_money_tr(s: str) -> str:
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*million\b", r"\1 milyon", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*billion\b", r"\1 milyar", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*thousand\b", r"\1 bin", s, flags=re.IGNORECASE)
    s = re.sub(r"\$\s*([0-9])", r"$\1", s)
    return s

TITLE_VERB_MAP = [
    (r"\bleaks?\b", "ifşa etti"),
    (r"\bclaims?\b", "iddia etti"),
    (r"\breveals?\b", "açıkladı"),
    (r"\bditching\b", "bırakmak"),
    (r"\bquits?\b", "bıraktı"),
    (r"\bwould make\b", "kazanacağını"),
    (r"\bslammed\b", "tepki çekti"),
    (r"\bshuts? down\b", "kapatıldı"),
]

def polish_title_tr(tr: str) -> str:
    if not tr: return tr
    t = tr
    for pat, rep in TITLE_VERB_MAP:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    if t and not t.endswith(('.', '!', '?')):
        t = t[0].upper() + t[1:]
    return t

def translate_en_to_tr(text: str, is_title=False) -> str:
    if not text: return text
    placeholders = {}
    safe = text
    for i, name in enumerate(sorted(PROPER_NOUNS, key=len, reverse=True)):
        key = f"__PN{i}__"
        placeholders[key] = name
        safe = re.sub(rf"\b{name}\b", key, safe, flags=re.IGNORECASE)
    safe = pretranslate_en(safe)
    try:
        tr = GoogleTranslator(source="en", target="tr").translate(safe)
    except Exception:
        tr = safe
    for key, name in placeholders.items():
        tr = tr.replace(key, name)
    tr = postprocess_money_tr(tr)
    if is_title:
        tr = polish_title_tr(tr)
    return tr

def summarize_en(text: str, n_sent: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text.split()) < 60:
        return text
    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LsaSummarizer()
        sents = summarizer(parser.document, n_sent)
        return " ".join(str(s) for s in sents)
    except Exception:
        return text

def bullets_tr(paragraph: str) -> str:
    if not paragraph: return paragraph
    sents = re.split(r"(?<=[.!?])\s+", paragraph)
    sents = [s.strip() for s in sents if s.strip()]
    if len(sents) <= 1:
        return paragraph
    sents = sents[:5]
    return "• " + "\n• ".join(sents)

def tg_send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram ENV eksik: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log(f"Telegram gönderim hatası: {e}")

# ----- Keyword yardımcıları -----

def text_matches_keywords_whole_words(text: str, keywords) -> bool:
    if not text or not keywords:
        return False
    t = text.lower()
    for kw in keywords:
        kw = kw.lower().strip()
        if not kw:
            continue
        pat = r"\b" + re.escape(kw) + r"\b"
        if re.search(pat, t, flags=re.IGNORECASE):
            return True
    return False

def entry_matches_keywords(title: str, body: str, kw_list) -> bool:
    t = (title or "")
    if not text_matches_keywords_whole_words(t, CORE_KEYWORDS):
        return False
    if kw_list:
        if text_matches_keywords_whole_words(t, kw_list):
            return True
        if SEARCH_IN_SUMMARY and text_matches_keywords_whole_words(body or "", kw_list):
            return True
        return False
    return True

def build_feed_catalog():
    catalog = {}
    for cat, spec in CATEGORIES.items():
        for f in spec.get("feeds", []):
            catalog[f] = cat
    return catalog

# -----------------------
# healthchecks.io ping
# -----------------------

def hc_url(suffix: str = "") -> str:
    base = (os.getenv("HEALTHCHECK_URL") or "").strip()
    if not base:
        return ""
    if suffix and not suffix.startswith("/"):
        suffix = "/" + suffix
    return base.rstrip("/") + suffix

def ping_healthcheck(suffix: str = ""):
    url = hc_url(suffix)
    if not url:
        return
    try:
        requests.get(url, timeout=10)
    except Exception as e:
        log(f"healthcheck ping başarısız ({suffix}): {e}")

# =======================
# ÇALIŞTIRMA
# =======================

def run_once():
    ping_healthcheck("start")

    conn = init_db()
    catalog = build_feed_catalog()
    sent_total = 0
    run_seen_links  = set()
    run_seen_titles = set()

    try:
        for feed_url, category in catalog.items():
            try:
                d = feedparser.parse(feed_url)
                entries = d.entries[:MAX_ITEMS_PER_FEED]
            except Exception as e:
                log(f"Feed hatası: {feed_url} -> {e}")
                continue

            cat_keywords = CATEGORIES.get(category, {}).get("keywords", [])

            for e in entries:
                raw_link = getattr(e, "link", "") or ""
                norm_link = normalize_link(raw_link)
                title = getattr(e, "title", "(başlıksız)")

                # 0) 15 dk tazelik kapısı
                if not is_new_enough(e):
                    continue

                # 1) Makale çek (kanonik + metin)
                base_text, canon = fetch_article(norm_link)
                canon_link = normalize_link(canon) if canon else ""
                primary_link = canon_link or norm_link

                # 2) Link dedupe (koşu içi ve DB)
                if primary_link in run_seen_links or norm_link in run_seen_links:
                    continue
                if link_seen(conn, primary_link) or link_seen(conn, norm_link):
                    continue

                # 3) Başlık parmakizi (koşu içi + 72 saatlik DB)
                pub  = publisher_of(primary_link)
                t_fp  = title_fp(title)
                t_fp2 = title_fp2(title)
                run_title_key = f"{pub}::{t_fp}"
                if run_title_key in run_seen_titles:
                    continue
                if recent_title_seen(conn, pub, t_fp2):
                    continue

                # 4) Yaş filtresi (güvence)
                if is_too_old(e):
                    continue

                # 5) Keyword filtresi
                plain_text = re.sub(r"<[^>]+>", " ", base_text or "")
                plain_text = re.sub(r"\s+", " ", plain_text).strip()
                if STRICT_KEYWORDS:
                    if not entry_matches_keywords(title, plain_text, GLOBAL_KEYWORDS):
                        if not entry_matches_keywords(title, plain_text, cat_keywords):
                            continue

                # 6) Deterministik ID
                ts = entry_unix_ts(e)
                _id = f"{primary_link}|{ts or ''}"
                if already_seen(conn, _id):
                    continue

                # 7) Özet + çeviri
                summary_en = summarize_en(plain_text, SUMMARY_SENTENCES)
                title_out  = translate_en_to_tr(title, is_title=True) if TRANSLATE_TITLES else title
                text_tr    = translate_en_to_tr(summary_en, is_title=False) if TRANSLATE_SUMMARIES else summary_en
                text_final = escape_html(bullets_tr(text_tr))
                title_out  = escape_html(title_out)

                msg = (
                    "🟢 Platcorn & Creator\n"
                    f"<b>{title_out}</b>\n"
                    f"Kaynak: {pub} ({host_of(primary_link)})\n\n"
                    f"{text_final}\n\n"
                    f"🔗 {primary_link}"
                )

                try:
                    tg_send(msg)
                    # Link & ID işaretleri
                    mark_seen(conn, _id, title, primary_link, category)
                    mark_link_seen(conn, primary_link)
                    mark_link_seen(conn, norm_link)
                    # Başlık-parmakizi işaretle (72 saatlik)
                    mark_recent_title(conn, pub, t_fp2)
                    # Koşu içi işaretler
                    run_seen_links.add(primary_link)
                    run_seen_links.add(norm_link)
                    run_seen_titles.add(run_title_key)
                    sent_total += 1
                    time.sleep(0.8)
                except Exception as ex:
                    log(f"Gönderim hatası: {title} -> {ex}")

        log(f"Gönderilen yeni özet: {sent_total}")
        ping_healthcheck("")   # success
    except Exception as e:
        log(f"run_once beklenmeyen hata: {e}")
        ping_healthcheck("fail")

def main():
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        run_once()
        return
    if INTERVAL_SECONDS <= 0:
        run_once()
        return
    log(f"Başladı. Her {INTERVAL_SECONDS} sn’de bir kontrol edilecek.")
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
