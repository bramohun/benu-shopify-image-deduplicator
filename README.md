<!--
================================================================================
FUNKCIONÁLIS SPECIFIKÁCIÓ (FSR) ÉS RENDSZERDOKUMENTÁCIÓ
================================================================================
Projekt: Shopify Termékkép Duplikáció Szűrő és GitHub Pages Dashboard
Verzió: 1.0.0

1. Rendszerfunkció és Felhasználás:
   - A projekt célja a benu.hu (és egyéb Shopify webshopok) termékkatalógusának
     automatikus auditálása képi duplikációk szempontjából, valamint egy interaktív,
     bárki számára elérhető vizuális dashboard (GitHub Pages) biztosítása.

2. Kapcsolódó User Storyk:
   - US-SYS-01: Üzemeltetőként szeretném, ha a teljes audit folyamat a GitHub felhőjében
     (GitHub Actions) futna le és automatikusan publikálná a GitHub Pages-re az eredményt.
   - US-SYS-02: SEO csapatként szeretném csökkenteni a webshop képi redundanciáját,
     ezzel javítva a Core Web Vitals (LCP) mutatókat és a sávszélesség-felhasználást.
   - US-SYS-03: QA ellenőrként szeretném egymás mellett látni a megtartandó és törlendő képeket.

3. Szabványok és Megfelelőség:
   - Modern Technikai SEO: Felesleges képek kivezetése a DOM-ból és galéria JSON-LD-ből.
   - WCAG 2.2 Level AA: Képernyőolvasó fókuszrend és nem-szöveges tartalom tisztítása.
================================================================================
-->

# Shopify Termékkép Duplikáció Szűrő és Vizuális Dashboard

Automatizált minőségbiztosítási rendszer Shopify webáruházakhoz (pl. benu.hu), amely Perceptual Hashing (dHash + pHash) segítségével észleli a vizuálisan azonos, de eltérő felbontású vagy formátumú (`.jpg` vs `.png`) termékképeket, és ezeket egy interaktív **GitHub Pages Dashboardon** jeleníti meg.

---

## Fő Funkciók

1. **Intelligens képi összehasonlítás (Perceptual Hash):**
   - Transzparencia normalizálás: a PNG átlátszó hátterét fehér háttérre illeszti, így a fehér hátterű JPG és átlátszó PNG képek tökéletes egyezést ($d=0$) adnak.
   - CDN optimalizáció: a képeket $300\times300$-as méretben kéri le az elemzéshez a sávszélesség és idő spórolása céljából.
2. **Kezdőbetű és Prefix Szűrés:**
   - Szűrés egy vagy több kezdőbetűre (pl. `a`, `b`, `allegra`, `béres`).
3. **Duplikált termékszám alapú korai leállás (`--max-dupes`):**
   - Leállítás adott számú hibás termék megtalálásakor (pl. 10 duplikált termék után).
4. **Interaktív GitHub Pages Dashboard (`index.html`):**
   - Vizuális kártyák egymás melletti képpárokkal (Megtartandó vs Törlendő).
   - Kereső, kezdőbetű választó (A-Z), rendezési opciók.
   - CSV letöltés és Shopify GraphQL törlési mutáció egykattintásos másolása.
5. **Automatizált Felhő Futtatás (GitHub Actions):**
   - Heti időzített audit (Cron) és manuális indítás paraméterekkel.

---

## GitHub Pages és GitHub Actions Beállítása

1. Töltsd fel (push) ezt a mappát a GitHub repozitóriumodba:
   ```bash
   git add .
   git commit -m "Shopify image deduplicator & GitHub Pages dashboard"
   git push origin main
   ```
2. Nyisd meg a GitHub repozitóriumot a böngészőben, majd menj a **Settings -> Pages** menüpontra.
3. A **Build and deployment -> Source** beállításnál válaszd a **GitHub Actions** opciót.
4. Menj az **Actions** fülre:
   - Válaszd ki a **Shopify Termekkeptisztitas es Dashboard Frissites** munkafolyamatot.
   - Kattints a **Run workflow** gombra, add meg a kívánt kezdőbetűt vagy limitet, majd indítsd el.
   - A lefutás után az interaktív dashboard elérhetővé válik a megadott GitHub Pages linken!

---

## Helyi (Lokális) Használat Windows alatt

### A. Kényelmi indítás dupla kattintással:
Indítsd el a [`run_deduplicator.bat`](run_deduplicator.bat) fájlt, és válassz a menüből:
- **1:** Allegra 120 mg minta termék ellenőrzése
- **2:** Első 5 termék vizsgálata
- **3:** Első 20 termék vizsgálata
- **4:** Kezdőbetű(k) szűrése + leállás $N$ db hibás terméknél
- **5:** Egyedi termék URL vizsgálata
- **6:** Teljes sitemap futtatás

### B. Parancssorból:
```bash
# 'B' betűs termékek vizsgálata, leállás 10 duplikált termék megtalálásakor:
python shopify_image_deduplicator.py --starts-with "b" --max-dupes 10

# Adott kezdőbetűk (a, al, béres) vizsgálata:
python shopify_image_deduplicator.py --starts-with "a,al,beres" --limit 50

# Egyedi termék URL ellenőrzése:
python shopify_image_deduplicator.py --url "https://benu.hu/products/allegra-120-mg-filmtabletta-30x"
```

---

## Fájlstruktúra

- `shopify_image_deduplicator.py` — Fő kereső és hashelő script (CLI, CSV és JSON exporttal).
- `index.html` — GitHub Pages vizuális webes dashboard (WCAG 2.2 AA és SEO kompatibilis).
- `.github/workflows/deduplicate_audit.yml` — GitHub Actions CI/CD automatizáció.
- `run_deduplicator.bat` — Windows indítófájl.
- `requirements.txt` — Függőségek (`requests`, `Pillow`, `imagehash`).
- `data/duplicates.json` — Strukturált adathalmaz a webes felület számára.
