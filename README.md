# WICI — sytuacja i ostrzeżenia

WICI to lokalna aplikacja do przeglądania oficjalnych komunikatów dotyczących Polski i dodatkowych danych na wspólnej mapie. Łączy publikacje IMGW, Regionalnego Systemu Ostrzegania (RSO), Rządowego Centrum Bezpieczeństwa (RCB) i Straży Granicznej z warstwami pogody, ruchu drogowego, pożarów, autobusów miejskich, samolotów, kolei i statków na Bałtyku.

Zakładka **Analiza** łączy katalog komunikatów, wodowskazów IMGW, stacji GIOŚ i obszarów PRG ze zsynchronizowaną mapą, tabelą, osią czasu i kartami obiektów. Obsługuje lokalną historię stacji oraz zapisane stanowiska. [Instrukcja stanowiska analitycznego](docs/analysis-workspace.md).

**Teczki analiz** gromadzą przypięte obiekty, notatki i zapisane kopie kart, historii oraz porównań. Materiał zachowuje źródło i kontekst czasu, pozostając dostępny po wygaśnięciu historii źródłowej. [Obsługa teczek](docs/analysis-dossiers.md).

**Graf powiązań** pokazuje relacje obiektów z obszarami, hierarchie regionów, alarmy i raporty pozycji. Rozwijaj sąsiadów, sprawdzaj pochodzenie połączeń i dodawaj uzasadnione relacje analityczne w teczce. Możesz zachować roboczy układ lub niezmienną kopię grafu. [Obsługa grafu i relacji](docs/analysis-relations.md).

Obejrzyj [film prezentujący, czym jest WICI](https://www.youtube.com/watch?v=zIEp2ceINj4).

Opcjonalna warstwa NEPTUN rozszerza widok o Ukrainę: obszary alarmów oraz doniesienia o dronach, rakietach i innych zagrożeniach.

W **Analizie → Kraj: Ukraina** dostępne są regiony, karty alarmów oraz porównanie do pięciu regionów na wspólnej mapie i osi czasu. Osobny przełącznik **Rejestruj historię alarmów Ukrainy** buduje lokalne archiwum od chwili włączenia; luki w odczytach pozostają widoczne. [Historia alarmów i porównanie regionów](docs/ukraine.md#analiza-historia-alarmów-i-porównanie-regionów-v0320).

Pozwala sprawdzić informacje dla wybranego dnia i województwa, otworzyć pełną zapisaną treść oraz przejrzeć historię zmian komunikatu. Dane i historia pozostają na Twoim komputerze. Aplikacja nie wymaga konta WICI ani klucza do modelu AI.

To pomocniczy przegląd publikacji: nie zapewnia pełnego obrazu sytuacji i nie zastępuje oficjalnych ostrzeżeń ani służb alarmowych.

Ta kopia rozpoczyna nową historię Git od wersji 0.29.0. Zakres przeglądu plików, wyniki kontroli i odrębne warunki zasobów opisuje [audyt przed publikacją](docs/license-audit.md).

## Szybki start

Potrzebujesz macOS lub Linux, przeglądarki oraz [uv](https://docs.astral.sh/uv/getting-started/installation/). Projekt wymaga **Pythona 3.12**; uv może pobrać go podczas instalacji zależności. Kod używa uniksowego `fcntl`, więc na Windows uruchamiaj go w WSL.

W terminalu:

```sh
git clone https://github.com/growdelan/WICI.git
cd WICI
uv sync --locked
uv run --locked python -m wici
```

Jeśli masz już repozytorium, zacznij od `uv sync --locked` w jego katalogu. Następnie otwórz **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. Aplikacja nasłuchuje tylko lokalnie. Zatrzymasz ją przez **Ctrl+C** w terminalu.

**Podstawowe funkcje działają bez konfiguracji i bez kluczy API.** W trybie zwykłym potrzebny jest internet do pobierania publikacji i warstw sieciowych. Pierwsze komunikaty pojawią się po odczycie źródeł; postęp i błędy sprawdzisz w widoku „Źródła”.

Aby obejrzeć aplikację na danych demonstracyjnych, uruchom zamiast powyższej komendy:

```sh
uv run --locked python -m wici --demo
```

Demo używa danych syntetycznych i nie łączy się z dostawcami. Po zainstalowaniu zależności działa offline, zapisuje dane osobno i korzysta z tego samego adresu. Przed zmianą trybu zatrzymaj poprzednią instancję.

Sentinel-2: „Warstwy mapy → Sentinel-2 — przed / po” pozwala wskazać punkt w Polsce, wyszukać obserwacje L2A i porównać dwa wybrane terminy suwakiem RGB 10 m. Osobne zakresy dat dla „przed” i „po” umożliwiają porównanie różnych lat, np. 2020 i 2026; każdy zakres obejmuje do 366 dni. Obszar 2/4/6 km, maski jakości i NoData. Domyślnie pokazuje pełny zasięg katalogowy; częściowe obserwacje można odsłonić filtrem, a rzeczywiste braki obrazu są podane procentowo przy suwaku. Wymaga bezpłatnego klienta OAuth CDSE w lokalnej sekcji `[sources.sentinel2]`; demo zawiera jawnie syntetyczne obrazy i działa offline. [Konfiguracja i ograniczenia](docs/sentinel2.md), [raport implementacji](docs/sentinel2-implementation.md).

Sentinel-5P: osobna, domyślnie wyłączona warstwa regionalnych kolumn NO₂ / SO₂ i bezwymiarowego indeksu aerozolowego UVAI. Wybierz dzień UTC i obserwację, sprawdź jednostki, czas, jakość i pochodzenie; GIOŚ może pozostać włączony. To nie pomiar przy ulicy ani dowód emisji z zakładu. Włącz `[sources.sentinel5p]`; można użyć istniejącego klienta CDSE Sentinel-2 lub osobnej pary OAuth. Demo jest syntetyczne i offline. [Konfiguracja, jakość, ograniczenie profilu SO₂ i uwagi UVAI](docs/sentinel5p.md).

GFM: włącz „Warstwy mapy → Zalania satelitarne — Copernicus GFM”. Domyślny tryb automatycznie sprawdza Polskę (ostatnie 48 h, katalog co 10 min), stopniowo pokazuje grupy wykryć, a po przybliżeniu piksele 20 m. Archiwum i próba Kłodzka są dostępne osobno. Możesz jednocześnie włączyć wodowskazy i ostrzeżenia IMGW. Demo jawnie pokazuje brak danych GFM. [Instrukcja, ograniczenia i scenariusze weryfikacji](docs/gfm.md).

W polu **„Obszar danych”** wybierz województwo albo **„Cała Polska”**. Aplikacja zapamiętuje region, ogranicza indeksy GIOŚ i siatkę prognozy oraz pokazuje wyniki kolejnych źródeł niezależnie. W panelu **„Postęp warstw”** sprawdzisz stan każdej włączonej warstwy. Źródła udostępniające wyłącznie krajowy zestaw są filtrowane lokalnie. [Zakres, cache i ograniczenia](docs/regions.md).

## Co znajdziesz w aplikacji

| Funkcja | Co daje | Klucz API |
| --- | --- | --- |
| Komunikaty IMGW, RSO, RCB i Straży Granicznej | Lista publikacji, mapa obszarów, treść, daty i historia wersji | Nie |
| Mapa OpenStreetMap i granice PRG | Drogi, miejscowości, województwa i powiaty | Nie |
| Pogoda IMGW / Open-Meteo | Pomiary i prognozy wiatru oraz opadów, wybór godziny prognozy | Nie |
| Jakość powietrza GIOŚ | Godzinowe stężenia, punkty według oficjalnego indeksu, legenda i tabela wyników stacji | Nie |
| Sentinel-2 — przed / po | Dwie wybrane obserwacje RGB L2A 10 m, suwak i maski SCL; CDSE OAuth | Tak, backend |
| Sentinel-5P — atmosfera regionalna | Kolumny NO₂/SO₂, indeks UVAI, wybór dnia i obserwacji, jakość i pochodzenie | Tak, backend CDSE |
| Zalania satelitarne Copernicus GFM | Automatyczny przegląd Polski i piksele Sentinel-1, archiwum i jakość; osobno od Rapid Mapping | Nie |
| Hydrologia IMGW | Wodowskazy, pomiary z czasem odczytu i filtrowana lista ostrzeżeń hydrologicznych | Nie |
| Radar RainViewer | Animowana historia opadów | Nie |
| Wyładowania EUMETSAT | Satelitarna aktywność wyładowań, także wewnątrz chmur | Nie |
| Zagrożenie pożarowe EFFIS | Prognoza warunków pogodowych sprzyjających pożarom | Nie |
| IODA | Anomalie dostępności internetu: Polska, regiony i wybrane ASN; historia SQLite, sygnały i status źródła | Nie |
| NASA FIRMS | Satelitarne wykrycia pożarów i anomalii cieplnych w Polsce, okno 24/48 h | Tak, opcjonalny |
| Zobrazowania po katastrofach | Materiały Copernicus EMS dla wskazanego miejsca, daty, zasięgi i podglądy | Nie |
| Utrudnienia GDDKiA | Opisy utrudnień na drogach krajowych i znaczniki odcinków | Nie |
| Ruch drogowy TomTom | Płynność ruchu oraz nazwa i oznaczenia drogi po kliknięciu | Tak, opcjonalny |
| Kolej PolishTrainsGTFS | Stacje, kursy, opóźnienia, trasy i wyraźnie oznaczone szacowane pozycje | Nie |
| Autobusy: Szczecin, Kraków, Poznań, Warszawa | Bieżące pozycje, wybór miasta i linii, szczegóły oraz wiek danych | Tylko Warszawa |
| Samoloty adsb.fi | Bieżące pozycje i dostępne dane lotów nad Polską; cache i odświeżanie 10 s, użytek osobisty i niekomercyjny | Nie |
| Ukraina — alerty NEPTUN | Obszary alarmów oraz osobno doniesienia o dronach i innych zagrożeniach, z czasem i źródłem | Nie |
| Jakość pozycji / GNSS | Opcjonalne lokalne agregaty jakości ADS-B; pośredni sygnał, bez diagnozy przyczyny | Nie |
| Statki AISStream | Bieżące pozycje i dostępne dane jednostek na Bałtyku i w cieśninach duńskich z Kattegatem | Tak, opcjonalny |

Hydrologię włączysz w grupie **„Pogoda”**: „Wodowskazy” i „Ostrzeżenia hydrologiczne”. Kliknij punkt lub wybierz stację, aby zobaczyć stan wody, przepływ i temperaturę z osobnymi datami oraz oznaczeniem starych pomiarów. [Zakres i ograniczenia integracji](docs/hydrology.md).

Warstwę **„Jakość powietrza GIOŚ”** włączysz w grupie „Pogoda”. Wybierz stację, zanieczyszczenie i stanowisko, aby zobaczyć stężenie, jego wiek, oficjalny indeks i tabelę godzinową. Punkty są kolorowane według oficjalnego indeksu ogólnego, z legendą; brak lub nieaktualny indeks jest szary. Indeksy pobierane są tylko dla widocznych stacji i cache’owane przez 30 min. Bez klucza API; domyślnie wyłączona na mapie, demo offline. Źródło danych: GIOŚ - EKOINFONET. Państwowy Monitoring Środowiska. Wyniki niezweryfikowane, mogą ulec zmianie. [Dokumentacja integracji i testów](docs/gios.md).

Warstwy włączasz w panelu **„Warstwy mapy”** nad mapą. Większość dodatkowych danych jest pobierana dopiero po włączeniu odpowiedniej warstwy na widocznej mapie. IODA zbiera dane w tle niezależnie od widoczności warstwy; FIRMS po skonfigurowaniu integracji.

Checkbox **„Komunikaty i ostrzeżenia”** w tym panelu włącza i wyłącza podstawową nakładkę: karteczki komunikatów, kolorowane obszary i ich legendę. Lista publikacji pozostaje dostępna. W trybie IODA wspólny widok wymaga także zaznaczenia „Pokaż też komunikaty i ostrzeżenia na mapie”.

Przeglądarka zapamiętuje wybory wszystkich checkboxów, także opcje pomocnicze warstw i podkład 3D. Ustawienia wracają po odświeżeniu lub ponownym otwarciu tego samego adresu aplikacji. Filtr komunikatów udostępnianych dziś zachowuje wybór po powrocie z archiwum do dzisiejszego dnia. Gdy pamięć przeglądarki jest niedostępna, wybory działają do zamknięcia strony.

Dostęp bez klucza nie oznacza dowolnego zastosowania komercyjnego: publiczne API Open-Meteo jest przeznaczone do użytku niekomercyjnego, a darmowy radar RainViewer do użytku osobistego i edukacyjnego. Warunki i atrybucje źródeł zebrano w [dokumentacji źródeł](docs/sources.md) i [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Samolot — śledzenie w 3D

Włącz warstwę **Samoloty** w Lotnictwie, kliknij świeżą pozycję z dostępną wysokością i wybierz **Podążaj w 3D**. Kamera zewnętrzna i pierwsza osoba poruszają się wraz z samolotem; powrót lub Escape zachowuje kadr i warstwy Atlasu. Silnik Cesium jest lokalny i nie wymaga kluczy. Podstawowy globus zawiera lokalne granice Polski; OpenStreetMap można włączyć osobno. Powierzchnia jest uproszczona, bez rzeźby terenu i budynków. Animacja korzysta z opóźnionych raportów i ograniczonej predykcji, a utrata świeżych danych zatrzymuje ruch. [Obsługa, dokładność i weryfikacja](docs/aircraft3d.md).

### Samoloty i statki — zapis tras i odtwarzanie

W zakładce **Analiza** samoloty i statki mają własne karty, wyszukiwanie po identyfikatorach oraz trwałą listę obserwowanych. Możesz rozpocząć zapis w karcie i porównać do pięciu zapisanych tras na wspólnej mapie, osi czasu oraz wykresach prędkości i wysokości. Obserwowanie nie uruchamia nagrywania. [Obsługa, zakres danych i ograniczenia](docs/analysis-moving-objects.md).

Kliknij samolot lub statek i wybierz **„Śledź trasę”**. Wokół wybranego obiektu pojawią się znaczniki zaznaczenia, a na mapie będzie przyrastała jego zapisana trasa. W panelu **„Trasy obserwacji”** wybierzesz obserwację, przewiniesz czas suwakiem i odtworzysz ruch z wybraną prędkością. Powrót do trybu bieżącego pokazuje najnowszy zapis. Zatrzymanie zapisu zachowuje dotychczasową historię.

WICI zapisuje wybrane obiekty w lokalnej bazie także po wyłączeniu warstwy lub zamknięciu karty przeglądarki. **Proces WICI musi działać, a komputer pozostawać aktywny.** Aktywne obserwacje są wznawiane po restarcie; przerwy nie są uzupełniane wstecz. Przechowywane jest ostatnie **7 dni**, maksymalnie 20 aktywnych obserwacji jednocześnie. Śledzenie zaczyna się od wybrania obiektu i obejmuje dostępne pozycje samolotów nad Polską oraz statków w obsługiwanym obszarze Bałtyku. [Obsługa i ograniczenia historii](docs/tracking.md).

### Ukraina — alerty NEPTUN

Włącz **„Warstwy mapy → Ukraina → Ukraina — alerty NEPTUN”**. Widok obejmie Polskę i Ukrainę, pokaże granice obwodów i obszary alarmów. Osobne oznaczenia przedstawiają doniesienia o dronach, rakietach i innych zagrożeniach; kliknięcie pokazuje dostępne szczegóły i czas. Dane są bieżące, niezależne od dnia publikacji i województwa. Przycisk „Pokaż Polskę i Ukrainę” przywraca wspólny widok.

Klucz i rejestracja nie są potrzebne. Pobieranie odbywa się tylko przy włączonej warstwie na widocznej mapie. NEPTUN jest agregatorem z niepełnym pokryciem i możliwymi opóźnieniami; doniesienie nie potwierdza uderzenia, a brak wpisu nie oznacza bezpieczeństwa. Obowiązują oficjalne sygnały alarmowe. Demo pokazuje jawny brak danych tej warstwy. Wyłączenie integracji w konfiguracji: `[sources.ukraine] enabled = false`. [Badanie API, znaczenie oznaczeń i ograniczenia](docs/ukraine.md).

## Konfiguracja i klucze API

Konfigurację zapisuj w **`config.local.toml` w głównym katalogu projektu**. Plik jest pomijany przez Git. Klucze FIRMS, TomTom, AISStream i Warszawy są używane przez backend i nie trafiają do kodu przeglądarki. Nie publikuj pliku z kluczami.

Jeśli plik jeszcze nie istnieje, skopiuj wzór:

```sh
cp config.example.toml config.local.toml
```

Jeśli już go masz, edytuj istniejący plik. **Po zmianie konfiguracji uruchom aplikację ponownie.** Nie trzeba włączać wszystkich integracji — bez kluczy wyłączone pozostają tylko funkcje, które ich wymagają.

### NASA FIRMS — wykrycia pożarów

1. Otwórz oficjalny [formularz FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).
2. Wybierz „Get MAP_KEY”, podaj adres e-mail i wyślij formularz. NASA prześle bezpłatny klucz e-mailem.
3. W `config.local.toml` zmień istniejącą sekcję `[sources.firms]` na:

```toml
[sources.firms]
enabled = true
interval_seconds = 900
map_key = "TWOJ_KLUCZ_FIRMS"
```

Po restarcie sprawdź odczyt NASA FIRMS w „Źródłach” i włącz „Satelitarne wykrycia pożarów” na mapie. To wykrycia anomalii cieplnych, a nie potwierdzone interwencje straży pożarnej. Szczegóły: [FIRMS](docs/firms.md).

### TomTom — ruch drogowy i identyfikacja dróg

1. Załóż konto lub zaloguj się w [MyTomTom](https://my.tomtom.com/).
2. Otwórz „API & SDK Keys” i skopiuj klucz, np. domyślny „My first API key”. [Oficjalna instrukcja](https://docs.tomtom.com/platform/documentation/my-tomtom/how-to-get-a-tomtom-api-key) opisuje ten proces.
3. Upewnij się, że klucz ma dostęp do **Traffic API** i **Reverse Geocoding API** — aplikacja korzysta z usług TomTom Orbis Maps.
4. Uzupełnij istniejącą sekcję w `config.local.toml`:

```toml
[sources.tomtom]
enabled = true
api_key = "TWOJ_KLUCZ_TOMTOM"
```

Po restarcie włącz „Ruch drogowy TomTom”. Kliknięcie drogi pobierze jej nazwę i oznaczenia, jeśli dostawca je udostępnia.

WICI zatrzymuje pobieranie po 190 000 próbach pobrania kafelków i 19 000 próbach identyfikacji drogi miesięcznie (UTC). Liczniki obejmują tylko tę instalację. Dostępny plan, opłaty i łączne wykorzystanie klucza sprawdzaj w koncie oraz [cenniku TomTom](https://docs.tomtom.com/pricing). Ruch drogowy nie jest archiwizowany.

### AISStream — statki na Bałtyku

1. Otwórz [konto AISStream](https://aisstream.io/account) i zaloguj się przez GitHub.
2. W panelu konta wygeneruj klucz API i od razu go skopiuj — nowy klucz jest pokazywany tylko raz. [Dokumentacja AISStream](https://aisstream.io/documentation) opisuje zarządzanie kluczami i limity połączeń.
3. Uzupełnij istniejącą sekcję w `config.local.toml`:

```toml
[sources.ships]
enabled = true
api_key = "TWOJ_KLUCZ_AISSTREAM"
```

Po restarcie wybierz **„Warstwy mapy → Bałtyk → Statki AIS”**, a następnie „Pokaż Bałtyk”. Pozycje pojawiają się stopniowo wraz z napływem wiadomości; nie jest pobierana pełna lista statków na start. Bieżący zbiór pozostaje w pamięci; przycisk **„Śledź trasę”** w szczegółach wybranej jednostki rozpoczyna zapis jej historii w lokalnej bazie. Kolory według deklarowanego AIS: fioletowy — kod 35, morski — rozpoznane typy cywilne, szary — nieustalone. Brak kodu 35 nie oznacza, że jednostka jest cywilna. Paski oznaczają pozycje starsze niż 5 minut. Szczegóły: [statki AIS](docs/ships.md).

### Kolej — stacje, kursy i opóźnienia

Włącz **„Warstwy mapy → Kolej → Stacje, kursy i opóźnienia”**. Kliknij stację, a następnie kurs, aby zobaczyć trasę i postoje. Integracja działa bez klucza. Pierwsze wczytanie dużego rozkładu może potrwać kilkadziesiąt sekund; backend współdzieli cache między odczytami.

Fioletowe punkty oznaczają stacje; romby ze znakiem pociągu — **pozycje szacowane, nie GPS**. Szacunki odświeżają się co 15 sekund, pokazują wiek danych i znikają przy nieaktualnym źródle lub błędzie. Odwołane kursy i objazdy bez geometrii nie otrzymują pozycji. Brak aktualizacji kursu oznacza rozkład planowy, nie potwierdzoną punktualność. Szczegóły: [kolej](docs/trains.md).

### Autobusy miejskie — Szczecin, Kraków, Poznań i Warszawa

Włącz **„Warstwy mapy → Komunikacja miejska → Autobusy miejskie”**, wybierz miasto i naciśnij „Pokaż…” aby ustawić mapę. Filtr „Linia” ogranicza znaczniki; kliknięcie numeru linii pokazuje dostępne szczegóły pojazdu i wiek pozycji. Zmiana miasta resetuje filtr linii i usuwa poprzednie znaczniki.

W szczegółach świeżej pozycji wybierz **„Podążaj w 3D”**. Kamera zewnętrzna i pierwsza osoba podążają za autobusem na uproszczonej powierzchni; opcjonalny OpenStreetMap można włączyć osobno. Brakujący kierunek kamery jest szacowany z kolejnych pozycji i oznaczony. Wspólny lokalny silnik 3D nie wymaga dodatkowych kluczy, a powrót zachowuje kadr Atlasu. [Obsługa, dokładność i ograniczenia](docs/buses3d.md).

Szczecin, Kraków i Poznań działają bez klucza. Pierwsze wczytanie Krakowa lub Poznania może potrwać dłużej, ponieważ WICI pobiera rozkład GTFS. Pobieranie działa tylko na widocznej mapie, bez zapisu historii. Szare znaczniki oznaczają pozycje starsze niż minutę lub problem odświeżania; po 2 minutach pozycje znikają. Warstwa obejmuje także trasy podmiejskie i jest niezależna od dnia publikacji oraz filtra województwa. W DEMO nie pobiera danych.

**Warszawa:** pobierz indywidualny klucz z [nowego portalu danych miejskich](https://dane.um.warszawa.pl/pl/key-api). W `config.local.toml` dodaj albo zmodyfikuj pojedynczą sekcję:

```toml
[sources.buses_warsaw]
enabled = true
api_key = "TWOJ_KLUCZ_NOWEGO_PORTALU"
```

Klucz starego `api.um.warszawa.pl` nie jest kluczem nowej integracji. Po zmianie konfiguracji uruchom aplikację ponownie. Brak klucza Warszawy nie blokuje pozostałych miast. `[sources.buses] enabled = false` wyłącza całą warstwę; osobne sekcje `buses_szczecin`, `buses_krakow`, `buses_poznan`, `buses_warsaw` pozwalają wyłączyć wybrane źródło.

Zakres szczegółów zależy od miasta: brak informacji o opóźnieniu oznacza brak danych, a nie potwierdzoną punktualność. [Źródła i ograniczenia autobusów](docs/buses.md).

### Zobrazowania po katastrofach

Włącz **„Warstwy mapy → Zobrazowania po katastrofach”**, a następnie wskaż miejsce na mapie lub użyj przycisku wyboru jej środka. WICI przeszuka katalog Copernicus EMS w otoczeniu miejsca. Wyniki pokazują źródło, datę wykonania, dostępny podgląd i przybliżony zasięg materiału. Gdy źródło nie podaje daty zdjęcia, widoczny jest brak daty; data opracowania mapy pozostaje osobna.

Copernicus udostępnia tu podglądy produktów kartograficznych dotyczących katastrof. Materiały mogą być archiwalne; warstwa jest niezależna od dnia publikacji i filtra województwa. Brak wyników nie potwierdza braku zdarzenia ani zdjęć. Pobieranie następuje po wyborze miejsca, bez klucza API; demo pozostaje bez sieci. Wyłączenie w konfiguracji: `[sources.imagery] enabled = false`. [Zakres i ograniczenia](docs/imagery.md).

### Pozostałe ustawienia

W [config.example.toml](config.example.toml) znajdziesz ustawienia portu, limitu rozmiaru odpowiedzi, timeoutu i aktywności źródeł. Przykładowo, aby zmienić port i wyłączyć samoloty, ustaw:

```toml
port = 8766

[sources.aircraft]
enabled = false
```

Ustawienia ogólne, takie jak `port`, wpisuj **przed sekcjami `[sources.…]`**. Każda sekcja może wystąpić w pliku tylko raz: modyfikuj istniejącą, zamiast dopisywać jej kopię. Nowy adres w tym przykładzie to `http://127.0.0.1:8766`.

## Jak korzystać z widoków

Przycisk **„WICI Noc”** w nagłówku przełącza między jasnym Atlasem i motywem nocnym; działa także klawiszami Enter i Spacja. Pierwszy start jest jasny. Przeglądarka zapamiętuje motyw — zmiana wyglądu zachowuje mapę, warstwy, filtry i otwarte szczegóły. Ponowne naciśnięcie przywraca Atlas. [Opis interfejsu i weryfikacji](docs/atlas-ui.md).

- **„Sytuacja”**: wybierz dzień, rozwiń „Filtry i zakres”, ustaw województwo i włącz potrzebne warstwy. Kliknij karteczkę województwa, a potem komunikat, aby zobaczyć treść, daty, odnośnik do źródła i historię wersji.
- **„Źródła”**: sprawdź ostatnie próby pobrania, błędy i zakres dostępnych danych; w razie potrzeby odśwież źródło ręcznie.
- **Archiwum**: wybierz wcześniejszy dzień, aby przeglądać zapisane publikacje. Aplikacja nie pobiera brakujących dni i nie odtwarza historycznego stanu całej mapy. Bieżące warstwy, takie jak ruch, pogoda, samoloty, kolej i statki, są niezależne od dnia publikacji.

Domyślnie lista obejmuje publikacje i aktualizacje źródła z wybranego dnia w strefie Europe/Warsaw. Opcja „Także ostrzeżenia IMGW i komunikaty RSO udostępniane dziś z innych dni” rozszerza dzisiejszy widok. Zapisany dokument pokazuje aktualną lokalną wersję; wcześniejsze wersje otworzysz w szczegółach.

Karteczka województwa służy nawigacji, a zaznaczony obszar komunikatu nie musi być miejscem zdarzenia. Brak punktów na mapie lub brak komunikatów nie potwierdza braku zagrożenia. Pokrycie i opóźnienia zależą od źródła.

## Dane i kopia zapasowa

- Tryb zwykły: `var/live/`, baza `var/live/app.sqlite3`.
- Demo: `var/demo/`, baza `var/demo/app.sqlite3`.
- Logi: podkatalog `logs/` odpowiedniego trybu, rotacja przez 14 dni.
- Szczegóły prób pobrania: 30 dni; historia komunikatów i obserwacji FIRMS nie jest automatycznie usuwana.
- Historia tras samolotów i statków: ostatnie 7 dni; aktywne obserwacje zapisane w tej samej bazie są wznawiane po restarcie.

Zbieranie danych działa tylko przy uruchomionej aplikacji. Po przerwie lub uśpieniu WICI wykonuje pojedyncze zaległe odświeżenie; źródła mogą już nie udostępniać wszystkich pominiętych publikacji. Błąd internetu nie kasuje zapisanych danych.

**Kopia zapasowa:** zatrzymaj aplikację i skopiuj cały katalog `var/live/`. Przywracaj go również przy zatrzymanej aplikacji. Nie kopiuj samego pliku SQLite podczas pracy. Konfigurację z kluczami zabezpiecz osobno, jeśli chcesz zachować ją w kopii.

Kontroluj rozmiar `var/`. Nie usuwaj plików `tomtom-usage.json` i `tomtom-road-usage.json` w trakcie miesiąca — przechowują lokalne liczniki wykorzystania API.

## Najczęstsze problemy

| Objaw | Co sprawdzić |
| --- | --- |
| Aplikacja nie startuje, port jest zajęty | Zatrzymaj wcześniejszą instancję przez Ctrl+C albo zmień `port` w konfiguracji. |
| Błąd odczytu konfiguracji | Sprawdź składnię TOML i powtórzone sekcje. Porównaj plik z `config.example.toml`. |
| Brak komunikatów | Sprawdź wybrany dzień i filtry, a następnie stan pobierania w „Źródłach”. Pusta lista nie musi oznaczać awarii. |
| Samoloty: błąd odświeżania | „Brak połączenia z lokalnym serwerem WICI” wymaga sprawdzenia działającej aplikacji. Komunikat o adsb.fi wskazuje timeout, błąd HTTP lub nieprawidłowe dane dostawcy; przyczyna trafia też do `var/live/logs/app.log`. Po błędzie backend czeka co najmniej 60 s (lub według Retry-After); ponowne lokalne odczyty nie przyspieszają pobierania źródła. |
| Warstwa wymagająca klucza jest niedostępna | Sprawdź `enabled = true`, właściwe pole klucza i restart po zmianie pliku. |
| Brak statków tuż po włączeniu warstwy | Wybierz „Pokaż Bałtyk” i poczekaj na napływ wiadomości. Pokrycie AIS jest niepełne. |
| Nie udało się wczytać widoku | Wybierz „Odśwież widok”. Po przerwanym ręcznym pobieraniu sprawdź stan źródła przed ponowieniem. |
| Brak podkładu mapy | Sprawdź internet i przełącznik OpenStreetMap; zapisane komunikaty i lokalne granice są dostępne niezależnie od kafelków. |

## Dla osób rozwijających projekt

W katalogu repozytorium:

```sh
uv run --locked pytest
uv run --locked ruff check .
```

Testy Python działają offline. Z dostępnym Node.js możesz również uruchomić testy interfejsu:

```sh
node --test tests/ui_*.test.cjs
node tests/ships_ui.cjs
node tests/buses_ui.cjs
```

Test hydrologii z pełnym `app.js`, jego harmonogramem i rzeczywistym Leaflet: `node --test tests/hydro_browser.cjs` (wymaga Playwright/Chromium; [szczegóły](docs/hydrology.md#regresje-interfejsu)). Uruchamia własny, odizolowany serwer demo.

Test przełącznika komunikatów i pamięci checkboxów: `node --test tests/preferences_browser.cjs` (Playwright/Chromium, własny serwer demo). Obejmuje odświeżanie strony i danych, zmianę dnia, tryb IODA oraz automatyczne przywrócenie wybranych warstw.

Dodatkowe narzędzia:

- `uv run --locked python scripts/check_sources.py` — jawny test dostępu do źródeł przez internet, bez zapisu do bazy; raport w ignorowanym `tmp/live-checks/`.
- `uv run --locked python scripts/verify_system.py` — test CLI i restartu z własnymi procesami demo; wymaga portu 8765 i zgodnej konfiguracji, raport w `tmp/live-checks/`.
- `uv run --locked python scripts/benchmark.py` — pomiar dla 10 000 rekordów.
- `uv run --locked python scripts/prepare_synthetic_fixtures.py` oraz `scripts/prepare_imgw_pdf_fixtures.py` — odtworzenie syntetycznych próbek offline.

Opcjonalna grupa GIS (`geo`) służy odtwarzaniu geometrii. Granice mapy i biblioteka Leaflet są dołączone do projektu. Generator PDF korzysta z podstawowej zależności pypdf; grupa `pdf-check` została usunięta.

Dokładny zakres integracji opisują: [źródła](docs/sources.md), [pogoda](docs/weather.md), [radar](docs/radar.md), [wyładowania](docs/lightning.md), [EFFIS](docs/effis.md), [FIRMS](docs/firms.md) [kolej](docs/trains.md) i [statki AIS](docs/ships.md). Wymagania znajdują się w [PRD.md](PRD.md), stan wdrożenia i wyniki weryfikacji w [raporcie](docs/implementation-status.md), a wcześniejsze raporty w [archiwum](docs/archive/README.md).

## Problemy łączności internetowej — IODA

Osobna warstwa mapy (domyślnie wyłączona) pokazuje anomalie dostępności internetu wykryte przez IODA dla Polski, regionów i ograniczonej listy ASN powiązanych z Polską. Kolektor działa w tle podczas pracy aplikacji live, co 300 lub 600 s, zapisuje dane w SQLite i zachowuje historię po restarcie. Warstwa ma listę, szczegóły, poziom kraj/region/ASN, okno 24/48 h i wykresy BGP, aktywnych sond i teleskopu sieciowego. ASN pozostaje na liście bez fikcyjnej lokalizacji. Dane ASN mogą dotyczyć także innych krajów.

Konfiguracja `[sources.ioda]`: `enabled=true`, `interval_seconds=300` (lub `600`), `asns=[5617,12741,12912]` (do 8). Interwał odczytu nie jest częstotliwością pomiarów ani gwarancją czasu publikacji. API `/api/ioda` czyta wyłącznie zapisane dane. Wybrany dzień kończy okno IODA; filtr województwa wyklucza kraj, ASN i regiony bez zweryfikowanego mapowania.

Brak zdarzeń nie potwierdza prawidłowej dostępności. Brak pomiarów, nieaktualność i błędy są odrębnymi stanami. Źródła pokazują wiek odczytu i pomiarów niezależnie. IODA nie ustala przyczyny zdarzenia; warstwa nie przypisuje cyberataku i nie stanowi ostrzeżenia polskich służb. Demo jest syntetyczne i całkowicie offline. Retencja pomiarów/alertów 30 dni; historia jest lokalna i nie odtwarza dawnego stanu wiedzy. [Kontrakt, mapowanie, ograniczenia i weryfikacja](docs/ioda.md).

Źródło: [IODA — Georgia Tech Internet Intelligence Lab](https://ioda.inetintel.cc.gatech.edu). Copyright © 2021–2025 Georgia Tech Research Corporation. All Rights Reserved. Dane przetworzone do lokalnego widoku; nie przypisujemy im otwartej licencji.

Od 18.10.2026 testy IODA korzystają z autorskich, syntetycznych fixture. Skopiowaną specyfikację OpenAPI i rzeczywiste odpowiedzi usunięto z bieżącej wersji repozytorium, a dawny raport ograniczono do informacji o wykonanym sprawdzeniu i usunięciu danych. Dawnej historii Git nie przeniesiono do tej kopii; przygotowanie syntetycznych fixture nie nadaje praw do danych pobieranych podczas pracy live. [Pochodzenie fixture](tests/fixtures/ioda/README.md).

## Anomalie jakości pozycji / GNSS

Osobna, domyślnie wyłączona warstwa lotnicza agreguje deklarowaną jakość pozycji ADS-B. Nie potwierdza jammingu ani spoofingu i nie jest oficjalnym ostrzeżeniem. Komórki pokazują obszary obserwacji, nie nadajniki zakłóceń. Mały ruch, brak pozycji i błąd API nie są alarmem.

Aby zbierać próbki podczas działania aplikacji live, dodaj do `config.local.toml` poniższą sekcję i uruchom aplikację ponownie:

```toml
[position_quality]
enabled = true
interval_seconds = 60
retention_hours = 72
```

Wymagana jest również aktywna integracja `sources.aircraft`. Kolektor działa bez widocznej mapy i współdzieli klienta, cache oraz backoff z samolotami. Dozwolony interwał wynosi 60–300 s, zgodnie z oknami detekcji. Zapis kolektora działa w osobnym workerze i nie blokuje cache samolotów ani pętli API. Kolejka jest ograniczona; UI pokazuje oczekujące zapisy i pominięte snapshoty przy przeciążeniu lub awarii bazy. Zaznaczenie warstwy w UI tylko wyświetla dane. Historia SQLite powstaje od uruchomienia kolektora, przetrwa restart i podlega retencji; nie pobieramy brakującej historii. Demo zawiera wyłącznie scenariusz syntetyczny offline.

Mapa oferuje 24/48 h historii, wybór okna 5 min, filtr województwa i dnia (Europe/Warsaw), próbę różnych samolotów, dostępność pól i wiek danych. Zmiana dostawcy lub endpointu rozpoczyna osobny okres zbierania i nowe tło; restart z tym samym źródłem zachowuje okres. Historia sprzed migracji 011 ma nieustalone pochodzenie i pozostaje poza oceną oraz tłem. Detekcja wymaga co najmniej 5 maszyn w dwóch kolejnych oknach i co najmniej 6 wcześniejszych okien tła (około 40 min rozgrzewki przy wystarczającym ruchu). Brak wystarczającej próby, nieaktualne dane i błąd źródła są rozróżniane. Mapa domyślnie śledzi najnowsze zakończone okno; po ręcznym wyborze historii wrócisz do śledzenia przyciskiem „Najnowsze okno”.

[Metoda, audyt rzeczywistego endpointu, progi i ograniczenia](docs/position-quality.md) · [fixture i pochodzenie](tests/fixtures/aircraft/README.md). Bieżące źródło: [adsb.fi](https://adsb.fi/) — [użytek osobisty, niekomercyjny i atrybucja](https://github.com/adsbfi/opendata). Historia sprzed zmiany źródła może zawierać dane [ADSB.lol](https://www.adsb.lol/) / [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

## Licencja

Własny kod źródłowy WICI jest udostępniany na licencji [MIT](LICENSE), która pozwala również na zastosowania komercyjne. Niekomercyjny charakter projektu nie ogranicza tych uprawnień.

Biblioteki, dołączone zasoby oraz dane i usługi zewnętrznych dostawców podlegają odrębnym licencjom i warunkom opisanym w [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). MIT kodu WICI nie zastępuje tych warunków. W szczególności:

- Maska morska zawiera geometrię VLIZ IHO Sea Areas v3, której strona produktu wskazuje **CC BY-NC-SA 4.0**: użytek niekomercyjny, atrybucja, oznaczenie zmian i ShareAlike dla adaptacji. Nie potwierdzono zastosowania liberalniejszych warunków do tej wersji.
- Darmowe API Open-Meteo ma ograniczenia niekomercyjnego użycia usługi, mimo że same dane są na CC BY 4.0. Publiczne API RainViewer ma własne ograniczenia zastosowań, opisane w wykazie.
- Pozostałe komponenty mogą wymagać zachowania informacji o autorach, tekstów licencji, oznaczenia przetworzenia lub spełnienia obowiązków dotyczących źródeł.

Przy zastosowaniu komercyjnym należy zapewnić odpowiednie uprawnienia do wykorzystywanych zasobów i usług albo je usunąć, zastąpić lub wyłączyć daną integrację. Samo wyłączenie warstwy nie usuwa dołączonych plików z rozpowszechnianej paczki. Ograniczenia zewnętrznych materiałów nie stanowią ogólnego zakazu komercyjnego użycia własnego kodu WICI.

[Audyt licencji](docs/license-audit.md) opisuje odrębne warunki zasobów i zakres publikacji. 18.10.2026 zastąpiono pozostałe rzeczywiste próbki autorskimi danymi syntetycznymi, usunięto kopie dokumentów i OpenAPI oraz rzeczywiste dane z raportów i archiwum. Usunięto także zależność PyMuPDF; generator testowych PDF używa pypdf. Ta kopia rozpoczyna nową historię Git od sprawdzonego drzewa WICI 0.29.0, bez dawnych commitów, gałęzi i tagów. Warunki danych pobieranych live pozostają niezależne od MIT kodu.
