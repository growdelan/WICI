# Teren i drzewa w 3D

Na mapie ogólnej przybliż interesujące miejsce i wybierz **Widok 3D** (prawy dolny róg). Kółko/gest przybliża; przeciągnięcie przesuwa; Ctrl + przeciągnięcie lub dwa palce obracają kamerę. **Wróć do 2D** zwalnia renderer i przywraca mapę Leaflet z jej warstwami i filtrami. Środek oglądanego miejsca wraca do 2D. Warstwy komunikatów, pogody i ruchu pozostają dostępne w 2D; widok ogólny 3D pokazuje podkład, teren i drzewa.

Te same dane otoczenia są ładowane automatycznie po wybraniu **Podążaj w 3D** dla samolotu lub autobusu, w kamerze zewnętrznej i pierwszej osobie. Autobus oraz jego kamera korzystają z wysokości załadowanego terenu. Samolot zachowuje wysokość barometryczną z raportu, z zabezpieczeniem położenia renderowania nad powierzchnią. Brak danych lub awaria dostawcy nie blokuje mapy i śledzenia: pozostaje powierzchnia zastępcza i jawny komunikat. Ponowne otwarcie widoku ponawia ładowanie.

## Dane i dokładność

- **Teren Polski:** [NMT GUGiK / WCS](https://www.geoportal.gov.pl/pl/usluga/uslugi-pobierania-wcs/), coverage `DTM_PL-KRON86-NH_TIFF`, GeoTIFF. Jest to model gruntu opracowany m.in. z lotniczego skanowania laserowego, a nie wyświetlanie surowej chmury LAS/LAZ. NMT nie zawiera brył budynków, koron ani mostów. Używamy gotowego NMT, aby nie wprowadzać konwerterów chmur punktów i dodatkowego serwera kafli.
- **Drzewa:** miejska Baza Zieleni, `BOS_ZIELEN_DRZEWA`, [Urząd m.st. Warszawy](https://mapa.um.warszawa.pl/). Obejmuje zinwentaryzowane drzewa w Warszawie, a nie wszystkie drzewa Polski ani cały drzewostan miasta. Pozycja, dostępna wysokość i średnica korony pochodzą z bazy. Brakująca wysokość = umowne 8 m; brakująca średnica = 4 m. Status wskazuje liczbę drzew z przybliżonymi wymiarami, aktualność wpisów i czas pobrania. Bryły pnia i korony są uproszczone; kolor jaśniejszy oznacza przybliżone wymiary. Drzewa są pokazywane przy wysokości kamery / samolotu poniżej 6 km. W innych miastach działa teren, a komunikat wskazuje zakres miejskiej bazy.
- NMT ma wysokości **PL-KRON86-NH**, a scena jest osadzona na WGS84. Nie wykonujemy geodezyjnej transformacji wysokości z siatką quasi-geoidy. Rzeźba i wysokości renderowania są przybliżeniem; nie porównuj ich pomiarowo z wysokością barometryczną ADS-B. Brak odwzorowania wiaduktów, tuneli, pochylenia pojazdu i modeli budynków. Widok nie służy nawigacji.

## Najprostsze wdrożenie

Uruchomienie jest takie samo jak dotychczas: `uv run --locked python -m wici`. Bez nowych zależności, kont, tokenów, procesów, migracji i przygotowywania danych. Cesium i workery pozostają lokalne, CSP nie dostaje nowych zewnętrznych origin. Backend pobiera wyłącznie z dwóch stałych adresów dostawców; przeglądarka rozmawia z lokalnym `/api/scene3d/…`. OSM nadal respektuje przełącznik podkładu i działa bezpośrednio z przeglądarki w LIVE. Demo nie pobiera danych zewnętrznych.

Awaryjne wyłączenie otoczenia (sam silnik i podkład nadal działają):

```toml
[sources.scene3d]
enabled = false
```

Warunki miejskich danych: [Warunki ponownego wykorzystania informacji publicznej](https://mapa.um.warszawa.pl/strony/Warunki-ponownego-wykorzystania-informacji-publicznej) ([treść CMS](https://mapa.um.warszawa.pl/api/modul-mapowy/open/cms/Warunki-ponownego-wykorzystania-informacji-publicznej)). Widok podaje źródło „Urząd m.st. Warszawy”, aktualność, datę pobrania i zakres modyfikacji (bryły 3D i szacowanie brakujących wymiarów). Punkt 3e wymaga poinformowania urzędu o przetworzeniu danych na `BG-informacjapubliczna@um.warszawa.pl`; operator powinien wykonać ten krok przy uruchomieniu integracji. Implementacja ani testy nie wysyłają wiadomości. Dane dostawców nie są objęte MIT kodu WICI.

## Budżet pracy i testowanie

Teren jest kafelkowany w schemacie Geographic Cesium: siatka 65×65, pobieranie dla Polski na poziomach 10–14, przy większym oddaleniu powierzchnia uproszczona. Najdrobniejsza siatka ma odstęp około 12–19 m w Polsce. Sąsiednie kafle próbkują te same współrzędne na krawędziach. Maksymalnie 4 oczekujące pobrania terenu po stronie widoku i 2 równoległe pobrania źródłowe w backendzie; wspólne zapytania są scalane. Cache LRU backendu: maks. 96 odpowiedzi, 1 h; błędy: 30 s. Limity źródłowe: NMT 256 KB/kafel, drzewa 4 MB/kafel i 1200 rekordów/kafel.

Drzewa: kafel celu i cztery sąsiednie, ładowane dopiero po zmianie kafla. Maksymalnie 1800 drzew w scenie, dwa zestawy geometrii łączone w jeden prymityw GPU; brak osobnych encji/pętli animacji drzew. Nadmiar jest jawnie sygnalizowany. Wysokości podstaw drzew próbkowane raz z tego samego cache NMT. Kamera pojazdu zachowuje limit 30 FPS; mapa ogólna używa `requestRenderMode` i zasypia bez zmian. Rozdzielczość renderowania jest ograniczona na ekranach o wysokim DPI. Wyjście niszczy WebGL i anuluje żądania przeglądarki; ukrycie karty wstrzymuje nowe żądania i renderowanie.

Testy offline:

```sh
uv run --locked pytest -q tests/test_scene3d.py tests/test_aircraft_api.py tests/test_buses_api.py
# NODE_PATH wskazuje katalog zawierający playwright i pngjs
node --test --test-concurrency=1 tests/scene3d_browser.cjs tests/aircraft3d_browser.cjs tests/buses3d_browser.cjs
```

`test_scene3d.py` generuje autorskie rastry i rekordy miejskie; repozytorium nie zawiera pobranych danych miejskich ani NMT. Chromium używa prawdziwego Cesium/WebGL i syntetycznych odpowiedzi: sprawdza wysokość powierzchni, bryły drzew, podparcie autobusu i POV, mapę ogólną, zmianę miejsca, brak pollingu bez ruchu, obsługę awarii i zwalnianie zasobów. To nie jest benchmark sprzętowych GPU ani test innych przeglądarek.

Weryfikacja 03.11.2026: 16 testów Python (otoczenie i istniejące API pojazdów), 76 testów Node (ruch kamer/pojazdów i preferencje) oraz 16 wybranych scenariuszy Chromium/WebGL przeszło. Scenariusze obejmują mapę ogólną, otoczenie obu pojazdów, OSM, awarie źródeł/GPU, anulowanie, powrót do Atlasu przy dużym zbliżeniu i telefon 390 px. Obejrzano zrzuty sceny i telefonu. Nie stwierdzono błędów JS, naruszeń CSP ani nieoczekiwanych połączeń zewnętrznych w testach offline. Ruff i kontrola składni JS przechodzą. Osobny odczyt rzeczywistych źródeł dla małego kafla Warszawy: NMT 4225 próbek w 1,00 s, drzewa 0,37 s; odczyty z cache 0,008 / 0,010 ms. Wyniki dotyczą jednego odczytu, a nie gwarancji wydajności dostawców. Nie wykonano pomiarów na fizycznych telefonach ani osobnych przebiegów Safari/Firefox. Powiadomienie urzędu pozostaje czynnością operatora.
