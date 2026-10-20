# Interfejs Atlas

Atlas zastępuje dotychczasowy układ widoku WICI. Lista publikacji i filtry zajmują lewy panel, mapa pozostałą przestrzeń. „Filtry i zakres” zawierają kategorię, województwo i rozszerzenie dzisiejszego widoku; licznik przy nagłówku pokazuje dodatkowe aktywne filtry. Dzień publikacji i rodzaj komunikatu pozostają widoczne.

„Warstwy mapy” otwierają ustawienia nad mapą. Zachowano wszystkie kontrolki, osie czasu, odtwarzanie, legendy, informacje o źródłach i ograniczenia: OpenStreetMap, NASA FIRMS, EFFIS, TomTom, GDDKiA, radar RainViewer, wyładowania EUMETSAT, pomiary IMGW i prognozę Open-Meteo z wiatrem i opadami, samoloty oraz statki AIS z widokiem Bałtyku. Zwijanie ustawień nie wyłącza warstw.

Wybór publikacji na liście lub mapie otwiera panel szczegółów z oryginałem, datami, ważnością, obszarem i historią wersji. Przycisk zamknięcia i Escape zamykają panel; na telefonie otwarcie przewija do szczegółów, a zamknięcie wraca do wybranego komunikatu. Szuflada nie jest modalna. Zmiana dnia zamyka poprzednie szczegóły. Spóźniona odpowiedź nie zastępuje nowszego wyboru ani nie otwiera ponownie ręcznie zamkniętego panelu.

„Źródła” zachowują aktualność, ograniczenia i ręczne odświeżanie. Zwięzły, rozwijany pasek pod widokiem informuje o ograniczeniach źródeł i przerwach w monitoringu. Pozostają widoczne oznaczenia DEMO/LIVE, czas serwera i komunikaty błędów. Legenda stopni IMGW nadal rozróżnia 1°/2°/3°; informacje mają osobne oznaczenie. Początkowy zasięg mapy dopasowuje się do granic Polski, także na małych ekranach.

Zmiany dotyczą statycznego interfejsu. Backend, integracje, konfiguracja, klucze i bazy danych nie wymagają migracji. Ikony i style są lokalne; nie dodano zależności sieciowych interfejsu.

Rozszerzenie 17.10.2026: przełącznik [„Ukraina — alerty NEPTUN”](ukraine.md) dodaje granice Ukrainy, obszary alarmów i osobne doniesienia. Włączenie kadruje Polskę i Ukrainę; cykliczny odczyt nie przesuwa mapy. Sekcja NEPTUN w istniejącej legendzie zapobiega utożsamieniu kolorów z polskimi stopniami IMGW. Szczegóły zachowują otwarcie i fokus podczas odświeżania; ukrycie lub wyłączenie warstwy zatrzymuje odczyt. Test `tests/ukraine_browser.cjs` używa własnego serwera demo i syntetycznych danych, a istniejący smoke test Atlas sprawdza teraz 13 grup warstw.

## Weryfikacja

```sh
uv run --locked pytest -q
uv run --locked ruff check .
node --test tests/ui_*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs
git diff --check
```

Opcjonalny test rzeczywistej przeglądarki wymaga dostępnego modułu Node `playwright` oraz jego Chromium. Uruchom osobną instancję DEMO, następnie:

```sh
WICI_UI_URL=http://127.0.0.1:8765 node scripts/check_atlas_ui.cjs
```

Jeśli moduł pochodzi z innego środowiska, ustaw `NODE_PATH` na jego katalog `node_modules`. Skrypt wymaga trybu DEMO i adresu loopback. Sprawdza filtry i dzień, szczegóły z historią, wszystkie kontrolki warstw, odtwarzanie prognozy, źródła, dostępność przycisku odświeżania, rozmiary 1440/1366/768/390/320 px i brak połączeń zewnętrznych. Zrzuty zapisuje w ignorowanym `tmp/atlas-ui-evidence/`; opcja `WICI_SCREENSHOT_DIR` zmienia ten katalog.

Historyczna weryfikacja Atlasu przed pracami nad WICI Noc: 350 testów Python, 65 testów Node, Ruff i test przeglądarkowy zakończone powodzeniem. Przeglądarka korzystała z odizolowanej bazy DEMO na porcie 8770, bez konfiguracji i kluczy LIVE. Faktycznej dostępności dostawców zewnętrznych nie sprawdzano ponownie; logikę ich warstw obejmują dotychczasowe testy offline. Nie uruchamiano kolektorów LIVE.


## Atlas i WICI Noc

Przycisk „WICI Noc” pozostaje w nagłówku obu widoków. Jest natywnym przyciskiem przełączającym: Enter lub Spacja zmienia wygląd, `aria-pressed=true` oznacza nocny. Ponowne naciśnięcie przywraca jasny Atlas. Pierwszy start pozostaje jasny, niezależnie od zegara i wyglądu systemu. Preferencja dotyczy profilu przeglądarki i origin, wspólnie dla DEMO/LIVE; po wyczyszczeniu danych witryny znika. Przy zablokowanej pamięci wybór działa w bieżącej karcie, bez gwarancji zachowania po odświeżeniu.

Nagłówek warstw pokazuje „Warstwy · N aktywnych”. Liczone są zaznaczone, dostępne główne przełączniki danych z jawnego słownika `layers.js`, także osobno wiatr/opady oraz wodowskazy/ostrzeżenia hydro. Podkład OSM i pomocnicze opcje modułów (np. animacja, maski jakości, obecność komunikatów przy IODA) nie zwiększają licznika. Zmiana dostępności aktualizuje licznik. Wszystkie 13 grup rozpoczyna zwinięte; otwarcie grupy odsłania ustawienia bez aktywacji danych. Wewnątrz panelu można przewijać długie ustawienia; Escape zamyka panel i zwraca fokus do podsumowania.

Karty pokazują tytuł przed znacznikami i metadanymi. Tekst pomocniczy ma co najmniej 12 px, treść dokumentu 14 px. Na telefonie nagłówek ma dodatkowy wiersz czasu, a główne przyciski, zoom mapy i kontrolki warstw mają obszary dotyku 44 px. Legendy i szczegóły pozostawiają miejsce na wielowierszową atrybucję. Fokus jest oddzielny od zaznaczenia; ograniczenie ruchu wyłącza przejścia przycisków, bez uruchamiania lub zmiany odtwarzania danych.

### Architektura prezentacji

`js/theme.js` jest małym lokalnym skryptem synchronicznym przed arkuszami CSS. Czyta wyłącznie `wici.ui.theme.v1` (`light`/`dark`), bezpiecznie obsługuje błędną wartość i wyjątki pamięci, a przed pierwszym renderem ustawia `<html data-theme>`. Po przygotowaniu DOM wiąże przycisk; zapisuje wyłącznie motyw i emituje prezentacyjne `wici:themechange` z `{theme}`. Nie wywołuje API, odświeżania, timerów ani zdarzeń `change` kontrolek danych. Zgodność z CSP `script-src 'self'` nie wymaga inline JS ani zmiany backendu.

Tokeny `:root` i `:root[data-theme="dark"]` w `css/app.css` rozdzielają UI od skal dostawców:

| Grupa | Tokeny | Przeznaczenie |
| --- | --- | --- |
| Powierzchnie | `--canvas`, `--paper`, `--raised`, `--hover` | Tło, karty, kontrolki, popupy i źródła |
| Typografia | `--ink`, `--muted`, `--navy`, `--teal` | Tekst i interakcje |
| Obramowanie i fokus | `--line`, `--control-line`, `--focus` | Separatory, kontury kontrolek, fokus klawiatury |
| Komunikaty UI | `--notice-*`, `--error-*`, `--red`, `--badge-*` | Ograniczenia, błędy i ogólne etykiety |
| Własna kartografia | `--map-bg`, `--map-prg-line`, `--map-prg-fill`, `--map-border-halo`, `--map-border-line` | Tylko lokalny podkład i obrysy PRG |
| Wykres | `--plot-bg` | Jasne pole wykresu IODA w obu motywach, zachowujące kontrast oryginalnej fioletowej linii |

Oryginalne stopnie IMGW, barwy GIOŚ, NEPTUN, hydrologii, FWI, GFM, ruchu i jakości satelitarnej pozostają odrębne. Ciemniejsze próbki legend otrzymują obrys, bez zmiany barwy danych. Logo `brand/logo-night.svg` jest kontrastową odmianą kolorystyczną tego samego znaku Sygnał.

`app.js` przechowuje istniejące obiekty granic PRG i po zdarzeniu zmienia tylko ich style. Nie zmienia `fillOpacity` zarządzanego przez OSM, geometrii, danych, instancji mapy, środka, zoomu ani popupu. Odpowiedź granic przychodząca po przełączeniu odczytuje bieżące tokeny. Filtr nocny `invert(1) hue-rotate(180deg) brightness(.98) contrast(.85) saturate(.15)` dotyczy wyłącznie `.leaflet-osmBase-pane`; rastry, markery i wszystkie pozostałe panele Leaflet pozostają poza nim. Przy braku kafelków nadal widać lokalne granice i zapisane obiekty.

### Odtwarzalna weryfikacja WICI Noc

Po `uv sync --locked` i udostępnieniu Playwright/Chromium:

```sh
uv run --locked pytest -q
uv run --locked ruff check .
node --test tests/*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs
node scripts/check_night_ui.cjs
WICI_TEST_THEME=light node --test --test-concurrency=1 tests/{gfm,gios,hydro,ioda,sentinel2,sentinel5p,ukraine}_browser.cjs
WICI_TEST_THEME=dark node --test --test-concurrency=1 tests/{gfm,gios,hydro,ioda,sentinel2,sentinel5p,ukraine}_browser.cjs
git diff --check
```

`check_night_ui.cjs` sam uruchamia i zatrzymuje tymczasowy serwer DEMO z zabronionym transportem zewnętrznym, bez pliku konfiguracji i kluczy LIVE. Można wskazać istniejące DEMO przez `WICI_UI_URL`; skrypt odrzuca LIVE i adresy inne niż loopback. `NODE_PATH` może wskazywać zainstalowany moduł Playwright. Zrzuty oraz raport z rzeczywistymi kolorami i obliczonym kontrastem zapisuje do ignorowanego `tmp/wici-night-evidence/` (zmiana przez `WICI_SCREENSHOT_DIR`). Zrzuty bazowe tej pracy: `tmp/wici-night-baseline/`. Są to lokalne dowody kontroli, nie pliki do publicznego wydania.

Skrypt sprawdza trwałość i błędy pamięci, motyw przed dostarczeniem CSS, obsługę klawiatury, ograniczenie ruchu, brak nowych żądań API po przełączeniu, tożsamość mapy/warstw/popupu, otwarte szczegóły i historię, stan filtrów i suwaków, oba motywy przy 320/390/768/1024/1366/1440/1920 × 600 px oraz izolację rastra i podkładu. Kontrast tekstu jest liczony na podstawie rzeczywistych stylów i złożenia przezroczystych teł; nieaktywne kontrolki są wyjątkiem WCAG. Rysunki i skale źródłowe wymagają dodatkowego oglądu, sam test DOM nie wystarcza.

Zakres zmian obejmuje statyczny HTML/CSS/JS, odmianę logo, testy i dokumentację. Jedyna korekta konfiguracji testowej to `testpaths = ["tests"]`: `pytest -q` nie zbiera już starych kopii repozytorium z ignorowanego `tmp/`. API, SQLite, integracje, harmonogramy i klucze nie zmieniają się. Nie dodano Scenariuszy ani wdrożenia.


### Wynik odbioru — 18.10.2026

- `uv run --locked pytest -q`: **776 zaliczonych**; trzy istniejące ostrzeżenia bibliotek (Starlette/httpx i syntetyczne rastry bez georeferencji).
- `uv run --locked ruff check .` i `git diff --check`: **zaliczone**.
- `node --test tests/*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs`: **165 zaliczonych**. Regresje obejmują pamięć motywu, zmianę podczas odczytu granic, licznik i zachowanie szuflady.
- Smoke Atlasu: **zaliczony** na osobnym DEMO; poprawiono przygotowanie testu do grupy Pogoda zwiniętej już od v0.24.3.
- `check_night_ui.cjs`: **zaliczony**. 34 zrzuty; 523 próbki rzeczywistego kontrastu tekstu, zero poniżej przyjętego progu. Najniższy kontrast zwykłego tekstu: **5,15:1**. Symbole strzałek pogody mają co najmniej **3,69:1** i zachowują oryginalny obrys. Brak zewnętrznych żądań i błędów wykonania przeglądarki.
- Dodatkowe scenariusze Chromium: **24 w Atlasie + 24 w WICI Noc = 48 zaliczonych**, z syntetycznymi danymi GFM, GIOŚ, hydrologii, IODA, Sentinel-2, Sentinel-5P i NEPTUN. Obejmują maski, skale, legendy, popupy, jakość/czas, brak danych i anulowanie odczytu. Zaktualizowano przygotowanie testów hydrologii/GIOŚ/Sentinel-5P do domyślnie zwiniętej Pogody. Sekwencyjne uruchomienie ogranicza przeciążenie Chromium i przypadkowe timeouty.
- Obejrzano jasny i nocny desktop, warstwy/szczegóły/popup, źródła, legendę, telefon oraz stany awarii. Sprawdzono wewnętrzny scroll wszystkich rozwiniętych grup, dojście do ostatniej grupy, atrybucję poza otwartą legendą i powrót fokusu. Osobno sprawdzono brak geometrii, puste komunikaty, błędne i nieaktualne źródło, brak klucza, API 503, offline oraz opóźnioną odpowiedź po zmianie dnia w obu motywach.
- **Rzeczywiste OSM** oceniono oddzielnie od offline DEMO: samodzielny lokalny podgląd Leaflet załadował 30 kafelków Warszawy (HTTP 200, bez błędów). Po porównaniu wariantów przyjęto spokojniejszy, mniej nasycony filtr; nazwy dzielnic i miejscowości, numery dróg oraz popup pozostały czytelne, a syntetyczny symbol zachował barwę. Porównanie lokalne: `tmp/wici-night-evidence/osm-warsaw-light.png` i `osm-warsaw-dark.png`. Ta próba korzystała z sieci wyłącznie do istniejącego podkładu OSM; nie uruchamiała LIVE ani kolektorów.

Zestaw porównawczy w `tmp/wici-night-evidence/`: `light-desktop.png`, `dark-desktop.png`, `dark-layers-details-popup.png`, `dark-sources.png`, `dark-map-legend.png`, `dark-390-short.png`. `report.json` zawiera szczegółowe próbki kontrastu i listę pozostałych zrzutów. Skrypt i zrzuty bazowe pozwalają powtórzyć kontrolę bez danych LIVE.

Granice weryfikacji: przetestowano rzeczywisty Chromium, bez audytu czytnikiem ekranu i bez osobnych przebiegów Safari/Firefox. Automatyczny kontrast dotyczy widocznego tekstu na złożonych tłach; oryginalne rastry/skale dostawców zachowują barwy i są oceniane razem z etykietami oraz obrysami. Nie potwierdzano bieżącej dostępności API dostawców ani kluczy użytkownika, nie wykonywano rzeczywistego odczytu LIVE. Nie dokonano publicznego wdrożenia.


Pliki wdrożenia: `static/index.html`, `static/css/app.css`, nowy `static/js/theme.js`, prezentacyjne zmiany w `static/js/app.js`, `static/js/atlas.js`, `static/js/layers.js` i kontrastowy `static/brand/logo-night.svg` (ścieżki względem `src/wici/`). Testy: nowy `scripts/check_night_ui.cjs`, poprawiony smoke Atlasu, `tests/ui_theme.test.cjs`, `tests/ui_layers.test.cjs`, rozszerzenia testów Atlasu i mocków oraz helper `tests/browser_theme.cjs` z siedmioma scenariuszami integracyjnymi. Dokumentacja: `README.md` i ten dokument; konfiguracja wyszukiwania testów: `pyproject.toml`.
