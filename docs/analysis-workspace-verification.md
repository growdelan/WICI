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
