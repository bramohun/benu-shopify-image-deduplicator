@echo off
REM ================================================================================
REM FUNKCIONALIS SPECIFIKACIO (FSR) ES FELADATLEIRAS
REM ================================================================================
REM Fajl: run_deduplicator.bat
REM 
REM Mire hasznaljuk:
REM   - Windows inditofajl a shopify_image_deduplicator.py kornyezetenek
REM     ellenorzesehez (Python, fuggosegek) es az interaktiv futtatasi modok
REM     (teszt futtatas kis mintan, kezdobetu szures, N db duplikalt termeknel
REM     valo korai leallas, egyedi URL, teljes futtas) kenyelmes inditasara.
REM 
REM Kapcsolodo User Storyk:
REM   - US-IMG-03: Minosegbiztosito kent es operatorkent egyetlen kattintassal
REM     szeretnem elinditani a kepi duplikacio ellenorzest teszt modban.
REM   - US-IMG-04: Kampanymenadzserkent szeretnem egy adott kezdobeture
REM     vagy termekcsoportra szurve (pl. 'b' vagy 'allegra') futtatni a vizsgalatot.
REM   - US-IMG-05: Auditorkent szeretnem a vizsgalatot automatikusan leallitani
REM     adott szamu (pl. 10 db) duplikaciot tartalmazo termek megtalalasakor,
REM     es idobelyeges, vesszovel tagolt CSV riportot kapni.
REM 
REM Kapcsolodo feluletek:
REM   - Windows Parancssor (CMD) / PowerShell terminal
REM   - shopify_image_deduplicator.py es requirements.txt
REM ================================================================================

title Shopify Termekkep Duplikacio Szuro

echo ================================================================================
echo        SHOPIFY TERMEKKEP DUPLIKACIO SZURO - INDITOPULT (BENU.HU)
echo ================================================================================
echo.

REM 1. Python megletenek ellenorzese
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [HIBA] A Python nincs telepitve vagy nincs a PATH-ban!
    echo Kerjuk, telepitse a Python 3.9+ verziot a futtatashoz.
    echo.
    pause
    exit /b 1
)

REM 2. Szukseges Python csomagok ellenorzese / telepitese
echo [1/2] Fuggosegek ellenorzese (requests, Pillow, imagehash)...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [FIGYELMEZTETES] Hiba a csomagok automatikus telepitesekor.
    echo Megprobaljuk a futtatast a meglevo csomagokkal...
)
echo [OK] Fuggosegek keszen allnak.
echo.

REM 3. Menu megjelenitese
:MENU
echo ================================================================================
echo Valasszon futtatasi modot:
echo ================================================================================
echo  1. TESZT: Mintapelda ellenorzese - Allegra 120 mg [JPG es PNG kep]
echo  2. TESZT: Sitemap elso 5 termekenek vizsgalata
echo  3. TESZT: Sitemap elso 20 termekenek vizsgalata
echo  4. SZURES: Kezdobetu(k) szurese + Leallas N db duplikalt termeknel
echo  5. EGYEDI: Sajat termek URL megadasa kezi teszteleshez
echo  6. TELJES FUTTATAS: Minden termek vizsgalata a sitemap-bol
echo  7. Kilepes
echo ================================================================================
set "CHOICE="
set /p "CHOICE=Adja meg a valasztott opcio szamat (1-7) [Alapertelmezett: 1]: "

if "%CHOICE%"=="" set CHOICE=1
if "%CHOICE%"=="1" goto TEST_ALLEGRA
if "%CHOICE%"=="2" goto TEST_5
if "%CHOICE%"=="3" goto TEST_20
if "%CHOICE%"=="4" goto FILTER_PREFIX
if "%CHOICE%"=="5" goto CUSTOM_URL
if "%CHOICE%"=="6" goto FULL_RUN
if "%CHOICE%"=="7" goto EXIT

echo Ervenytelen valasztas, kerjuk probalja ujra!
echo.
goto MENU

:TEST_ALLEGRA
echo.
echo [INDITAS] Allegra 120 mg mintatermek vizsgalata...
python shopify_image_deduplicator.py --url "https://benu.hu/products/allegra-120-mg-filmtabletta-30x"
goto END

:TEST_5
echo.
echo [INDITAS] Sitemap elso 5 termekenek vizsgalata...
python shopify_image_deduplicator.py --limit 5
goto END

:TEST_20
echo.
echo [INDITAS] Sitemap elso 20 termekenek vizsgalata...
python shopify_image_deduplicator.py --limit 20
goto END

:FILTER_PREFIX
echo.
set "PREFIX="
set /p "PREFIX=Adja meg a kezdobetut vagy prefixeket (pl. 'b' vagy 'a,al,beres'): "
if "%PREFIX%"=="" (
    echo Nem adott meg prefixet!
    goto MENU
)
set "PMAXDUPES="
set /p "PMAXDUPES=Hany duplikalt termek megtalalasakor alljon le? [0 = nincs korlat, pl. 10]: "
if "%PMAXDUPES%"=="" set PMAXDUPES=0

set "PLIMIT="
set /p "PLIMIT=Osszesen legfeljebb hany termeket vizsgaljon? [0 = mind, alapertelmezett: 0]: "
if "%PLIMIT%"=="" set PLIMIT=0

echo.
echo [INDITAS] Szures '%PREFIX%' prefixre, max duplikalt termek limit: %PMAXDUPES%, osszes limit: %PLIMIT%...
python shopify_image_deduplicator.py --starts-with "%PREFIX%" --max-dupes %PMAXDUPES% --limit %PLIMIT%
goto END

:CUSTOM_URL
echo.
set "USER_URL="
set /p "USER_URL=Adja meg a vizsgalando termek teljes URL-jet: "
if "%USER_URL%"=="" (
    echo Nem adott meg URL-t!
    goto MENU
)
python shopify_image_deduplicator.py --url "%USER_URL%"
goto END

:FULL_RUN
echo.
set "PMAXDUPES="
set /p "PMAXDUPES=Hany duplikalt termek megtalalasakor alljon le? [0 = nincs korlat, pl. 10]: "
if "%PMAXDUPES%"=="" set PMAXDUPES=0

echo [FIGYELEM] A sitemap feldolgozasa elindul.
set "CONFIRM="
set /p "CONFIRM=Biztosan elinditja a futtatast? (i/n) [n]: "
if /i not "%CONFIRM%"=="i" goto MENU
python shopify_image_deduplicator.py --limit 0 --max-dupes %PMAXDUPES%
goto END

:END
echo.
echo ================================================================================
echo A folyamat befejezodott. Az idobelyeges CSV riport elkeszult a mappaban.
echo ================================================================================
echo.
pause
goto MENU

:EXIT
exit /b 0
