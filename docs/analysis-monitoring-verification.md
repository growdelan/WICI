# Weryfikacja v0.35.0 — obszary, reguły i zdarzenia

Data: 25.10.2026. Branch: `codex/wici-areas-rules-events-v0350`.

## Zakres i testy

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
