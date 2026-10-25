# Weryfikacja v0.35.0 — obszary, reguły i zdarzenia

Data: 25.10.2026. Branch: `codex/wici-areas-rules-events-v0350`.

Pierwsze sekcje opisują weryfikację commita `cb92a06`. Wyniki napraw po dodatkowym
niezależnym przeglądzie (1151 Python, 375 Node, 52 Chromium) znajdują się w
[końcowej części raportu](#poprawki-po-niezależnym-przeglądzie-cb92a06).

## Zakres i testy — pierwotny commit

Zmiana obejmuje migrację 021, wydzielone usługi obszarów, reguł, monitora
i skrzynki, integracje z rzeczywistymi ścieżkami zapisu oraz trzy moduły UI.
Testy automatyczne korzystają z tymczasowych baz i źródeł syntetycznych;
przeglądarki odrzucają żądania poza własnym lokalnym serwerem testowym.

| Kontrola | Wynik |
|---|---|
| Pełny Python `uv run --locked pytest -q` | 1126 zaliczonych; 3 ostrzeżenia bibliotek. |
| Pełny Node `node --test tests/*.test.cjs tests/*_ui.cjs` | 375 zaliczonych. |
| Dotychczasowe scenariusze Chromium | 57/57 zaliczonych, sekwencyjnie. |
| Nowe scenariusze Chromium | 11/11 zaliczonych. |
| Końcowa powtórka Analizy i nowych paneli | 46/46 zaliczonych, w tym 11 nowych. |
| Ruff, zgodność lockfile, składnia JS i diff | Poprawne. |
| Budowa wheel i sdist v0.35.0 | Poprawna; zasoby i migracja w paczce. |

W pełnym Pythonie pozostają trzy ostrzeżenia bibliotek: deprecjacja klienta
Starlette/httpx oraz dwa ostrzeżenia georeferencji syntetycznych rastrów.
Nie są błędami testów.

Dotychczasowe Chromium obejmuje Analizę, transport i trasy, Ukrainę, teczki,
graf, hydrologię, GIOŚ oraz samoloty i autobusy 3D z rzeczywistym WebGL.
Po końcowych zmianach kontrolera powtórzono całe zestawy stanowiska,
transportu, Ukrainy, teczek i grafu razem z nowymi panelami.
57 wcześniejszych i 11 nowych scenariuszy to **68 różnych scenariuszy**;
powtórka nie jest doliczana drugi raz.

## Warunki odbioru

- Dokładny wielokąt zamiast ramki, granica należąca do obszaru, koła
  geodezyjne, walidacja samoprzecięć i niepoprawnych współrzędnych.
- Rewizje, powielenie, archiwizacja, katalog, mapa, karta, przypięcie
  i wyliczone relacje grafu z rewizją geometrii oraz czasem pozycji.
- Migracja 020 → 021 z zachowaniem wierszy zależnych, w tym historii
  Ukrainy, oraz dokładnych bajtów i SHA-256 wcześniejszych materiałów.
- Cztery szablony, konkretne stanowisko pomiarowe/parametr/jednostka,
  próg powrotu, NULL, korekta przy tym samym czasie, nowe wersje komunikatu.
- Pierwszy punkt wewnątrz nie udaje wejścia; zniknięcie obiektu i awaria
  nie są wyjściem. Pierwszy alarm po luce nie udaje dokładnego początku.
- Powtórzenie raportu, restart i ponowiona transakcja nie dublują zdarzenia.
  Symulowana awaria po emisji cofa również checkpoint. Restart przerywa
  domniemaną ciągłość, zachowując trwałą pozycję oceny.
- Edycja reguły i obszaru rozpoczyna nową ocenę; oczekujące stare pozycje
  nie są oceniane według nowych granic. Dawna podstawa pozostaje niezmienna.
- Strumień transportu zachowuje pośrednie raporty pomijane przez łączenie
  aktualizacji katalogu. Przetworzone wpisy zwalniają miejsce pod presją;
  przepełnienie nieprzetworzonej części wyznacza jawną lukę.
- Podgląd nie zmienia `db.total_changes`, checkpointów ani skrzynki.
  Uwzględnia także luki w starszych historiach stacji i Ukrainy.
  Przerwa jednej trasy nie resetuje innych obiektów.
- Wspólne odczyty w tle, prawidłowe liczbowe identyfikatory GIOŚ,
  pobranie czujników przed wartościami, widoczna awaria i brak świeżych danych.
- Niezależna obsługa Nowe → Przyjęte → Zamknięte, komentarze, konflikty 409,
  niezmienna podstawa oraz kopia zdarzenia czytelna po retencji i restartach.
- Ochrona Host/Origin/CSRF, walidacja definicji, limity 100 obszarów,
  50 aktywnych reguł i 5 MiB materiału.

## Przegląd i UI

Niezależny przegląd backendu doprowadził do regresji dla historycznych kluczy
pozycji, wersjonowanych przypisań komunikatów, krótkich luk sprzed v0.35,
korekt o tym samym czasie oraz zakresu luki jednego obiektu. Sprawdzono
niezmienność zdarzeń i materiałów oraz atomowość oceny. Po poprawkach
nie pozostały znane blokujące uwagi przeglądu.

Przegląd UI wykrył i naprawił nadpisywanie szkicu odpowiedzią zapisu,
przejęcie wyboru przez opóźnione wczytanie, utratę nowego komentarza
wpisanego podczas zapisu starszego i niewłaściwy czujnik przy nawigacji.
Nakładka podstawy zdarzenia ma jawny czas, przycisk zamknięcia i znika
przy niezależnej zmianie kontekstu. Zapisana geometria pozostaje odróżniona
od ewentualnego odczytu aktualnego katalogu.

Nowe 11 scenariuszy obejmuje trzy kształty i rewizje, kreator i podgląd,
pełny przebieg zdarzenia do teczki, konflikt mobilny, opóźnione odpowiedzi,
komentarz, cykl nakładki, prawdziwe kliknięcia i dotyk nad markerami
nieprzekazującymi zdarzeń, błędy odczytu oraz oba motywy i rozmiary ekranu.
Zrzuty viewportu sprawdzono wizualnie dla Obszarów, Reguł i Zdarzeń:
390 × 844 oraz 1440 × 1000, oba motywy. Mobilne dialogi są jawnie przypięte
do viewportu, ze sprawdzonymi granicami i przewijaniem.

W dostępnym pakiecie Playwright `waitForFunction` nie oczekiwało poprawnie
na asynchroniczny predykat. Test zdarzeń początkowo czytał skrzynkę przed
pracą workera. Poprawiono sam harness: jawne, ograniczone odpytywanie
lokalnego API zakończone asercją rzeczywistego niepustego wyniku.
Nie stwierdzono znikania zapisanych zdarzeń.

## Próby LIVE

`uv run --locked python scripts/check_workspace_monitor.py` pobrał publiczny
odczyt IMGW hydrologii. Na tymczasowej bazie utworzono celowo własny próg
poniżej rzeczywistego pomiaru; wykryto jedno zdarzenie, powtórzenie tego
samego odczytu zachowało jedno, a materiał teczki zachował podstawę i hash.
To próba integracyjna własnego progu, bez wnioskowania oficjalnego ostrzeżenia.
Baza testowa i odczyty źródłowe zostały usunięte po próbie.

Osobny `scripts/check_sources.py` wykonał odczyt czterech dotychczasowych
źródeł bez zapisu do bazy: RSO, RCB i Straż Graniczna zwróciły `success`;
IMGW meteorologiczne zwróciło `partial` z poprawnymi ostrzeżeniami i plikami
wymagającymi kontroli parsera. Nie przedstawiamy tego wyniku jako pełnego
pokrycia ani gwarancji stałej dostępności źródeł.

## Odtworzenie i ograniczenia

```sh
uv run --locked pytest -q
node --test tests/*.test.cjs tests/*_ui.cjs
uv run --locked ruff check .
uv lock --check
uv build
# W środowisku z Playwright i pobranym Chromium:
node --test --test-concurrency=1 tests/workspace_browser.cjs tests/moving_workspace_browser.cjs tests/ukraine_workspace_browser.cjs tests/dossiers_workspace_browser.cjs tests/graph_workspace_browser.cjs tests/monitor_workspace_browser.cjs
```

Jeśli Playwright nie jest w standardowej ścieżce Node, ustaw `NODE_PATH`
na katalog `node_modules` środowiska testowego. Użyto lokalnie dostępnego
pakietu i Chromium; bez instalacji globalnej.
Logi i zrzuty są lokalnie w ignorowanym `tmp/`; nie są pakowane do wydania.
Nie zmieniano istniejącej bazy `var/live`, kluczy ani konfiguracji lokalnej.
Nie uruchamiano autostartu ani wdrożenia. Safari i Firefox oraz długotrwały
monitoring dostawców i pełne obciążenie 50 reguł nie były sprawdzane.

## Poprawki po niezależnym przeglądzie `cb92a06`

Trzej niezależni recenzenci wskazali osiem usterek pierwszej implementacji.
Wszystkie otrzymały poprawki i regresje:

| Usterka | Poprawka i potwierdzenie |
|---|---|
| Prawidłowe pomiary GIOŚ były niewiarygodne | Obsługa źródłowego `status=value`, oddzielnie od hydrologicznego `fresh`; zachowana kontrola świeżości i jakości czasu. Test prowadzi przez rzeczywisty `GiosService`, normalizator, kolejkę historii i regułę, także dla zera, NULL, starych, przyszłych i niejednoznacznych pomiarów. |
| Wolne źródło blokowało całą ocenę | Osobne zadania pobierania dla zasobów, ograniczenie 100 zadań i deduplikacja. Ocena oraz pozostałe źródła działają podczas oczekiwania. Zachowano zależność metadanych czujnika przed wartościami GIOŚ i bezpieczne zatrzymanie z zakończeniem rozpoczętych zapisów. |
| Surowy raport sprzed edycji przechodził do nowej rewizji | Znacznik odbioru jest nadawany przed kolejką; rewizja reguły/obszaru ustanawia własną granicę odbiorów. Testy używają rzeczywistych kolejek transportu i stacji, stałego zegara, restartu oraz błędu transakcji. Niezmienione reguły zachowują swoje obserwacje. |
| Podgląd Ukrainy ignorował poprawne odczyty | Stan jest potwierdzany przez rzeczywiste udane odczyty, nie tylko rzadkie zmiany stanu. Jawne przerwy, brak odczytów i zatrzymanie rejestracji nadal tworzą luki; strumień bieżący i archiwum zachowują swoje progi pokrycia. |
| Archiwizacja obszaru uniemożliwiała wyłączenie reguły | Istniejącą regułę z niezmienionym selektorem można wyłączyć. Ponowne włączenie lub zmiana definicji nadal podlegają walidacji. Edytor zachowuje wybrany obszar archiwalny lub niedostępny; sprawdzono CSRF i konflikt rewizji. |
| Stronicowanie mieszało wyniki po zmianie filtrów | Nowe zapytanie zeruje listę i offset; kolejne strony są blokowane do otrzymania pierwszej. Test zatrzymuje odpowiedź filtrowania i próbuje pobrać kolejną stronę. |
| Czytniki nie pokazywały przejść stanów audytu | Skrzynka i teczka czytają rzeczywiste `payload.from` / `payload.status`. Testy korzystają ze struktury API i sprawdzają przejścia Nowe → Przyjęte → Zamknięte. |
| Komentarz ze spacjami pozostawał po wysłaniu | Porównanie odbywa się z oryginalnym wysłanym szkicem. Niezmieniony tekst jest czyszczony, a nowa edycja wpisana podczas żądania pozostaje zachowana. |

Dla GIOŚ i wyłączania reguły uruchomiono nowe testy z modułami poprzedniego
commita załadowanymi wyłącznie w pamięci: 4 testy zawiodły. Z poprawkami cały
zestaw 8 testów przeszedł. Pięć regresji rzeczywistych kolejek oraz regresje
stronicowania, audytu i selektora obszaru również potwierdziły RED → GREEN.

Nowy znacznik odbioru wykorzystuje istniejące `workspace_monitor_meta`
i JSON obserwacji. Nie zmienia schematu SQLite i nie porównuje źródłowego
czasu pomiaru z czasem edycji. Dzięki temu świeżo otrzymany raport z wcześniejszym
czasem źródłowym nadal może być oceniony, a oczekujący stary raport jest pomijany.

Ponowny niezależny przegląd całego diffu poprawek nie wskazał nowych usterek;
recenzent uruchomił dodatkowo 63 testy celowane. Nie wykonywał osobno testów
przeglądarkowych ani długiego obciążenia 50 reguł.

Końcowe wyniki poprawek: **1151 testów Python i 375 testów Node zaliczonych**;
pozostały trzy wcześniej opisane ostrzeżenia bibliotek. Ruff, lockfile,
`git diff --check` oraz budowa paczki są poprawne. Ponowiona próba LIVE
hydrologii IMGW na bazie tymczasowej potwierdziła wykrycie, deduplikację
oraz trwałą kopię w teczce.

Końcowa regresja przeglądarkowa po poprawkach: **52/52 Chromium** (Analiza,
transport, Ukraina, teczki, graf, nowe panele, GIOŚ, hydrologia i trasy).
Pierwszy szeroki przebieg miał wynik 51/52: nowy test niedostępnego obszaru
wybierał poprzednią opcję przed zakończeniem ponownego odczytu metadanych.
Poprawiono wyłącznie sekwencję testu — jawnie zatrzymaną odpowiedź i oczekiwanie
na inicjalizację edytora — bez zmiany asercji lub kodu produktu. Izolowana
próba, cały zestaw 13 testów monitora i ponowny szeroki przebieg przeszły.

Dodatkowo przeszły **2/2 próby 3D z rzeczywistym WebGL**: samolot (kamery,
wstrzymanie, powrót i istniejący feed) oraz autobus (model, obie kamery,
wstrzymanie i odzyskanie danych). Są to wybrane scenariusze kontrolne,
nie ponowienie wszystkich wcześniejszych testów 3D.
