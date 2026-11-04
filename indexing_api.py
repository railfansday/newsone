import os
import json
import time
import requests
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# ==========================================
# KONFIGURASI OTOMATIS
# ==========================================
# ✅ Mendeteksi otomatis nama repo GitHub Actions (misal: railfansday/berita1jam)
REPO_FULL_NAME = os.environ.get("GITHUB_REPOSITORY", "railfansday/berita1jam")
USERNAME = REPO_FULL_NAME.split("/")[0]
REPO_NAME = REPO_FULL_NAME.split("/")[1]

# ✅ Membuat URL sitemap secara otomatis
SITEMAP_URL = f"https://{USERNAME}.github.io/{REPO_NAME}/sitemap.xml"

SCOPES = ['https://www.googleapis.com/auth/indexing']
ENDPOINT = 'https://indexing.googleapis.com/v3/urlNotifications:publish'

def get_urls_from_sitemap(sitemap_url):
    print(f"[*] Mengambil URL dari sitemap: {sitemap_url}")
    try:
        response = requests.get(sitemap_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        urls = [loc.text for loc in soup.find_all('loc')]
        print(f"[*] Ditemukan {len(urls)} URL.")
        return urls
    except Exception as e:
        print(f"[!] Gagal mengambil sitemap: {e}")
        return []

def send_indexing_request(session, url):
    body = {"url": url, "type": "URL_UPDATED"}
    try:
        response = session.post(ENDPOINT, json=body)
        if response.status_code == 200:
            print(f"  [OK] Terkirim: {url}")
            return True
        elif response.status_code == 429:
            print(f"  [LIMIT] Kuota harian habis.")
            return False
        else:
            print(f"  [ERR] {url} -> Status: {response.status_code}")
            return True
    except Exception as e:
        print(f"  [ERR] {url} -> Exception: {e}")
        return True

def main():
    print("="*50)
    print("MEMULAI PENGIRIMAN URL KE GOOGLE INDEXING API")
    print("="*50)
    
    # ✅ MEMBACA DARI GITHUB SECRETS
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        print("[!] Error: Secret GOOGLE_CREDENTIALS tidak ditemukan.")
        return

    try:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
        session = AuthorizedSession(credentials)
        print("[*] Autentikasi berhasil.")
    except Exception as e:
        print(f"[!] Gagal autentikasi: {e}")
        return

    urls = get_urls_from_sitemap(SITEMAP_URL)
    if not urls:
        return

    print(f"\n[*] Memulai pengiriman (Batas aman: 190 URL/hari)...")
    count = 0
    for url in urls:
        if count >= 190:
            print("\n[!] Mencapai batas aman pengiriman harian.")
            break
        if send_indexing_request(session, url):
            count += 1
            time.sleep(1) 
        else:
            break

    print(f"\n[SELESAI] Berhasil mengirim {count} URL.")

if __name__ == "__main__":
    main()
