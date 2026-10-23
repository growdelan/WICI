# Stanowisko analityczne — raport weryfikacji etapu 1

Data: 22.10.2026. Branch: `codex/wici-analysis-workspace-plan`.

Wdrożono katalog czterech typów obiektów, karty szczegółów, wspólny wybór i filtrowanie mapy/tabeli/osi czasu, trwałą historię stacji oraz zapis konfiguracji stanowiska. Obsługa i semantyka danych: [instrukcja](analysis-workspace.md). Podstawa odbioru: [plan etapu 1](plan-stanowisko-analityczne-etap-1.md).

## Wyniki

| Sprawdzenie | Wynik |
|---|---|
| Pełny zestaw Python | **880 zaliczonych**, 101,94 s |
| Zestaw jednostkowy UI Node | **322 zaliczone**, 1,18 s |
| Nowe scenariusze Analizy w Chromium | **2 zaliczone**, 8,28 s |
| Istniejące scenariusze Chromium | **27 zaliczonych po poprawkach i ponownych próbach odpowiednich scenariuszy** |
| Ruff, składnia JS, poprawność diffu i lockfile | Poprawne; bez nowych zależności |

Testy Python zgłosiły trzy ostrzeżenia: istniejącą deprecjację integracji Starlette/httpx oraz dwa ostrzeżenia Rasterio o syntetycznych rastrach bez georeferencji. Nie było błędów ani pominiętych testów.

Istniejące scenariusze Chromium obejmują preferencje i komunikaty (3), region (2), hydrologię (1), GIOŚ (1), zapis/odtwarzanie tras (2) oraz samoloty i autobusy w 3D (18). Pierwszy zbiorczy przebieg zakończył się wynikiem 24/27. Po poprawkach ponownie zaliczono komplet preferencji i regionu (5/5) oraz GIOŚ (1/1). Pozostałych 21 zakończonych powodzeniem scenariuszy nie powtarzano bez zmian dotyczących ich działania.

W czasie regresji poprawiono przepełnienie nawigacji przy szerokości 320 px oraz kolejkowanie GIOŚ: metadane i pomiary nie czekają w kolejce indeksów, a wycofane zadania nie opóźniają nowego regionu. Próba przycinania mapy wymagała też poprawienia fixture — testowy punkt umieszczono nad kartami komunikatów, które wcześniej przechwytywały kliknięcie. Zachowano sprawdzenie klikalności wewnątrz regionu i braku klikalności poza nim.

## Co zweryfikowano

- Migracje nowej i wcześniejszych baz, idempotentny backfill, stabilne referencje, zachowanie oryginalnych dokumentów, także późne pozyskanie starszej wersji PDF.
- Trwały zapis pomiarów, restart, retencję, błędy i przeciążenie kolejki, korekty A → B → A, wartości `null`, nieznany/przyszły czas oraz zachowanie stacji po częściowym odczycie.
- Wspólne filtry i rewizje wyników, podpisane kursory stronicowania, konflikt po zmianie danych, odrębne tło histogramu, agregację mapy i oddzielne liczniki obiektów oraz zdarzeń.
- Rozróżnienie okresu udostępniania RSO i ważności IMGW, granice przedziału `[od, do)`, dni zmiany czasu w Warszawie oraz lokalny wybór próbki przy kursorze.
- Wspólny wybór z mapy i tabeli, ochronę przed spóźnionymi odpowiedziami A → B → A i po zamknięciu karty, zachowanie ręcznego czasu i kamery po odświeżeniu.
- Odrębność dwóch czujników PM10 na tej samej stacji; kolor mapy według oficjalnego indeksu GIOŚ i jego własnego czasu, niezależnie od stężenia substancji.
- Wspólne żądania i cache, limity indeksów GIOŚ, wycofanie zbędnych zadań, odświeżanie wybranego czujnika i zatrzymanie nowych odczytów po ukryciu widoku.
- Zapis i przywrócenie stanowiska, rewizje konfiguracji, działanie przy zablokowanym localStorage, zachowanie jednej instancji mapy i ustawień Atlasu.
- Układ 320/390/768/1366/1920 px, motyw dzienny i nocny, przełącznik Mapa/Tabela, obsługę kursora klawiaturą i powrót fokusu po zamknięciu karty również po odświeżeniu DOM.
- Ochronę nowych endpointów przez istniejące Host/Origin/CSRF, walidację kontraktów i limit ciała żądania.

Pełny zestaw Python/Node obejmuje również wcześniejsze źródła, warstwy i kolektory. Próby przeglądarkowe sprawdzają rzeczywisty Leaflet i interakcje aplikacji. Przejście Sytuacja → Analiza ukrywa poprzednie warstwy, ale nie kończy aktywnego zapisu tras.

## Wydajność

Fixture: **10 000 komunikatów, 1500 stacji, 1 000 000 pomiarów**, strona 100 rekordów, 14-dniowy zakres i agregaty mapy. Maszyna raportowana przez runtime: `macOS-27.0.1-arm64-arm-64bit`, Python 3.12.12. Po pierwszym zapytaniu wykonano 30 przebiegów na niezmienianej tymczasowej bazie.

| Pomiar | Wynik | Cel planu |
|---|---:|---:|
| Pierwsze zapytanie bez rozgrzania | 2204,74 ms | Raportowane oddzielnie |
| Mediana zapytania po rozgrzaniu | 28,41 ms | — |
| p95 zapytania po rozgrzaniu | **54,99 ms** | <500 ms |
| p95 karty po rozgrzaniu | **0,57 ms** | <300 ms |
| Odpowiedź zapytania | około 69,5 kB | Raportowane |
| Maksymalny RSS procesu benchmarku | około 48 MiB | Raportowane |
| Lokalna zmiana kursora, p95 z 20 prób Chromium | **42,90 ms** | <100 ms |

Zapytanie zwróciło 11 500 obiektów i 1 010 000 zdarzeń histogramu. Pomiar Python obejmuje lokalny serwis i SQLite, bez transportu HTTP i renderowania. Wyniki po rozgrzaniu korzystają z ograniczonego cache rewizji/histogramu; pierwsze zapytanie lub unieważnienie cache może być istotnie wolniejsze. Wynik nie jest gwarancją dla każdej kombinacji filtrów ani dla równoległych zapisów LIVE. Pole licznika zaznaczonego zakresu dodane po pomiarze zmienia rozmiar odpowiedzi o kilkadziesiąt bajtów.

Pomiar kursora obejmuje wybranie kolejnych lokalnych próbek i dwie klatki renderowania. Test potwierdził **zero nowych żądań do endpointów hydro/GIOŚ podczas przesuwania kursora**.

## Odtworzenie sprawdzeń

Z katalogu repozytorium:

```sh
uv run --locked --offline pytest -q
node --test tests/ui_*.test.cjs tests/*_ui.cjs tests/workspace_ui.test.cjs
uv run --locked --offline ruff check .
git diff --check
uv lock --check --offline
uv run --locked --offline python scripts/benchmark_workspace.py --samples 1000000 --runs 30
```

Testy przeglądarkowe wymagają modułu Playwright dostępnego dla Node oraz zainstalowanego Chromium. Jeśli moduł pochodzi ze współdzielonego runtime, należy wskazać jego katalog `node_modules` przez `NODE_PATH`.

```sh
node --test --test-concurrency=1 tests/workspace_browser.cjs
node --test --test-concurrency=1 tests/preferences_browser.cjs tests/hydro_browser.cjs tests/gios_browser.cjs tests/region_browser.cjs tests/tracking_browser.cjs tests/aircraft3d_browser.cjs tests/buses3d_browser.cjs
```

Nowe testy backendu znajdują się w `test_workspace.py`, `test_workspace_history.py` i `test_workspace_integration.py`; testy stanu/interakcji w `workspace_ui.test.cjs`, a managera źródeł w `ui_workspace_sources.test.cjs`. To ostateczny podział testów zamiast roboczych nazw z planu.

## Granice weryfikacji

Wszystkie próby korzystały z tymczasowych baz i syntetycznych danych. Nowe scenariusze Chromium blokują ruch zewnętrzny. Nie zmieniano lokalnej konfiguracji ani bazy LIVE. Dostawców na żywo, Safari i Firefox nie weryfikowano.

Historia stacji zaczyna się od rzeczywiście pozyskanych odpowiedzi i nie odtwarza okresu sprzed instalacji. Retencja wynosi 14 dni; fizyczne czyszczenie przy starcie i co godzinę może usunąć rekord do godziny po przekroczeniu granicy. Kursor odtwarza wyłącznie wybraną stację, a metadane i geometria pozostają aktualnym katalogiem. Przy historii wymagającej kilku stron kursor jest dostępny dopiero po doczytaniu kompletu. Zakres etapu nie obejmuje historycznej rekonstrukcji całej mapy, nowych dostawców ani pełnej ontologii relacji.

## Końcowy przegląd wydania v0.30.0 — 22.10.2026

Przegląd przed scaleniem objął wszystkie pliki diffu do `main`: kontrakty i zabezpieczenia API, migracje 015/016, projekcję dokumentów, zapis/retencję i rewizje pomiarów, współdzielenie źródeł, wybór/czas/mapę, konfiguracje stanowisk, testy i dokumentację. Po poprawkach nie pozostały uwagi blokujące scalenie.

Znaleziono i poprawiono utratę oczekującego tekstu wyszukiwarki po kliknięciu filtra w oknie debounce 250 ms. Wpisany tekst jest zachowany; przywrócenie zapisanego stanowiska anuluje poprzednie oczekujące wyszukiwanie. Nowy scenariusz Chromium odtwarzał błąd przed poprawką i przechodzi po niej. Istniejący test kursora oczekuje na gotowość historii zamiast wysyłać zdarzenie do wyłączonego suwaka. Test hydrologii odczekuje też 200-milisekundową animację Leafleta przed sprawdzeniem usunięcia dymka przy zatrzymanym zegarze. Indeks PRD wskazuje wdrożoną instrukcję.

Ponowna weryfikacja wydania:

- 880 testów Python: zaliczone (3 znane ostrzeżenia, bez błędów).
- 322 testy Node: zaliczone.
- 55 scenariuszy Chromium: zaliczone z ponownymi próbami hydrologii i jakości pozycji, w tym 3 scenariusze Analizy (szczegóły w raporcie).
- Ruff, składnia zmienionych plików JS, lockfile i poprawność diffu: poprawne.
- Budowa sdist i wheel 0.30.0 oraz obecność nowych modułów i migracji w pakiecie: poprawne.

Pierwszy zbiorczy przebieg obejmował 56 pozycji: 54 właściwe scenariusze `node:test`, skrypt jakości pozycji i moduł pomocniczy motywu. Wynik wyniósł 54 zaliczone / 2 nieudane. W hydrologii końcowe sprawdzenie DOM wyprzedzało animację zamknięcia dymka; osobna próba już przed poprawką przeszła, a po dodaniu oczekiwania na animację ponownie zaliczono ten scenariusz. Skrypt jakości pozycji wymaga osobnego serwera — w zbiorczym przebiegu brakowało procesu na porcie 8773. Próbę uruchomiono ponownie z odizolowanym serwerem DEMO i `WICI_UI_URL`; przeszła. W rezultacie zaliczono łącznie 55 scenariuszy Chromium.

Zbiorczy przebieg Chromium uruchomiono poleceniem `node --test --test-concurrency=1 tests/*_browser.cjs tests/browser_theme.cjs` z modułem Playwright przez `NODE_PATH`. Moduł `browser_theme.cjs` jest helperem; nie jest liczony jako osobny scenariusz Chromium. Testy końcowe używały odizolowanych serwerów i baz demo, bez okien na pulpicie. Dodatkowo po poprawce powtórzono 20 powiązanych testów Node i trzy scenariusze Analizy. Przegląd wykazał również poprawny build `uv build`; sprawdzono wersję pakietu, nowe moduły/migracje oraz brak lokalnych baz, konfiguracji prywatnej i filmów w archiwach. GitHub nie zgłasza kontroli CI dla PR #1; powyższe wyniki pochodzą z lokalnych przebiegów.

## Historia alarmów Ukrainy i porównanie regionów — 0.32.0, 23.10.2026

Implementacja na branchu `codex/wici-ukraine-alarm-history`. Weryfikacja korzystała z izolowanych tymczasowych baz i serwerów, bez migracji ani restartowania działającej instancji LIVE. Dane scenariuszy przeglądarkowych są syntetyczne i opisane jako TEST; komunikacja zewnętrzna jest blokowana. Osobne odczyty kontraktu NEPTUN potwierdziły kształt kluczy regionów i nadrzędnych nazw; nie archiwizowano odpowiedzi.

| Kontrola | Wynik |
|---|---|
| Pełny Python, `uv run --locked pytest -q` | **979 zaliczonych**, 104,38 s; trzy znane ostrzeżenia Starlette/httpx i Rasterio. |
| Pełny Node, `node --test tests/*.test.cjs tests/*_ui.cjs` | **345 zaliczonych**. |
| Nowa Analiza Ukrainy w Chromium | **3 zaliczone**: porównanie/kursor/luki/strefy/zapisane widoki, hierarchia/rejestracja, pierwsze otwarcie pustego katalogu. |
| Regresje wcześniejszych funkcji w Chromium | **22 zaliczone**: Analiza (3), Analiza transportu (4), trasy (2), Ukraina w Sytuacji (3), samoloty 3D (10). |
| Ruff, lockfile, składnia JS/CJS i `git diff --check` | Poprawne. |
| Migracja 017 → 018 | Zachowane dane dzieci katalogu i watchlista; poprawne klucze obce. |
| Sdist i wheel 0.32.0 | Poprawny build, metadane wersji, nowe moduły, migracja i zasoby; obecne pliki licencyjne. |

Po przeglądzie poprawiono rewizje zakończonych przedziałów historii, ponawianie lokalnego zapisu granic oraz liczenie epizodów na granicach zakresu. Dodano **23 przypadki regresyjne**. Testy odtwarzają HTTP 409 po nieistotnym późniejszym odczycie, zachowanie właściwego konfliktu po zmianie pokrycia lub niepewnego końca alarmu, czyszczenie retencji (również przy zachowanych rekordach granicznych), rzeczywistą blokadę SQLite oraz bezpieczne zamknięcie podczas ponawiania zapisu. Pełne zestawy Python i Node oraz Ruff ponownie przeszły po tych poprawkach. Powtórzona regresja Chromium: **25/25 zaliczonych**, 286,7 s.

Wcześniej zbudowane archiwa nie zawierały baz użytkownika, prywatnej konfiguracji ani nagrań; po poprawkach z przeglądu nie wykonywano nowego wydania. Safari i Firefox nie były sprawdzane; testy offline nie potwierdzają przyszłej dostępności dostawcy.

Sprawdzone przypadki obejmują idempotencję cache, korekty A → B → A, niepewne zakończenie alarmu, odpowiedzi częściowe i awarie, zachowanie luk po restarcie, blokadę SQLite, równoczesne wyłączenie rejestracji i odczyt, czyszczenie przy wyłączonym kolektorze, granicę 30 dni, niezależność obserwowania od zapisu, retencję aktywnej tożsamości, brak odczytów dostawcy podczas odtwarzania, stare zapisane widoki oraz kontrolę CSRF/Origin. Pierwsze otwarcie Ukrainy pobiera granice i alarmy także przy wyłączonej rejestracji.

Próba wydajności na tymczasowej bazie: **172 801 odczytów** (30 dni co 15 s), pięć regionów o niezmiennym stanie, pełny replay w **0,483 s**, po jednym scalonym odcinku na region. To pomiar konkretnej fixture, nie gwarancja czasu dla dowolnej liczby zmian. Odtwarzanie ponad 12 000 zmian regionu wymaga zawężenia zakresu; nie wykonuje się cichego pomijania próbek.

Przeglądarkowe polecenie do ponowienia z dostępnym modułem Playwright:

```sh
NODE_PATH=/sciezka/do/node_modules node --test --test-concurrency=1 \
  tests/ukraine_workspace_browser.cjs tests/ukraine_browser.cjs \
  tests/workspace_browser.cjs tests/moving_workspace_browser.cjs \
  tests/tracking_browser.cjs tests/aircraft3d_browser.cjs
```
