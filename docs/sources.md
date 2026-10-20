# Kontrakty źródeł i geografia

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Sprawdzono 12 października 2026 r. Zapis kontrolowanej próby rzeczywistych adapterów: [historyczne dane usunięto](evidence/README.md). Testy domyślne nie używają internetu. Żadne dane prób nie trafiają do bazy live.

**Aktualny tryb:** oficjalne PDF IMGW zostały zweryfikowane na autentycznych ostrzeżeniach 2026; wcześniejsza blokada pustego JSON jest zakończonym etapem. Komunikaty zapisane przez rozpoznane adaptery są automatycznie dostępne w widoku dnia, bez modelu i akceptacji. Zasady czasu, mapy, minimalizacji i wyniki najnowszego live: [automatic-communications.md](automatic-communications.md). Dawny tryb interpretacji i parser JSON IMGW zostały usunięte; pozostają źródłowe metadane, diagnostyka odczytu i bezpośrednie wyświetlanie komunikatów.

## Wspólne zasady

- Wyłącznie HTTPS i jawnie dopuszczony host/ścieżka; przekierowanie poza zakres jest błędem. Wyjątek techniczny **tylko dla robots** Gov.pl: `/robots.txt` → `/static/code/robots.txt` na tym samym hoście; został rzeczywiście zaobserwowany. Nie obejmuje treści komunikatów.
- Identyfikujący User-Agent WICI, domyślnie 20 sekund i 10 MB; runtime przekazuje konfigurację. Brak CAPTCHA, logowania, tokenów CAP, obchodzenia antybotów. 401/403 blokują, 429 respektuje Retry-After i backoff. HTML kontrolujący dostęp zamiast JSON/artykułu nie jest pustym sukcesem.
- robots sprawdzany przy pierwszym pobraniu adaptera w procesie; 404 oznacza brak reguł, nie zgodę licencyjną. Aktualne reguły mają pierwszeństwo nad poniższym zapisem. W próbie IMGW/RSO robots 404, SG pusty 200, Gov.pl jawne `Allow: /`.
- ETag/Last-Modified i cache odpowiedzi w pamięci; 304 ma sens tylko ze znaną reprezentacją. Po restarcie pełne pobranie. Nie usuwa się publikacji na podstawie braku w wyniku, 404 ani częściowej odpowiedzi.
- Czas bez offsetu RSO przyjęty jako Europe/Warsaw z jawną walidacją DST; niejednoznaczny lub nieistniejący czas do kontroli. Sama data publikacji HTML zachowana jako data w `fields.source_published_date`, bez wymyślania północy. Czas zdarzenia nie jest wyliczany z czasu publikacji lub odczytu; „jutro/wczoraj” nie odnosi się do pobrania.
- URL dokumentu jest źródłem tożsamości tam, gdzie nie ma identyfikatora. Tekst oczyszczony przed zapisem; skryptów, multimediów i nawigacji nie zapisuje się jako treści.

## IMGW — `imgw_meteo`

Bieżąca integracja używa [oficjalnego katalogu PDF](https://danepubliczne.imgw.pl/data/current/ost_meteo/), w ramach tej samej instytucji i ostrzeżeń meteorologicznych (§6.1/6.2 PRD). Szczegółowy kontrakt, tożsamość ostrzeżeń, czas, zakres, redakcja i dowody: [imgw-pdf-contract.md](imgw-pdf-contract.md). Oficjalne [apiinfo i regulamin](https://danepubliczne.imgw.pl/apiinfo) dopuszczają prywatne użycie i wymagają oznaczeń pochodzenia/przetworzenia, dostarczonych w UI i notices.

Syntetyczne testy obejmują dokumenty wielostronicowe, zmiany i odwołania. Parser rozpoznaje cztery przetestowane typy zwykłych ostrzeżeń; zmiany i odwołania aktualizują komunikat automatycznie, a ograniczenia odczytu są jawne. Zestawy zbiorcze nie tworzą duplikatów tej samej tożsamości powiat/numer/rok. Kolektor nie pobiera archiwów, hydro, map, zdjęć ani podpisów. Domyślnie 5 minut; maksymalnie 20 najnowszych PDF, jeden na prefiks wydawniczy. Pusty katalog nie oznacza odwołania zapisanych ostrzeżeń.

Wcześniejszy JSON `warningsmeteo` nadal nie ma potwierdzonego niepustego schematu i **nie jest używany w live**. Nie ma już kodu tego parsera; historyczne próbki i raporty usunięto z bieżącego drzewa.

## RSO — `rso`

Oficjalne [zasady integracji](https://komunikaty.tvp.pl/Info/Integration) wyraźnie opisują publiczne XML/JSON oraz osobny autoryzowany CAP/OpenAPI (nieużywany). Właściwy pobierany adres to [publiczny JSON /0](https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/0?_format=json).

Zweryfikowano semantykę: `/0` = wszystkie pozycje z pominięciem stronicowania; `/1` = strona. `pagination.totalitems` dla strony nie należy interpretować jako globalnej liczby. Dla /0 porównuje się liczbę elementów z `totalitems`; rozbieżność lub wadliwe elementy daje stan częściowy. Nie jest to pełne archiwum, nie gwarantuje nadrabiania przerwy.

Autentyczny schemat: obiekt `pagination:{totalitems,itemsperpage}`, `newses` lista. Rekordy: `id` stabilny identyfikator, `title`, `shortcut`, `content`, `rso_alarm`, `rso_icon`, `valid_from`, `valid_to`, `created_at`, `updated_at`, `provinces` słownik obiektów `id/name/slug_name`, `latitude`, `longitude`, opcjonalne pola wody/rzeki. Występują techniczne klucze `0..3` z tekstem formatu daty; nie są metadanymi merytorycznymi.

Czasy mają format `YYYY-MM-DD HH:MM:SS` bez offsetu. Znaczenie created_at/updated_at zachowano jako publikację/aktualizację źródła. Nie są czasem zdarzenia. Powiatów nie zgaduje się z opisów. Województwa mapowane po slug do PRG, rola **notification_area**, nie event_location. Puste współrzędne są prawidłowe; współrzędne nie są automatycznie interpretowane jako miejsce incydentu.

Komunikaty RSO są dostępne bez zatwierdzania, z pełną oczyszczoną treścią. Pole `rso_alarm` nie jest podstawą nowej oceny ryzyka, a typ ćwiczenia i temat to etykiety widoku, nie niezależna weryfikacja. Źródło wskazuje zweryfikowany kanał JSON, identyfikatorem dokumentu jest `id`. Publiczny feed nie udostępnia odpowiadających mu identyfikatorów permalinków witryny; próba budowania URL z numerycznego id zwróciła 404, więc aplikacja tego nie robi. Zapisany tekst i id identyfikują konkretną pozycję w kanale.

## RCB — `rcb`

Strona informacyjna [Alert RCB](https://www.gov.pl/web/rcb/alertrcb) zawiera FAQ i przykładowe SMS, **nie bieżący feed**. Bieżące publikacje są w oficjalnym wykazie [Komunikaty RCB](https://www.gov.pl/web/rcb/komunikaty). Parser wybiera tylko odnośniki `/web/rcb/alert-rcb-...`; inne aktualności/raport dobowy pozostają poza zakresem.

Faktycznie odczytano HTML listy i artykuł [ćwiczenia 11.10](https://www.gov.pl/web/rcb/alert-rcb---cwiczenia-z-wykorzystaniem-syren-1110). Początkowe urllib/curl miały timeout, późniejszy httpx uzyskał 200. Nie pomijano weryfikacji TLS i nie obchodzono blokad.

Kontrakt listy: `main article .art-prev li`, odnośnik `.title a`, data `.date`; jawny `#js-pagination-page-next` z `?page=2&size=10`. Parser podąża wyłącznie za tym odnośnikiem w tym samym wykazie, maksymalnie 3 strony i 7 dni. Limit lub błąd daje partial. Dodatkowo `tracked_urls` pozwala runtime sprawdzać znane aktywne starsze ostrzeżenia. Kontrakt artykułu: `article.article-area__article`, `h2`, `p.event-date`, `div.editor-content`. Tożsamość kanoniczny URL, data bez godziny, aktualizacji nie zgaduje się z czasu pobrania. Zmiany treści pod tym samym URL tworzą kolejne wersje i kontrolę.

Wszystkie nowe/zmienione materiały do operatora. Ćwiczenia jako kontekst; lokalizacje pozostawiono do kontroli, co zapobiega umieszczaniu zdarzenia zagranicznego w polskim obszarze wysłania alertu. Domyślnie 10 minut. Teksty Gov.pl objęte **CC BY-SA 4.0**, zgodnie z oficjalną stopką; zachować autorstwo RCB, odnośnik, licencję i informację o przetworzeniu. Nie pobiera się zdjęć/audio/wideo.

## Straż Graniczna — `sg`

Wyłącznie [centralne aktualności](https://www.strazgraniczna.pl/pl/aktualnosci); listę i [publiczny komunikat podróżny](https://www.strazgraniczna.pl/pl/aktualnosci/16278,Utrudnienia-na-przejsciu-granicznym-w-Bezledach-i-Grzechotkach.html) odczytano HTTP 200. [Warunki SG](https://www.strazgraniczna.pl/pl/pozostale-informacje/prawa-autorskie/2316,Prawa-autorskie.html) dopuszczają kopiowanie z powołaniem na źródło. Brak odrębnego szerokiego prawa licencyjnego nie jest przedstawiany jako otwarta licencja.

Kontrakt listy `#content .okno ul`, `li.news a`, `h3`, `.data`; `?page=1` to następna strona (pierwsza bez parametru). Maksymalnie 3 strony, publikacje ostatnich 7 dni. Identyfikator liczbowy z `/{id},slug.html`; artykuł `#content .head h2/h3`, `.metryka .data`, `article.txt`. Data bez godziny; brak automatycznej lokalizacji i publikacji.

**Minimalizacja przed zapisem:** szczegółowy tekst i oryginalny tytuł zapisuje się jedynie dla wąskich publicznych komunikatów podróżnych o ograniczeniach przejścia, bez wykrytych danych osobowych/operacyjnych. Pozostałe materiały dostają ogólny tytuł i notatkę redakcyjną, bez oryginalnego szczegółowego opisu. Operator widzi URL i ocenia znaczenie; nie przechowuje się nazwisk, PESEL, pozycji patroli ani ścieżek operacji. To celowo ogranicza wygodę kontroli i pokrycie treści incydentów. Materiały organizacyjne mają propozycję pominięcia i można je odrzucić z uzasadnieniem; nie znikają po jednym słowie kluczowym. Zbiorczych statystyk nie rozbija się na incydenty. Domyślnie 30 minut.

## PRG i Leaflet — lokalna mapa

Źródło urzędowe [PRG Geoportal](https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/) dopuszcza bezpłatne dowolne wykorzystanie. Użyto oficjalnej [usługi WFS](https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries), nie cudzych schematycznych granic. Pobranie ZIP przerwano po timeout, jego niepełny plik **nie został wykorzystany**. WFS GetCapabilities potwierdził typy `ms:A01_Granice_wojewodztw`, `ms:A02_Granice_powiatow` oraz GML 3.2. GetFeature 2.0.0 EPSG:2180 zwrócił odpowiednio 16/16 i 380/380; zweryfikowano unikalność TERYT oraz geometrie.

Bundled: `static/geo/provinces.geojson` (16), `counties.geojson` (380), `metadata.json` z datą, SHA256 wejść/wyjść, wersjami źródła, CRS i uproszczeniem. WFS GML formalnie northing/easting; konwersja z EPSG:2180 do longitude/latitude EPSG:4326. Visvalingam-Whyatt coverage_simplify z parametrem 150 w metrach układu 2180 (pierwiastek z pola usuwanych trójkątów, nie gwarantowany maksymalny błąd odległości), zapis 5 miejsc po przecinku. Sprawdzono ważność oryginalnego pokrycia oraz pokrycia po uproszczeniu i zaokrągleniu: wspólne brzegi jednostek identyczne, brak wewnętrznych luk/nakładania. Różnica symetryczna zewnętrznych obwiedni obu warstw wynosi 0,454 km² / 313730,8 km² (0,000145%). [validation.json](../src/wici/static/geo/validation.json) zawiera pomiar. Podkład orientacyjny, nie geodezyjny. Algorytm opisuje [dokumentacja Shapely](https://shapely.readthedocs.io/en/stable/reference/shapely.coverage_simplify.html). Kody w GeoJSON i `geometry_ref` identyczne. Nieznany kod nie dostaje arbitralnego punktu.

Granice PRG nie są pobierane podczas startu; pozostają lokalne. Podkład drogowy OSM w live korzysta z sieciowych kafelków opisanych poniżej; demo używa tylko lokalnych granic. Leaflet 1.9.4 (BSD-2-Clause) wraz z CSS, ikonami i LICENSE lokalnie w `static/vendor/leaflet`; brak CDN biblioteki w uruchomionym UI.

Opcjonalne samodzielne odtworzenie granic (niepotrzebne do uruchomienia):

```bash
uv sync --locked --group geo
curl --fail --max-time 120 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:A01_Granice_wojewodztw&srsName=EPSG:2180' -o provinces.gml
curl --fail --max-time 120 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:A02_Granice_powiatow&srsName=EPSG:2180' -o counties.gml
uv run --locked --group geo python scripts/prepare_geo.py --provinces provinces.gml --counties counties.gml
```

Zależności GIS służą wyłącznie przygotowaniu, bez globalnej instalacji. Aktualizacja podkładu jest ręczna. Daty WERSJA_OD jednostek nie są obietnicą daty obowiązywania wszystkich granic.

## Uzupełnienia końcowego audytu

Publiczny kanał RSO jest źródłowym URL dokumentu, ponieważ numeryczne ID nie odpowiada permalinkowi HTML (kontrolowana próba 404). Adapter nie konstruuje takiego linku. Wszystkie adaptery przed zapisem minimalizują też wykryte osobowe/operacyjne szczegóły: patrol, funkcjonariusze, poszukiwania/zatrzymani, PESEL i adresy e-mail kierują bezpieczny ogólny tytuł oraz URL do kontroli. To nie jest automatyczna analiza osób. Oryginalna szczegółowa treść nie trafia do bazy. Wartość daty 9999 jest niezweryfikowanym znacznikiem technicznym do kontroli, a nie rzeczywistą ważnością. Brak końca ważności nie staje się automatycznie „do odwołania”; jawny znacznik w dowodzie jest wymagany. Odpowiedzi HTTP304 są raportowane jako `not_modified` tylko z zachowaną reprezentacją.

Katalog kategorii określa tematy, nie znaczenie `rso_alarm`. Kolizje opisane w komunikatach mogą mieć propozycję wydarzenia infrastrukturalnego; pozostają do kontroli, z nieznanym czasem zdarzenia oraz obszarem powiadomienia. Negacja i ćwiczenia wykluczają tę regułę propozycji.

## Wynik dodatkowego poszukiwania historycznej próbki IMGW

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

## NASA FIRMS — `firms`

Opcjonalne rozszerzenie zlecone 13.10.2026; osobna warstwa obserwacji, poza czterema adapterami komunikatów. VIIRS NRT z S-NPP, NOAA-20 i NOAA-21, oficjalne API NASA, bezpłatny MAP_KEY przechowywany lokalnie. Polska według lokalnego PRG, polling co 900 s, lokalna historia. Kontrakt, ograniczenia i wyniki weryfikacji: [firms.md](firms.md).

## EFFIS — prognoza FWI

Osobna warstwa prognozy ECMWF na dziś, jutro i pojutrze w Europe/Warsaw. Oficjalny WMS `/gwis`, `ecmwf.fwi`, stały zakres Polski, legenda źródła i lokalne proxy obrazów. Bez klucza, demo offline. Nie jest komunikatem IMGW ani detekcją FIRMS. Kontrakt i ograniczenia: [effis.md](effis.md).

## TomTom — opcjonalna bieżąca płynność ruchu

Dodano i sprawdzono 13.10.2026. Oficjalne [Orbis v2 Raster Flow Tiles](https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/traffic-flow/raster-flow-tiles), styl `light`, 256 px, zoom 6–18 i kafelki przecinające obwiednię Polski. Warstwa nie pobiera szczegółów incydentów ani wyznaczonych tras. Klucz z `[sources.tomtom]` w ignorowanym `config.local.toml`, jako `SecretStr`, jest wysyłany wyłącznie nagłówkiem backendu `TomTom-Api-Key`; nie trafia do URL, przeglądarki, bazy komunikatów ani licznika użycia. Próba na żywo zwróciła poprawny PNG dla Warszawy.

Przełącznik UI domyślnie wyłączony; aktywna widoczna mapa odświeża się co 300 s, bez prefetchu poza widokiem. Demo nie używa sieci. Bieżąca warstwa nie zależy od daty publikacji i nie odtwarza historii. Kolor oznacza prędkość względem swobodnego ruchu; brak kafelków nie jest dowodem braku korków. Czas w UI to ostatnie lokalne pobranie dowolnego kafelka, nie czas obserwacji wszystkich dróg. Krótkotrwały cache w pamięci respektuje `max-age` dostawcy (maks. 300 s); dane nie są zapisywane na dysku. Błędy usuwają częściowy widok i wstrzymują kolejne próby na co najmniej 300 s; 429 respektuje także Retry-After. Przekierowania są odrzucane, odpowiedzi ograniczone do 1 MiB i zweryfikowanego PNG 256×256.

Lokalny trwały licznik w `var/live/tomtom-usage.json` rezerwuje każde zapytanie przed kontaktem z API i blokuje dalsze pobieranie przy 190 000 prób w miesiącu UTC. Restart nie zeruje zużycia; uszkodzony lub niezapisywalny licznik zatrzymuje pobieranie. To ograniczenie tej instalacji, nie odczyt rozliczeń TomToma. Aktualny [cennik](https://docs.tomtom.com/pricing) podaje 200 000 darmowych zapytań miesięcznie dla kafelków raster; plan przypisany do konta i użycie klucza poza WICI należy uwzględnić osobno. Testy offline: `tests/test_traffic.py`, `tests/ui_traffic.test.cjs`.

Kliknięcie przy aktywnej warstwie pobiera identyfikację drogi z [Orbis v2 Reverse Geocode](https://docs.tomtom.com/reverse-geocoding-api/documentation/tomtom-orbis-maps/v2/reverse-geocode). Współrzędne longitude,latitude są wysyłane wyłącznie po kliknięciu, promień 250 m; backend zwraca wyłącznie `street` i `routeNumbers` dla Polski, bez numerów domów, pełnych adresów, rekordów osób lub zapisu odpowiedzi. Oznaczenia pozostają zgodne ze źródłem, bez dopisywania DK/DW na podstawie samego numeru. To droga blisko kliknięcia, nie gwarancja identyfikacji konkretnej jezdni z obrazu; UI zaleca przybliżenie. Osobny trwały licznik `tomtom-road-usage.json`, limit 19 000/miesiąc UTC, względem obecnego darmowego limitu 20 000 Reverse Geocoding. Błędy, limity, demo, niedozwolone współrzędne i spóźnione odpowiedzi popupu są objęte testami.

## GDDKiA — utrudnienia drogowe

Integracja korzysta z publicznego [XML utrudnień](https://www.archiwum.gddkia.gov.pl/dane/zima_html/utrdane.xml), wskazanego przez [Gov.pl](https://www.gov.pl/web/gddkia/dane-xml). Parser opiera się na [specyfikacji XML v1.1](https://www.gov.pl/attachment/0c47ae2a-7fca-459d-8ebe-a2b9ead424d7); bieżące regresje używają syntetycznego XML. Nie korzysta z listy HTML ani nie obchodzi jej kontroli dostępu.

Kontrakt: root `utrudnienia`, `gen` — czas wygenerowania zestawienia; rekord `utr`: `typ`, `nr_drogi`, `woj`, `nazwa_odcinka`, `geo_lat/geo_long`, `rodzaj/poz`, `skutki`, flagi i ograniczenia, `objazd`, `data_powstania`, `data_likwidacji`. Według specyfikacji współrzędne są środkiem odcinka objętego utrudnieniem, a `data_likwidacji` oznacza planowaną likwidację. Kody przyczyn i skutków tłumaczone według tabel 4/5; nieznane kody pozostają jawne. Skutki tekstowe są zachowywane, flagi pokazywane tylko gdy źródło podało `true`; brak wartości nie oznacza braku utrudnienia. Opis/objazd nie jest automatycznie interpretowany jako oddzielne pole skutków. Tekst oczyszczony z HTML i skryptów; multimedia nie są pobierane.

Brak współrzędnych nie uruchamia geokodowania ani punktu w środku województwa. Identyczne punkty grupują się w dymku, ale rekordy, opisy i różne terminy pozostają osobne. Upływ planowanego końca nie usuwa znacznika; jawny opis wskazuje, że rekord nadal występuje w zestawieniu. Błędne lub pozbawione strefy daty są pomijane z diagnostyką; nie zgaduje się czasu ani odwołania.

## OpenStreetMap — podkład dróg

Dodano 14.10.2026 jako podkład niezależny od warstw GDDKiA i TomTom. Standardowe kafelki raster OSM z `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, pobierane bezpośrednio przez przeglądarkę; w trybie live domyślnie włączone, w demo wyłączone także przez CSP. Atrybucja © OpenStreetMap contributors z odnośnikiem do praw autorskich widoczna na mapie. Widoczność nazw i oznaczeń zależy od stylu OSM i powiększenia — nie są to dane o bieżącej płynności ruchu.

Zgodnie z [polityką kafelków OSMF](https://operations.osmfoundation.org/policies/tiles/): tylko aktywny widok, bez prefetchu/archiwum/offline download i okresowego wymuszania odświeżania; `keepBuffer: 0`, cały widoczny obszar mapy także poza Polską, zoom maksymalnie 19. Przeglądarka obsługuje nagłówki cache i walidatory dostawcy oraz wysyła standardowy User-Agent. Dla obrazów OSM ustawiono indywidualny `referrerPolicy: strict-origin-when-cross-origin`, aby wysłać wymagany Referer pochodzenia aplikacji. Globalna polityka odnośników i innych zasobów pozostaje `no-referrer`; brak klucza w adresie kafelków. CSP dopuszcza jedynie ten dodatkowy host obrazów w live, bez dodatkowych zewnętrznych skryptów ani połączeń API. Usługa społecznościowa bez gwarancji dostępności.

Podkład leży pod granicami PRG i innymi warstwami. Wypełnienie bazowych granic PRG jest przezroczyste, gdy OSM jest aktywne, dzięki czemu drogi pozostają widoczne; po wyłączeniu podkładu wraca lokalne wypełnienie. Błąd kafelków jest jawny i nie kasuje komunikatów ani znaczników utrudnień. Testy offline: `tests/test_osm.py`, `tests/ui_osm.test.cjs`.

Granica Polski w `poland-border.geojson` jest obrysem sumy lokalnych województw PRG (bez granic wewnętrznych), generowanym przez `scripts/prepare_geo.py`. Dwie linie — białe podbicie i ciemny obrys — pozostają nad podkładem i warstwą ruchu, pod znacznikami; nie przechwytują kliknięć.

## EUMETSAT — aktywność wyładowań LI AFA

Publiczny EUMETView WMS bez klucza, kolorowe obszary wykrytej aktywności, oficjalna legenda, pięciominutowe okresy z ostatniej dostępnej godziny i szczegóły piksela po kliknięciu. To aktywność optyczna także w chmurach, bez rozróżnienia doziemnych i bez dokładnych punktów uderzeń. Opóźnienie pokazane jawnie, cache, demo offline; [dostęp, ograniczenia i weryfikacja](lightning.md).

## NEPTUN — Ukraina

Opcjonalna warstwa obszarów alarmowych i doniesień o zagrożeniach powietrznych. Publiczne REST `/api/v1/alerts`, `/api/v1/threats` oraz granice `/oblasts.geojson`, `/raions.geojson` przez lokalny backend. Bez klucza, cache pamięciowy, brak historii i odczytów w demo. Obszary oraz doniesienia mają odrębną symbolikę; `areaOnly` nie tworzy punktu, `advisory` pozostaje informacją. Granice są pobierane na żądanie, bez kopiowania do repozytorium. [Badanie źródła, kontrakt i ograniczenia](ukraine.md).

## adsb.fi — samoloty nad Polską

Bieżące pozycje przez lokalny backend, filtrowane według lokalnych granic PRG. Endpoint `https://opendata.adsb.fi/api/v3/lat/52.05/lon/19.2/dist/250`, cache 10 sekund; pobieranie po włączeniu warstwy na widocznej mapie, podczas aktywnego śledzenia trasy lub przez opcjonalny kolektor jakości pozycji, niezależny od mapy. Kolektor i warstwa współdzielą żądania, cache i Retry-After. Bez klucza, demo offline. Znak wywoławczy, rejestracja i typ, wysokość barometryczna w metrach, prędkość względem ziemi w km/h i wiek pozycji. Pozycje starsze niż 120 sekund są odrzucane, błędy i ostatni zachowany odczyt oznaczane jawnie. [API i warunki adsb.fi](https://github.com/adsbfi/opendata): użytek osobisty i niekomercyjny, wymagana atrybucja z linkiem do adsb.fi; publiczny limit 1 żądanie/s, brak opublikowanego limitu dziennego. Brak gwarancji dostępności. Znak wywoławczy może różnić się od numeru rejsu na bilecie; pokrycie nie jest pełne.


## Statki AISStream — `ships`

Osobna bieżąca warstwa mapy. Wspólny strumień z kluczem tylko na backendzie, klasy A/B. Wybrane obiekty mają opcjonalną [historię tras z ostatnich 7 dni](tracking.md), zbieraną także bez otwartej karty. Filtr wielokątów wody EEA/VLIZ obejmuje Bałtyk i cieśniny duńskie z Kattegatem, wyklucza Morze Północne, Skagerrak i śródlądzie; niezależny od filtrów publikacji. [Kontrakt, ograniczenia i próba 14.10.2026](ships.md).


## Kolej PolishTrainsGTFS — `trains`

Osobna bieżąca warstwa mapy: stacje w Polsce, kursy i opóźnienia po kliknięciu stacji oraz rozkładowa trasa wybranego kursu. Bez klucza, źródła ZIP GTFS i JSON, współdzielony cache, jawne starzenie na podstawie czasu źródła. Szacowane pozycje wzdłuż trasy z aktualizowanych godzin, osobno oznaczone jako szacunki bez GPS; brak pozycji przy starych danych, błędach, odwołaniach i objazdach bez potwierdzonej geometrii. Bez historii opóźnień i bez sieci w demo. [Kontrakt i ograniczenia](trains.md).


## Autobusy miejskie — `buses`

Szczecin (JSON ZDiTM), Kraków (GTFS/GTFS-RT ZTP, MPK i Mobilis), Poznań (GTFS/GTFS-RT ZTM, po odfiltrowaniu tramwajów) i Warszawa (nowy portal miasta, klucz wyłącznie w backendzie). Wybór miasta i linii, szczegóły dostępne w źródle i wiek pozycji; dane bieżące niezależnie od dnia publikacji oraz województwa. Szare znaczniki po 60 sekundach lub błędzie odświeżania, wygaszanie po 120 sekundach. Bez historii i bez sieci w DEMO. Osobny cache i stan błędów każdego miasta; częściowa awaria Krakowa zachowuje dostępnego operatora.

Źródła, znaczenie opóźnień, klucz Warszawy, warunki i ograniczenia: [autobusy](buses.md).


## Zobrazowania po katastrofach — `imagery`

Copernicus EMS Rapid Mapping, bez klucza, wyszukiwanie po wskazaniu miejsca. Zasięgi materiałów, daty wykonania oddzielone od dat produktów, podglądy przez lokalny backend. Podglądy przedstawiają produkty kartograficzne dotyczące katastrof. Ograniczone pokrycie katalogów, jawne błędy źródła, bez archiwizacji i bez sieci w demo. [Kontrakt, źródła i ograniczenia](imagery.md).

## Hydrologia IMGW JSON

Osobna bieżąca warstwa wodowskazów i ostrzeżeń z oficjalnych API `hydro/` i `warningshydro/`, zweryfikowanych 17.10.2026. Nie zmienia adaptera publikacji meteorologicznych PDF. [Kontrakt, obsługa błędów, czasy i ograniczenia](hydrology.md).

## Jakość powietrza GIOŚ

Bieżąca warstwa godzinowych pomiarów, niezależna od publikacji, dnia i województwa. Punkty i legenda według oficjalnego indeksu ogólnego GIOŚ; brak lub nieaktualny indeks jest szary. Indeksy pobierane wyłącznie w widoku mapy, cache 30 min, kolejka z ograniczeniem współbieżności i respektowaniem backoffu. Oficjalne API v1 JSON-LD zweryfikowane 17.10.2026; stacje 2/min, stanowiska, wyniki i indeks 1500/min. Bez klucza; bez archiwizacji. Wszystkie stężenia, także CO: µg/m³. Źródło danych: GIOŚ - EKOINFONET. Państwowy Monitoring Środowiska. Wyniki niezweryfikowane, mogą ulec zmianie. [Kontrakt, czasy, limity i ograniczenia](gios.md).

## IODA — anomalie dostępności internetu

Publiczne [API v2](https://api.ioda.inetintel.cc.gatech.edu/v2/): kraj PL, regiony związane z country/PL i maks. 8 konfigurowanych, zweryfikowanych ASN. Źródło `ioda` jest w schedulerze, odczyt w tle co 300/600 s niezależnie od warstwy. Podstawą są zdarzenia; alerty i szeregi BGP/ping-slash24/merit-nt są kontekstem. Paginacja od zera, ograniczony czas/rozmiar/liczba zapytań, backoff i Retry-After; poprawne dane pozostają dostępne przy częściowych błędach. Ostatnia próba, pełny sukces, zakres i wiek pomiarów są osobne. Brak detekcji nie oznacza sprawnej łączności; API error nie tworzy anomalii. ASN nie jest ograniczony pomiarowo do Polski ani geolokalizowany na mapie. Pełny [kontrakt i atrybucja IODA](ioda.md). Od 18.10.2026 `tests/fixtures/ioda` zawiera autorskie próbki syntetyczne; wcześniejsze odpowiedzi i kopię OpenAPI usunięto z bieżącej wersji. Historia pierwotnego repozytorium nie jest dołączona do tej kopii.

Opcjonalna [regionalna jakość pozycji / GNSS](position-quality.md): lokalna historia SQLite 24/48 h z retencją, heurystyka jakości raportów ADS-B, bez diagnozy zakłóceń. Audyt i syntetyczne próbki dostępności pól: `tests/fixtures/aircraft/`.


## Copernicus Global Flood Monitoring (GFM)

Osobna, domyślnie wyłączona warstwa „Zalania satelitarne — Copernicus GFM”. Gotowe produkty Sentinel-1, nie prognoza ani Rapid Mapping. Ograniczone wyszukiwanie oficjalnego STAC EODC i HTTP Range do wskazanych assetów; rzeczywiste piksele w Equi7 reprojektowane najbliższym sąsiadem. Wybór obszaru i czasu jest niezależny od publikacji komunikatów. Konfiguracja `[sources.gfm] enabled = true`; automatyczny przegląd Polski przy aktywnej, widocznej warstwie (48 h, katalog co 10 min), grupy wykryć i natywne piksele po przybliżeniu. Osobny tryb archiwalny. Bez sieci w demo; bez pracy po zamknięciu aplikacji.

Kontrakt, warunki CEMS (STAC deklaruje `proprietary`), wymagana atrybucja, klasy, limity, cache i wyniki prób: [docs/gfm.md](gfm.md). Zweryfikowano raster dla Kłodzka 15.09.2024 oraz 17.10.2026. Niepełne produkty bez wymaganej maski są oznaczone na liście i nie mogą być renderowane. Wiek obserwacji i stan pokrycia są odrębne od braku detekcji; brak detekcji nie potwierdza braku powodzi.


## Sentinel-2 — przed / po (CDSE)

Osobna warstwa wyłączona domyślnie. Catalog API `sentinel-2-l2a` wyszukuje wybrany wycinek, Process API renderuje dokładne produkty B04/B03/B02 (10 m), SCL i dataMask. Sekcja `[sources.sentinel2]` jest opcjonalna, OAuth dostępny wyłącznie backendowi. Bez okresowego odpytywania, automatycznego zastępowania dat ani mozaik wielodniowych. Demo całkowicie offline i syntetyczne. [Kontrakt, oficjalne źródła sprawdzone 17.10.2026, limity i jakość](sentinel2.md); [wyniki LIVE i testów](sentinel2-implementation.md).

## Sentinel-5P — regionalna atmosfera (CDSE)

Oddzielna warstwa kolumn NO₂/SO₂ w mol/m² i bezwymiarowego UVAI 354/388 nm. Catalog i Process `sentinel-5p-l2`, backend OAuth, sekcja `[sources.sentinel5p]` domyślnie wyłączona. Dzień i obserwacja są niezależne od publikacji komunikatów oraz stacji GIOŚ. Trzy osobne progi QA: 76/51/81 procent; zachowane prawidłowe zera i wartości ujemne. Brak przeliczania na PM, przyziemne stężenie lub indeks jakości powietrza. Publiczna dokumentacja kanału nie potwierdza wariantu wysokościowego SO₂; UVAI ma udokumentowane ograniczenia zależne od wersji procesora. Demo syntetyczne, bez sieci. [Kontrakt zweryfikowany 17.10.2026, interpretacja, chmury, limity i pochodzenie](sentinel5p.md).
