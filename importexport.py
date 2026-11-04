import sqlite3
import feedparser
import requests
from bs4 import BeautifulSoup
import os
import re
import json
import html as html_mod
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# ==========================================================================
# KONFIGURASI PATH & URL (PORTABEL)
# ==========================================================================
BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = str(BASE_DIR / "database_5menit" / "database.sqlite")

# ⚠️ PASTIKAN NAMA FILE INI SESUAI DENGAN YANG ADA DI REPO ANDA
RSS_FILE = str(BASE_DIR / "rss_list.txt") 

# ✅ Simpan file HTML langsung di folder utama
OUTPUT_DIR = BASE_DIR 

# ⚠️ GANTI URL INI dengan URL GitHub Pages Anda
BASE_URL = "https://railfansday.github.io/berita1jam" 

ARTICLES_PER_PAGE = 20
SITE_NAME = "News Portal Indonesia"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

ADSTERRA_CODE = """
<div style="text-align:center; margin:20px 0;">
    <script type="text/javascript">
        atOptions = {'key' : 'f9e40eb3b3cd05f1038aac7b36b33ad2','format' : 'iframe','height' : 90,'width' : 728,'params' : {}};
    </script>
    <script type="text/javascript" src="https://upholdbrilliancerecast.com/f9e40eb3b3cd05f1038aac7b36b33ad2/invoke.js"></script>
</div>
"""

CATEGORIES = [
    "technology", "business", "sports", "entertainment", 
    "health", "science", "politics", "world", 
    "finance", "travel", "food", "automotive", 
    "education", "lifestyle", "other"
]

KEYWORDS = {
    "technology": ["teknologi", "tech", "ai", "artificial intelligence", "software", "digital", "internet", "komputer", "programming", "developer", "aplikasi", "sistem"],
    "business": ["bisnis", "business", "ekonomi", "finance", "saham", "investasi", "keuangan", "bank", "market", "funding", "ipo", "perusahaan"],
    "sports": ["olahraga", "sports", "sepakbola", "bola", "football", "soccer", "nba", "fifa", "liga", "pertandingan", "atlet", "motogp", "badminton"],
    "entertainment": ["hiburan", "entertainment", "film", "musik", "selebriti", "artis", "movie", "konser", "drama", "aktor"],
    "health": ["kesehatan", "health", "medis", "dokter", "rumah sakit", "obat", "penyakit", "virus", "vaksin"],
    "science": ["sains", "science", "penelitian", "nasa", "antariksa", "luar angkasa", "iklim", "lingkungan", "bumi"],
    "politics": ["politik", "politics", "pemerintah", "presiden", "menteri", "dpr", "pemilu", "partai"],
    "world": ["dunia", "world", "internasional", "global", "luar negeri"],
    "finance": ["keuangan", "finance", "uang", "kredit", "pinjaman", "pajak"],
    "travel": ["travel", "wisata", "liburan", "destinasi", "pariwisata", "hotel"],
    "food": ["makanan", "food", "kuliner", "resep", "restoran", "masakan"],
    "automotive": ["otomotif", "automotive", "mobil", "motor", "kendaraan", "mesin"],
    "education": ["pendidikan", "education", "sekolah", "kampus", "universitas", "belajar"],
    "lifestyle": ["gaya hidup", "lifestyle", "fashion", "kecantikan", "kesehatan mental"]
}

# ==========================================================================
# BAGIAN 1: FUNGSI IMPORT (SCRAPING)
# ==========================================================================
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artikel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE, judul TEXT, konten TEXT, gambar TEXT,
            kategori TEXT DEFAULT 'other', tanggal_publish TEXT, tanggal_update TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(artikel)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'gambar' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN gambar TEXT")
    if 'kategori' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN kategori TEXT DEFAULT 'other'")
    if 'tanggal_publish' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN tanggal_publish TEXT")
    if 'tanggal_update' not in columns:
        cursor.execute("ALTER TABLE artikel ADD COLUMN tanggal_update TEXT")
    conn.commit()
    conn.close()

def detect_kategori(text):
    lower = text.lower()
    for cat, kws in KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lower) for kw in kws):
            return cat
    return "other"

def extract_full_content(url):
    try:
        # ✅ PERBAIKAN 1: Timeout dipercepat jadi 3 detik
        response = requests.get(url, headers=HEADERS, timeout=3)
        if response.status_code != 200: return None, None, None
        soup = BeautifulSoup(response.text, 'html.parser')

        image_url = None
        og_image = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
        if og_image and og_image.get('content'): image_url = og_image['content']

        tanggal = None
        for meta_prop in ['article:published_time', 'article:modified_time', 'datePublished']:
            meta = soup.find('meta', property=meta_prop) or soup.find('meta', attrs={'name': meta_prop})
            if meta and meta.get('content'):
                tanggal = meta['content']
                break

        paragraphs = soup.find_all('p')
        full_text = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 40 and not any(x in text.lower() for x in ['cookie', 'privacy policy', 'subscribe', 'all rights reserved', 'terms of use']):
                full_text.append(f"<p>{text}</p>")

        return "\n".join(full_text) if full_text else None, image_url, tanggal
    except Exception:
        return None, None, None

def process_single_feed(feed_url):
    feed_url = feed_url.strip()
    if not feed_url or feed_url.startswith("#"): return 0, 0, 0

    baru = 0
    duplikat = 0
    dilewati_lama = 0

    try:
        feed = feedparser.parse(feed_url)
        conn = sqlite3.connect(DB_PATH, timeout=15)
        cursor = conn.cursor()
        
        # FILTER WAKTU 1 JAM (Sesuai nama folder berita1jam)
        batas_waktu = datetime.now() - timedelta(hours=1)

        # ✅ PERBAIKAN 2: Hanya ambil maksimal 5 artikel terbaru per RSS
        for entry in feed.entries[:5]:
            link = entry.get('link', '')
            judul = entry.get('title', 'Tanpa Judul')
            if not link: continue

            # Filter Waktu
            published_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
            if published_parsed:
                waktu_terbit = datetime(*published_parsed[:6])
                if waktu_terbit < batas_waktu:
                    dilewati_lama += 1
                    continue

            cursor.execute("SELECT id FROM artikel WHERE link = ?", (link,))
            if cursor.fetchone():
                duplikat += 1
                continue

            full_text_html, image_url, tanggal = extract_full_content(link)
            if not full_text_html:
                full_text_html = f"<p>{entry.get('summary', 'Konten tidak tersedia.')}</p>"

            if not tanggal:
                tanggal = datetime(*published_parsed[:6]).isoformat() if published_parsed else datetime.now().isoformat()

            tanggal_update = datetime.now().isoformat()
            kategori = detect_kategori(judul + " " + full_text_html)
            
            img_tag = f'<div style="text-align:center; margin-bottom:20px;"><img src="{image_url}" alt="{judul}" style="max-width:100%; height:auto; border-radius:8px;" loading="lazy"></div>' if image_url else ""
            
            konten_lengkap = f"""
            {img_tag}
            {ADSTERRA_CODE}
            <div class="article-body" style="font-size: 16px; line-height: 1.8; color: #333;">
                {full_text_html}
                <p style="margin-top: 25px;">
                    <a href="{link}" target="_blank" rel="nofollow noopener" style="color: #0d6efd; text-decoration: none; font-weight: bold;">
                        &rarr; Baca artikel asli
                    </a>
                </p>
            </div>
            {ADSTERRA_CODE}
            """

            try:
                cursor.execute(
                    "INSERT INTO artikel (link, judul, konten, gambar, kategori, tanggal_publish, tanggal_update) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (link, judul, konten_lengkap, image_url, kategori, tanggal, tanggal_update)
                )
                conn.commit()
                baru += 1
            except sqlite3.IntegrityError:
                duplikat += 1
            except Exception:
                pass
                
        conn.close()
    except Exception:
        pass
        
    return baru, duplikat, dilewati_lama

def jalankan_scraping():
    if not os.path.exists(RSS_FILE):
        print(f"[ERROR] File {RSS_FILE} tidak ditemukan!")
        return
    init_db()
    with open(RSS_FILE, "r", encoding="utf-8") as f:
        rss_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    print(f"[*] Memulai scraping (HANYA 1 JAM TERAKHIR) dari {len(rss_urls)} RSS...")
    total_baru, total_duplikat, total_lama = 0, 0, 0
    
    # ✅ PERBAIKAN 3: Kurangi worker jadi 5 agar stabil
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_single_feed, url): url for url in rss_urls}
        for future in as_completed(futures):
            b, d, l = future.result()
            total_baru += b
            total_duplikat += d
            total_lama += l

    print(f"[SELESAI SCRAPING] Baru: {total_baru} | Duplikat: {total_duplikat} | Dilewati (Lama): {total_lama}\n")


# ==========================================================================
# BAGIAN 2: FUNGSI EXPORT (GENERATE HTML)
# ==========================================================================
def esc(text):
    return html_mod.escape(str(text)) if text else ""

def format_date(date_str):
    if not date_str: return "-"
    try:
        return datetime.fromisoformat(str(date_str).replace('Z', '+00:00')).strftime('%b %d, %Y')
    except Exception:
        return str(date_str)[:10]

HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="index, follow, max-image-preview:large">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<style>
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f4f6f8;margin:0;padding:20px;color:#333;line-height:1.6}}
.container{{max-width:1000px;margin:0 auto}}
header{{background:#1e293b;color:#fff;padding:20px;border-radius:12px;margin-bottom:20px;text-align:center;box-shadow:0 4px 6px rgba(0,0,0,.1)}}
header h1{{margin:0;font-size:26px;letter-spacing:1px}}
nav{{background:#fff;padding:10px;border-radius:12px;margin-bottom:24px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center;box-shadow:0 2px 4px rgba(0,0,0,.05)}}
nav a{{padding:8px 16px;border-radius:8px;color:#475569;text-decoration:none;font-weight:600;transition:all .2s;font-size:14px}}
nav a:hover,nav a.active{{background:#2563eb;color:#fff}}
.article-card{{background:#fff;padding:24px;margin-bottom:24px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.06);border-left:4px solid #2563eb}}
.article-card h2{{margin:0 0 12px;font-size:22px;color:#1e293b}}
.article-meta{{font-size:13px;color:#64748b;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid #e2e8f0}}
.article-meta a{{color:#2563eb;text-decoration:none;font-weight:bold}}
.article-body{{font-size:16px;line-height:1.8;color:#334155}}
.article-body img{{max-width:100%;height:auto;border-radius:8px;margin:16px 0}}
.pagination{{text-align:center;margin:40px 0;display:flex;flex-wrap:wrap;justify-content:center;gap:8px}}
.pagination a{{display:inline-block;padding:10px 16px;border-radius:8px;text-decoration:none;color:#334155;font-weight:bold;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.05);transition:all .2s}}
.pagination a:hover{{background:#f1f5f9}}
.pagination a.active{{background:#2563eb;color:#fff}}
footer{{text-align:center;color:#64748b;font-size:14px;padding:30px 0;border-top:1px solid #e2e8f0;margin-top:20px}}
</style>
</head>
<body>
<div class="container">
<header><h1>{site}</h1></header>
{nav}
"""

HTML_FOOT = """<footer>&copy; {year} {site}. All rights reserved.</footer>
</div></body></html>"""

def render_nav(active_cat, available_categories):
    html = '<nav>'
    a_all = ' class="active"' if active_cat == "" else ''
    html += f'<a href="index.html"{a_all}>🏠 All News</a>'
    
    for cat in CATEGORIES:
        if cat in available_categories and cat != "other":
            a_cat = ' class="active"' if active_cat == cat else ''
            html += f'<a href="{cat}.html"{a_cat}>📰 {cat.title()}</a>'
            
    if "other" in available_categories:
        a_other = ' class="active"' if active_cat == "other" else ''
        html += f'<a href="other.html"{a_other}>📰 Other</a>'
        
    return html + '</nav>'

def render_card(row, filename="index.html"):
    title = row["judul"] if "judul" in row.keys() else "No Title"
    content = row["konten"] if "konten" in row.keys() else ""
    gambar = row["gambar"] if "gambar" in row.keys() else ""
    kategori = row["kategori"] if "kategori" in row.keys() else "other"
    link = row["link"] if "link" in row.keys() else "#"
    tanggal = row["tanggal_publish"] if "tanggal_publish" in row.keys() else ""
    aid = row["id"] if "id" in row.keys() else ""

    img = f'<img src="{esc(gambar)}" alt="{esc(title)}" loading="lazy">' if gambar else ""
    cat_label = kategori.title() if kategori else "Other"

    schema_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "image": [gambar] if gambar else [],
        "datePublished": tanggal or datetime.now().isoformat(),
        "dateModified": tanggal or datetime.now().isoformat(),
        "mainEntityOfPage": f"{BASE_URL}/{filename}#artikel-{aid}"
    }, ensure_ascii=False)

    return f"""
<article class="article-card" id="artikel-{aid}">
    <script type="application/ld+json">{schema_json}</script>
    <h2>{esc(title)}</h2>
    <div class="article-meta">
        📅 {format_date(tanggal)} &nbsp;|&nbsp; Category: <strong>{esc(cat_label)}</strong> &nbsp;|&nbsp; 
        <a href="{esc(link)}" target="_blank" rel="nofollow">Read Source &rarr;</a>
    </div>
    <div class="article-body">
        {img}
        {content or ""}
        {ADSTERRA_CODE}
    </div>
</article>"""

def render_page(title, desc, canonical, rows, active_cat, available_categories, page_nav="", filename="index.html"):
    cards = "".join(render_card(r, filename) for r in rows)
    head = HTML_HEAD.format(title=esc(title), desc=esc(desc), canonical=esc(canonical), site=esc(SITE_NAME), nav=render_nav(active_cat, available_categories))
    body = f'<h1 style="color:#1e293b;border-left:5px solid #2563eb;padding-left:15px;margin-bottom:30px;">{esc(title)}</h1>'
    body += cards + page_nav
    return head + body + HTML_FOOT.format(year=datetime.now().year, site=esc(SITE_NAME))

def jalankan_export():
    print("[*] Exporting HTML...")
    # Tidak perlu mkdir karena output langsung ke BASE_DIR

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT DISTINCT kategori FROM artikel WHERE kategori IS NOT NULL")
    available_categories = [row[0] for row in c.fetchall()]

    c.execute("SELECT * FROM artikel ORDER BY tanggal_publish DESC, id DESC")
    all_rows = c.fetchall()
    total = len(all_rows)
    print(f"   Total articles: {total}")

    if total > 0:
        pages = [all_rows[i:i+ARTICLES_PER_PAGE] for i in range(0, total, ARTICLES_PER_PAGE)]
        for i, page_rows in enumerate(pages, start=1):
            if i == 1:
                fn, canon, title = "index.html", f"{BASE_URL}/", f"{SITE_NAME} - Latest News"
            else:
                fn, canon, title = f"page{i}.html", f"{BASE_URL}/page{i}.html", f"{SITE_NAME} - Page {i}"

            nav = '<div class="pagination">'
            for j in range(1, len(pages)+1):
                href = "index.html" if j == 1 else f"page{j}.html"
                a = ' class="active"' if j == i else ''
                nav += f'<a href="{href}"{a}>{j}</a>'
            nav += '</div>'

            html = render_page(title, f"Page {i}", canon, page_rows, "", available_categories, nav, filename=fn)
            with open(os.path.join(OUTPUT_DIR, fn), "w", encoding="utf-8") as f:
                f.write(html)

    for cat in available_categories:
        c.execute("SELECT * FROM artikel WHERE kategori = ? ORDER BY tanggal_publish DESC LIMIT 100", (cat,))
        rows = c.fetchall()
        if not rows: continue
        
        html = render_page(f"{cat.title()} - {SITE_NAME}", f"Latest {cat} news", f"{BASE_URL}/{cat}.html", rows, cat, available_categories, filename=f"{cat}.html")
        with open(os.path.join(OUTPUT_DIR, f"{cat}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"   ✅ {cat}.html ({len(rows)} articles)")

    # SITEMAP & ROBOTS
    today = datetime.now().strftime('%Y-%m-%d')
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    pages_count = max(1, (total + ARTICLES_PER_PAGE - 1) // ARTICLES_PER_PAGE)
    for i in range(1, pages_count+1):
        url = f"{BASE_URL}/" if i == 1 else f"{BASE_URL}/page{i}.html"
        xml.append(f'<url><loc>{url}</loc><lastmod>{today}</lastmod><priority>1.0</priority></url>')
    for cat in available_categories:
        xml.append(f'<url><loc>{BASE_URL}/{cat}.html</loc><lastmod>{today}</lastmod><priority>0.9</priority></url>')
    xml.append('</urlset>')
    
    with open(os.path.join(OUTPUT_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(xml))
    with open(os.path.join(OUTPUT_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")
    print(f"   ✅ sitemap.xml & robots.txt")
    conn.close()

# ==========================================================================
# BAGIAN 3: JALANKAN SEMUANYA
# ==========================================================================
if __name__ == "__main__":
    print("=" * 55)
    print("MULAI PROSES IMPORT & EXPORT (FILTER 1 JAM)")
    print("=" * 55)
    
    # 1. Jalankan Scraping
    jalankan_scraping()
    
    # 2. Jalankan Export
    print("\n" + "=" * 55)
    print("MULAI EXPORT HTML")
    print("=" * 55)
    jalankan_export()
    
    print("\n[PROSES SELESAI]")
