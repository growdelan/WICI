# Analiza obiektów ruchomych — raport weryfikacji

Data: 23.10.2026. Branch: `codex/wici-analysis-moving-objects`.

Zakres obejmuje katalog i karty samolotów/statków, trwałą listę obserwowanych,
sterowanie istniejącym zapisem tras oraz porównanie maksymalnie pięciu obiektów
na wspólnym czasie. [Obsługa, architektura i ograniczenia](analysis-moving-objects.md).

## Poprawka ikon transportu — v0.32.1, 23.10.2026

Branch: `codex/analysis-transport-map-icons`, na bazie `v0.32.0`.
Mapa Analizy korzysta teraz ze wspólnych funkcji ikon Sytuacji zamiast kółek,
zarówno dla pozycji bieżących, jak i zapisanego odtwarzania. Sprawdzono kolory
samolotów i trzech klas AIS, kierunki symboli, nazwy w etykietach, wybór karty,
obwódkę zaznaczenia oraz paskowanie statków względem czasu kursora.
Kolory tras nadal identyfikują obiekty porównania. API odtwarzania przekazuje
wybrane metadane symbolu z jawnym `metadata_context: current`; pozycja i kierunek
nadal pochodzą wyłącznie z zapisanych punktów.

- Pełny Python: **985 zaliczonych**, 116,47 s. Sześć regresji obejmuje metadane
  symboli w odtwarzaniu bez zastępowania zapisanego kierunku bieżącym.
- Pełny Node: **349 zaliczonych**. Cztery nowe scenariusze sprawdzają zgodność
  ikon z główną mapą, kierunek, zaznaczenie, wiek historycznych pozycji i zachowanie
  dotychczasowych symboli stacji.
- Chromium: **13 zaliczonych** — transport (5), bazowa Analiza/GIOŚ (3),
  Analiza Ukrainy (3) i trasy (2). Nowy scenariusz obejmuje jasny/ciemny motyw
  oraz szerokość 390 px i etykiety mieszczące się w mapie; istniejące odtwarzanie dodatkowo sprawdza sylwetki
  i kierunek samolotu/statku oraz brak błędnego paskowania dawnych raportów.
- Ruff, składnia zmienionych skryptów oraz `git diff --check`: poprawne.

Testy korzystały z izolowanych baz, syntetycznych źródeł i Chromium bez okna
na pulpicie. Zablokowano żądania zewnętrzne; instancja LIVE nie była zmieniana.
Trzy znane ostrzeżenia Python dotyczą Starlette/httpx i Rasterio.
Po dopracowaniu zawijania etykiet na telefonie powtórzono pięć scenariuszy
transportu oraz cały Node; wszystkie ponownie przeszły. Powtórki nie zwiększają
powyższej liczby testów.

## Wyniki

| Sprawdzenie | Wynik |
|---|---|
| Pełny zestaw Python | **898 zaliczonych**, 109,52 s |
| Zestaw jednostkowy Node | **332 zaliczone** |
| Nowe scenariusze transportu w Chromium | **4 zaliczone** |
| Dotychczasowe scenariusze Chromium | **15 zaliczonych**: Analiza (3), trasy (2), samoloty 3D (10) |
| Ruff, składnia zmienionych JS, lockfile i diff | Poprawne |
| Budowa sdist i wheel | Poprawna; nowe moduły, migracja i skrypt UI obecne w paczce |

Powtórki tych samych scenariuszy nie zwiększają liczby testów. Skrypt `ships_ui.cjs`
także przeszedł; jest liczony w zestawie Node, a nie jako scenariusz Chromium.
Python zgłosił trzy znane ostrzeżenia: deprecjację integracji Starlette/httpx
oraz dwa ostrzeżenia Rasterio o syntetycznych rastrach bez georeferencji.

## Sprawdzone zachowania

- Migracja wypełnionej bazy z wersji 16 zachowuje obiekty, pomiary, czujniki,
  indeksy i relacje; po migracji nie ma naruszeń kluczy obcych.
- Tożsamości ICAO/MMSI, metadane z najnowszej zapisanej sesji, wyszukiwanie,
  trwałość obserwowanych po restarcie oraz retencja nieobserwowanych obiektów.
- Wspólne kolektory i cache: czytanie katalogu nie odpytuje dostawcy, a odtwarzanie
  nie włącza nowych odczytów transportu. Projekcja ma ograniczoną kolejkę.
- Błąd, wyłączenie albo brak obiektu w źródle usuwa aktualną pozycję, zachowując
  tożsamość, ostatni znany raport, obserwowane i historię.
- Zapis i zatrzymanie sesji z karty, ponowne otwarcie historii, maksymalnie pięć
  porównywanych obiektów oraz zapis porównania w konfiguracji stanowiska.
- Dokładny przedział `[od, do)`, brak punktów z przyszłości względem kursora,
  przerwy 120/900 sekund i granice sesji rozdzielające linie. Braki nie są zerami.
- Zsynchronizowana mapa, tabela i wykresy, lokalne przesuwanie czasu,
  utrzymanie fokusu klawiatury podczas odtwarzania oraz układ telefonu.
- Limity punktów i geometrii mają jawne komunikaty. Błąd utrwalenia katalogu
  pozostaje widoczny obok ostrzeżeń zapytania i znika po odzyskaniu zapisu.
- Powrót do Sytuacji zachowuje mapę, hydrologię i istniejący zapis tras;
  dotychczasowe scenariusze samolotów 3D nadal przechodzą.

## Poprawki wynikające z przeglądu

Pierwsza pełna regresja wykryła, że zewnętrzna blokada zapisu SQLite mogła
opóźnić odpowiedź `/api/aircraft` o pięć sekund. Projekcja teraz natychmiast
próbuje rozpocząć transakcję, zgłasza zajętą bazę i nie blokuje czytelników
oczekiwaniem SQLite. Endpoint czeka na projekcję najwyżej 100 ms i zachowuje
dotychczasowy format odpowiedzi. Test regresji przeszedł po poprawce,
następnie zaliczono pełne 898 testów.

Przegląd poprawił też odświeżenie kontekstu karty po rozpoczęciu/zakończeniu
zapisu, wybór najnowszych metadanych podczas odtwarzania katalogu ze starych
sesji, koszt wyliczania rewizji historii oraz niezależność komunikatu błędu zapisu
od ostrzeżenia zapytania. Indeks typu i identyfikatora ogranicza koszt połączenia
katalogu z dużą historią tras.

Końcowa kontrola wizualna ujawniła komunikat o pustym wyborze typów, który
pozostawał po udanym kolejnym zapytaniu. Poprawka czyści nieaktualne ostrzeżenia
zapytania bez usuwania niezależnego statusu zapisu; dodano regresję jednostkową
i sprawdzenie w przeglądarce.

## Odtworzenie sprawdzeń

Z katalogu repozytorium, po instalacji zależności:

```sh
uv run --locked pytest -q
node --test tests/*.test.cjs tests/*_ui.cjs
uv run --locked ruff check .
uv lock --check --offline
git diff --check
uv build --out-dir tmp/moving-workspace-evidence/dist
```

Testy przeglądarkowe wymagają Playwright i Chromium. Przy współdzielonym runtime
trzeba wskazać katalog jego modułów przez `NODE_PATH`.

```sh
node --test --test-concurrency=1 tests/moving_workspace_browser.cjs tests/workspace_browser.cjs
node --test --test-concurrency=1 tests/tracking_browser.cjs tests/aircraft3d_browser.cjs
```

Nowe testy backendu: `test_workspace_moving.py`, `test_moving_ingestion.py`
i `test_moving_ingestion_api.py`. Testy UI: `moving_workspace_ui.test.cjs`,
uzupełnienia `workspace_ui.test.cjs` i `ui_workspace_sources.test.cjs`.

## Granice weryfikacji

Testy używają tymczasowych baz i danych syntetycznych; nowe scenariusze
przeglądarkowe blokują ruch zewnętrzny. Nie modyfikują lokalnej bazy LIVE
ani konfiguracji dostawców. Nie potwierdzają bieżącej dostępności adsb.fi
lub AISStream. Safari i Firefox nie były sprawdzane.

Historia obejmuje tylko rzeczywiście zapisane sesje, z dotychczasową retencją
siedmiu dni. Lista obserwowanych nie rozpoczyna nagrywania. Metadane obiektu
pozostają bieżącym katalogiem, a kursor odtwarza zapisane pozycje i wartości.
Pierwszy build wykonano jeszcze z wersją pakietu 0.30.0. Końcowa weryfikacja
wydania 0.31.0 jest opisana poniżej.

## Próba LIVE — 23.10.2026, 16:48–16:57 Warszawa

Po testach offline uruchomiono zwykły tryb aplikacji z istniejącą konfiguracją
użytkownika. adsb.fi i AISStream zwróciły rzeczywiste dane. W Analizie dodano
do obserwowanych BTI695 (`aircraft:icao:502d47`, YL-ABF) i BALTIC PRINCESS
(`ship:mmsi:230639000`). Uruchomione przez interfejs sesje zebrały odpowiednio
33 i 2 raporty. Rzadsze raportowanie AIS pozostało widoczne; nie uzupełniano luk.

Pokazano wspólne odtwarzanie, zmianę kursora, mapę i wykresy w zakresie
16:49–16:57. Przy kursorze 16:52 raporty dawały 785,2 km/h i 11 582 m dla
samolotu oraz 17,6 km/h dla statku. Zapisane stanowisko przywrócono po
przeładowaniu strony; lista obserwowanych i porównanie pozostały zachowane.
Obie sesje zakończono w interfejsie, zachowując historię i obserwowane obiekty.

Próba ujawniła mylące puste pola pozycji podczas przejściowego odświeżania karty
oraz etykietę nieaktywnego przycisku rozpoczęcia zapisu przy trwającej sesji.
Karta pokazuje teraz „Odświeżanie pozycji…” i „Zapis trwa”. Dodano regresję
renderowania rzeczywistego kształtu danych; pełny zestaw Node po poprawce:
**333 zaliczone**, `git diff --check` poprawny. Weryfikacja dostawców dotyczy
wyłącznie czasu tej próby; wcześniejsze wyniki Python i Chromium pozostają
wynikami testów offline.

## Końcowa weryfikacja wydania 0.31.0 — 23.10.2026

Po przeglądzie wszystkich lokalnych zmian przygotowano wersję pakietu 0.31.0
bez aktualizacji zależności. Ponowiono pełny zestaw Python i Node oraz wskazane
scenariusze Chromium na izolowanych bazach:

- **898 testów Python zaliczonych**, 134,44 s; trzy wcześniej opisane ostrzeżenia.
- **333 testy Node zaliczone**.
- **19 scenariuszy Chromium zaliczonych**, 241,27 s: Analiza transportu (4),
  dotychczasowa Analiza (3), zapis tras (2), samoloty 3D (10).
- Ruff, składnia 13 zmienionych plików JS/CJS, lockfile i kontrola diffu: poprawne.
- Build sdist i wheel **0.31.0**: poprawny. Sprawdzono wersję metadanych,
  nowe moduły, migrację 017, skrypt `workspace-motion.js` i pliki licencyjne.
  Archiwa nie zawierają lokalnych baz, konfiguracji, sekretów ani filmów.

Przegląd nie wykazał potwierdzonych regresji. Repozytorium nie ma skonfigurowanego
CI; powyższe wyniki pochodzą z lokalnych przebiegów. Końcowe testy nie ponawiały
odczytów dostawców LIVE i nie obejmowały Safari ani Firefox.
