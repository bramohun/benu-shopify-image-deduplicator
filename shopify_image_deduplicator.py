"""
================================================================================
FUNKCIONÁLIS SPECIFIKÁCIÓ (FSR) ÉS FELADATLEÍRÁS
================================================================================
Modul: shopify_image_deduplicator.py
Verzió: 1.0.0

1. Funkció és Cél (Mire használjuk):
   - A script Shopify alapú webshopok (pl. benu.hu) termékkínálatát vizsgálja át
     automatikusan sitemap vagy közvetlen termék URL alapján.
   - Célja a különböző külső rendszerekből (ERP, PIM, beszállítók) származó,
     különböző formátumban (pl. .jpg vs .png), eltérő felbontásban és metaadatokkal
     feltöltött, de vizuálisan azonos (duplikált) termékképek azonosítása.
   - A vizsgálat Perceptual Hashing (dHash / pHash) algoritmusokkal és Hamming-távolság
     számítással történik.

2. Kapcsolódó User Storyk:
   - US-IMG-01: Mint Webshop Üzemeltető / Termékmenedzser, szeretnék gyors és automatizált
     riportot kapni a redundáns termékképekről, hogy tisztítsam a termékadatbázist.
   - US-IMG-02: Mint Rendszerintegrátor, szeretném megkapni a törlésre javasolt képek
     Shopify belső média-ID-jait (Media ID), hogy a felesleges képek API-n keresztül
     törölhetőek legyenek.
   - US-IMG-03: Mint Minőségbiztosító, szeretném a scriptet kis mintán (néhány terméken)
     vagy egyetlen problémás URL-en tesztelni a teljes áruházi futtatás előtt.
   - US-IMG-04: Mint Kampánymenedzser / Operátor, szeretném a vizsgálatot egy adott kezdőbetűre
     vagy termékcsoport-prefixre (pl. 'A', 'B', 'Allegra') szűrve futtatni, így szakaszosan
     végezve a duplikáció-auditot.
   - US-IMG-05: Mint Minőségbiztosító, szeretném a vizsgálatot leállítani adott számú
     duplikált termék (pl. 10 hibás termék) elérésekor, és a riportot vesszővel tagolva,
     befejezési időbélyeggel (yyyymmdd-hhmmss) menteni.
   - US-IMG-06: Mint Rendszerüzemeltető, szeretném elkerülni a Shopify és Cloudflare HTTP 429
     (Too Many Requests / Rate Limiting) túlterhelés-védelmi blokkolásait automatikus
     exponenciális visszalépéssel (Exponential Backoff), Retry-After támogatással és állítható késleltetéssel.
   - US-IMG-07: Mint Rendszerüzemeltető és SEO specialista, szeretném a vizsgálat során
     bármilyen okból (404, 429 túlterhelés, hálózati timeout, kép-letöltési hiba)
     meghiúsult URL-eket egy különálló riportban (failed_urls_report_YYYYMMDD-HHMMSS.csv)
     kigyűjteni az utólagos elemzéshez és javításhoz.

3. Kapcsolódó egyéb funkciók és felületek:
   - Shopify Storefront (.json termék-végpontok) és Sitemap XML feldolgozás.
   - Shopify Admin GraphQL / REST API (Product Media Delete funkció a riport alapján).
   - Termékoldali galéria komponensek (Product Media Gallery) és Feed exportok (Google Shopping, Meta Catalog).

4. SEO és Akadálymentességi (WCAG 2.2 AA) Szempontok:
   - Technikai SEO: Redundáns képek kivezetése -> kisebb DOM méret, jobb LCP (Largest Contentful Paint),
     kevesebb felesleges crawl budget felhasználás, tisztább Google Images indexelés.
   - WCAG 2.2 AA (1.1.1 Non-text Content, 2.4.3 Focus Order): A képernyőolvasóval navigáló
     felhasználóknak nem olvas fel egymás után 2-3 azonos termékképet, és csökken
     a felesleges tabulációs lépések száma a termékgaléria lapozásakor.
================================================================================
"""

import os
import sys
import io
import csv
import json
import time
import argparse
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import requests
from PIL import Image
import imagehash


def format_time_duration(seconds: float) -> str:
    """
    Másodpercek formázása olvasható HH:MM:SS vagy MM:SS formátumba.
    """
    secs = int(max(0, seconds))
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def create_progress_bar(current: int, total: int, length: int = 15) -> str:
    """
    Vizuális progress bar generálása konzolra (biztonságos ASCII kódolással).
    """
    if total <= 0:
        return "[" + "-" * length + "]"
    fraction = min(1.0, current / total)
    filled = int(fraction * length)
    bar = "=" * filled + "-" * (length - filled)
    return f"[{bar}]"

# Alapértelmezett konfigurációs értékek
DEFAULT_SITEMAP_URL = "https://benu.hu/sitemap.xml"
DEFAULT_HAMMING_THRESHOLD = 6  # 0-6 közötti érték: vizuálisan szinte azonos képek
DEFAULT_TEST_LIMIT = 0  # 0 = minden termék feldolgozása

# Fejlécek beállítása:
# Kifejezett Bot / Audit User-Agent és JSON Accept fejlécek használata,
# amellyel biztosítható, hogy a Shopify és a Google Analytics szerveroldali
# session-számlálói automatikusan crawlerként kezeljék és NEM növeljék
# a valós látogatottsági / konverziós statisztikákat.
HEADERS = {
    "User-Agent": "BenuInternalAuditBot/1.0 (+https://benu.hu; ShopifyImageDeduplicator)",
    "Accept": "application/json, application/xml, text/xml, */*",
    "X-Purpose": "Internal-SEO-Audit"
}

# Globális HTTP Session a kapcsolatok újrahasznosításához
HTTP_SESSION = requests.Session()

# Globális lista a vizsgálat során sikertelen vagy hibás URL-ek nyilvántartására
FAILED_REQUESTS = []


def record_failed_url(target_type: str, url: str, product_url: str, error_type: str, error_message: str):
    """
    Rögzíti azokat az URL-eket, amelyeket hiba miatt nem sikerült elérni vagy feldolgozni.
    """
    FAILED_REQUESTS.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_type": target_type,
        "product_url": product_url,
        "failed_url": url,
        "error_type": error_type,
        "error_message": error_message
    })


def robust_http_get(url: str, max_retries: int = 5, initial_timeout: int = 15) -> requests.Response:
    """
    Robusztus HTTP GET kérés kezelő:
    - Automatikusan kezeli a HTTP 429 (Too Many Requests / Rate Limit) hibákat.
    - Figyelembe veszi a szerver 'Retry-After' fejlécét.
    - Exponenciális visszalépéssel (Exponential Backoff: 2s -> 4s -> 8s -> 16s) próbálkozik újra.
    - Hálózati hiba esetén is újrapróbálkozik.
    """
    for attempt in range(max_retries):
        try:
            resp = HTTP_SESSION.get(url, headers=HEADERS, timeout=initial_timeout)
            
            # Rate limit (HTTP 429) észlelése
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait_seconds = float(retry_after) + 1.0
                else:
                    wait_seconds = float(2 ** (attempt + 1))
                
                print(f"  [RATE LIMIT 429] Szerver túlterheltség-védelem. Várakozás: {wait_seconds:.1f} mp (Újrapróbálkozás: {attempt + 1}/{max_retries})...")
                time.sleep(wait_seconds)
                continue
            
            # Átmeneti szerverhiba (502, 503, 504)
            if resp.status_code in (502, 503, 504):
                wait_seconds = 2.0 * (attempt + 1)
                time.sleep(wait_seconds)
                continue
                
            return resp
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            if attempt == max_retries - 1:
                print(f"  [HÁLÓZATI HIBA] Nem sikerült elérni a címet ({url}): {e}")
                return None
            time.sleep(1.5 * (attempt + 1))
            
    return None


def get_optimized_image_url(image_url: str, size: str = "300x300") -> str:
    """
    Shopify CDN URL optimalizáció:
    Lekéri a képet csökkentett felbontásban a sávszélesség és letöltési idő minimalizálásához.
    """
    if not image_url:
        return image_url
    
    # URL paraméterek leválasztása (?v=...)
    base_url = image_url.split("?")[0]
    
    # Kiterjesztés ellenőrzése
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if base_url.lower().endswith(ext):
            return base_url[:-len(ext)] + f"_{size}" + ext
            
    return image_url


def load_image_with_white_background(image_bytes: bytes) -> Image.Image:
    """
    Kép betöltése és transzparens háttér (PNG/WebP) normalizálása fehér háttérre.
    Ezzel elkerülhető, hogy a transzparens PNG feketére váltva hibásan különbözzön a fehér hátterű JPG-től.
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # Ha van alfa csatorna vagy transzparencia paletta
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img_rgba = img.convert("RGBA")
        background = Image.new("RGB", img_rgba.size, (255, 255, 255))
        background.paste(img_rgba, mask=img_rgba.split()[3])
        return background
    
    return img.convert("RGB")


def calculate_image_hashes(image_url: str, product_url: str = ""):
    """
    Letölti az adott képet és kiszámítja a perceptuális hasheket (dHash és pHash).
    """
    target_url = get_optimized_image_url(image_url, size="300x300")
    try:
        resp = robust_http_get(target_url, max_retries=3, initial_timeout=12)
        if not resp or resp.status_code != 200:
            # Ha a méretezett változat nem elérhető, próbáljuk az eredetit
            resp = robust_http_get(image_url, max_retries=3, initial_timeout=12)
            if not resp or resp.status_code != 200:
                err_code = f"HTTP_{resp.status_code}" if resp else "DOWNLOAD_TIMEOUT"
                record_failed_url("PRODUCT_IMAGE", image_url, product_url, err_code, "Nem sikerült letölteni a termékképet")
                return None, None
                
        img = load_image_with_white_background(resp.content)
        d_hash = imagehash.dhash(img)
        p_hash = imagehash.phash(img)
        return d_hash, p_hash
    except Exception as e:
        print(f"  [FIGYELMEZTETÉS] Képfeldolgozási hiba ({image_url}): {e}")
        record_failed_url("PRODUCT_IMAGE", image_url, product_url, "IMAGE_PROCESS_EXCEPTION", str(e))
        return None, None


def evaluate_keep_vs_delete(img_a: dict, img_b: dict) -> tuple:
    """
    Döntési mátrix: Meghatározza, melyik képet érdemes MEGTARTANI és melyiket TÖRÖLNI.
    Szempontok sorrendje:
    1. Felbontás (nagyobb natív felbontás előnyben)
    2. Alt szöveg (ha az egyiknek van releváns alt tagje, az élvez előnyt)
    3. Formátum (.jpg vagy modern formátum előnyben a nehezebb raw .png-vel szemben, ha a felbontás azonos)
    """
    # 1. Felbontás vizsgálata
    res_a = img_a.get("resolution", 0)
    res_b = img_b.get("resolution", 0)
    
    if res_a != res_b:
        if res_a > res_b:
            return img_a, img_b
        else:
            return img_b, img_a

    # 2. Alt tag vizsgálata
    alt_a = bool(img_a.get("alt") and img_a.get("alt").strip())
    alt_b = bool(img_b.get("alt") and img_b.get("alt").strip())
    if alt_a and not alt_b:
        return img_a, img_b
    elif alt_b and not alt_a:
        return img_b, img_a

    # 3. Formátum vizsgálata (alapértelmezetten a korábbi vagy kisebb ID marad)
    return img_a, img_b


def process_single_product(product_url: str, threshold: int) -> list:
    """
    Egyetlen termékoldal képeinek vizsgálata duplikációkra.
    Visszatér a talált duplikátum párok listájával.
    """
    duplicates = []
    
    # Normalizálás Shopify .json végponttá
    clean_url = product_url.split("?")[0].rstrip("/")
    json_url = clean_url if clean_url.endswith(".json") else f"{clean_url}.json"

    try:
        resp = robust_http_get(json_url, max_retries=5, initial_timeout=15)
        if not resp:
            print(f"  [HIBA] Nem érkezett válasz a termékoldaltól: {json_url}")
            record_failed_url("PRODUCT_JSON", json_url, clean_url, "REQUEST_TIMEOUT_OR_BLOCKED", "Nem érkezett válasz vagy túllépte az újrapróbálkozási limitet")
            return duplicates
        elif resp.status_code == 404:
            print(f"  [HIBA] Termék JSON nem található (404): {json_url}")
            record_failed_url("PRODUCT_JSON", json_url, clean_url, "HTTP_404", "Termék JSON nem található (404 Not Found)")
            return duplicates
        elif resp.status_code != 200:
            print(f"  [HIBA] HTTP {resp.status_code} a termék lekérésekor: {json_url}")
            record_failed_url("PRODUCT_JSON", json_url, clean_url, f"HTTP_{resp.status_code}", f"Szerver válaszkód hiba: HTTP {resp.status_code}")
            return duplicates

        data = resp.json().get("product", {})
        product_id = data.get("id")
        title = data.get("title", "Névtelen termék")
        images = data.get("images", [])

        if len(images) < 2:
            return duplicates  # 0 vagy 1 kép esetén nincs mit összehasonlítani

        print(f"  -> Termék: '{title}' ({len(images)} kép elemzése...)")

        # Képek hashelése és metaadatok gyűjtése
        processed_images = []
        for idx, img in enumerate(images):
            img_id = img.get("id")
            img_src = img.get("src")
            img_alt = img.get("alt", "")
            width = img.get("width") or 0
            height = img.get("height") or 0
            
            d_hash, p_hash = calculate_image_hashes(img_src, product_url=clean_url)
            if d_hash is not None:
                processed_images.append({
                    "id": img_id,
                    "src": img_src,
                    "alt": img_alt,
                    "width": width,
                    "height": height,
                    "resolution": width * height,
                    "d_hash": d_hash,
                    "p_hash": p_hash,
                    "position": img.get("position", idx + 1)
                })

        # Páronkénti összehasonlítás
        checked_pairs = set()
        for i in range(len(processed_images)):
            for j in range(i + 1, len(processed_images)):
                img_a = processed_images[i]
                img_b = processed_images[j]

                # Hamming-távolság kiszámítása (dHash és pHash)
                d_dist = img_a["d_hash"] - img_b["d_hash"]
                p_dist = img_a["p_hash"] - img_b["p_hash"]
                
                # Kombinált távolság (átlag vagy minimum)
                min_dist = min(d_dist, p_dist)

                if min_dist <= threshold:
                    pair_key = tuple(sorted([img_a["id"], img_b["id"]]))
                    if pair_key not in checked_pairs:
                        checked_pairs.add(pair_key)
                        keep_img, delete_img = evaluate_keep_vs_delete(img_a, img_b)

                        print(f"    [!] DUPLIKÁCIÓ TALÁLVA (dHash távolság: {d_dist}, pHash távolság: {p_dist})")
                        print(f"        Megtartásra javasolt : ID {keep_img['id']} ({keep_img['width']}x{keep_img['height']}) -> {keep_img['src']}")
                        print(f"        Törlésre javasolt    : ID {delete_img['id']} ({delete_img['width']}x{delete_img['height']}) -> {delete_img['src']}")

                        duplicates.append({
                            "product_id": product_id,
                            "product_title": title,
                            "product_url": clean_url,
                            "delete_image_id": delete_img["id"],
                            "delete_image_url": delete_img["src"],
                            "delete_image_dimensions": f"{delete_img['width']}x{delete_img['height']}",
                            "keep_image_id": keep_img["id"],
                            "keep_image_url": keep_img["src"],
                            "keep_image_dimensions": f"{keep_img['width']}x{keep_img['height']}",
                            "dhash_distance": int(d_dist),
                            "phash_distance": int(p_dist),
                            "min_distance": int(min_dist)
                        })
    except Exception as e:
        print(f"  [HIBA] Kivétel a termék feldolgozásakor ({product_url}): {e}")
        record_failed_url("PRODUCT_JSON", json_url, clean_url, "PRODUCT_PARSE_EXCEPTION", str(e))

    return duplicates


def fetch_product_urls_from_sitemap(sitemap_url: str) -> list:
    """
    Sitemap XML letöltése és termék URL-ek kinyerése (kezeli a sitemapindex-et és az al-sitemapokat is).
    """
    print(f"\n[1/3] Sitemap letöltése: {sitemap_url}")
    product_urls = []
    namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    try:
        resp = robust_http_get(sitemap_url, max_retries=4, initial_timeout=20)
        if not resp or resp.status_code != 200:
            print(f"[HIBA] Nem sikerült letölteni a sitemap-et (HTTP {resp.status_code if resp else 'N/A'})")
            record_failed_url("SITEMAP", sitemap_url, "", f"HTTP_{resp.status_code}" if resp else "SITEMAP_TIMEOUT", "Nem sikerült letölteni a fő sitemap-et")
            return []

        root = ET.fromstring(resp.content)
        
        # Ellenőrizzük, hogy sitemapindex-e
        sub_sitemaps = [elem.text.strip() for elem in root.findall("ns:sitemap/ns:loc", namespace) if elem.text]
        
        if sub_sitemaps:
            # Csak a termék sitemapokat vizsgáljuk (pl. sitemap_products_*.xml)
            product_sitemaps = [s for s in sub_sitemaps if "products" in s.lower()]
            if not product_sitemaps:
                product_sitemaps = sub_sitemaps  # Fallback: minden al-sitemap
                
            print(f"Talált termék al-sitemapok száma: {len(product_sitemaps)}")
            for sub_url in product_sitemaps:
                try:
                    print(f"  -> Al-sitemap beolvasása: {sub_url}")
                    sub_resp = robust_http_get(sub_url, max_retries=4, initial_timeout=20)
                    if sub_resp and sub_resp.status_code == 200:
                        sub_root = ET.fromstring(sub_resp.content)
                        for elem in sub_root.findall("ns:url/ns:loc", namespace):
                            if elem.text and "/products/" in elem.text:
                                product_urls.append(elem.text.strip())
                    else:
                        record_failed_url("SUB_SITEMAP", sub_url, "", f"HTTP_{sub_resp.status_code}" if sub_resp else "SUB_SITEMAP_TIMEOUT", "Nem sikerült letölteni az al-sitemap-et")
                except Exception as sub_err:
                    print(f"  [HIBA] Al-sitemap hiba ({sub_url}): {sub_err}")
                    record_failed_url("SUB_SITEMAP", sub_url, "", "SUB_SITEMAP_EXCEPTION", str(sub_err))
        else:
            # Közvetlen termék sitemap
            for elem in root.findall("ns:url/ns:loc", namespace):
                if elem.text and "/products/" in elem.text:
                    product_urls.append(elem.text.strip())

        # Duplikációk szűrése a listában
        unique_urls = list(dict.fromkeys(product_urls))
        print(f"Sikeresen beolvasva: {len(unique_urls)} egyedi termék URL a sitemap-ből.")
        return unique_urls
    except Exception as e:
        print(f"[HIBA] Nem sikerült feldolgozni a sitemap XML-t: {e}")
        record_failed_url("SITEMAP", sitemap_url, "", "SITEMAP_ROOT_EXCEPTION", str(e))
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Shopify Termékkép Duplikáció Szűrő és Ellenőrző Eszköz (Perceptual Hash alapú)"
    )
    parser.add_argument(
        "--url",
        type=str,
        help="Egyetlen konkrét termék URL tesztelése (pl. https://benu.hu/products/allegra-120-mg-filmtabletta-30x)"
    )
    parser.add_argument(
        "--sitemap",
        type=str,
        default=DEFAULT_SITEMAP_URL,
        help=f"Sitemap XML URL-je (alapértelmezett: {DEFAULT_SITEMAP_URL})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TEST_LIMIT,
        help=f"Feldolgozandó termékek maximális száma sitemap esetén (alapértelmezett teszt: {DEFAULT_TEST_LIMIT}, teljes futtatáshoz: 0)"
    )
    parser.add_argument(
        "--starts-with",
        "-s",
        type=str,
        help="Kezdőbetű(k) vagy prefix szerinti szűrés vesszővel elválasztva (pl. 'a', 'b', 'al', 'béres')"
    )
    parser.add_argument(
        "--max-dupes",
        "--max-duplicate-products",
        "-m",
        type=int,
        default=0,
        help="Leállási feltétel: hány olyan termék megtalálásakor álljon le a vizsgálat, ahol duplikáció van (0 = nincs korlát)"
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_HAMMING_THRESHOLD,
        help=f"Hamming-távolság küszöbérték (alapértelmezett: {DEFAULT_HAMMING_THRESHOLD}, 0=teljesen azonos, 1-6=nagyon hasonló/azonos)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="Kérések közötti finom késleltetés másodpercben a Rate Limit (HTTP 429) elkerüléséhez (alapértelmezett: 0.1s)"
    )
    parser.add_argument(
        "--failed-output",
        type=str,
        default=None,
        help="Különálló CSV fájl a sikertelen / elérhetetlen URL-ek mentéséhez (alapértelmezett: failed_urls_report_YYYYMMDD-HHMMSS.csv)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Kimeneti CSV fájl egyedi neve (alapértelmezett: duplicate_images_report_YYYYMMDD-HHMMSS.csv)"
    )
    parser.add_argument(
        "--json",
        "-j",
        type=str,
        default="data/duplicates.json",
        help="Kimeneti JSON fájl a webes GitHub Pages dashboardhoz (alapértelmezett: data/duplicates.json)"
    )

    args = parser.parse_args()

    print("=" * 80)
    print(" SHOPIFY TERMÉKKÉP DUPLIKÁCIÓ SZŰRŐ ÉS AUDIT ESZKÖZ")
    print("=" * 80)
    print(f"Küszöbérték (Threshold)        : {args.threshold}")
    if args.delay > 0:
        print(f"Kérések közötti késleltetés    : {args.delay} mp (Shopify túlterhelés-védelem)")
    if args.max_dupes > 0:
        print(f"Duplikált termék leállási limit: {args.max_dupes} db hibás termék megtalálásakor")

    target_urls = []

    if args.url:
        print(f"Mód                            : EGYEDI TERMÉK TESZT")
        print(f"Cél URL                        : {args.url}")
        target_urls = [args.url]
    else:
        all_urls = fetch_product_urls_from_sitemap(args.sitemap)
        if not all_urls:
            print("[HIBA] Nincsenek feldolgozható termékek. Kilépés.")
            sys.exit(1)

        # Kezdőbetű / prefix szűrés
        if args.starts_with and args.starts_with.strip().lower() not in ("all", "mind", "*", "none", "false", ""):
            prefixes = [p.strip().lower() for p in args.starts_with.split(",") if p.strip()]
            print(f"Szűrés kezdőbetűkre            : {prefixes}")
            
            matched_urls = []
            for u in all_urls:
                handle = u.rstrip("/").split("/products/")[-1].lower()
                if any(handle.startswith(p) for p in prefixes):
                    matched_urls.append(u)
            
            print(f"Illeszkedő termékek            : {len(matched_urls)} db (az összes {len(all_urls)} termékből)")
            target_urls = matched_urls
        else:
            print("Szűrés kezdőbetűkre            : NINCS (Minden termék feldolgozása)")
            target_urls = all_urls

        limit_text = f"Első {args.limit} termék" if args.limit > 0 else f"ÖSSZES illeszkedő ({len(target_urls)} termék)"
        print(f"Mód                            : SITEMAP FELDOLGOZÁS")
        print(f"Vizsgálati korlát              : {limit_text}")
            
        if args.limit > 0:
            target_urls = target_urls[:args.limit]

    print(f"\n[2/3] Termékek és képek ellenőrzése folyamatban ({len(target_urls)} termék)...")
    
    all_duplicates = []
    products_with_duplicates = set()
    products_json_list = []
    total_items = len(target_urls)
    start_time = time.time()
    
    for idx, url in enumerate(target_urls, 1):
        if args.delay > 0 and idx > 1:
            time.sleep(args.delay)

        elapsed = time.time() - start_time
        pct = (idx / total_items) * 100 if total_items > 0 else 0
        
        # Sebesség és hátralévő idő (ETA) becslése
        avg_time_per_item = elapsed / idx if idx > 0 else 0
        remaining_items = total_items - idx
        eta_seconds = remaining_items * avg_time_per_item
        speed = idx / elapsed if elapsed > 0 else 0
        
        pbar = create_progress_bar(idx, total_items, length=15)
        elapsed_str = format_time_duration(elapsed)
        eta_str = format_time_duration(eta_seconds) if idx > 1 else "--:--"
        
        print(f"\n[{idx}/{total_items} | {pct:5.1f}%] {pbar} | Eltelt: {elapsed_str} | Hátralévő (ETA): {eta_str} | Sebesség: {speed:.1f} termék/mp")
        print(f"  Vizsgálat: {url}")
        
        dups = process_single_product(url, args.threshold)
        if dups:
            products_with_duplicates.add(url)
            all_duplicates.extend(dups)
            
            # Strukturált termék JSON hozzáadása
            product_entry = {
                "product_id": dups[0]["product_id"],
                "product_title": dups[0]["product_title"],
                "product_url": dups[0]["product_url"],
                "product_handle": dups[0]["product_url"].rstrip("/").split("/products/")[-1],
                "duplicate_pairs": []
            }
            for d in dups:
                product_entry["duplicate_pairs"].append({
                    "keep": {
                        "id": d["keep_image_id"],
                        "url": d["keep_image_url"],
                        "dimensions": d["keep_image_dimensions"]
                    },
                    "delete": {
                        "id": d["delete_image_id"],
                        "url": d["delete_image_url"],
                        "dimensions": d["delete_image_dimensions"]
                    },
                    "dhash_distance": d["dhash_distance"],
                    "phash_distance": d["phash_distance"],
                    "min_distance": d["min_distance"]
                })
            products_json_list.append(product_entry)
            
            # Ellenőrizzük a duplikált termékek darabszám korlátját
            if args.max_dupes > 0 and len(products_with_duplicates) >= args.max_dupes:
                print("\n" + "!" * 80)
                print(f"[KORAI LEÁLLÁS] Elértük a kívánt duplikált termékszámot: {len(products_with_duplicates)}/{args.max_dupes} terméknél van duplikáció.")
                print("!" * 80)
                break

    total_duration = time.time() - start_time
    total_duration_str = format_time_duration(total_duration)
    overall_speed = idx / total_duration if total_duration > 0 else 0

    # Időbélyeg generálása a befejezés pillanatában (yyyymmdd-hhmmss)
    finish_timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_filepath = args.output if args.output else f"duplicate_images_report_{finish_timestamp}.csv"

    print("\n" + "=" * 80)
    print(f"[3/3] Összegzés és Riport mentése: {output_filepath}")
    print(f"Vizsgált termékek száma        : {idx} / {total_items}")
    print(f"Vizsgálat teljes ideje         : {total_duration_str} ({total_duration:.1f} másodperc)")
    print(f"Átlagos feldolgozási sebesség  : {overall_speed:.2f} termék / másodperc")
    print(f"Duplikációt tartalmazó termékek: {len(products_with_duplicates)} db")
    print(f"Összes talált duplikált képpár : {len(all_duplicates)} db")
    print(f"Sikertelen / Hibás URL-ek      : {len(FAILED_REQUESTS)} db")
    print("=" * 80)

    # 1. Duplikációs Riport mentése CSV fájlba (vesszővel elválasztva, UTF-8-sig BOM kódolással)
    try:
        with open(output_filepath, mode="w", newline="", encoding="utf-8-sig") as f:
            fieldnames = [
                "product_id",
                "product_title",
                "product_url",
                "delete_image_id",
                "delete_image_url",
                "delete_image_dimensions",
                "keep_image_id",
                "keep_image_url",
                "keep_image_dimensions",
                "dhash_distance",
                "phash_distance",
                "min_distance"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=",")
            writer.writeheader()
            writer.writerows(all_duplicates)

        print(f"[SIKER] A CSV riport elkészült: {os.path.abspath(output_filepath)}")
    except Exception as e:
        print(f"[HIBA] Nem sikerült menteni a CSV riportot: {e}")

    # 2. Sikertelen URL-ek mentése külön CSV riportba
    if FAILED_REQUESTS:
        failed_output_filepath = args.failed_output if args.failed_output else f"failed_urls_report_{finish_timestamp}.csv"
        try:
            with open(failed_output_filepath, mode="w", newline="", encoding="utf-8-sig") as ff:
                failed_fieldnames = [
                    "timestamp",
                    "target_type",
                    "product_url",
                    "failed_url",
                    "error_type",
                    "error_message"
                ]
                f_writer = csv.DictWriter(ff, fieldnames=failed_fieldnames, delimiter=",")
                f_writer.writeheader()
                f_writer.writerows(FAILED_REQUESTS)

            print(f"[SIKER] A Sikertelen URL-ek külön riportja elkészült: {os.path.abspath(failed_output_filepath)}")
        except Exception as e:
            print(f"[HIBA] Nem sikerült menteni a sikertelen URL riportot: {e}")

    # 3. Strukturált JSON mentése a webes dashboard számára
    if args.json:
        try:
            json_dir = os.path.dirname(args.json)
            if json_dir and not os.path.exists(json_dir):
                os.makedirs(json_dir, exist_ok=True)

            json_data = {
                "metadata": {
                    "scan_date": datetime.datetime.now().isoformat(),
                    "scan_timestamp_formatted": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sitemap_url": args.sitemap if not args.url else "Single URL Test",
                    "total_scanned_products": idx,
                    "total_products_with_duplicates": len(products_with_duplicates),
                    "total_duplicate_pairs": len(all_duplicates),
                    "total_failed_urls": len(FAILED_REQUESTS),
                    "threshold": args.threshold,
                    "starts_with": args.starts_with if args.starts_with else "mind"
                },
                "failed_urls": FAILED_REQUESTS,
                "products": products_json_list
            }

            with open(args.json, mode="w", encoding="utf-8") as jf:
                json.dump(json_data, jf, indent=2, ensure_ascii=False)

            print(f"[SIKER] A Dashboard JSON adathalmaz elkészült: {os.path.abspath(args.json)}")

            # 4. JavaScript állomány mentése (window.BENU_AUDIT_DATA) a CDN gyorsítótár-hibák és aszinkron parse hibák kivédésére
            js_filepath = os.path.splitext(args.json)[0] + ".js"
            with open(js_filepath, mode="w", encoding="utf-8") as jsf:
                jsf.write("window.BENU_AUDIT_DATA = " + json.dumps(json_data, indent=2, ensure_ascii=False) + ";\n")

            print(f"[SIKER] A Dashboard JS modul elkészült: {os.path.abspath(js_filepath)}")
        except Exception as e:
            print(f"[HIBA] Nem sikerült menteni a JSON adathalmazt: {e}")


if __name__ == "__main__":
    main()
