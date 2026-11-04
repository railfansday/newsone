import re
from pathlib import Path

# ⚠️ GANTI DENGAN URL YANG BENAR
BASE_URL_BENAR = "https://railfansday.github.io/newsone" 

def perbaiki():
    print(f"[*] Memindai file HTML di folder: {Path('.').resolve()}")
    file_html = list(Path('.').glob("*.html"))
    total_diperbaiki = 0
    
    for file_path in file_html:
        with open(file_path, "r", encoding="utf-8") as f:
            konten = f.read()

        if '<link rel="canonical"' in konten:
            pola = r'(<link rel="canonical" href=")[^"]+(">)'
            konten_baru = re.sub(pola, f'\\1{BASE_URL_BENAR}/{file_path.name}\\2', konten)
            
            if konten_baru != konten:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(konten_baru)
                total_diperbaiki += 1
                
    print(f"[SELESAI] Berhasil memperbaiki {total_diperbaiki} file HTML.")

if __name__ == "__main__":
    perbaiki()
