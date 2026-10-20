# Zalania satelitarne — Copernicus GFM

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Integracja lokalna, na żądanie. Osobne źródło od Copernicus EMS Rapid Mapping. Korzysta z gotowych produktów Global Flood Monitoring, bez obróbki surowych danych Sentinel-1. Zweryfikowano 17.10.2026: produkt historyczny `GFM v3.1.0` i bieżący `v4.1.1`, odczyt rzeczywistych rastrów oraz UI desktop/mobile.

## Użycie

1. `uv sync --locked`, następnie `uv run --locked python -m wici`.
2. W „Warstwy mapy” rozwiń „Zalania satelitarne — Copernicus GFM” i włącz warstwę (domyślnie wyłączona).
3. Pozostaw domyślny tryb **„Automatycznie · Polska”**. Nie wybierasz obserwacji: WICI przegląda produkty z ostatnich 48 godzin, sprawdza katalog co 10 minut i odczytuje kolejne sceny. Pierwszy pełny przegląd może potrwać kilka minut. Panel pokazuje liczbę przetworzonych produktów i błędy/brakujące maski.
4. Różowe punkty wskazują grupy rzeczywistych detekcji w blokach źródłowych około 10 km; punkt **nie jest obrysem ani powierzchnią zalania**. Przybliż mapę do poziomu 10 lub kliknij „Przybliż wykrycia”, aby zobaczyć rzeczywistą geometrię pikseli 20 m. Widok nie przestawia się sam przy nowych danych. Kliknięcie pokazuje czas, wiek, produkt, jakość i źródło. Przezroczystość działa dla obu trybów.
5. Nowe sceny trafiają na mapę po publikacji w GFM, następnym sprawdzeniu katalogu i odczycie. Brak punktów podczas przeglądu, awarii lub bez pokrycia nie dowodzi braku powodzi. Brakujące wymagane maski są jawnie pomijane. Mapa zawiera obserwacje o różnych czasach, podanych w dymkach.
6. Archiwum: wybierz „Wybrana obserwacja / archiwum”. Przybliż obszar do maks. 0,5° × 0,5°, wybierz do 15 dni UTC, wyszukaj i wybierz obserwację (jedna strona, do 24 produktów). „Ostatnie 7 dni” ustawia daty. Przycisk próby historycznej od razu przełącza tryb, wyszukuje stały obszar Kłodzka (16,55–16,75°E / 50,35–50,55°N, 14–17.09.2024) i wczytuje obserwację 15.09.2024 05:01:49 UTC, także na szerokim ekranie. Powrót do „Automatycznie · Polska” wznawia nowe dane.
7. Włącz osobno wodowskazy i ostrzeżenia hydrologiczne IMGW. Ich znaczniki i dymki pozostają nad GFM. Nie wyznaczamy związku ostrzeżenia z wykryciem ani geometrii zlewni.

Czas GFM jest niezależny od dnia publikacji i filtra województwa. Automatyczny przegląd dotyczy całej Polski, a przesunięcie mapy dobiera szczegóły z pamięci. Wyłączenie warstwy, ukrycie karty lub wyjście z mapy zatrzymuje odpytywanie, przerywa trwające żądanie HTTP i blokuje jego ponowienia po błędzie sieci. Spóźnione odpowiedzi są unieważniane. Rozpoczęty odczyt jednego produktu może dokończyć ograniczoną pracę; kolejne nie startują bez aktywnego klienta. Po powrocie tryb automatyczny wznawia pracę. W archiwum nakładka pozostaje w wybranym obszarze; ponów wyszukiwanie po przesunięciu, a po ukryciu wybierz obserwację ponownie.

## Automatyczny przegląd Polski

`GET /api/gfm/monitor` uruchamia najwyżej jeden krok pracy i zwraca aktualny stan bez czekania na cały kraj. UI odpytuje co 3 s podczas pracy i co 30 s poza nią; katalog dostawcy ma własny interwał 10 min. Parametr `bbox` dotyczy szczegółów mapy, nie zakresu odkrywania produktów. Katalog zawsze używa ramki 14–24,3°E / 49–55°N, a natywne piksele są ograniczone do lokalnych poligonów województw PRG (środek piksela wewnątrz Polski).

Sceny są odczytywane od najnowszych. Dla tej samej siatki źródłowej nowsza poprawna ocena zastępuje starszą detekcję, także gdy nowsza klasa oznacza brak detekcji, wodę referencyjną albo wykluczenie. Nowsze NoData nie kasuje ostatniej poprawnej oceny. Zachowane wykrycie ma zawsze czas swojej obserwacji; po 48 h znika, a po 24 h jest oznaczone jako nieaktualne. Różnych siatek nie utożsamiamy. To zestaw ostatnich dostępnych ocen pikseli, bez obietnicy jednoczesnego pokrycia kraju. Poszczególne przeloty, poprawki dostawcy oraz błędy odczytu mogą zmieniać obraz w toku przeglądu.

Zmiana metadanych lub assetów tego samego produktu nie usuwa ostatniej poprawnie odczytanej wersji. Jej piksele i pokrycie (także ocena bez zalania) pozostają do udanego odczytu nowej wersji; nieudany odczyt ani brak maski nie przywracają starszego zalania. Nowa wersja zastępuje poprzednią w całości dopiero po sukcesie, z zachowaniem jej własnych metadanych. Licznik przetworzonych produktów dotyczy wersji aktualnie wskazanych w katalogu, więc podczas zastępowania wynik jest częściowy. Zachowana wersja nadal podlega oknu 48 h i limitowi cache.

Odczyt odbywa się blokami 512 × 512 na natywnej siatce 20 m, z wymaganymi maskami i dostępną jakością. Nie ma zmniejszania obrazu przed wyszukaniem pozytywnych pikseli. Po przybliżeniu źródłowe kwadraty są przeliczane z Equi7 do WGS84 jako poligony; nawet widok mniejszy od piksela zachowuje przecinającą go geometrię. Na poziomie kraju widać wyłącznie lokalizacje grup, bez udawania zasięgu na podstawie obrysu kafla.

| Zasób automatyczny | Limit |
| --- | --- |
| Okno czasu i katalog | 48 h; co 10 min, do 4 stron × 24 produkty; do 45 s; 3 MiB JSON na stronę |
| Jeden odczyt produktu | 24 MiB łącznie, do 512 żądań Range po 64 KiB, deadline 40 s + trwający odczyt do 8 s |
| Raster / tablice | do 15000 × 15000 pikseli źródła, blok roboczy 512²; maski wyrównywane nearest neighbour |
| Przechowywane detekcje | do 250000 pikseli na produkt, dalsze pokrycie nadal oceniane; przekroczenie jawnie oznaczone |
| Cache krajowy | do 64 MiB pikseli i skompresowanego pokrycia w RAM; najstarsze obserwacje usuwane pierwsze |
| Odpowiedź mapy | do 2000 grup, 20000 pikseli geometrii szczegółowej, 4 MiB JSON; ograniczenie jawnie oznaczone |
| Współbieżność | wspólna blokada z archiwum, jeden worker dostawcy; przetwarzanie poza pętlą FastAPI |
| Błędy | pozostałe poprawne wyniki zachowane, ponowienie produktu po 10 min; co najmniej 60 s po błędzie źródła, respektowane Retry-After |
| Życie pracy | wyłącznie żądania aktywnej warstwy; bez demona, autostartu, schedulera i trwałego archiwum |

Początkowy przegląd całej Polski wymaga większego transferu niż pojedyncza próba Kłodzka. Ruch mapy korzysta z odczytanych scen, nie pobiera wszystkich rastrów od nowa. Limity, brak masek i awarie oznaczają wynik częściowy. Stan `processed/products` opisuje postęp katalogu, nie procent powierzchni kraju z obserwacją. Demo pozostaje offline.

## Źródło, kontrakt i prawa

- Oficjalne [STAC EODC](https://stac.eodc.eu/api/v1), [kolekcja GFM](https://stac.eodc.eu/api/v1/collections/GFM), `GET /search?collections=GFM&bbox=...&datetime=...&limit=24`.
- [Oficjalny przykład odkrywania danych](https://www.docs.eodc.eu/notebooks/gfm-download.html), [wiki GFM](https://extwiki.eodc.eu/en/GFM), [Product User Manual, V20251201](https://extwiki.eodc.eu/gfm_assets/gfm4.0_pum_2025.pdf), rozdziały 3 i 7.1.4.
- Kolekcja deklaruje **`license: proprietary`**, licencjodawcę JRC CEMS oraz procesora/host EODC. Nie zamieniamy tego wpisu na CC BY na podstawie publicznego dostępu.
- PUM odsyła do [warunków CEMS](https://global-flood.emergency.copernicus.eu/terms-of-service/) (odczytane 17.10.2026, strona z aktualizacją 29.07.2026). Dopuszczają dostęp, reprodukcję, dystrybucję i modyfikację z oznaczeniem źródła i zmian; odrębne dane stron trzecich mogą mieć inne warunki. Dane są informacyjne, bez gwarancji, i nie stanowią urzędowego ostrzeżenia.
- Dla przeliczonego i pokolorowanego produktu UI i mapa podają `Contains modified Copernicus Emergency Management Service information [YYYY]`, gdzie YYYY jest rokiem obserwacji. Kolory, próbkowanie i reprojekcja: WICI. Obecne próbki w repozytorium są syntetyczne i oznaczone jako własne dane testowe WICI na MIT.

Nie korzystamy z `thumbnail` ani `tilejson` jako detekcji. Backend przyjmuje wyłącznie lokalny identyfikator uzyskany z ograniczonego wyszukiwania. Zachowuje `id`, `processing:version`, `processing:lineage`, `processing:facility`, linki `derived_from`, źródłowy URL STAC i metadane assetów. Nazwy plików, ścieżki i CRS pochodzą ze źródła.

## Czasy

| Pole lokalne | Pole źródłowe / znaczenie |
| --- | --- |
| `observed_at` | STAC `properties.datetime`: obserwacja Sentinel-1, z wymaganą strefą, normalizowana do UTC |
| `processed_at` | `processing:datetime`, brak pola pozostaje brakiem informacji |
| `catalog_created_at` | `created`: utworzenie wpisu STAC; nie czas przelotu |
| `fetched_at` | lokalny czas pobrania metadanych |
| `rendered_at` | lokalny czas zakończenia odczytu rastrów i renderowania; cache zachowuje pierwotny czas |

UI pokazuje czas polski, wiek w godzinach i etykietę archiwalności powyżej 24 h (konwencja WICI, nie próg dostawcy). Wiek i status są przeliczane z czasu obserwacji i bieżącego zegara przeglądarki co minutę oraz przy synchronizacji widoku, także gdy odpowiedź pochodzi z cache. Nie wymagają kolejnego pobrania ani ponownego wyboru obserwacji; wyłączenie warstwy, zmiana dat lub obserwacji i ukrycie widoku zatrzymują zegar poprzedniego wyniku. Obserwacje radarowe są możliwe nocą i przez chmury, ale wymagają przelotu. Około 8 godzin oznacza docelowe udostępnienie po obserwacji przy terminowej dostawie danych; **nie aktualizację co 8 godzin**.

## Piksele i jakość

Podstawa to `ensemble_flood_extent`. Obowiązkowe są też `reference_water_mask` i `exclusion_mask`; odczytujemy dostępne `advisory_flags` i `ensemble_likelihood`.

| Klasa nakładki | Warunek i znaczenie |
| --- | --- |
| Różowa: zalanie | Flood = 1, reference = 0, exclusion = 0; detekcja w chwili obserwacji |
| Niebieska: woda referencyjna | Reference = 1 lub 2, poprawne pozostałe maski; stała lub sezonowa woda odniesienia |
| Brązowoszara: wykluczenie | Exclusion = 1 przy poprawnych maskach; piksel nie służy do wnioskowania o braku zalania |
| Jasnoszara: brak obserwacji | NoData = 255 w dowolnej wymaganej warstwie albo nierozpoznana wartość; obejmuje obszar poza pokryciem danej sceny |
| Bladozielona: ocenione bez detekcji | Flood = 0, reference = 0, exclusion = 0 |

NoData ma pierwszeństwo, następnie wykluczenie, woda referencyjna i zalanie. To ostrożne łączenie masek; piksel z nieznaną klasą nie staje się „suchy”. Brak produktów w ograniczonym katalogu, brak pokrycia w rastrze, obszar wykluczony, woda referencyjna, brak detekcji w ocenionych pikselach i awaria mają osobne komunikaty. Wynik może zawierać mieszaninę klas; liczniki pokazują wszystkie. Status detekcji jest liczony z pełnej siatki źródłowej zalania 20 m (`source_counts`), po zastosowaniu pozostałych masek i ograniczeniu do pikseli, których powierzchnia przecina wybrany obszar (`all_touched=True`). Piksel jest liczony raz, także przy częściowym przecięciu; liczniki nie oznaczają powierzchni zalania. Ta sama zasada obowiązuje przy granicy obszaru i dla obszarów mniejszych niż piksel 20 m — brak środka piksela w obszarze nie oznacza braku obserwacji. Drobne wykrycie pominięte przy zmniejszaniu obrazu nie powoduje statusu „brak detekcji”; panel wskazuje wtedy potrzebę przybliżenia mapy.

Dostawca nie zawsze publikuje wszystkie assety: podczas próby 17.10.2026 część wpisów nie miała `exclusion_mask`. Takie obserwacje pozostają widoczne na liście z podaniem brakującej maski, ale nie można ich renderować. Nie dopisujemy URL ani nie zastępujemy maski zerami.

Advisory flags: 0 brak flag, 1 niski regionalny backscatter (m.in. mróz, śnieg lub sucha gleba), 2 szorstka powierzchnia wody, 3 obie flagi, 255 NoData. Panel pokazuje histogram próbek; flagi nie są maską wykluczenia. Likelihood: wskaźnik klasyfikacji 0–100, z granicą klas 50 i NoData 255; panel pokazuje zakres oraz liczbę braków. **Nie jest prawdopodobieństwem przyszłej powodzi.** Panel rozdziela liczniki próbek obrazu (`counts`) i pikseli źródłowych (`source_counts`); histogramy jakości dotyczą próbek obrazu. Liczniki nie są obliczeniem powierzchni terenu.

Piksel źródłowy ma 20 m. Detekcja jest ograniczona m.in. przez zabudowę, gęstą roślinność, cienie radarowe i rzeźbę terenu. Brak detekcji nie potwierdza bezpieczeństwa ani braku powodzi. Nie wyznaczamy głębokości wody ani przejezdności dróg.

## Renderowanie archiwum, zasoby i bezpieczeństwo

Minimalne bezpośrednie zależności: Rasterio (GDAL/PROJ z koła uv) oraz NumPy. PNG RGBA powstaje przez standardowe `zlib`/`struct`; bez Pillow, geopandas, xarray, serwera kafelków czy instalacji globalnych.

Rasterio używa własnego otwieracza pliku `RangeReader`, a nie pełnego `MemoryFile` zdalnego TIFF. Każdy odczyt to blok 64 KiB przez HTTP Range; wymagamy poprawnego 206, `Content-Range` i długości. Brak Range kończy się jawnym błędem; nie ma automatycznego pobrania całego pliku. Zweryfikowana maska referencyjna jest TIFF paskowym (1 × 15000), mimo deklaracji COG w STAC; odczyt działa także dla niej. Limit bloku dekodowanego wynosi 1 048 576 pikseli.

CRS i transformację czytamy z rastra Equi7Grid (dla sprawdzonej Polski: azimuthal equidistant). GDAL WarpedVRT przelicza do EPSG:3857; **nearest neighbour** dla każdej warstwy. Do Leaflet ImageOverlay trafia obraz z granicami WGS84 dokładnie odpowiadającymi docelowej siatce Web Mercator. Cały kafel 15000 × 15000 nie jest ładowany jako tablica. Dodatkowa ocena wszystkich wymaganych masek na siatce natywnego zalania obejmuje jedynie ograniczony fragment do 4 mln pikseli, również po zaokrągleniu okna do pełnych pikseli. Maski są wyrównywane najbliższym sąsiadem, a piksele poza obszarem zainteresowania nie wpływają na podsumowanie. Nakładka nadal jest próbkowana najbliższym sąsiadem do rozmiaru widoku.

| Zasób | Limit |
| --- | --- |
| STAC | 1 strona, 24 produkty, 3 MiB JSON; 12 s timeout I/O, 15 s całego odczytu |
| Obszar | do 0,5° × 0,5°; do 4 mln pikseli w prostokącie źródłowym każdej warstwy |
| Raster | pojedyncze pasmo uint8, NoData 255, rozdzielczość 20 m |
| Transfer jednego renderu, wszystkie warstwy | 24 MiB, do 160 żądań Range, 8 s timeout I/O, kontrola deadline 40 s między odczytami |
| Obraz wynikowy | do 768 × 768; siatka może mieć różne rozmiary piksela x/y, pozostaje poprawnie georeferencyjna |
| Współbieżność | jeden job dostawcy naraz, wspólna blokada i cache dla identycznych żądań; czekanie do 55 s |
| Praca kosztowna | osobny wątek `asyncio.to_thread`, bez blokowania pętli FastAPI; anulowanie klienta nie zwalnia blokady przed zakończeniem worker |
| Cache w RAM | wspólne maks. 12 wyników: STAC 10 min, render 30 min; do 288 zarejestrowanych produktów przez 1 h; fragmenty Range tylko w czasie renderu |
| Backoff | rosnący 20–640 s po awariach, `Retry-After` liczbowy lub HTTP-date respektowany do 1 h; bez cyklicznego odpytywania archiwum; wspólny transport może ponowić odczyt do 3 razy po błędzie połączenia, odpowiedzi HTTP z błędem nie są ponawiane automatycznie |

Błędy czytnika zdalnego są zapamiętywane w budżecie danego zadania. Callback odczytu GDAL zwraca wówczas krótki odczyt, a wyjątek jest zgłaszany dopiero poza natywnym callbackiem. Zapobiega to komunikatom „Exception ignored in rasterio._err.log_error”; także pozornie udany odczyt z zapamiętanym błędem jest odrzucany. Osobne komunikaty rozróżniają limit transferu, liczbę żądań, czas i błąd sieci. Panel zachowuje poprzednie poprawne oceny i pokazuje przyczynę błędu. Limitów nie zwiększono.

Geometria pikseli w trybie automatycznym jest tworzona z małego, jawnie georeferencyjnego rastra w pamięci (512²), przekazanego jako pasmo do polygonizacji. Nie tworzy pomocniczych datasetów przez `shapes(ndarray, mask=...)` i nie wycisza globalnie ostrzeżeń. CRS i transformacja nadal pochodzą ze zweryfikowanego produktu. Testy równoległej polygonizacji sprawdzają brak `NotGeoreferencedWarning` i dokładne współrzędne pikseli 20 m.

Deadline jest kooperacyjny; trwający odczyt HTTP może dołożyć do 8 s. Każdy fragment jest ograniczony rozmiarem, więc serwer bez Range nie wywoła pełnego transferu. Cache nie jest trwałym archiwum. Maksymalna pamięć zależy od treści PNG, ale liczba wyników i rozmiar wejścia/wyjścia są ograniczone.

Akceptowane assety: wyłącznie HTTPS, dokładny host `data.eodc.eu`, ścieżka `/collections/GFM_… .tif` z ograniczonym alfabetem, bez portu, danych logowania, query, fragmentu i `..`. Przekierowania STAC i rastrów są odrzucane. Pomocnicze pliki GDAL są wyłączone; opener odrzuca ścieżki inne niż dokładnie zarejestrowany asset. API nie przyjmuje URL zasobu. Obowiązują dotychczasowe kontrole Host i same-origin. Nie dodano migracji SQLite ani zadań schedulera.

Konfiguracja w `config.local.toml` (po zmianie restart aplikacji):

```toml
[sources.gfm]
enabled = true
```

`enabled = false` wyłącza sieć źródła. W trybie `--demo` zawsze zwracamy **„Demo offline: brak danych GFM”**, bez sieci i bez podszywania próbek rzeczywistych pod aktualne dane. Testy przeglądarkowe wstrzykują autorską szachownicę i syntetyczne metadane oraz fixture hydrologiczne; to nie zachowanie domyślnego demo.

## Weryfikacja i odtworzenie

Połączenie z dostawcą jest potrzebne wyłącznie do ponowienia prób rzeczywistych:

```sh
uv run python scripts/check_gfm.py
uv run python scripts/check_gfm.py --current
```

Szczegółowe wyniki historycznego odczytu live usunięto 18.10.2026. Ponowne sprawdzenie zapisuje wyniki lokalnie w `tmp/live-checks/`.

Szczegółowe wyniki historycznego odczytu live usunięto 18.10.2026. Ponowne sprawdzenie zapisuje wyniki lokalnie w `tmp/live-checks/`.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

```sh
uv run pytest -q
node --test tests/ui_*.test.cjs tests/imagery_ui.cjs
uv run ruff check .
# Playwright z już dostępnego lokalnego runtime, bez globalnej instalacji:
NODE_PATH=/ścieżka/do/node_modules node --test tests/gfm_browser.cjs
```

Regresje po review obejmują pojedynczy źródłowy piksel zalania pomijany przez nakładkę (na tle ocenionym i NoData), zastosowanie masek do podsumowania natywnego i wykluczenie detekcji całkowicie poza wybranym obszarem. Dodatkowo sprawdzane są obszary około 1 m wewnątrz piksela, bez zawierania jego środka: zalanie, piksele bez detekcji, maski referencyjna i wykluczenia oraz rzeczywiste NoData, a także mały obszar przecinający dwa sąsiednie piksele. Testy Node przesuwają zegar przez próg 24 h, sprawdzają aktualizację podczas synchronizacji i z cache, zachowanie obrazu bez dodatkowych żądań oraz usuwanie timerów po wyłączeniu, ukryciu, zmianie wyboru i awarii obrazu.

Testy Python obejmują kontrakt i czasy STAC, klasy/maski/NoData, rzeczywistą reprojekcję GDAL na syntetycznym rastrze Equi7, cache i współdzielenie, limity, 206/redirecty/hosty, backoff i Retry-After, brakujące maski i offline API. Testy Node obejmują istniejące warstwy i obsługę żądań. Playwright sprawdza prawdziwy Leaflet w 1440 × 1000, 390 × 844 i 2804 × 1756: brak żądań przy wyłączonej warstwie, jednoklikową próbę historyczną ze stałym AOI także przy widoku przekraczającym 0,5° szerokości, wyszukiwanie/wybór, obraz, regulację widoczności, IMGW i dymki, ostrzeżenia, wyścig odpowiedzi po zmianie obserwacji i wyłączeniu, brak żądań zewnętrznych i błędów JS. Zrzuty `desktop.png`, `mobile.png` i warianty `*-map.png` zapisują ten kontrolowany scenariusz.

W jednej próbie równoczesnego uruchomienia dwóch plików przeglądarkowych istniejący test `hydro_browser.cjs` przekroczył czas oczekiwania przy usuwaniu stacji po symulowanej awarii. Ponowiony osobno przeszedł; testy GFM desktop/mobile przeszły również w próbie równoległej. Przyczyny niestabilności tamtej próby nie potwierdzono. Zachowano osobne wyniki końcowe w `hydro-browser-tests.txt` i `browser-tests.txt`.

## Weryfikacja automatycznego trybu (17.10.2026)

Regresje automatyki: natywne pojedyncze detekcje, maski i jakość, nowsza ocena bez zalania, zachowanie przy NoData, wygaśnięcie po 48 h, detale mniejsze od piksela, paginacja i jej host, limity, współdzielony worker, brak kolejnego zadania bez klienta, Retry-After i demo. Node sprawdza samoczynne odpytywanie, zmianę wyniku, debounce mapy, przezroczystość, błędy i zatrzymanie timerów/ignorowanie spóźnionych odpowiedzi. Playwright sprawdza domyślny tryb bez ręcznego wyboru, geometrię po przybliżeniu, automatyczne usunięcie wygaszonego wykrycia i wyłączenie podczas trwającego żądania, na desktopie i telefonie. `auto-desktop.png` i `auto-mobile.png` pokazują jawny syntetyczny scenariusz UI, a nie rzeczywistą powódź.

Test ręczny: uruchom aplikację LIVE, włącz warstwę, obserwuj rosnący licznik przetworzonych produktów, przybliż różowy punkt i otwórz dymek z czasem. Przesuń mapę i porównaj piksele, wyłącz warstwę i sprawdź w narzędziach przeglądarki ustanie `/api/gfm/monitor`. Po powrocie do trybu automatycznego praca powinna się wznowić. Publikacji nowej sceny przez dostawcę nie da się wymusić ręcznie; ten przypadek pokrywają kontrolowane testy regresji zmiany rewizji danych.

Szczegółowe wyniki historycznego odczytu live usunięto 18.10.2026. Ponowne sprawdzenie zapisuje wyniki lokalnie w `tmp/live-checks/`.

Końcowy Playwright: 5/5 scenariuszy GFM (archiwum na trzech rozmiarach, automatyka desktop/mobile) — zaliczone. Dodatkowa regresja stanu bezczynności potwierdza, że po przetworzeniu katalogu nie startują puste zadania i panel nie pokazuje fałszywego odczytu w toku (18 testów modułu monitorowania).
