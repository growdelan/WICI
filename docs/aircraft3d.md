# Śledzenie samolotu w 3D

W Lotnictwie włącz **Samoloty**, kliknij samolot na mapie i wybierz **Podążaj w 3D**. Przycisk jest dostępny dla pozycji nie starszej niż 30 s z podaną wysokością. Otwiera osobny widok CesiumJS. **Kamera zewnętrzna** oferuje regulację odległości 300–12 000 m i obrót wokół celu. **Pierwsza osoba** patrzy zgodnie z kursem lotu, 12° poniżej horyzontu; wymaga znanego kursu właśnie wyświetlanej pozycji. Nowszy raport z kursem nie odblokowuje POV, dopóki opóźnione odtwarzanie nie dosięgnie próbki o znanym kursie. Odblokowanie działa również między odczytami API; brak kursu ponownie wyłącza POV, zamiast kierować kamerę na północ. Model własnego samolotu jest wtedy ukryty. **Wróć do Atlasu** lub Escape zamyka widok i oddaje fokus przyciskowi w popupie, a gdy ten zniknął — mapie.

Atlas zachowuje swoją instancję Leaflet, kadr, warstwy, filtry i szczegóły. Na czas 3D wstrzymane jest automatyczne przesuwanie mapy przez popup samolotu, także przy dużym zoomie i nowych raportach. Jeżeli popup wyjdzie poza kadr, powrót zamyka go i ustawia fokus na mapie; kolejne odświeżenie nie przesuwa Atlasu. Popup pozostający w kadrze zachowuje fokus przycisku. Pierwotna opcja automatycznego przesuwania zostaje przywrócona, więc ponowne jawne otwarcie popupu działa normalnie. Nowy widok jest modalny: sterowanie aplikacją pod spodem nie zmienia przypadkowo śledzonego celu. Wyłączenie samolotów, przejście do Źródeł lub zmiana regionu zamyka śledzenie. Ukrycie karty wstrzymuje animację i odczyty; powrót wznawia je z oceną aktualności danych. Wyjście niszczy viewer i zwalnia zasoby WebGL. Nie powstaje drugi poller danych lotniczych.

## Podkład i zakres

Silnik i wszystkie jego zasoby są lokalne, ładowane dopiero przy pierwszym otwarciu. Nie trzeba Node, npm, konta Cesium ion ani klucza Google. Podstawą jest globus WGS84 z lokalnymi granicami województw PRG, siatką współrzędnych i podpisami kilku dużych miast. Powierzchnia jest uproszczona: **brak rzeźby terenu i budynków**, w tym fotogrametrii. To pierwszy etap funkcji kamery, nie kopia fotorealistycznego krajobrazu God's Eye View.

Ten sam renderer obsługuje także [autobusy w 3D](buses3d.md). W danej chwili istnieje jeden aktywny viewer; otwarcie innego rodzaju pojazdu zwalnia poprzedni. Odczyty i synchronizacja autobusów nie zmieniają śledzenia samolotu ani odwrotnie. Profil samolotu zachowuje własną wysokość, zakres kamery, aktualność i ograniczoną predykcję.

**Podkład OpenStreetMap (online)** jest opcjonalny i domyślnie wyłączony przy każdym otwarciu. Pobiera wyłącznie widoczne kafelki z `https://tile.openstreetmap.org/`, z widoczną atrybucją. Błąd kafelków nie usuwa lokalnych granic ani śledzenia. Obowiązują zasady dostawcy opisane w `THIRD_PARTY_NOTICES.md`. Aplikacja nie pobiera map hurtowo ani nie archiwizuje ich. W rzeczywistym DEMO nie ma danych lotniczych ani połączeń zewnętrznych; testy używają jawnie syntetycznych pozycji.

## Ruch, czas i utrata danych

Istniejący endpoint `/api/aircraft` i odczyt co 10 s pozostają wspólne dla mapy 2D i 3D. Bufor w pamięci przechowuje maksymalnie 32 raporty wybranego samolotu, według źródłowego `position_at`, bez trwałej historii. Duplikaty i raporty cofające czas nie zastępują przyjętych próbek. Przerwa ponad 30 s lub niefizyczny skok rozpoczyna nowy odcinek, bez rysowania lotu między odległymi punktami.

Oś wyświetlania jest opóźniona o 12 s. Po dwóch raportach pozycja jest interpolowana geodezyjnie, a kurs najkrótszym łukiem (także 359°→1°). Po wyjściu poza ostatni raport można przewidywać pozycję maksymalnie przez 5 s, jeśli znane są prędkość i kurs. Następnie obiekt zatrzymuje się na końcu tego odcinka, bez cofnięcia do ostatniego raportu. Jeden raport nie wystarcza do animacji. Osobna korekta pozycji renderowanej wygładza spóźnione raporty; kamera i model korzystają z tego samego punktu.

Wygładzanie uwzględnia rzeczywisty czas między kolejnymi klatkami, również przy 2 FPS i nieregularnym renderowaniu. Nie pomija zwykłego ruchu tylko dlatego, że klatka trwa ponad 250 ms. Jawne wstrzymanie albo przerwa klatek ponad 1 s rozpoczyna łagodne ponowne dopasowanie z ograniczonym pierwszym krokiem; nie nadrabia całego czasu ukrycia karty. Testy 60-sekundowego lotu przy 2, 3, 4, 5 i 30 FPS sprawdzają brak narastającej zaległości oraz zachowanie ograniczonej korekty po skoku źródła.

Błąd odczytu, brak celu w najnowszej odpowiedzi lub brak świeżej pozycji/wysokości natychmiast wstrzymuje ruch na ostatnio wyświetlonym punkcie. Sam wiek raportu jest kontrolowany również między odczytami. Po 30 s raport jest nieaktualny. Status rozróżnia oczekiwanie, interpolację, predykcję, zatrzymanie i błąd. Odzyskanie danych tego samego ID pozwala kontynuować; wyjście samolotu poza Polskę może zakończyć dostępność pozycji, ponieważ backend nadal ogranicza dane do Polski.

Błąd samego renderera (`scene.renderError`) lub utrata kontekstu GPU zatrzymuje pętlę do zamknięcia widoku. Nowe dane i synchronizacja widoczności nie wznawiają uszkodzonej sceny. WICI pokazuje jeden komunikat błędu i pozostawia powrót do Atlasu; wyłączono seryjne panele błędów wbudowanej pętli Cesium. Ponowne otwarcie tworzy nowy viewer i resetuje stan awarii. Listener błędu jest odpinany przy sprzątaniu.

Wysokość barometryczna jest przybliżeniem, a nie wysokością geometryczną nad elipsoidą. Rysowanie stosuje minimalną wysokość 100 m nad uproszczoną powierzchnią, aby kamera nie weszła w globus. Kurs względem ziemi wyznacza kierunek widoku; rzeczywiste przechylenie, pochylenie kadłuba i orientacja kabiny są nieznane. Nie odtwarzamy startu/lądowania na rzeczywistym modelu terenu. Brakujące dane nie są zastępowane zerem.

## Zasoby i CSP

CesiumJS 1.146.0 jest przypięty w `scripts/vendor_cesium.py`: archiwum npm jest sprawdzane SHA-256 przed rozpakowaniem, a manifest zawiera sumy każdego pliku i lokalną poprawkę globalnego lookupu Knockout. Aplikacja nigdy nie pobiera zależności podczas startu. Kontrola offline: `python scripts/vendor_cesium.py --check`. Odtworzenie: `python scripts/vendor_cesium.py` lub `--archive /ścieżka/cesium-1.146.0.tgz`.

JavaScript eval pozostaje zabroniony. CSP dopuszcza `wasm-unsafe-eval`, wymagane przez moduły WebAssembly inicjalizowane w lokalnym buildzie Cesium, oraz lokalne workery i ich bootstrap `blob:`. WICI wyłącza osadzony global `CESIUM_WORKERS` paczki IIFE, wymuszając dołączone lokalne moduły ESM; nie poszerza `script-src` o skrypty `blob:`. DOM-owe widżety Knockout są wyłączone; kontrolki WICI używają zwykłych zdarzeń. DEMO nie dopuszcza zewnętrznych origin; LIVE dopuszcza tylko istniejący dostawca rastra OSM. Nie dodano Google, ion, CDN ani dowolnego proxy URL.

Model `src/wici/static/models/aircraft.gltf` to autorska, schematyczna geometria WICI na licencji MIT, zbudowana deterministycznie przez `scripts/build_aircraft_model.py`. Nie przedstawia konkretnego typu samolotu; nie korzysta z cudzych modeli, tekstur, logo ani materiałów zewnętrznych. Osie modelu: nos +X, góra +Y, skrzydła ±Z; jednostka: metr. Odtworzenie i kontrola: `python scripts/build_aircraft_model.py` oraz `python scripts/build_aircraft_model.py --check`.

## Weryfikacja

Testy czystej matematyki i kamery używają deterministycznych zegarów i danych syntetycznych. Test lifecycle istniejącej warstwy sprawdza współdzielenie odczytu, świeżość przycisku i zachowanie węzła/fokusu popupu. Test Chromium uruchamia odizolowany serwer DEMO z zabronionym transportem zewnętrznym, podaje syntetyczny feed przez przechwytywanie żądań i używa prawdziwego lokalnego Cesium/WebGL. Zrzuty trafiają do ignorowanego `tmp/aircraft3d-evidence/`.

Regresje po review obejmują trzy przypadki: wyjątek rzucany przez rzeczywisty prymityw Cesium zatrzymuje renderowanie po jednym zdarzeniu, także po synchronizacji widoku i nowym raporcie; minutowy lot przy niskim FPS nie gromadzi opóźnienia; nowszy raport ze znanym kursem nie odblokowuje POV przed dojściem odtwarzania do tej próbki. Ostatni test przesuwa zegar odtwarzania przy niezmienionym znaczniku raportu i sprawdza kierunek kamery. Obie regresje przeglądarkowe odtworzyły błędy przed poprawką i przeszły po niej; testy ruchu sprawdzają też nieregularne klatki, korektę 805 m i wznowienie po 60 s.

Osobna regresja przy zoomie 14 sprawdza dwa raporty przemieszczające samolot poza kadr Atlasu. Mierzy środek mapy podczas 3D, przy powrocie i po kolejnym odświeżeniu, z tolerancją poniżej jednego piksela na zaokrąglenia Leaflet. Potwierdza równocześnie ruch kamery 3D, zamknięcie popupu poza kadrem, fokus na mapie oraz rzeczywiste automatyczne przesunięcie po ponownym jawnym otwarciu popupu. Test odtworzył usterkę przed poprawką.

```sh
uv run --locked pytest -q
uv run --locked ruff check .
node --test tests/*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs
node --test tests/aircraft3d_browser.cjs
python scripts/vendor_cesium.py --check
python scripts/build_aircraft_model.py --check
git diff --check
```

Do testu Chromium potrzebny jest opcjonalny moduł Playwright z przeglądarką; `NODE_PATH` może wskazywać jego katalog. Testy nie uruchamiają rzeczywistych kolektorów LIVE, nie sprawdzają pokrycia ADS-B ani dostępności usług. Awaria WebGL lub wczytywania silnika pozostawia działający przycisk powrotu do Atlasu. Brak danych ruchu i fotorealizmu nie jest zastępowany symulacją udającą pomiary.

Weryfikacja po poprawkach review 19.10.2026: **800 testów Python**, **227 testów Node** i **10 scenariuszy Chromium** zaliczonych. Chromium sprawdził rzeczywisty renderer WebGL 2, kamerę, utratę i odzyskanie danych, cofnięty raport, anulowanie ładowania, brak WebGL, zamykanie i zwalnianie zasobów, powrót do kadru/fokusu Atlasu, telefon 390 px w obu motywach oraz opcjonalny OSM na syntetycznych kafelkach. Nowe scenariusze sprawdziły trwałe zatrzymanie po błędzie renderera, dostępność POV według wyświetlanego kursu i zachowanie kadru Atlasu przy zoomie 14; 11 nowych testów Node objęło ruch przy niskim FPS i nieregularnych odstępach. W regresji kadru dwa raporty w 3D dały przesunięcie 0 px, powrót i kolejny odczyt — po 0,39 px zaokrąglenia; kamera 3D przemieściła się ponad 220 m, a ponowne jawne otwarcie popupu przywróciło normalne automatyczne przesunięcie mapy o 135 px. Nie wystąpiły nieoczekiwane błędy JavaScript, naruszenia CSP ani rzeczywiste połączenia zewnętrzne. Obejrzano zrzuty komputera i telefonu, w tym stan po błędzie renderera, POV po odblokowaniu kursu oraz śledzenie i powrót przy dużym zoomie. Oddzielny `check_night_ui.cjs` przeszedł dla Atlasu i WICI Noc w siedmiu szerokościach. Ruff, whitespace, manifest Cesium i struktura/powtarzalność modelu również przechodzą. Pozostają trzy dotychczasowe ostrzeżenia zależności Python. Nie wykonano osobnych przebiegów Safari/Firefox ani rzeczywistego testu usług LIVE.
