# Raport implementacji: Sentinel-2 — przed / po

Data odbioru: 17.10.2026. Implementacja lokalna, Python 3.12 / uv / FastAPI / Leaflet, bez nowych zależności, wdrożenia i autostartu.

## Co działa

Osobna, domyślnie wyłączona warstwa w panelu Atlas, niezależna od EMS Rapid Mapping i GFM. Punkt wskazywany jawnym trybem kliknięcia lub środkiem mapy; walidacja geometrii Polski, obszar 2/4/6 km (domyślnie 4 km). Własne daty UTC i filtr zachmurzenia, dwie listy obserwacji z rzeczywistymi czasami, identyfikatorami, zachmurzeniem i pokryciem katalogowym. Brak samoczynnego wyboru zastępczej daty.

Dwa rendery RGB L2A B04/B03/B02 z jedną siatką EPSG:3857 i stałymi parametrami kolorów. Backend wymaga zgodnych metadanych produktu i czasu, odrzuca wieloscenowe mozaiki i niezgodną geometrię. Suwak z pionową linią podziału, stale widocznymi datami, myszą, dotykiem i klawiaturą. Obrazy zachowują położenie po pan/zoom. Szachownica NoData nie odsłania drugiej daty. Opcjonalne maski SCL oraz udział chmur, cieni i śniegu w wycinku.

Żądania tylko na wyraźną akcję. Ograniczony cache, deduplikacja, kolejka i współbieżność; limity czasu, zasięgu i odpowiedzi. Cache tokenu OAuth z wygaśnięciem. Kontrolowane lokalne endpointy, bez URL zasobów od klienta i bez sekretów w frontendzie. Rozróżnione: brak konfiguracji, brak obserwacji, brak pokrycia, chmury, błędy uprawnień, limitu i dostawcy. Brak automatycznych ponowień; Retry-After i wspólny backoff. Stare odpowiedzi nie przywracają poprzedniego punktu, dat ani wyłączonej warstwy.

Demo w pełni offline, oznaczone jako syntetyczne (także atrybucja); suwak, przykładowa wycinka, chmury i NoData działają bez konta i sieci. Istniejące moduły zachowują własny cykl życia.

## Weryfikacja

| Kontrola | Wynik |
| --- | --- |
| `uv run pytest -q` | **667 passed**, 63,42 s; w tym 30 testów Sentinel-2 |
| `node --test tests/ui_*.test.cjs` | **119 passed** |
| `node --test tests/sentinel2_browser.cjs` | **2 passed**, Chromium desktop 1440 × 1000 oraz telefon 390 × 844 z emulacją dotyku |
| GFM / GIOŚ / IODA w rzeczywistym Chromium | **8 passed** (w tym GFM desktop/mobile/wide i tryb auto) |
| Hydrologia w rzeczywistym Chromium | **1 passed** w osobnym przebiegu; pierwszy przebieg równolegle z innymi przeglądarkami przekroczył timeout oczekiwania na popup. Bez zmiany kodu hydrologii przeszedł osobno w 6,23 s. |
| `uv run ruff check .` | **All checks passed** |
| `git diff --check` | **OK** |
| Próba CDSE LIVE | **OK**, katalog i dwa różne produkty, wspólny bbox, 400 × 400, EPSG:3857 |

Node/Playwright uruchomiono z pakietami dostarczonego runtime (`NODE_PATH` wskazywał katalog `dependencies/node/node_modules`). Dwa ostrzeżenia pytest: istniejąca deprecjacja Starlette/httpx oraz oczekiwany brak georeferencji w PNG czytanym w teście przez rasterio — położenie PNG jest przekazywane Leaflet osobno, a weryfikacja georeferencji dotyczy źródłowego GeoTIFF-a.

Testy obejmują: dokładny wybór produktu i czasu, odrzucenie obcej daty/mozaiki/przesuniętego rastra, geometrię i jakość, nieprzezroczyste NoData, cache LRU/TTL i współdzielenie, maksymalną kolejkę/współbieżność, anulowanie klienta i zamknięcie serwisu, wygasanie tokenów i wyborów, 401/403/429/500/503, Retry-After, timeout i limit transferu, sanitację błędów i ochronę konfiguracji, lokalne API i origin oraz brak sieci demo. W przeglądarce sprawdzono faktyczne kliknięcie mapy, dotyk, strzałki klawiatury, maski, identyczne położenie obu obrazów po zmianie widoku, brak żądań przy ruchu suwaka, puste wyniki, awarię i spóźnione odpowiedzi po zmianie punktu/daty lub wyłączeniu warstwy. Zrzuty ekranów oceniono wizualnie; poprawiono zasłanianie suwaka przez legendę i atrybucję na telefonie.

## Próba LIVE i dowody

Wykonano historyczną próbę live. Dane produktów, pomiary zachmurzenia, obrazy i szczegółowe zestawienie usunięto 18.10.2026. Bieżące testy korzystają z syntetycznych danych.

## Konfiguracja i ograniczenia odbioru

Dostarczone dane klienta zapisano w ignorowanym `config.local.toml`, sekcja `[sources.sentinel2]`, `enabled=true`, prawa `0600`. Warstwa UI pozostaje domyślnie wyłączona. W `config.example.toml` znajdują się wyłącznie komentarze i puste przykładowe pola, `enabled=false`. Konto CDSE i token nie trafiają do odpowiedzi ani repozytorium. Instrukcja [konfiguracji, kontraktu i limitów](sentinel2.md) zawiera oficjalne źródła sprawdzone przed implementacją; README, opis źródeł i THIRD_PARTY_NOTICES uzupełniono.

Odbiór LIVE obejmuje jedno miejsce i dwa terminy, a nie cały historyczny katalog i wszystkie granice kafli. Dostępność i limity konta zależą od CDSE. Obrazy mają natywną informację RGB 10 m, maska SCL 20 m; reprojekcja i powiększanie nie zwiększają szczegółowości. Porównanie nie potwierdza automatycznie zmiany terenu. Test telefonu jest emulacją mobilnego Chromium z dotykiem, nie testem fizycznego telefonu ani Safari/iOS. Automatyczne monitorowanie, klasyfikacja i alerty pozostają poza zakresem. Nie uruchamiano wdrożenia, autostartu ani trwałego serwera.


## Poprawki po przeglądzie — 17.10.2026

Naprawiono kolizję cache demo: identyfikator zawiera wariant oraz datę pozyskania, a ponowne wyszukiwanie nie nadpisuje obserwacji z innego terminu. Zachowano różne obrazy syntetyczne „przed” i „po”. Frontend sprawdza też zgodność czasu renderu z wyborem, obok identyfikatora i siatki.

Szerokość kontrolki porównania jest ograniczona do panelu mapy, zamiast całego okna. Kontener Leaflet udostępnia jej rzeczywistą szerokość mapy. Przy 700, 800 i 900 px podpis „po” i prawy koniec suwaka nie są obcinane.

Nowe regresje przed poprawką wykazały błędne daty renderów (3 przypadki Python) i kontrolkę szerokości 570 px w panelu mapy 420 px (Chromium 700 px). Po poprawce: pełny zestaw Python — 670 testów przeszło (62,31 s), w tym 33 testy modułu Sentinel-2; 5 testów przeglądarkowych również przeszło. Ruff i `git diff --check` zakończyły się poprawnie. Sprawdzono zmianę obu dat, każdej daty osobno, powrót do wcześniejszego zakresu, zgodność metadanych i odmienność obrazów demo; w UI ponowne porównanie z nowymi datami. Dla 700/800/900 px sprawdzono granice kontrolki, obu podpisów i suwaka, kliknięcie wartości 0/100 oraz zmianę rozmiaru okna do 1440 px i z powrotem. Regresje dotychczasowego UI: 119 testów Node przeszło. Testy używają wyłącznie demo offline; nie powtarzano żądań LIVE do CDSE.

## Poprawka wskazywania punktu — 17.10.2026

Potwierdzono zgłoszenie użytkownika: kliknięcie karteczki komunikatu podczas wskazywania punktu otwierało popup i nie docierało do obsługi `map.on('click')`. Wybór środka mapy działał, ponieważ omijał zdarzenia warstw.

Jawny tryb wskazywania obsługuje teraz kliknięcie/tap w fazie capture kontenera mapy, zanim Leaflet przekaże je interaktywnym warstwom. Tylko w tym trybie kliknięcie wybiera punkt zamiast otwierać popup; poza nim zachowano normalne działanie warstw. Kontrolki, popupy, aktywacja klawiaturą oraz gesty przeciągania nie wyznaczają punktu. Otwarte popupy zamykają się przy rozpoczęciu wskazywania. Znacznik ma własną nieinteraktywną warstwę ponad pozostałymi obiektami oraz stały podpis „Sentinel-2 · wybrany punkt”.

Nowy test najpierw odtworzył błąd na prawdziwej karteczce komunikatu. Po poprawce przeszło 7 testów przeglądarkowych Sentinel-2, w tym dwa nowe dla desktopu i emulacji telefonu: kliknięcie/tap karteczki, marker z `bubblingMouseEvents:false`, polygon z popupem, położenie i widoczność wybranego punktu oraz zachowanie zwykłego klikania poza trybem wskazywania. Sprawdzono także zoom bez wyboru punktu i przeciąganie mapy. Regresje UI Node: 119 testów przeszło; Ruff i `git diff --check` poprawne. Backend nie był zmieniany; testy nie wykonują żądań LIVE.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

## Pełny zasięg i ostrzeżenia o brakach — 18.10.2026

Wyszukiwanie domyślnie pokazuje wyłącznie obserwacje z pełnym footprintem na docelowej siatce RGB. Wyniki częściowe i o nieznanym pokryciu można odsłonić, odznaczając filtr; interfejs podaje liczbę ukrytych wyników i ostrzega w opisach obserwacji. Filtrowanie nie mutuje cache ani nie powtarza żądania katalogowego. Limit 50 dotyczy partii przed filtrowaniem i jest opisany w komunikacie o ucięciu.

Po renderze rzeczywiste NoData jest liczone z `dataMask`, niezależnie od chmur. API podaje procent i liczbę brakujących pikseli oraz stan `partial_coverage` lub `no_coverage`. Ostrzeżenie z procentem dla każdej strony jest widoczne przy suwaku również po zamknięciu panelu warstw. Nawet pojedynczy brakujący piksel nie daje statusu pełnego obrazu. Zmiana filtra usuwa porównanie i unieważnia trwające żądania.

Weryfikacja offline: **787 testów Python**, **182 testy UI Node** i **9 scenariuszy Chromium** przeszło, w tym dotychczasowe regresje dat demo, wskazywania punktu oraz szerokości 700/800/900 px. Dwa nowe scenariusze pokrycia sprawdzono również w ciemnym motywie. Regresje obejmują pokrycie pełne, częściowe, nieznane, brak obrazu, pojedynczy brakujący piksel, ponowne użycie cache, domyślny parametr API i świadome odsłonięcie częściowych wyników, usuwanie ostrzeżeń po pełnym porównaniu oraz spóźnione odpowiedzi. Ruff i `git diff --check` poprawne. Zrzuty syntetycznego desktopu i telefonu oceniono wizualnie; pozostają w ignorowanym `tmp/browser-evidence/`. Trzy ostrzeżenia pełnego pytest dotyczą deprecjacji Starlette/httpx i dwóch istniejących odczytów PNG bez georeferencji. Nie powtarzano próby LIVE; pełny footprint katalogowy nadal nie gwarantuje rzeczywistych danych ani braku chmur.

## Osobne zakresy „przed” i „po” — 18.10.2026

Interfejs ma osobne pola „Od/Do” dla obu stron. Jedno uruchomienie wyszukiwania pobiera dwie listy, każdą ograniczoną do własnego przedziału. Pozwala to porównywać np. październik 2020 i październik 2026 bez wieloletniego zapytania katalogowego. Limit 366 dni i 50 wyników przed filtrowaniem dotyczy każdej listy; ustawienia miejsca, rozmiaru, zachmurzenia i pełnego pokrycia pozostają wspólne. Oba zakresy domyślnie obejmują ostatnie 30 dni.

Zmiana dat jednej strony usuwa jej listę i całe porównanie, zachowując istniejący wybór drugiej strony. Trwające zapytania są anulowane; ich spóźnione wyniki i błędy nie wracają pod nowymi datami. Ponowne wyszukanie odświeża obie listy i wymaga ponownego wyboru. Błąd lub brak wyników jednej strony jest opisany osobno i nie usuwa poprawnej odpowiedzi drugiej. Porównanie nadal wymaga dwóch różnych obserwacji we właściwej kolejności czasowej i sprawdza dokładny identyfikator, czas oraz wspólną siatkę obu renderów.

Regresje offline: API demo wyszukuje osobno lata 2020/2026 i renderuje dokładnie wybrane produkty, również po powrocie do obrazu w cache. Pięć dodatkowych testów Node sprawdza osobne parametry zapytań i listy, odwrotną kolejność odpowiedzi, błąd lub pustą listę jednej strony, ochronę przed wyborem z przeciwnej listy i anulowanie po zmianie każdego zakresu. Scenariusze Chromium desktop/telefon porównują 2020 → 2026, następnie 2021 → 2026, sprawdzają zachowanie drugiego wyboru po edycji dat i mieszczące się pola dat. Pełny zestaw Python: **793 testy przeszły**, w tym 42 testy modułu Sentinel-2. Przeszło także **187 testów UI Node i 11 scenariuszy Chromium** (7 Sentinel-2, 2 pokrycia, 2 regionu); porównanie między latami przeszło również w ciemnym motywie na obu rozmiarach. Zachowano regresje szerokości 700/800/900 px i wskazywania punktu. Zrzuty obu motywów oceniono wizualnie. Ruff i `git diff --check` poprawne. Nie wykonywano nowych żądań LIVE.
