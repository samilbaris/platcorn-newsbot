import os, re, time, sqlite3, sys
from datetime import datetime
from urllib.parse import urlparse

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
# AYARLAR
# =======================
TELEGRAM_BOT_TOKEN = "7766727211:AAHl8BnCzQey74LKZb4mw6bFqqR5jZYqw-U"
TELEGRAM_CHAT_ID   = "8513010757"

INTERVAL_SECONDS     = 300      # 5 dk’da bir kontrol
MAX_ITEMS_PER_FEED   = 5
SUMMARY_SENTENCES    = 4
TRANSLATE_TITLES     = True
TRANSLATE_SUMMARIES  = True

# 🌍 Tüm anahtar kelimeler (TR + EN)
GLOBAL_KEYWORDS = [
    # 🧩 Platformlar & Ekosistem
    "youtube","twitch","kick","tiktok","instagram","x.com","threads","rumble",
    "livestream","stream","streamer","creator","influencer","content creator",
    "broadcast","subscriber","followers","viewers","shorts","clip","ban","partner",
    "community","platform","streaming","upload","algorithm","monetization","feature",
    "viral","trend","controversy","backlash","criticism","tepki","tepki çekti","linç",
    "drama","reaksiyon","yayın yasağı","trend oldu","viral oldu",

    # 🌍 Ünlü yayıncılar & internet figürleri
    "mrbeast","ishowspeed","hasanabi","asmongold","xqc","kai cenat",
    "ludwig","ninja","pokimane","amouranth","valkyrae","shroud","drdisrespect",
    "ice poseidon","adin ross","nickmercs","summit1g","tfue","sykkuno",
    "myth","pewdiepie","dream","tommyinnit","markiplier","jacksepticeye",
    "logan paul","ksi","jake paul","moistcr1tikal","charli d’amelio","bella poarch",

    # 💬 Trendler & topluluk dinamikleri
    "reaction","drama","controversy","leak","clip","highlight","rage quit",
    "cancelled","apology","comeback","announcement","collab","partnership",
    "reveal","exclusive","interview","livestream fail","viral clip","top moment",
    "trending","memes","internet reaction","eleştirildi","skandal","tartışma",
    "gündem oldu","sosyal medya tepki","yayıncı kavgası","clash","fued","debate",

    # 💰 Creator economy & dijital iş dünyası
    "sponsorship","deal","brand","agency","marketing","ads","revenue",
    "creator economy","influencer marketing","merch","startup","partnership",
    "brand deal","promotion","sponsorluk","işbirliği","ajans","kampanya","kazan",
    "income","platform change","exclusive deal","collaboration","network",
    "marka anlaşması","kampanya","tanıtım videosu","sponsorlu içerik",

    # 🇹🇷 Türkçe karşılıklar & yerel dijital kültür
    "yayıncı","influencer","içerik üretici","dijital kültür","sosyal medya",
    "viral","akım","banlandı","yasaklandı","işbirliği","sponsor","ajans","anlaşma",
    "abonelik","yayın kazancı","platform değişikliği","trend oldu","komik video",
    "reaksiyon","twitch draması","kick yayını","youtube videosu","sızdırıldı",
    "takipçi","izlenme","tıklanma","algoritma","viral oldu","yayın yasağı",
    "tepki çekti","tepki gördü","eleştirildi","gündem oldu","linç yedi"
]

# 🔤 Çeviri sırasında dokunulmaması gereken özel isimler
PROPER_NOUNS = [
    "YouTube", "Twitch", "Kick", "Rumble",
    "MrBeast", "iShowSpeed", "HasanAbi", "Asmongold", "xQc",
    "Kai Cenat", "Ludwig", "Ninja", "Pokimane", "Amouranth",
    "Valkyrae", "Shroud", "Dr Disrespect", "Platcorn"
]

# 🌍 Kaynak isim eşlemesi (görünür isimler)
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


# 🗞️ Tek kategori: Platcorn & Creator dünyası
CATEGORIES = {
    "🟢 Platcorn & Creator": {
        "feeds": [
            # — İngilizce yayıncı/creator haberleri —
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

            # — Reddit (sadece haber tarzı içerik için) —
            "https://www.reddit.com/r/LivestreamFail/new/.rss",

            # — Türkçe teknoloji ve eğlence kaynakları —
            "https://onedio.com/rss",
            "https://www.webtekno.com/rss",
            "https://shiftdelete.net/feed",
            "https://www.technopat.net/feed/",
            "https://www.log.com.tr/feed/",
            "https://www.donanimhaber.com/rss/tum/",

            # — RSS.app üzerinden eklenen özel kaynaklar —
            "https://rss.app/feeds/we2ENM1QjscyHS6V.xml",  # Sportskeeda (streamer news)
            "https://rss.app/feeds/we2ENM1QjscyHS6V.xml"   # Complex (streamer tag)
        ],
        "keywords": GLOBAL_KEYWORDS
    }
}

APP_DIR = os.path.join(os.path.expanduser("~"), ".newsbot")
DB_PATH = os.path.join(APP_DIR, "seen.db")

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
    conn.commit()
    return conn

def host_of(url):
    try:
        return urlparse(url).netloc
    except:
        return ""

def publisher_of(url):
    host = host_of(url).lower()
    return PUBLISHER_MAP.get(host, host)

def pretranslate_en(s: str) -> str:
    # EN kısaltmaları genişlet (çeviri daha doğal olsun)
    if not s: return s
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?B\b", r"\1 billion", s, flags=re.IGNORECASE)
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?M\b", r"\1 million", s, flags=re.IGNORECASE)
    s = re.sub(r"\$?(\d+(\.\d+)?)\s?K\b", r"\1 thousand", s, flags=re.IGNORECASE)
    s = s.replace("’","'").replace("“","\"").replace("”","\"")
    return s

def postprocess_money_tr(s: str) -> str:
    # million/billion → milyon/milyar; thousand → bin
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*million\b", r"\1 milyon", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*billion\b", r"\1 milyar", s, flags=re.IGNORECASE)
    s = re.sub(r"\b([0-9]+(?:[.,][0-9]+)?)\s*thousand\b", r"\1 bin", s, flags=re.IGNORECASE)
    # $ işaretinin yeri
    s = re.sub(r"\$\s*([0-9])", r"$\1", s)
    s = s.replace(" $", " $")  # bırak
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

    # tipik kötü çevirileri düzelt / fiil eşleştirme
    for pat, rep in TITLE_VERB_MAP:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    # başı/bitişi temizle, fazla boşlukları at
    t = re.sub(r"\s+", " ", t).strip()

    # cümle başı büyük, kalan normal; özel isimler korunacak
    if t and not t.endswith(('.', '!', '?')):
        t = t[0].upper() + t[1:]

    return t

def translate_en_to_tr(text: str, is_title=False) -> str:
    if not text: return text

    # Özel isimleri yer tutucuya al
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

    # Yer tutucuları geri koy
    for key, name in placeholders.items():
        tr = tr.replace(key, name)

    tr = postprocess_money_tr(tr)

    if is_title:
        tr = polish_title_tr(tr)

    return tr

def fetch_article_text(url: str) -> str:
    try:
        art = Article(url)
        art.download(); art.parse()
        return (art.text or "").strip()
    except Exception:
        return ""

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
    """Uzun paragrafı 3-5 maddeye bölmeye çalış (TR çıktıyı daha okunur yapar)."""
    if not paragraph: return paragraph
    sents = re.split(r"(?<=[.!?])\s+", paragraph)
    sents = [s.strip() for s in sents if s.strip()]
    if len(sents) <= 1:
        return paragraph
    sents = sents[:5]
    return "• " + "\n• ".join(sents)

def tg_send(text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False
        }, timeout=30).raise_for_status()
    except Exception as e:
        log(f"Telegram gönderim hatası: {e}")

def norm_id(entry) -> str:
    return getattr(entry, "id", None) or getattr(entry, "link", None) or getattr(entry, "title", "")

def already_seen(conn, _id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen WHERE id=?", (_id,))
    return cur.fetchone() is not None

def mark_seen(conn, _id: str, title: str, link: str, category: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen (id,title,link,category,ts) VALUES (?,?,?,?, strftime('%s','now'))",
        (_id, title, link, category)
    )
    conn.commit()

def match_keywords(title: str, kw_list) -> bool:
    if not kw_list:
        return True
    t = (title or "").lower()
    return any(k.lower() in t for k in kw_list)

def build_feed_catalog():
    catalog = {}
    for cat, spec in CATEGORIES.items():
        for f in spec.get("feeds", []):
            catalog[f] = cat
    return catalog

def run_once():
    conn = init_db()
    catalog = build_feed_catalog()
    sent_total = 0

    for feed_url, category in catalog.items():
        try:
            d = feedparser.parse(feed_url)
            entries = d.entries[:MAX_ITEMS_PER_FEED]
        except Exception as e:
            log(f"Feed hatası: {feed_url} -> {e}")
            continue

        cat_keywords = CATEGORIES.get(category, {}).get("keywords", [])

        for e in entries:
            _id   = norm_id(e)
            title = getattr(e, "title", "(başlıksız)")
            link  = getattr(e, "link", "")

            if already_seen(conn, _id):
                continue

            if not (match_keywords(title, GLOBAL_KEYWORDS) or match_keywords(title, cat_keywords)):
                mark_seen(conn, _id, title, link, category)
                continue

            base_text   = fetch_article_text(link) or getattr(e, "summary", "") or getattr(e, "description", "")
            summary_en  = summarize_en(base_text, SUMMARY_SENTENCES)

            title_out   = translate_en_to_tr(title, is_title=True) if TRANSLATE_TITLES else title
            text_tr     = translate_en_to_tr(summary_en, is_title=False) if TRANSLATE_SUMMARIES else summary_en
            text_final  = bullets_tr(text_tr)

            pub = publisher_of(link)
            msg = f"{category}\n<b>{title_out}</b>\nKaynak: {pub} ({host_of(link)})\n\n{text_final}\n\n🔗 {link}"

            try:
                tg_send(msg)
                mark_seen(conn, _id, title, link, category)
                sent_total += 1
                time.sleep(0.8)
            except Exception as ex:
                log(f"Gönderim hatası: {title} -> {ex}")

    log(f"Gönderilen yeni özet: {sent_total}")

def main():
    if INTERVAL_SECONDS <= 0:
        run_once()
        return
    log(f"Başladı. Her {INTERVAL_SECONDS} sn’de bir kontrol edilecek.")
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
