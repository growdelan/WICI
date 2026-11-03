# Wydajność autobusów i Analizy — 03.11.2026

## Plan i wdrożony zakres

1. Zachować znaczniki autobusów i zmieniać pozycję, ikonę oraz tytuł tylko po zmianie odpowiednich danych. Oddzielić aktualizację wieku od obliczania przynależności do regionu.
2. Usunąć powieloną kolekcję obiektów mapy z odpowiedzi API Analizy i dostosować klientów oraz testy.
3. Aktualizować istniejące warstwy Analizy, ograniczyć zmiany niezmienionych wierszy i paneli oraz pomiary układu strony. Sprawdzić wybór obiektu, historię, graf i monitoring.

Zmiany są na branchu `codex/performance-map-analysis`. Nie wymagają migracji bazy ani zmiany konfiguracji.

## Zachowanie po zmianie

- Autobusy zachowują obiekt Leaflet, ikonę i współrzędne podczas zwykłego odświeżania wieku. Przekroczenie 60 s nadal zmienia wygląd i dostępność 3D; przekroczenie 120 s usuwa pozycję. Awaria źródła, zmiana linii, miasta lub regionu są nadal obsługiwane. Przynależność przestrzenna jest obliczana raz na nowy snapshot i unieważniana po zmianie regionu. Węzły otwartej karty, przewinięcie i fokus przycisku pozostają zachowane.
- `POST /api/workspace/query` zwraca obiekty mapy wyłącznie w `map.points`, `map.areas` i `map.aggregates`. Powielone `map.items` zostało usunięte. Główne `items` nadal zawiera stronę tabeli; zliczenia, zakres mapy, limity i stronicowanie pozostają takie same.
- Mapa Analizy zachowuje warstwy według identyfikatora, porównuje ich prezentację i usuwa wyłącznie obiekty opuszczające wynik. Zachowuje wspólne obszary wielu komunikatów, aktualizuje ich listę i nazwy, a warstwę geometrii zastępuje dopiero po rzeczywistej zmianie geometrii. Tak samo aktualizowane są znaczniki odtwarzania i grafu. Luki nadal usuwają pozycję, nie łącząc przerwanych tras.
- Wiersze tabeli porównują dane potrzebne do prezentacji. Ruch kursora stacji nie zmienia pozostałych wierszy ani panelu pokrycia źródeł. Zmiany porównywanych tras i alarmów, obserwowanych obiektów, strefy czasu, kolumn oraz oficjalnych indeksów nadal odświeżają odpowiednie elementy.
- Ustalanie położenia karty odbywa się po zmianie układu, rozwinięciu panelu lub zmianie rozmiaru. `ResizeObserver` i `requestAnimationFrame` łączą pomiary; nie są one wykonywane po każdym ruchu kursora.

## Pomiary

Próby wykonano na tej samej maszynie macOS ARM64, Python 3.12.12 i Chromium 153, z danymi syntetycznymi oraz tymczasowymi bazami. Przeglądarka blokowała połączenia poza własnym serwerem demo. Czasy przeglądarki obejmują wywołania renderowania i wymuszone obliczenie układu DOM, a nie pełny odczyt API ani pomiar FPS GPU.

| Scenariusz | Przed | Po |
|---|---:|---:|
| 500 autobusów, niezmienione dane, mediana aktualizacji | 30,3 ms | 0,4 ms |
| Wymiany ikon / pozycji w 10 takich aktualizacjach | 5000 / 5000 | 0 / 0 |
| 1000 punktów Analizy, nowa odpowiedź z niezmienionymi punktami, mediana | 17,5 ms | 1,8 ms |
| 1000 punktów, ponowne renderowanie tego samego zestawu, mediana | 5,5 ms | 1,0 ms |
| Zmiany stylów / dymków w 20 niezmienionych renderach | 20 000 / 20 000 | 0 / 0 |
| Odpowiedź dla 1000 stacji, 100 rekordów tabeli | 2 395 189 B | 1 260 093 B |

Usunięcie `map.items` zmniejsza ten payload o 47,4%. W próbie porównującej samą serializację FastAPI koszt zmalał z 104–126 ms do 54–59 ms. Dokładne czasy zależą od sprzętu i obciążenia; liczby operacji DOM i brak powielonej kolekcji są sprawdzane niezależnie od czasu wykonania.

## Odtworzenie pomiarów

```sh
uv run --locked python scripts/benchmark_workspace.py --samples 100000 --runs 10 --stations 1000 --communications 0
node scripts/benchmark_map.cjs
```

Benchmark przeglądarki wymaga dostępnego pakietu Playwright i jego Chromium, jak pozostałe scenariusze przeglądarkowe projektu. `NODE_PATH` może wskazywać katalog z pakietem. Opcjonalna zmienna `WICI_CHROMIUM_EXECUTABLE` wskazuje istniejący plik wykonywalny Chromium. Benchmark uruchamia własny serwer na wolnym porcie i usuwa jego bazę po zakończeniu.

## Weryfikacja i ograniczenia

- Pełny Python: 1174 zaliczone, trzy dotychczasowe ostrzeżenia bibliotek.
- Pełny Node: 379 zaliczonych.
- Końcowa weryfikacja Analizy: 49/49 scenariuszy Chromium — katalog, transport, Ukraina, teczki, graf, obszary, reguły i skrzynka, w tym nowy test zmian DOM podczas przesuwania kursora.
- Ruff, składnia zmienionego JS oraz kontrola diffu: poprawne.
- Nowe regresje obejmują niezmienione i przesunięte autobusy, zmianę aktualności, linii i regionu, zachowanie kart, pojedynczą kolekcję API, stabilne znaczniki, wspólne obszary, zmianę geometrii i selektywne aktualizacje tabeli oraz źródeł. Pierwotne regresje dla niezmienionych znaczników i powielonej kolekcji odtworzyły problem przed poprawką.

W zestawie ośmiu scenariuszy autobusów 3D sześć przeszło, a dwa zatrzymały się na asercjach ruchu kamery poniżej 0,1 m po zatrzymaniu lub odrzuceniu raportu (`buses3d_browser.cjs:87` i `:185`). Oba błędy odtworzono również na odizolowanym, niezmienionym `main` (`36e8cd4`) z tym samym Chromium. Nie zmieniano algorytmu kamery ani tolerancji tych testów.

Próby nie oceniają szybkości usług LIVE, Safari ani Firefox.
