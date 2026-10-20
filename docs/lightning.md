# EUMETSAT — wykryta aktywność wyładowań

Zweryfikowano 14.10.2026. Oficjalny [EUMETView](https://user.eumetsat.int/data-access/eumetview) udostępnia publiczny WMS `https://view.eumetsat.int/geoserver/wms`. GetCapabilities, GetMap i GetLegendGraphic działają bez konta, klucza i opłaty. Wybrano `mtg_fd:li_afa`, styl `mtg_li_afa`: [LI Accumulated Flash Area](https://view.eumetsat.int/productviewer/productDetails/mtg_fd%3Ali_afa). Alternatywny Data Store udostępnia produkty do pobrania, ale jego uwierzytelnienie i przetwarzanie netCDF nie są potrzebne do tego widoku.

Publiczny dostęp nie oznacza gwarantowanej dostępności ani aktualności. Nie znaleziono jawnego limitu zapytań dotyczącego tego WMS; limitów Data Store nie przenosimy na EUMETView. WICI pobiera metadane najwyżej co 300 s, obrazy tylko na żądanie i współdzieli cache sześciu obrazów. Legenda pozostaje w pamięci procesu. HTTP 429 respektuje Retry-After, błędy wstrzymują ponowienia. Brak masowego pobierania i archiwizacji. Warstwa domyślnie wyłączona; ukrycie mapy/karty lub wyłączenie przełącznika zatrzymuje odświeżanie. Demo nie kontaktuje się z EUMETSAT.

Użycie w prywatnej aplikacji z atrybucją © EUMETSAT; [warunki użycia](https://www.eumetsat.int/about-us/terms-use) i [polityka danych](https://www.eumetsat.int/legal-framework/data-policy). Publiczne metadane produktu AFA `EO:EUM:DAT:0687` wskazują `NoConditions`. Nie traktujemy tego jako deklaracji nieograniczonej licencji na wszystkie zasoby strony ani gwarancji usługi dla wdrożenia komercyjnego.

## Znaczenie obrazu

AFA pokazuje obszary optycznej aktywności wyładowań na siatce instrumentu, nie dokładne punkty uderzeń w ziemię. [Lightning Imager](https://www.eumetsat.int/meteosat-third-generation-imaging-services) obserwuje także wyładowania w chmurach i nie rozróżnia ich od doziemnych. Rozdzielczość siatki około 2 km nie oznacza takiej dokładności lokalizacji uderzenia.

Każda klatka sumuje pięć minut: czas WMS jest początkiem okresu. Selektor pokazuje początek i koniec w Europe/Warsaw, do 13 klatek z ostatniej dostępnej godziny. Obraz obejmuje prostokąt Polski 49–55°N, 14–24,2°E (także fragmenty sąsiadów), 768×768 px w EPSG:3857. Kolory i skala pochodzą z oficjalnej legendy; nie dopisujemy własnych liczników wyładowań. Kliknięcie odczytuje przezroczystość piksela zweryfikowanego obrazu bez dodatkowego zapytania do źródła. GetFeatureInfo w próbie zwracał kanały RGB, nie surową liczbę wyładowań. Przezroczysty piksel nie dowodzi braku burzy.

UI pokazuje wiek końca najnowszego okresu, ostrzegając powyżej 15 minut. To lokalny próg informacyjny, nie SLA EUMETSAT. Dostępne czasy pochodzą wyłącznie z GetCapabilities, nie z zegara aplikacji. Początkowa próba miała około 27 minut opóźnienia; kolejne odczyty zmieniają tę wartość. Nie zastępuje ostrzeżeń IMGW ani informacji służb. Warstwa jest niezależna od daty publikacji komunikatów, radaru i prognozy pogody.

## Weryfikacja

Testy offline: `tests/test_lightning.py`, `tests/ui_lightning.test.cjs`: źródłowe okresy, cache i równoległe żądania, poprawny całkowicie przezroczysty PNG, uszkodzone/za duże odpowiedzi, ograniczenia czasu i współrzędnych, 429, opóźniony odczyt, demo, zmiana okresu i spóźnione odpowiedzi po wyłączeniu warstwy.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).
