# Teczki analiz v0.33.0 — raport weryfikacji

Data: 25.10.2026. Branch: `codex/wici-analysis-dossiers-v0330`, baza `v0.32.2`.

Zakres obejmuje trwałe teczki, notatki, przypięcia ośmiu typów obiektów
oraz niezmienne kopie kart, historii i porównań. [Obsługa i ograniczenia](analysis-dossiers.md).

## Wyniki

| Sprawdzenie | Wynik |
|---|---|
| Dotychczasowy pełny zestaw Python | **985 zaliczonych**, 138,60 s |
| Nowe testy teczek w Python | **27 zaliczonych**, 4,40 s |
| Pełny zestaw Node | **357 zaliczonych** |
| Dotychczasowe scenariusze Chromium | **25 zaliczonych** |
| Nowe scenariusze teczek w Chromium | **5 zaliczonych** |
| Ruff, składnia zmienionego JS, lockfile, diff | Poprawne |
| Budowa sdist i wheel v0.33.0 | Poprawna |

Łącznie sprawdzono 1012 różnych testów Python: pełne 985 istniejących testów
oraz osobno 27 nowych po końcowej poprawce zachowania dawnej wersji komunikatu.
Powtórki tych samych testów nie zwiększają liczby wyników. Node obejmuje
349 dotychczasowych i 8 nowych testów. Chromium obejmuje bazową Analizę/GIOŚ
(3), transport w Analizie (5), Ukrainę w Analizie (3), zapis tras (2), samoloty
3D (10), GIOŚ na głównej mapie (1), hydrologię na głównej mapie (1) i teczki (5).

Po końcowych poprawkach kontrolera ponownie przeszło 13 scenariuszy Chromium:
teczki (5), bazowa Analiza (3) i transport w Analizie (5), 55,56 s.
Końcowy pełny Node obejmuje również regresję zachowania źródeł LIVE po
otwarciu przypięcia. Paczki v0.33.0 sprawdzono pod kątem obecności migracji,
nowych modułów oraz zgodności plików uruchomieniowych z drzewem roboczym.

Python zgłasza trzy znane ostrzeżenia: deprecjację Starlette/httpx oraz dwa
ostrzeżenia Rasterio o syntetycznych rastrach bez georeferencji. Nowy zestaw
teczek zgłasza tylko tę samą deprecjację Starlette/httpx.

## Sprawdzone zachowania

- Tworzenie, wybór, zmiana nazwy/opisu i usuwanie teczek. Migracja wypełnionej
  bazy z wersji 18 zachowuje katalog, obserwowane, zapisane stanowiska i stan
  aplikacji; kontrola kluczy obcych nie wykazuje naruszeń.
- Przypinanie bez uruchamiania rejestracji lub zmiany obserwowanych;
  przypięcie zachowuje etykietę i identyfikator po usunięciu obiektu z katalogu.
- Trwałość notatek i materiałów po ponownym otwarciu aplikacji oraz izolacja
  zawartości różnych teczek. Usunięcie teczki nie usuwa danych źródłowych.
- Konflikty równoczesnej edycji notatki i opisu: HTTP 409, zachowany lokalny
  szkic, odczyt konkurencyjnej treści i świadome odrzucenie szkicu. Własny zapis
  notatki nie uniemożliwia zapisania zmienionego opisu.
- Kopie tworzone przez serwer z lokalnych danych; odrzucanie treści kopii
  przesłanej przez klienta, nieaktualnych rewizji, zmienionych filtrów, obiektów
  poza zakresem, niewłaściwych wersji dokumentu i materiałów innej teczki.
- Pełna paginacja historii: 2003 pomiary i 2002 oficjalne indeksy GIOŚ
  zachowane raz, bez pomijania i dublowania stron. Osobno sprawdzone korekty,
  wartości `null` i zero, jednostki, czas źródła oraz czas pobrania.
- Dawna wersja komunikatu zachowuje własny tekst, datę o precyzji dnia,
  oryginalne pola i adres materiału. Data publikacji nie przechodzi z aktualnej
  wersji; historia publikacji nie prezentuje umownej północy jako znanej godziny.
- Porównanie tras zachowuje raporty, kursor, przerwy i klasyfikację; porównanie
  Ukrainy zachowuje pokrycie, nieznane okresy i niepewny koniec alarmu.
- Usunięcie pomiarów lub tras oraz restart nie zmienia wcześniej zapisanej
  kopii i jej SHA-256. Trigger SQLite blokuje aktualizację materiału.
- Limity kolekcji, liczby rekordów i rozmiaru kopii odrzucają operację atomowo.
  Wszystkie nowe mutacje korzystają z istniejącej ochrony CSRF/Origin.
- Czytelne tabele zapisanych danych ze stronicowaniem, bezpieczne odnośniki,
  tekst HTML traktowany jako tekst, tryb jasny/ciemny, telefon 390×844,
  potwierdzenia usuwania oraz zachowanie fokusu i szkiców.

## Poprawki z przeglądu

Zapisana karta GIOŚ bez wybranego stanowiska pokazuje „Nie wybrano stanowiska”.
Nie przedstawia ostatniego pomiaru dowolnego czujnika jako wyboru użytkownika;
oficjalny indeks oraz tabela dostępnych parametrów pozostają osobno.

Opóźniony odczyt materiału nie przełącza widoku po zamknięciu lub ponownym
otwarciu teczki i nie przywraca właśnie usuniętej kopii. Regresja w Chromium
celowo opóźnia odpowiedź i sprawdza zachowanie edytora, tekstu oraz fokusu.

Otwarcie przypiętego obiektu zachowuje zapotrzebowanie na już aktywne źródła
LIVE. Pomija jedynie automatyczne odkrywanie stanowisk przypiętej stacji GIOŚ.
Test kontrolera sprawdza też zachowanie już wybranego czujnika oraz zwykły
odczyt stanowisk po otwarciu stacji z katalogu.

## Odtworzenie sprawdzeń

```sh
uv run --locked pytest -q
node --test tests/*.test.cjs tests/*_ui.cjs
uv run --locked ruff check .
uv lock --check --offline
git diff --check
uv build
```

Chromium wymaga Playwright i zainstalowanej przeglądarki. Przy współdzielonym
runtime należy ustawić `NODE_PATH` na katalog jego modułów.

```sh
node --test --test-concurrency=1 tests/dossiers_workspace_browser.cjs tests/workspace_browser.cjs tests/moving_workspace_browser.cjs
node --test --test-concurrency=1 tests/ukraine_workspace_browser.cjs tests/tracking_browser.cjs tests/aircraft3d_browser.cjs tests/gios_browser.cjs tests/hydro_browser.cjs
```

## Granice weryfikacji

Testy korzystają z tymczasowych baz, kontrolowanych danych i przeglądarki
działającej bez okna na pulpicie. Nowe testy przeglądarkowe blokują ruch
zewnętrzny. Instancja LIVE na porcie 8765 i jej baza nie były zmieniane.
Wyniki potwierdzają zachowanie aplikacji na sprawdzonych scenariuszach;
nie potwierdzają bieżącej dostępności zewnętrznych dostawców. Safari i Firefox
nie były sprawdzane.

## Niezależny przegląd przed commitem

Subagent stosujący skill `review-agent` przejrzał pełny zakres v0.33.0,
łącznie z nowymi plikami, migracją, API, interfejsem, testami i dokumentacją.
Wynik: **No findings.** Niezależnie przeszło 27 testów Python teczek,
21 testów Node teczek/kontrolera, 5 scenariuszy Chromium i kontrola diff.
Pełnej dotychczasowej regresji nie powtarzano podczas tego przeglądu.
Zapis porównania Ukrainy ma test backendowy, bez osobnego scenariusza
przeglądarkowego teczki.

## Próba LIVE — 25.10.2026

Na polecenie użytkownika uruchomiono aktualną aplikację i wykonano cały
przebieg w interfejsie na rzeczywistych danych GIOŚ. Stacja: Warszawa,
al. Niepodległości (`530`), PM10, stanowisko `3584`. Ostatni dostępny pomiar
podczas próby: 30,5 µg/m³, 25.10.2026 o 09:00 czasu Warszawy.

Utworzono lokalną teczkę, przypięto stację, dodano notatkę i zapisano historię
ostatnich 24 godzin. Kopia zawierała 21 rekordów PM10, zachowane braki danych
i osobno oficjalny indeks GIOŚ. Otworzono podgląd materiału z zakresem,
czasami obserwacji/pobrania i pochodzeniem, a następnie ponownie wczytano
teczkę, potwierdzając zapis jej zawartości. Ta próba, w odróżnieniu od
opisanych wyżej testów automatycznych, zapisała dane w lokalnej bazie LIVE.
