# Third-party notices

Licencja [MIT](LICENSE) dotyczy własnego kodu WICI i pozwala również na jego komercyjne wykorzystanie, modyfikowanie i rozpowszechnianie zgodnie z jej warunkami. Niekomercyjny charakter projektu nie dodaje ograniczeń do MIT. Biblioteki, geometrie, teksty, próbki odpowiedzi i obrazy zewnętrzne zachowują własne licencje oraz warunki, a dostęp do usług podlega regulaminom dostawców.

## Zakres licencji i ograniczeń

- **Kod WICI:** MIT, także do zastosowań komercyjnych. Ograniczenia konkretnych zasobów nie stanowią ogólnego zakazu komercyjnego użycia odrębnego kodu WICI.
- **Dołączone materiały:** należy zachować właściwą licencję, wymagane oznaczenia autorstwa i pochodzenia oraz informacje o zmianach. Dla materiałów na CC BY-NC-SA obowiązują dodatkowo użytek niekomercyjny i ShareAlike dla adaptacji; MIT kodu nie znosi tych wymagań.
- **Usługi i dane pobierane live:** prawo do kodu klienta API nie gwarantuje prawa do korzystania z usługi w każdym celu ani do dalszego udostępniania pobranych danych. Licencja danych i regulamin dostępu do API mogą mieć różny zakres, jak w przypadku Open-Meteo.
- **Użycie komercyjne:** należy uzyskać wymagane uprawnienia do ograniczonych zasobów i usług albo je usunąć, zastąpić lub wyłączyć odpowiednią integrację. Przy rozpowszechnianiu paczek samo wyłączenie funkcji nie usuwa dołączonych materiałów i ich obowiązków licencyjnych.
- **Niepotwierdzone prawa:** wpis w tym wykazie, publiczny dostęp do API ani cel niekomercyjny nie stanowią samodzielnego zezwolenia na kopiowanie lub redystrybucję. Nierozstrzygnięte przypadki są wskazane poniżej i w audycie; nie oznaczamy ich jako materiałów dopuszczonych do dowolnego użytku niekomercyjnego.

Aktualizacja z 18.10.2026: rzeczywiste próbki i skopiowane dokumenty zastąpiono autorskimi fixture, a źródłowe dane i obrazy usunięto z raportów oraz archiwum. Usunięto też narzędzie zależne od PyMuPDF. Pozostają odrębne warunki bibliotek, geometrii PRG i maski EEA/VLIZ oraz usług live. Nie należy traktować całego repozytorium lub jego paczek jako zawierających wyłącznie materiały MIT. Historia pierwotnego repozytorium nie została przepisana i nie jest dołączona do tej kopii. Ta kopia rozpoczyna nową historię Git. Szczegóły: [audyt licencji](docs/license-audit.md).

## Wykaz zasobów, bibliotek i usług

| Zasób / zależność | Licencja / warunki | Pochodzenie |
|---|---|---|
| Leaflet 1.9.4, JS/CSS/ikony | BSD-2-Clause; pełna wymagana treść [LICENSE](src/wici/static/vendor/leaflet/LICENSE) | [Leaflet](https://leafletjs.com/), dystrybucja `leaflet@1.9.4/dist` |
| CesiumJS 1.146.0, lokalny silnik 3D i zasoby runtime | Apache-2.0 oraz odrębne licencje komponentów i zasobów: pełne teksty i oznaczenia w [LICENSE.md](src/wici/static/vendor/cesium/LICENSE.md), wykaz dostawcy w [ThirdParty.json](src/wici/static/vendor/cesium/ThirdParty.json). Zachowano nagłówki oryginalnych plików i logo/atrybucję Cesium w widoku | [CesiumJS](https://github.com/CesiumGS/cesium), przypięte `cesium@1.146.0/Build/Cesium`; pochodzenie i sumy SHA-256 w [VENDOR.json](src/wici/static/vendor/cesium/VENDOR.json), odtwarzanie przez `python scripts/vendor_cesium.py` |
| Podkład OpenStreetMap, standardowe kafelki raster | Dane OSM: ODbL; kartografia i warunki użycia według [copyright](https://www.openstreetmap.org/copyright) oraz [polityki kafelków OSMF](https://operations.osmfoundation.org/policies/tiles/). Widoczna atrybucja © OpenStreetMap contributors, bez archiwizacji kafelków i bez trybu pobierania offline | [OpenStreetMap](https://www.openstreetmap.org/), kafelki `https://tile.openstreetmap.org/{z}/{x}/{y}.png` |
| PRG, województwa/powiaty | GUGiK: dane bezpłatne do dowolnego wykorzystania; wskazano pochodzenie, przetworzenie i datę | [Geoportal PRG](https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/), [lokalne metadane](src/wici/static/geo/metadata.json) |
| TomTom Orbis Traffic, kafelki raster płynności ruchu | Usługa komercyjna z darmowym limitem, według warunków konta/API; bez deklaracji otwartej licencji danych. Atrybucja © TomTom na mapie; pamięciowy cache ograniczony nagłówkami dostawcy, bez archiwizacji | [TomTom](https://www.tomtom.com/copyright/), [API](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/traffic-flow/raster-flow-tiles), [cennik](https://docs.tomtom.com/pricing) |
| Utrudnienia GDDKiA, publiczny XML | Oficjalna specyfikacja dopuszcza pobieranie przez zainteresowane osoby i instytucje; nie deklaruje się otwartej licencji całego XML. Atrybucja GDDKiA i odnośnik do źródła, opis normalizacji i ograniczeń w dokumentacji | [Publiczne dane GDDKiA](https://www.gov.pl/web/gddkia/dane-xml), [specyfikacja XML v1.1](https://www.gov.pl/attachment/0c47ae2a-7fca-459d-8ebe-a2b9ead424d7), [XML utrudnień](https://www.archiwum.gddkia.gov.pl/dane/zima_html/utrdane.xml) |
| Prognoza FWI EFFIS / ECMWF | [CC BY 4.0](https://forest-fire.emergency.copernicus.eu/about-effis/data-license), o ile źródło nie zastrzega inaczej; wskazano pochodzenie i przetworzenie | EFFIS / Copernicus EMS / European Commission JRC; model ECMWF; lokalny zakres Polski i projekcja EPSG:3857, przezroczystość w UI |
| Satelitarne obserwacje NASA FIRMS / VIIRS | Otwarte dane FIRMS według [FAQ NASA](https://forum.earthdata.nasa.gov/viewtopic.php?t=5184); zachować źródło/cytowanie produktu i informacje o przetworzeniu. Nie oznacza to licencji na wszystkie treści portalu | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), [API](https://firms.modaps.eosdis.nasa.gov/api/area/); lokalne filtrowanie PRG i zapis historii |
| Dane IMGW-PIB | [Regulamin IMGW §5](https://danepubliczne.imgw.pl/apiinfo): dane wysokiej wartości mogą służyć każdemu celowi; dla pozostałych danych ta oferta przewiduje użycie prywatne. Obowiązkowe źródło i oznaczenie przetworzenia; nie przypisujemy automatycznie jednej licencji wszystkim PDF/HTML | Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy; [zakres HVD w rozporządzeniu 2023/138](https://eur-lex.europa.eu/eli/reg_impl/2023/138/oj/eng) |
| Kafelki radaru RainViewer | Bezpłatne publiczne API do użytku osobistego i edukacyjnego; bez deklaracji otwartej licencji/SLA. Widoczna atrybucja „Weather data by RainViewer”, pamięciowy cache i ograniczony lokalny zakres/zoom | [RainViewer API](https://www.rainviewer.com/api.html), [zmiany i limity 2026](https://www.rainviewer.com/api/transition-faq.html), [kolory](https://www.rainviewer.com/api/color-schemes.html) |
| Prognoza Open-Meteo | Dane CC BY 4.0; publiczne darmowe API do użytku niekomercyjnego, bez gwarancji dostępności. Zachowano atrybucję i oznaczenie przetworzenia | [Open-Meteo](https://open-meteo.com/), [licencja](https://open-meteo.com/en/licence), [warunki](https://open-meteo.com/en/terms); wybór punktów siatki Polski, wizualizacja kierunku i konwersja czasu w UI |
| RSO | Publiczny kanał do [integracji](https://komunikaty.tvp.pl/Info/Integration); nie deklaruje się otwartej licencji całego tekstu | Regionalny System Ostrzegania / TVP |
| Teksty RCB Gov.pl | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), o ile źródło nie zastrzega inaczej; zachować autorstwo/odnośnik/licencję i oznaczenie przetworzenia | Rządowe Centrum Bezpieczeństwa / [Gov.pl](https://www.gov.pl/web/rcb) |
| Teksty SG | Kopiowanie z powołaniem na źródło zgodnie z [warunkami SG](https://www.strazgraniczna.pl/pl/pozostale-informacje/prawa-autorskie/2316,Prawa-autorskie.html) | Komenda Główna Straży Granicznej |
| FastAPI / Starlette / Uvicorn | MIT / BSD-3-Clause / BSD-3-Clause | [FastAPI](https://github.com/fastapi/fastapi), [Starlette](https://github.com/encode/starlette), [Uvicorn](https://github.com/encode/uvicorn) |
| HTTPX / HTTPCore / h11 / AnyIO | BSD-3-Clause / BSD-3-Clause / MIT / MIT | [HTTPX](https://github.com/encode/httpx), projektowe metadane zainstalowanych pakietów |
| Pydantic / pydantic-core / annotated-types / typing-extensions / typing-inspection | MIT / MIT / MIT / PSF-2.0 / MIT | [Pydantic](https://github.com/pydantic/pydantic), metadane pakietów |
| Beautiful Soup 4 / SoupSieve | MIT / MIT | [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/), metadane pakietów |
| pypdf (parser PDF podczas pracy) | BSD-3-Clause, potwierdzone metadanymi dystrybucji | [pypdf](https://github.com/py-pdf/pypdf) |
| annotated-doc / opentelemetry-api | MIT / Apache-2.0 (potwierdzone metadanymi zainstalowanych dystrybucji) | Metadane pakietów |
| Click / idna | BSD-3-Clause / BSD-3-Clause | Metadane pakietów |
| certifi | MPL-2.0 (certyfikaty; niezależna licencja) | [certifi](https://github.com/certifi/python-certifi) |
| pytest / pytest-asyncio / pluggy / iniconfig / packaging / Pygments | MIT / Apache-2.0 / MIT / MIT / BSD-2-Clause or Apache-2.0 / BSD-2-Clause | Metadane pakietów narzędzi deweloperskich |
| Colorama 0.4.6 (warunkowa zależność testów na Windows) | BSD-3-Clause | [Pełny tekst autora](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt), wpis w `uv.lock`; nie jest instalowana na macOS |
| Ruff / Hatchling | MIT / MIT | [Ruff](https://github.com/astral-sh/ruff), [Hatch](https://github.com/pypa/hatch) |
| pathspec / tomlkit / trove-classifiers (zależności narzędzia budowania Hatchling) | MPL-2.0 / MIT / Apache-2.0 | [pathspec](https://github.com/cpburnz/python-pathspec), [tomlkit](https://github.com/python-poetry/tomlkit), [trove-classifiers](https://github.com/pypa/trove-classifiers); build nie jest przypięty w `uv.lock` |
| pyproj / PROJ (opcjonalne przygotowanie) | MIT / MIT | [pyproj](https://github.com/pyproj4/pyproj), [PROJ](https://proj.org/) |
| Shapely / GEOS (opcjonalne przygotowanie) | BSD-3-Clause / LGPL-2.1-or-later | [Shapely](https://github.com/shapely/shapely), [GEOS](https://libgeos.org/) |
| NumPy (zależność aplikacji) | BSD-3-Clause; dystrybucja dodatkowo 0BSD, MIT, Zlib, CC0-1.0 | [NumPy](https://numpy.org/doc/stable/license.html), pełne oznaczenia komponentów w dystrybucji |

`uv.lock` zawiera 38 zależności Python poza WICI, łącznie z grupami `dev`, `geo` i warunkami platformowymi. [Historyczna inwentaryzacja](docs/evidence/license-audit-2026-10-17.json) zapisuje stan z 17.10.2026, przed usunięciem PyMuPDF; aktualny zestaw określa `uv.lock`. `sniffio` i `pyshp` nie należą do tego zestawu. Hatchling jest osobną, nieprzypiętą zależnością budowania; jego zestaw zależności trzeba sprawdzić dla faktycznie użytej wersji.

NumPy i Rasterio są zależnościami aplikacji używanymi przez GFM i Sentinel. `pyproj` oraz Shapely są opcjonalnymi narzędziami przygotowania geometrii. Binaria GDAL, PROJ, GEOS i pozostałe komponenty zależą od konkretnego wheel i platformy; licencja pakietu Python nie zastępuje ich własnych warunków.

Wheel WICI nie zawiera pakietów zależności Python: są instalowane osobno. Przy redystrybucji środowiska, kontenera lub instalatora trzeba zachować ich licencje i oznaczenia, a dla MPL/LGPL spełnić także odpowiednie obowiązki dotyczące źródeł. Większość sprawdzonych dystrybucji zawiera teksty licencyjne, lecz `gtfs-realtime-bindings==1.0.0` nie zawiera osobnego pełnego pliku LICENSE. Samo skopiowanie `.venv` i tego wykazu nie jest pełną procedurą zgodnej redystrybucji.

Użycie `certifi` na MPL-2.0 nie wymaga objęcia odrębnych plików WICI tą licencją ([FAQ Mozilla](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)). Generator syntetycznych PDF korzysta obecnie z pypdf (BSD-3-Clause). PyMuPDF, grupa `pdf-check` i kod pobierania/redakcji rzeczywistych PDF zostały usunięte z bieżącej wersji.

Wymagane oznaczenia IMGW przy przetworzonych danych:

> Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy

> Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały przetworzone

## Materiały zapisane w repozytorium

| Pliki / zakres | Warunki i pochodzenie |
|---|---|
| `tests/fixtures/` | Autorskie syntetyczne próbki WICI na MIT: RSO, RCB, SG, IMGW PDF i hydro, GDDKiA, GIOŚ, ADS-B, GFM oraz IODA. Opis i odtwarzanie w [README fixture](tests/fixtures/README.md). Pola kontraktów i kody administracyjne nie są rzeczywistymi pomiarami. |
| `src/wici/static/geo/{provinces,counties,poland-border}.geojson`, `administrative-units.json` | PRG/GUGiK; pochodzenie i przetworzenie w `metadata.json`. Dane administracyjne służą również mapowaniu w testach. |
| `src/wici/static/geo/baltic-water.geojson.gz` | Osobny zasób EEA/VLIZ z ograniczeniami CC BY-NC-SA dla części VLIZ i jej adaptacji, opisany poniżej. Nie jest syntetyczną próbką. |
| `docs/evidence/` i `docs/archive/` | Usunięto rzeczywiste odpowiedzi, kopie dokumentów, zrzuty warstw i zbędne archiwalne raporty. Pozostały własne opisy techniczne, logi testów, historyczny audyt zależności i oczyszczona notatka IODA. [Zakres porządkowania](docs/evidence/README.md). |

Skopiowane specyfikacje OpenAPI IODA i GIOŚ usunięto. Testy sprawdzają własne przypadki kontraktu aplikacji, bez dołączania dokumentacji dostawców. Przyszłe próby live zapisują wyniki domyślnie w ignorowanym `tmp/live-checks/`; taki lokalny wynik nie jest automatycznie materiałem dopuszczonym do publikacji. Wcześniejsze kopie pozostały wyłącznie w historii pierwotnego repozytorium, której nie przeniesiono do tej kopii.

Nie znaleziono dołączonych plików fontów: CSS odnosi się do fontów systemowych, a syntetyczne PDF używają standardowej czcionki PDF bez osadzonego pliku fontu. Pochodzenie koncepcji logo opisano w `docs/branding/concepts/PROMPTS.md`; produkcyjne SVG są zapisane jako ścieżki. Audyt nie stanowi niezależnego potwierdzenia autorstwa każdego kształtu.

## CesiumJS — lokalny widok 3D

© 2011–2026 CesiumJS Contributors. Dołączono zminifikowany build przeglądarkowy 1.146.0 oraz katalogi `Assets`, `Workers`, `ThirdParty` i `Widgets` z opublikowanej paczki npm. Jedyna lokalna poprawka: wyszukanie obiektu globalnego Knockout przez `eval("this")` zastąpiono `globalThis`, aby utrzymać zakaz wykonywania JavaScript przez eval w CSP. Poprawkę jawnie odtwarza skrypt vendoringu i opisuje manifest. Pominięto moduły `index.js`/`index.cjs`, źródła, mapy źródeł i zależności instalacyjne. Pełny plik licencyjny dostawcy obejmuje także teksty licencji zależności i informacje o zasobach; należy go zachować przy redystrybucji. Zasoby runtime zawierają m.in. lokalne tekstury i logo Cesium; nie są obrazami satelitarnymi pobranymi przez WICI. Nie dołączono modeli pojazdów z God's Eye View ani jego kodu.

Widok WICI używa elipsoidy bez usługi terenu Cesium ion, Google ani ich kluczy. Lokalny runtime nie wymaga serwera CDN. Opcjonalny raster OpenStreetMap podlega odrębnym zasadom opisanym wyżej; licencja CesiumJS nie rozszerza praw do map ani danych lotniczych. Odtwarzanie paczki jest wyłącznie jawną czynnością deweloperską, nigdy częścią uruchomienia aplikacji; `python scripts/vendor_cesium.py --check` weryfikuje pliki bez sieci.

Wspólny widok obsługuje samoloty i autobusy. Schematyczne modele WICI w `static/models/aircraft.gltf` i `static/models/bus.gltf` są autorską geometrią generowaną z kodu przez `scripts/build_aircraft_model.py` i `scripts/build_bus_model.py` na licencji MIT; nie zawierają cudzych modeli, tekstur, logo ani oznaczeń przewoźników. Licencje i atrybucje źródeł autobusowych pozostają odrębne i są widoczne również w widoku 3D.

## EUMETSAT — Meteosat Lightning Imager AFA

© EUMETSAT 2026. Publiczna warstwa EUMETView `mtg_fd:li_afa` i oficjalna legenda przez WMS, wyłącznie na żądanie aktywnej mapy. Atrybucja w panelu i na mapie. [Produkt](https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Ali_afa), [warunki](https://www.eumetsat.int/about-us/terms-use), [polityka danych](https://www.eumetsat.int/legal-framework/data-policy). Ograniczenia prywatnego widoku i znaczenie obserwacji opisano w [docs/lightning.md](docs/lightning.md).

[Metadane produktu LI AFA `EO:EUM:DAT:0687`](https://api.eumetsat.int/data/browse/collections/EO%3AEUM%3ADAT%3A0687?format=html) wskazują politykę `NoConditions`. Jest to informacja dla konkretnego produktu, a nie ogólna licencja na portal ani legendy; zachowujemy atrybucję EUMETSAT i warunki pozostałych widocznych warstw. Dawne zrzuty usunięto z repozytorium.

## NEPTUN — alerty Ukrainy

Źródło: [NEPTUN](https://neptun.in.ua/), [dokumentacja API](https://neptun.in.ua/developers), [warunki API](https://neptun.in.ua/api-terms), sprawdzone 17.10.2026. Publiczne odczyty bez klucza; warunki dopuszczają użytek komercyjny i niekomercyjny, wymagają widocznego linku obok danych i informacji o ograniczeniach agregatora. WICI zachowuje atrybucję w panelu i na mapie. REST jest odpytywany nie częściej niż co 15 sekund na zasób (dostawca wymaga minimum 5 sekund).

Granice obwodów/rejonów są pobierane na żądanie z udokumentowanych plików GeoJSON NEPTUN i przechowywane wyłącznie w pamięci. Nie są dołączone do dystrybucji WICI. Pliki nie określają odrębnej licencji ani pochodzenia granic; ogólne warunki zachowują prawa dostawców kartografii. WICI nie przypisuje tym plikom domniemanej licencji OSM ani CC. Logo i SDK NEPTUN nie są kopiowane. [Zakres integracji](docs/ukraine.md).

## adsb.fi — bieżące pozycje samolotów i jakość pozycji

Źródło: [adsb.fi](https://adsb.fi/), [API i warunki](https://github.com/adsbfi/opendata). Publiczne dane API są przeznaczone wyłącznie do osobistego, niekomercyjnego użytku; wymagana atrybucja adsb.fi z linkiem. Nie wolno sprzedawać, wynajmować ani licencjonować danych/usługi. Użycie komercyjne wymaga kontaktu z dostawcą. Dostęp bez klucza; limit publiczny 1 żądanie/s, bez gwarancji dostępności. Te warunki są odrębne od MIT kodu WICI i nie są licencją ODbL.

Pozycje są filtrowane do Polski, wysokość przeliczana na metry, a prędkość na km/h. Rejestracja i typ pochodzą z bazy dostawcy, znak wywoławczy z pola `flight`. Cache warstwy działa w pamięci; opcjonalny kolektor jakości pozycji zachowuje ograniczoną historię wskaźników w lokalnym SQLite (domyślnie 72 h), do osobistego, niekomercyjnego użytku. Atrybucja pozostaje w panelu i na mapie.

## ADSB.lol — wcześniejsze źródło danych lotniczych

Do zmiany źródła 18.10.2026 WICI korzystało z [ADSB.lol](https://www.adsb.lol/) / [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). Lokalna historia jakości pozycji sprzed tej zmiany może zawierać wcześniejsze dane; zachowano ich atrybucję. Zmiana dostawcy nie zmienia praw do istniejącej historii i nie usuwa jej. Obecna próbka w `tests/fixtures/aircraft/` jest autorska i syntetyczna na MIT, bez zachowanych odpowiedzi źródłowych.

## AISStream — pozycje statków

Źródło: [AISStream](https://aisstream.io/), [dokumentacja i ograniczenia](https://aisstream.io/documentation). Bezpłatny dostęp przez klucz i backend WebSocket; atrybucja w panelu oraz na mapie. Brak deklaracji otwartej licencji na redystrybucję danych. WICI pokazuje wybrane pola AIS z Bałtyku i cieśnin duńskich, bez publikowania surowego strumienia; wybrane trasy mogą być zapisywane lokalnie przez 7 dni na żądanie użytkownika; [zakres](docs/ships.md). Klient Python `websockets` (wersja w `uv.lock`) na licencji BSD-3-Clause; licencja dostarczana z pakietem.


## Granice wody dla statków — EEA i VLIZ

Plik `src/wici/static/geo/baltic-water.geojson.gz`, obecny również w wheel, opracowano z danych EEA, ETC/ICM, EC: [Marine regions, Baltic Sea](https://marine.discomap.eea.europa.eu/arcgis/rest/services/Marine/Marine_regions_subregions/MapServer/2), oraz Flanders Marine Institute (2018): [IHO Sea Areas v3, Kattegat](https://doi.org/10.14284/323). Przetworzenie: połączenie geometrii, uproszczenie topologiczne 0,0001°, zaokrąglenie współrzędnych i kompresja; nie są to granice nawigacyjne. Pochodzenie i odtwarzanie: [docs/ships.md](docs/ships.md), `scripts/prepare_marine_area.py`, metadane wewnątrz pliku.

**Rozbieżność licencji VLIZ, sprawdzona 17.10.2026:** [strona pobierania konkretnego zbioru IHO Sea Areas v3](https://www.marineregions.org/download_file.php?name=World_Seas_IHO_v3.zip) i [rekord DOI produktu](https://marineinfo.org/en/doc/dataset/5444?doiid=323) wskazują [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). [Ogólny disclaimer](https://www.marineregions.org/disclaimer.php) mówi o CC BY od Maritime Boundaries v11 (2019). Nie potwierdzono, że liberalniejsze warunki obejmują tę konkretną geometrię z 2018 r. Nie należy oznaczać jej jako MIT ani zakładać dowolnego zastosowania komercyjnego. Dla wykorzystania części VLIZ i jej adaptacji należy respektować wskazane przy produkcie CC BY-NC-SA 4.0: atrybucję, link do licencji, oznaczenie zmian, użytek niekomercyjny i ShareAlike dla adaptacji. Własny wkład WICI w adaptację tej geometrii udostępniamy na CC BY-NC-SA 4.0; nie zmienia to MIT odrębnego kodu aplikacji. Komercyjne wykorzystanie maski wymaga odpowiedniego uprawnienia od dostawcy albo usunięcia lub zastąpienia ograniczonej geometrii. [Warunki EEA](https://www.eea.europa.eu/en/about/contact-us/faqs/can-i-use-eea-content-in-my-work-or-in-my-organisations-products) pozostają odrębne i nie rozszerzają praw do części VLIZ.


## PolishTrainsGTFS — rozkład i aktualizacje kolejowe

Źródło: [PolishTrainsGTFS — Mikołaj Kuranowski](https://mkuran.pl/gtfs/), dane rozkładowe PKP Polskie Linie Kolejowe S.A. oraz Koleje Mazowieckie – KM sp. z o.o. Aktualizacje: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) oraz wskazane przez dostawcę [warunki ponownego wykorzystywania danych PKP PLK](https://www.plk-sa.pl/klienci-i-kontrahenci/api-otwarte-dane). Rozkład: warunki PKP PLK i [Kolei Mazowieckich](https://bip.mazowieckie.com.pl/pl/ponowne-wykorzystywanie-informacji-sektora-publicznego), odnośniki szczegółowe w [katalogu dostawcy](https://mkuran.pl/gtfs/). Licencja MIT repozytorium narzędzia nie zastępuje warunków danych. Przetworzenie w WICI: grupowanie stacji/peronów, wybór kursów w bieżącym oknie czasu, obliczanie różnic między rozkładem a aktualizacjami oraz wizualizacja tras i szacowanie położenia z godzin postojów wzdłuż geometrii rozkładowej (nie pomiar GPS). Atrybucja w panelu i na mapie; czas źródła i stan aktualności w szczegółach. Pamięciowy cache bez archiwizacji przejazdów. [Zakres i ograniczenia](docs/trains.md).


## ZDiTM Szczecin — bieżące pozycje autobusów

Źródło: Zarząd Dróg i Transportu Miejskiego w Szczecinie, [API pojazdów v2 i warunki](https://www.zditm.szczecin.pl/pl/zditm/dla-programistow/api-pojazdy). Dane na licencji [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). WICI wybiera autobusy, normalizuje pola i oznacza wiek danych; atrybucja w panelu i na mapie. Pamięciowy cache, bez archiwizacji pozycji. Dostawca nie gwarantuje poprawności ani kompletności danych.


## Autobusy Krakowa, Poznania i Warszawy

- Kraków: [ZTP GTFS / GTFS-RT](https://gtfs.ztp.krakow.pl/), dane MPK i Mobilis. WICI odczytuje autobusowe zestawy A/M, łączy pozycje z rozkładem i oznacza wiek danych. Nie deklaruje licencji CC0 dla tego źródła.
- Poznań: [ZTM](https://www.ztm.poznan.pl/otwarte-dane/dla-deweloperow/), publiczne GTFS i GTFS-RT. Zgodnie z zasadami wskazano źródło, aktualność oraz przetworzenie danych przez WICI; odfiltrowano tramwaje. Nie wykorzystuje się znaków towarowych ani kont PEKA.
- Warszawa: [nowy portal danych miasta](https://dane.um.warszawa.pl/), uwierzytelniony odczyt lokalizacji pojazdów, z atrybucją i zgodnie z regulaminem dostawcy. Dane są filtrowane według wieku pozycji i ujednolicone w WICI, bez archiwizacji.
- `gtfs-realtime-bindings` oraz `protobuf`: Apache-2.0 / BSD-3-Clause, dokładne wersje w `uv.lock`. Dla bindings 1.0.0 pełny tekst Apache jest w [repozytorium dostawcy](https://github.com/MobilityData/gtfs-realtime-bindings/blob/master/LICENSE); sprawdzony wheel nie zawiera osobnego LICENSE. Przy bundlowaniu należy dołączyć wymagany tekst, zachować atrybucje i sprawdzić ewentualne NOTICE.

Wspólny opis zakresu i przetworzenia: [autobusy](docs/buses.md).


## Copernicus EMS — zobrazowania


Copernicus Emergency Management Service — Mapping, © European Union. Identyfikatory aktywacji i produktów oraz źródło przy wyniku; oryginalne oznaczenia w podglądach. [Zasady cytowania](https://mapping.emergency.copernicus.eu/about/citation-guidelines/). Publiczne podglądy produktów nie oznaczają dowolnej licencji na surowe zobrazowania satelitarne. [Zakres integracji](docs/imagery.md).

## GIOŚ — jakość powietrza

Źródło danych: GIOŚ - EKOINFONET. Państwowy Monitoring Środowiska. Wybrane stacje i stanowiska; przetworzono format i czas. Wyniki udostępniane przez API nie są na bieżąco weryfikowane i mogą ulec zmianie. API v1: https://powietrze.gios.gov.pl/pjp/content/api ; warunki ponownego wykorzystania: https://powietrze.gios.gov.pl/pjp/content/terms_of_service . WICI pokazuje stężenia punktowe i oficjalny indeks, bez interpolacji i bez obliczania norm dobowych z pojedynczej godziny. Autorskie syntetyczne próbki w `tests/fixtures/gios` służą regresjom offline; nie są kopiami odpowiedzi GIOŚ.

## IODA / Georgia Tech Internet Intelligence Lab

Anomalie dostępności internetu i kontekst pomiarowy: https://ioda.inetintel.cc.gatech.edu/ oraz oficjalne API https://api.ioda.inetintel.cc.gatech.edu/v2/ .

Oryginalna atrybucja odpowiedzi: **This data is Copyright (c) 2021-2025 Georgia Tech Research Corporation. All Rights Reserved.** Zachowana w pochodzeniu danych. WICI przetwarza format i czas do lokalnego widoku, bez ustalania przyczyn detekcji. Nie jest to oficjalne ostrzeżenie polskich służb.

Nie potwierdzono otwartej licencji danych ani zezwolenia na ich redystrybucję. Licencja historycznego kodu CAIDA/ioda-api nie jest licencją obecnych danych. Kod API nie został skopiowany do WICI.

**Zmiana z 18.10.2026:** `tests/fixtures/ioda/` zawiera autorskie próbki przygotowane od zera na MIT, ze zmyślonymi danymi do testowania kontraktu. Usunięto skopiowaną specyfikację OpenAPI i wcześniejsze rzeczywiste odpowiedzi. Z `docs/evidence/ioda-live-2026-10-17.json` usunięto dane źródłowe i wyniki pomiarów; pozostała jedynie krótka informacja o dawnym sprawdzeniu oraz usunięciu tych danych. Rozwiązuje to problem dołączonych kopii IODA w bieżącej wersji repozytorium. Dawny audyt rzeczywiście korzystał z odpowiedzi live; nie oznaczamy ich wstecznie jako syntetycznych i nie zmieniamy wcześniejszej historii pierwotnego repozytorium, której nie dołączono do tej kopii.

Ta zmiana nie jest zezwoleniem na redystrybucję ani komercyjne wykorzystanie danych IODA pobieranych przez aplikację live. Demo aplikacji nadal korzysta z danych syntetycznych. Szczegóły pochodzenia: [fixture IODA](tests/fixtures/ioda/README.md), [integracja](docs/ioda.md).


## Copernicus GFM i biblioteki rastrowe

GFM / EODC / JRC CEMS: kolekcja STAC ma `license: proprietary`. [Warunki CEMS](https://global-flood.emergency.copernicus.eu/terms-of-service/) dopuszczają reprodukcję, dystrybucję i modyfikację z podaniem pochodzenia i zmian; nie deklarujemy CC BY dla danych GFM. Reprojekcja i kolory WICI: `Contains modified Copernicus Emergency Management Service information [YYYY]` (rok obserwacji). Dawne rzeczywiste próbki i obrazy usunięto; autorskie syntetyczne dane GFM i szachownica testowa są na MIT. [Kontrakt i pochodzenie](docs/gfm.md).

Rasterio i affine: BSD-3-Clause. NumPy: BSD-3-Clause oraz oznaczenia komponentów dystrybucji (0BSD, MIT, Zlib, CC0-1.0); attrs i pyparsing: MIT. Sprawdzony wheel Rasterio zawiera GDAL, PROJ i inne biblioteki natywne; zachowane teksty licencji nie stanowią kompletnego audytu całego zestawu. Należy zachować pliki licencyjne dystrybucji. [Rasterio](https://github.com/rasterio/rasterio), [NumPy](https://numpy.org/doc/stable/license.html), metadane i pliki licencyjne zależności zainstalowanych przez `uv sync --locked`.


## Sentinel-2 L2A / Copernicus Data Space Ecosystem

RGB pobierane live w warstwie Sentinel-2: `Contains modified Copernicus Sentinel data [2026]`, processed with Sentinel Hub / CDSE; WICI wykonuje dobór pasm B04/B03/B02, stałe wzmocnienie reflectance, reprojekcję, szachownicę NoData i opcjonalne barwienie masek SCL. Rok atrybucji na mapie wynika z czasu obserwacji. Dane Sentinel udostępniane są na zasadach free/full/open zgodnie z [warunkami CDSE](https://dataspace.copernicus.eu/terms-and-conditions) i [Sentinel Data Legal Notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice). Nie deklarujemy osobnej licencji CC dla obrazów źródłowych. Syntetyczne obrazy demo i zrzuty demo nie są danymi Copernicus; UI oznacza je jako demonstracyjne. Biblioteki NumPy/rasterio opisano przy GFM. [Pełny opis przetwarzania i ograniczeń](docs/sentinel2.md).

## Sentinel-5P L2 / Copernicus Data Space Ecosystem

Obrazy NO₂, SO₂ i UVAI pobierane live: `Contains modified Copernicus Sentinel data [rok obserwacji]`, processed with Sentinel Hub / CDSE. Modyfikacje WICI: wybór obserwacji i pasma, progi jakości, maski braków, reprojekcja nearest-neighbour, kolory i przezroczystość. Obowiązują [warunki CDSE](https://dataspace.copernicus.eu/terms-and-conditions) oraz [atrybucja Sentinel](https://documentation.dataspace.copernicus.eu/FAQ.html); nie deklarujemy odrębnej licencji CC. Demo i jego zrzuty są syntetyczne, nie pochodzą z Copernicus. NumPy/rasterio są używane na zasadach opisanych powyżej. [Kontrakt, profil SO₂, jakość i ograniczenia interpretacji](docs/sentinel5p.md).
