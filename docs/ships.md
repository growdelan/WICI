# Statki AISStream — 14.10.2026

Minimalna lokalna warstwa statków na istniejącej mapie WICI. [Dokumentacja dostawcy](https://aisstream.io/documentation).

## Plan wdrożenia — wykonany

1. Sprawdzić klucz, format i polskie wybrzeże w próbie live.
2. Dodać wspólny strumień backendu, lokalne API i ochronę sekretu.
3. Dodać znaczniki, szczegóły, stan połączenia i starzenie pozycji.
4. Przeprowadzić testy offline, przegląd kodu i kontrolę w przeglądarce.

## Konfiguracja

Klucz wyłącznie w ignorowanym przez Git `config.local.toml`:

```toml
[sources.ships]
enabled = true
api_key = "TWÓJ_KLUCZ_AISSTREAM"
```

Start: `uv run --locked python -m wici`. „Warstwy mapy → Bałtyk → Statki AIS”, następnie „Pokaż Bałtyk”. Kliknięcie pokazuje dostępne dane jednostki. Nowy klucz wymaga restartu. Konfiguracja używa `SecretStr`; klucz nie trafia do JavaScript ani URL, debug ramek WebSocket jest wyciszony, surowe błędy dostawcy nie są zwracane do przeglądarki.

## Działanie i ograniczenia

- Strumień `wss://stream.aisstream.io/v0/stream`, kompresja `permessage-deflate`, tylko backend. `GET /api/ships` uruchamia jedno współdzielone połączenie i odnawia zapotrzebowanie na 45 s. UI odczytuje API co 10 s tylko na widocznej mapie z aktywną warstwą. Wyłączenie, ukrycie karty lub przejście do Źródeł zatrzymuje odczyty. Aktywne obserwacje wybrane przez „Śledź trasę” podtrzymują pobieranie niezależnie od przeglądarki. Po 45 s bez odbiorców i aktywnych obserwacji backend zamyka strumień; zamknięcie aplikacji anuluje zadanie.
- Subskrypcja `[[[53, 9], [66, 31]]]` jest tylko wstępnym ograniczeniem transmisji. Każda pozycja przechodzi dodatkowo lokalny filtr wielokątów wody: region morski Bałtyku EEA oraz Kattegat i cieśniny z Marine Regions / VLIZ IHO Sea Areas. Pozostają Bałtyk z zatokami, Øresund, Wielki i Mały Bełt oraz Kattegat; wykluczamy Morze Północne, Skagerrak, Oslofjord, jeziora, rzeki i kanały. Nowsza pozycja poza obszarem usuwa wcześniejszy znacznik. Filtr działa offline; brzegi są kartograficzne (uproszczenie 0,0001°, około kilku–kilkunastu metrów), więc tuż przy linii brzegowej klasyfikacja jest przybliżona. Dzień publikacji i województwo nie wpływają na warstwę.
- Pozycje: `PositionReport`, `StandardClassBPositionReport`, `ExtendedClassBPositionReport`. Metadane: `ShipStaticData`, `StaticDataReport`. Łączenie po MMSI. Nazwa, IMO, typ i cel mogą być nieobecne lub pochodzić ze starszej wiadomości statycznej. Cel nie potwierdza trasy; braki są jawne.
- Start nie pobiera pełnej listy statków. Mapa uzupełnia się stopniowo; restart rozpoczyna zbieranie od nowa. Przy wznowieniu mogą pozostać świeże pozycje z pamięci.
- Wiek z `MetaData.time_utc` dostawcy, nie z czasu pobrania lokalnego API ani sekundowego `Timestamp` AIS. To czas raportu w strumieniu, bez niezależnego potwierdzenia momentu pomiaru na statku. Metadane nie odmładzają pozycji; starszy raport nie zastępuje nowszego.
- Po 5 min ikona otrzymuje paski zachowując kolor klasyfikacji; po 15 min pozycja znika także z backendu. Kierunek dziobu ma pierwszeństwo przed kursem nad dnem; brak obu daje koło. Prędkość w węzłach, wartości AIS oznaczające brak danych odrzucane.
- Błędy i cisza powodują ponawianie z rosnącym opóźnieniem i losowym rozproszeniem. Pozycje starzeją się także przy awarii. Bufor do 10 000 jednostek, ramka do 64 KiB; bieżący zbiór tylko w pamięci, bez zapisu surowych wiadomości. Wybrane obserwacje mają osobną, trwałą [historię tras z ostatnich 7 dni](tracking.md).
- Brak klucza, wyłączenie i demo nie otwierają połączenia. API blokuje obce pochodzenie i nie zwraca sekretu.
- AISStream obecnie bezpłatny, wymaga konta i klucza. Brak SLA, gwarancji pełnego pokrycia i odtwarzania wiadomości. Limit trzech połączeń na konto/IP obejmuje także inne aplikacje. Darmowy dostęp nie jest otwartą licencją na redystrybucję strumienia.

## Weryfikacja

14.10 około 18:53 CEST: `CompressionEnabled=true`; w około 35 s odebrano 380 raportów pozycji klasy A, 75 klasy B, 31 `StaticDataReport` i 56 `ShipStaticData`. Wiadomości od 43 różnych MMSI w obszarze polskiego wybrzeża 14–20°E / 53,5–56°N. To próbka dostępności, nie pomiar kompletności.

Lokalne API: HTTP 200, `status=ready`, 111 jednostek, w tym 4 w powyższym obszarze na wczesnym etapie zbierania; klucz nieobecny w odpowiedzi. W przeglądarce potwierdzono przyrost znaczników, widok Bałtyku i dymek jednostki RSP-SB 110 z MMSI, prędkością, kursem, wiekiem i jawnymi brakami pozostałych pól.

Testy offline: klasy A/B, nanosekundowe daty i boolean `PartNumber`, metadane i starzenie, starsze raporty, skrajne liczby/daty, wartości niedostępne, współdzielenie, bezczynność i zamykanie, błędy, demo i maskowanie klucza. UI: odświeżanie, znaczniki, opóźnione odpowiedzi po wyłączeniu, ukrywanie, starzenie i nawigacja. Polecenia: `uv run --locked pytest -q`, `uv run --locked ruff check .`, `node tests/ships_ui.cjs`, `node --test tests/ui_*.test.cjs`.

Wynik końcowy: 317 testów Python, 54 dotychczasowe testy UI oraz test cyklu warstwy statków przechodzą; Ruff, kontrola lockfile i diff bez błędów. Klucz sprawdzony: uprawnienia lokalnego pliku 0600, plik ignorowany przez Git, brak sekretu w wersjonowanych i nowych plikach źródłowych.

## Dane granic akwenów

**Licencja zasobu:** audyt z 17.10.2026 wykazał, że [konkretny zbiór VLIZ IHO Sea Areas v3](https://www.marineregions.org/download_file.php?name=World_Seas_IHO_v3.zip) wskazuje CC BY-NC-SA 4.0, mimo ogólnego opisu CC BY w serwisie Marine Regions. Dotyczy to części Kattegat w dołączonej masce. Nie należy zakładać swobodnego komercyjnego wykorzystania tego pliku ani obejmować go MIT; szczegóły i dalsze działania w [audycie](license-audit.md) i [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Plik `src/wici/static/geo/baltic-water.geojson.gz`: suma regionu `Baltic Sea` z [EEA Marine regions](https://marine.discomap.eea.europa.eu/arcgis/rest/services/Marine/Marine_regions_subregions/MapServer/2) (EEA, ETC/ICM, EC) i obszaru `Kattegat` z [VLIZ Marine Regions IHO Sea Areas v3, 2018](https://doi.org/10.14284/323). Zachowano otwory lądowe; uproszczono topologicznie i zaokrąglono współrzędne do 6 miejsc, naprawiając zapadnięte przy zaokrągleniu pierścienie mniejsze od dokładności zapisu. Obszaru IHO Gulf of Finland nie użyto jako maski wody, ponieważ obejmuje także Ładogę. Pochodzenie, adresy i sumy SHA-256 plików źródłowych zapisano we właściwościach GeoJSON. Indeksy krawędzi według szerokości i otworów według komórek przyspieszają testy pozycji; brak zależności GIS w uruchomionej aplikacji.

Odtworzenie z jawnie pobranych plików: `uv run --group geo python scripts/prepare_marine_area.py --eea tmp/baltic-eea-source.geojson --iho tmp/baltic-iho-source.geojson`. EEA: zapytanie `/query` z `where=localId='BAL'`, `f=geojson`, `outFields=name_text`, `outSR=4326`. VLIZ WFS: `service=WFS`, `version=1.0.0`, `request=GetFeature`, `typeName=MarineRegions:iho`, `outputFormat=application/json`, `srsName=EPSG:4326`, `CQL_FILTER=name IN ('Baltic Sea','Gulf of Bothnia','Gulf of Finland','Gulf of Riga','Kattegat')`. Skrypt nie pobiera sieciowo danych.

Po zawężeniu obszaru: 350 testów Python i test warstwy statków przechodzą; Ruff i diff bez błędów. Geometria po spakowaniu poprawna topologicznie; lokalny filtr znajduje się także w zbudowanym wheel. Próba bieżącego strumienia: stan ready, 124 zaakceptowane jednostki, wszystkie wewnątrz maski. Sprawdzono konkretne punkty Bałtyku, zatok i cieśnin oraz odrzucanie Morza Północnego, Skagerraku, Oslofjordu, Łaby, Wisły, Odry, Newy, Kanału Kilońskiego i jezior Mälaren, Vänern, Saimaa i Ładoga.

## Kolory typu AIS — 15.10.2026

Fioletowy: „Wojskowe według AIS”, wyłącznie kod 35. Morski: rozpoznane typy cywilne według AIS. Szary: „Nieustalone”, w tym brak typu, zero, kody zarezerwowane, „inne” (90–99), ratownictwo (51), służby porządkowe (55) i pozostałe niejednoznaczne kody. Kategorię pokazują także dymek i podpowiedź tekstowa, legenda znajduje się w panelu Bałtyku oraz w legendzie mapy przy aktywnej warstwie. Po 5 minutach paski oznaczają wiek bez utraty koloru kategorii; po 15 minutach pozycja znika. Później odebrane metadane mogą zmienić kategorię istniejącego znacznika.

Brak kodu 35 nie oznacza, że jednostka jest cywilna. Klasyfikacja opiera się na deklarowanym typie AIS, nie na potwierdzonej przynależności. Ta informacja jest widoczna przy legendzie i w dymku jednostki. Nie klasyfikujemy po nazwie ani nie uznajemy każdego kodu innego niż 35 za cywilny.

Rozpoznawane typy cywilne: 20–24 i 29 (WIG), 30–34 (rybołówstwo, holowanie, prace podwodne), 36–37 (żaglowe i rekreacyjne), 40–44 i 49 (HSC), 50, 52–54 (pilotowe, holowniki, obsługa portu, ochrona przed zanieczyszczeniami), 60–64 i 69 (pasażerskie), 70–74 i 79 (towarowe), 80–84 i 89 (zbiornikowce). Zarezerwowane podtypy pozostają nieustalone. [Tabela typów AIS — USCG NAVCEN](https://www.navcen.uscg.gov/sites/default/files/pdf/AIS/AISGuide.pdf).
