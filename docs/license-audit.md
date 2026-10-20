# Audyt licencji WICI — czysta kopia z 20.10.2026


## Uzupełnienie kopii — 21.10.2026

Przed publikacją przeniesiono również późniejszą poprawkę OpenStreetMap w widokach LIVE 3D: polityka Referer pozwala przekazać dostawcy sam origin, a DEMO zachowuje `no-referrer`. Przeniesiono zmianę kodu i testów bez importowania starego commita ani jego rodziców. Kontrole OSM, runtime i Cesium oraz Ruff przeszły po aktualizacji.

## Przegląd przed pierwszym commitem nowego repozytorium — 20.10.2026

Kopię przygotowano przez eksport drzewa WICI 0.29.0 (`git archive HEAD`), bez starego `.git`, gałęzi, tagów, lokalnej konfiguracji, baz LIVE/DEMO, katalogu `.secrets`, środowisk Python i `tmp`. Nowe repozytorium rozpoczyna historię jednym commitem. Stare repozytorium pozostaje bez zmian. Własna historia opisów wydań w dokumentacji jest zachowana; wymieniane tam dawne identyfikatory commitów nie są obiektami tego repozytorium.

Przejrzano wykaz 733 eksportowanych plików, formaty binarne, pochodzenie fixture, zasoby map i bibliotek oraz zachowane raporty. Skan wzorców sekretów i porównanie z wartościami poświadczeń lokalnej konfiguracji źródłowego projektu nie wykazały rzeczywistych poświadczeń w eksporcie. Trafienia dotyczyły placeholderów, negatywnych testów URL i fragmentów odtwarzalnego bufora base64 modelu autobusu. Wartości poświadczeń nie są zapisane w raporcie. Usunięto prywatny prefiks ścieżek komputera z dawnych logów testowych; `.gitignore` uzupełniono o pliki systemowe, `.env`, bazy, logi i wyniki budowania. Skan heurystyczny nie jest gwarancją wykrycia każdego możliwego sekretu.

Oba generatory syntetycznych fixture odtworzyły identyczne bajty wszystkich istniejących próbek; zestaw obejmuje dziewięć syntetycznych PDF. Osobne fixture IODA zachowują własne oznaczenia syntetyczne. Modele samolotu i autobusu przeszły kontrolę struktury i odtwarzalności. Obrazy runtime Cesium są zasobami biblioteki z zachowanymi oznaczeniami dostawcy, a nie zapisanymi warstwami usług WICI. Koncepcje logo mają opis pochodzenia w `docs/branding/concepts/PROMPTS.md`.

Sprawdzenie licencji dołączonych zasobów:

- MIT własnego kodu i autorstwo w `LICENSE` pozostają bez zmian; nie oznaczamy całej paczki jako wyłącznie MIT.
- Leaflet 1.9.4 zachowuje pełne BSD-2-Clause; sprawdzono [licencję wersji źródłowej](https://raw.githubusercontent.com/Leaflet/Leaflet/v1.9.4/LICENSE).
- Cesium 1.146.0 zachowuje pełną [licencję i wykaz komponentów](https://raw.githubusercontent.com/CesiumGS/cesium/1.146/LICENSE.md). Lokalna kontrola SHA-256 obejmuje 346 plików runtime. Dodano bezpośrednio do zmodyfikowanego `Cesium.js` opis istniejącej zmiany CSP, zgodnie z wymogiem oznaczania zmodyfikowanych plików Apache-2.0; generator i manifest uwzględniają ten komentarz. Logika runtime nie została zmieniona.
- [GUGiK](https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/) potwierdza bezpłatne, dowolne wykorzystanie PRG; zachowano metadane pochodzenia i przetworzenia.
- [EEA](https://www.eea.europa.eu/en/about/contact-us/faqs/can-i-use-eea-content-in-my-work-or-in-my-organisations-products) dopuszcza ponowne użycie z atrybucją, z zastrzeżeniem warunków konkretnych zbiorów. Zachowano źródła EEA/ETC-ICM/EC w masce.
- [Strona IHO Sea Areas v3](https://www.marineregions.org/download_file.php?name=World_Seas_IHO_v3.zip) nadal wskazuje [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Adaptacja fragmentu Kattegat pozostaje na tych warunkach, z cytowaniem VLIZ (2018), DOI, opisem zmian i ograniczeniem niekomercyjnym. Dostawca prosi również o kierowanie po pełny, aktualny produkt do Marine Regions; repozytorium zawiera opisaną adaptację fragmentu, nie pełny archiwalny produkt.

Weryfikacja wykonana w nowym katalogu: `uv sync --locked`, **838 testów Python**, **283 testy Node**, Ruff, kontrola 346 plików Cesium oraz obu modeli glTF zakończyły się powodzeniem. Trzy ostrzeżenia Pythona dotyczą deprecjacji Starlette/httpx i dwóch syntetycznych rastrów bez georeferencji. Licencje Leaflet i Cesium porównano z plikami wskazanych wersji upstream — są identyczne po normalizacji końców linii. Lokalne odnośniki Markdown mają istniejące cele. Zbudowano sdist i wheel; sprawdzono brak prywatnych katalogów i danych oraz obecność oznaczeń licencyjnych. Testów usług LIVE i scenariuszy Chromium nie uruchamiano w tym przeglądzie.

Nie znaleziono nowych nierozstrzygniętych materiałów testowych wymagających usunięcia. Kopia zachowuje mieszane licencje zasobów i ograniczenie niekomercyjne maski VLIZ. Przegląd dotyczy zawartości repozytorium i paczek źródłowych/WICI, nie stanowi pełnej opinii prawnej, audytu wszystkich binariów zależności ani ponownej weryfikacji regulaminów wszystkich usług LIVE. Samo przygotowanie nowej historii nie usuwa ewentualnych wcześniejszych publicznych kopii.

Własny kod WICI pozostaje na MIT, także do zastosowań komercyjnych. Biblioteki, geometrie i usługi zachowują odrębne warunki. Nie wymaga się, aby każdy dołączony zasób miał licencję MIT. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) określa zakres i wymagane oznaczenia.

## Stan po uporządkowaniu próbek

| Materiał | Bieżący stan |
|---|---|
| Próbki IODA, RSO, IMGW, RCB/SG, GDDKiA, GIOŚ, ADS-B i GFM | Autorskie syntetyczne dane przygotowane od zera. Usunięto rzeczywiste odpowiedzi, dokumenty PDF/HTML i ich rendery, raporty oraz archiwalne kopie. Usunięto OpenAPI IODA i wyciąg OpenAPI GIOŚ. Szczegóły: [fixture](../tests/fixtures/README.md). |
| Raporty i zrzuty | Usunięto zapisane rzeczywiste dane, obrazy satelitarne, zrzuty warstw i zbędne historyczne zestawienia. Pozostałe logi testów opisują lokalne sprawdzenia. Nowe próby live zapisują do ignorowanego `tmp/live-checks/`. [Zasady](evidence/README.md). |
| PyMuPDF / AGPL | Zależność i grupa `pdf-check` usunięte z `pyproject.toml` i lockfile. Generator PDF używa pypdf i standardowej czcionki PDF bez osadzonego pliku fontu. Nie pobiera dokumentów IMGW. |
| Maska EEA/VLIZ | Pozostaje zasobem zewnętrznym. Część VLIZ IHO Sea Areas v3 i własna adaptacja zachowują CC BY-NC-SA 4.0, w tym ograniczenie niekomercyjne, atrybucję i ShareAlike. Jest to przyjęty model publikacji, nie wymóg zastąpienia maski tylko z powodu innej licencji. Liberalniejsze warunki dla tej wersji nie zostały potwierdzone; zastosowanie komercyjne wymaga uprawnienia albo zastąpienia/usunięcia ograniczonej geometrii. |
| Historia Git | Nowe repozytorium utworzono z aktualnego drzewa WICI 0.29.0. Nie przeniesiono starego `.git`, commitów, tagów ani gałęzi. Pierwotne repozytorium pozostawiono bez zmian. |
| Dane live | Porządkowanie fixture nie nadaje praw do dalszej redystrybucji danych pobranych przez użytkownika. Nadal obowiązują licencje danych i regulaminy usług. |
| Metadane paczek | `license-files` dołącza MIT i wykaz zasobów. Nie przywrócono uproszczonego `License-Expression: MIT` dla całej dystrybucji zawierającej zasoby na innych warunkach. |

## Zależności i zakres sprawdzenia

Aktualny `uv.lock` zawiera 38 zależności poza WICI, w tym grupy `dev`, `geo` i zależności warunkowe. Usunięto wyłącznie PyMuPDF; wersje pozostałych pakietów nie wymagały zmiany. [Inwentaryzacja z 17.10.2026](evidence/license-audit-2026-10-17.json) jest historycznym dowodem wcześniejszego audytu, zatem nadal wymienia wówczas obecny PyMuPDF. Hatchling jest oddzielnym nieprzypiętym backendem budowania.

Nie znaleziono wymogu zmiany licencji niezależnego kodu WICI z MIT. MIT, BSD, Apache i PSF zachowują własne wymogi. `certifi` podlega MPL-2.0 na poziomie objętych nią plików; opcjonalny Shapely zawiera GEOS na LGPL. Wheel WICI nie bundluje środowiska Python. Przy dystrybucji kontenera, instalatora lub `.venv` trzeba sprawdzić pełne licencje, źródła i oznaczenia również bibliotek natywnych. W szczególności sprawdzony wheel `gtfs-realtime-bindings==1.0.0` nie zawiera pełnego osobnego LICENSE; należy go zapewnić przy bundlowaniu.

Audyt obejmuje kod, zestaw zależności i materiały repozytorium; nie jest pełną opinią prawną o wszystkich warunkach usług ani audytem binariów każdej platformy. Syntetyczne testy nie zastępują weryfikacji aktualnych kontraktów API. Nie zmieniono produkcyjnych geometrii PRG i EEA/VLIZ ani Leaflet.

Źródła dla maski: [produkt VLIZ](https://www.marineregions.org/download_file.php?name=World_Seas_IHO_v3.zip), [rekord DOI](https://marineinfo.org/en/doc/dataset/5444?doiid=323), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Rozbieżność z ogólnym opisem CC BY nie jest podstawą do przyjęcia liberalniejszych warunków konkretnego produktu.

## Zasoby z potwierdzonymi odrębnymi warunkami

- **Leaflet:** BSD-2-Clause, pełny plik licencji zachowany w repo i wheel.
- **PRG:** [GUGiK](https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/) dopuszcza dowolne wykorzystanie; repo zachowuje źródło i przetworzenie.
- **Teksty RCB:** [Gov.pl](https://www.gov.pl/web/gov/prawa-autorskie) wskazuje CC BY-SA 4.0; własny kod aplikacji może pozostać odrębny. Adaptowane teksty zachowują warunki źródła. Nie przypisano tej licencji automatycznie całym szablonom HTML.
- **adsb.fi:** bieżące źródło lotnicze od 18.10.2026; wyłącznie użytek osobisty i niekomercyjny z atrybucją. [Warunki API](https://github.com/adsbfi/opendata); nie są zastępowane przez MIT kodu WICI.
- **ADSB.lol (wcześniejsza historia) / OSM:** odrębne warunki ODbL i wymagane atrybucje; MIT kodu nie zastępuje praw do baz danych.
- **GFM:** [warunki CEMS](https://global-flood.emergency.copernicus.eu/terms-of-service/) pozwalają na dystrybucję i modyfikacje z pochodzeniem i oznaczeniem zmian. Wpis STAC `proprietary` nie jest samodzielną podstawą do stwierdzenia zakazu. Nie zmieniono go na CC BY.
- **Sentinel-2/5P:** [Sentinel Data Legal Notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) i [CDSE](https://dataspace.copernicus.eu/terms-and-conditions) określają prawa i atrybucje. Obrazy należy przekazywać z rokiem, pochodzeniem i opisem przetworzenia.
- **EFFIS:** [CC BY 4.0 z wyjątkami](https://forest-fire.emergency.copernicus.eu/about-effis/data-license). **FIRMS:** [NASA potwierdza otwartość danych](https://forum.earthdata.nasa.gov/viewtopic.php?t=5184); zachować cytowanie odpowiedniego produktu.
- **Open-Meteo:** [CC BY 4.0 dla danych](https://open-meteo.com/en/licence) oraz odrębne ograniczenia [darmowego API](https://open-meteo.com/en/terms). Komercyjne prawo do kodu MIT nie znosi ograniczeń dostępu do usługi.
- **EUMETSAT LI AFA:** [metadane konkretnego produktu](https://api.eumetsat.int/data/browse/collections/EO%3AEUM%3ADAT%3A0687?format=html) wskazują `NoConditions`. Nie rozszerzono tego ustalenia na każdy element portalu, legendy i zrzutów map.
