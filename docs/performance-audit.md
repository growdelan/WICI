# Audyt i usprawnienia wydajności — 05.11.2026

Zakres: backend, SQLite, API, kolektory, geometria PRG, Atlas, Eksplorator,
historia i graf, teczki oraz cykl życia widoków 3D. Punkt odniesienia:
`128de1a` (WICI 0.37.0), branch `codex/performance-audit`.

Zmiany ograniczają powtarzaną pracę. Nie zmieniają schematu bazy, retencji,
częstotliwości odczytów, limitów wyników, rozdzielczości obrazów ani geometrii.
Nie wymagają nowych zależności ani konfiguracji. Dane live i istniejące
materiały w `output/` nie są używane przez pomiary.

## Wdrożone zmiany

### Odczyty SQLite i przygotowanie wyników

- Katalog pobiera obszary, najnowsze pomiary i oficjalne indeksy porcjami
  do 500 identyfikatorów, zamiast osobnych zapytań dla każdego obiektu.
- Tabela i mapa wykorzystują tę samą prezentację obiektu w ramach jednego
  zapytania pod blokadą repozytorium. Nie powstaje cache wyników pomiędzy
  kolejnymi odczytami; korekty i zmiana aktualności pozostają widoczne.
- Lista komunikatów sprawdza źródło i dzień przed kosztowną prezentacją
  treści. Po osiągnięciu limitu nadal liczy wszystkie pasujące rekordy,
  ale nie przechowuje niepotrzebnych pełnych wyników.
- Lista teczek odczytuje liczniki w jednym SQL. Graf pobiera węzły i
  kandydatów zbiorczo, prezentuje wersję komunikatu raz na odczyt i nie
  buduje odfiltrowanych rodzajów relacji.
- Monitoring współdzieli dekodowanie najwyżej 256 obserwacji w pojedynczym
  cyklu, z osobnym słownikiem dla wyniku każdej reguły. Niedopasowane
  obserwacje pomijają odczyt poprzedniego stanu. Nadal przechodzą przez
  checkpoint i kontrole przepełnienia; rollback usuwa także cache cyklu.

### Odpowiedzi API

Duże odczyty katalogu, historii, grafu, materiałów, transportu, środowiska,
geometrii i zobrazowań zwracają `JSONResponse`. Usługi wcześniej przygotowują
wartości zgodne z JSON, więc dodatkowe rekurencyjne kopiowanie przez FastAPI
nie jest potrzebne. Serializacja zachowuje te same bajty odpowiedzi,
pełną precyzję liczb, polskie i ukraińskie znaki oraz `null`.
Ochrona Host/Origin/CSRF, walidacja wejścia, statusy błędów i `no-store`
pozostają aktywne.

### Geometria i zapis transportu

- Stały indeks krawędzi PRG wybiera odcinki przecinające szerokość
  geograficzną punktu. Nie upraszcza pierścieni ani nie zaokrągla pozycji.
  Współdzielą go Analiza, samoloty, pogoda i FIRMS.
- Zachowane są różnice dotychczasowych reguł granic i otworów poszczególnych
  integracji, w tym tolerancja `1e-10`. Indeks obejmuje wyłącznie dołączone
  PRG, więc jego rozmiar nie zależy od liczby odczytów.
- Kolejka transportu wykonuje jedną prywatną głęboką kopię snapshotu.
  Obserwacja i projekcja czytają te same zagnieżdżone dane, a metadane
  receipt pozostają osobne. Każdy odbiór, jego kolejność, przepełnienia
  i luki są nadal zachowywane.

### Interfejs

- Wspólne funkcje formatowania czasu Eksploratora używają maksymalnie sześciu
  obiektów `Intl.DateTimeFormat`: dwa style dla Warszawy, Kijowa i UTC.
  Atlas ponownie wykorzystuje osobny formatter.
- Wybór próbki przy kursorze wykonuje jeden przebieg historii bez tworzenia
  i sortowania dodatkowej tablicy. Zachowuje korekty, remisy, brak wartości
  i półotwarte przedziały czasu.
- Samoloty i statki zmieniają pozycję i ikonę tylko po zmianie odpowiednich
  danych. Nadal aktualizują treść, kierunek, klasyfikację, wiek i dostępność
  działań; zachowują istniejące elementy okienek.
- Filtrowanie regionu odrzuca punkty poza zapamiętaną obwiednią pierścienia,
  a następnie wykonuje dotychczasowy dokładny test. Granice Leaflet dla
  stałych geometrii PRG są ponownie wykorzystywane.
- Atlas porównuje pola prezentacji komunikatów oraz zapytanie. Przy
  niezmienionym wyniku zachowuje listę, karteczki, obszary, fokus i popupy.
  Nadal odczytuje API, zastępuje pełne metadane oraz aktualizuje liczniki.
  Zmiana ostrzeżenia, wersji, lokalizacji, dnia lub filtrów wymusza render.
- Regresja mobilna ujawniła istniejące także na wersji bazowej zasłanianie
  popupu IODA przez zoom i przycisk „Widok 3D”. Kontrolki są teraz ukryte
  wyłącznie na czas otwarcia tego popupu i wracają po zamknięciu.
  Przycisk wyjścia z aktywnego 3D pozostaje dostępny.

## Pomiary

Lokalny macOS ARM64, Python 3.12.12, Chromium 151.0.7922.34. Mediany
powtórzeń, syntetyczne dane, bez dostawców live. Czasy operacji nie są
pomiarem FPS GPU ani gwarancją czasu całej interakcji użytkownika.

| Operacja i rozmiar próby | Przed | Po |
|---|---:|---:|
| Tabela i mapa: 800 stacji, 64 tys. pomiarów | 35,355 ms | 19,466 ms |
| SQL tej tabeli i mapy | 2711 | 20 |
| Dzisiejsze komunikaty z 5000 zapisanych | 121,004 ms | 37,160 ms |
| Wszystkie komunikaty, limit odpowiedzi 1000 | 126,872 ms | 50,434 ms |
| Lista 100 teczek | 0,644 ms / 301 SQL | 0,368 ms / 1 SQL |
| Graf własnego obszaru: 800 sąsiadów | 22,132 ms / 1605 SQL | 13,391 ms / 9 SQL |
| Monitoring: 50 reguł × 256 pasujących obserwacji | 283,749 ms | 227,220 ms |
| Monitoring: dopasowania mieszane, receipt i luki | 164,405 ms / 29 614 SQL | 147,003 ms / 19 488 SQL |
| API: gotowy wynik katalogu, 405 481 B | 21,895 ms | 3,317 ms |
| API: gotowa warstwa, 368 808 B | 19,646 ms | 2,903 ms |
| API: gotowa historia, 272 622 B | 16,799 ms | 2,353 ms |
| Przypisanie województw: 1000 punktów | 393,275 ms | 5,594 ms |
| Filtr Polski dla 1000 samolotów | 157,406 ms | 2,839 ms |
| Przypisanie województw FIRMS: 1000 punktów | 163,771 ms | 4,590 ms |
| Pełna normalizacja 1000 samolotów | 165,826 ms | 7,457 ms |
| Kopiowanie do kolejki: 1000 obiektów | 7,498 ms | 3,675 ms |
| 2000 formatowań czasu | 63,7 ms | 1,6 ms |
| 120 ruchów kursora, 5000 próbek | 113,4 ms | 55,2 ms |
| Odświeżenie 1000 niezmienionych samolotów | 32,7 ms | 5,0 ms |
| Odświeżenie 1000 niezmienionych statków | 14,9 ms | 5,3 ms |
| 10 tys. punktów względem Mazowsza w przeglądarce | 168,7 ms | 20,6 ms |
| Atlas: odświeżenie 1000 niezmienionych komunikatów | 88,6 ms | 2,2 ms |

W 15 identycznych odświeżeniach każdej warstwy transportu liczba wymian
ikon i zmian pozycji spadła z 15 000 + 15 000 do 0 + 0. Wynik regionalny
pozostał identyczny: 746 punktów. Backend zachował liczby wyników i rozmiary
odpowiedzi; benchmark API dodatkowo porównuje bajty odpowiedzi.

W Atlasie 15 niezmienionych odświeżeń tworzyło 720 GeoJSON, 240 karteczek,
usuwało 1200 warstw i powodowało 15 075 mutacji listy. Po zmianie wszystkie
te liczniki wynoszą zero, a p95 spadło ze 101,5 ms do 3,4 ms.

Benchmark API izoluje koszt routingu, zabezpieczeń i serializacji gotowego
snapshotu, bez zapytania SQLite. Nie należy dodawać ani mnożyć przyspieszeń
z różnych scenariuszy. Backend porównano z tym samym fixture na bazowych
modułach `128de1a`; benchmark usług uruchamia także pierwotne algorytmy
referencyjne i sprawdza równoważność wyników.
Benchmark monitoringu porównuje pełny zrzut SQLite po przetwarzaniu:
zdarzenia, stany, checkpointy i pozostałe tabele są identyczne.

### Odtworzenie

```sh
uv run --locked --offline python scripts/benchmark_backend_queries.py
uv run --locked --offline python scripts/benchmark_api.py --runs 15
uv run --locked --offline python scripts/benchmark_services.py --runs 7
uv run --locked --offline python scripts/benchmark_monitor.py --runs 15 --compare-ref 128de1a
node scripts/benchmark_frontend.cjs
node scripts/benchmark_atlas.cjs
```

Benchmark frontendu wymaga Playwright/Chromium. `NODE_PATH` może wskazywać
istniejący katalog modułów. Wszystkie bazy benchmarków są tymczasowe.

Polecenia backendu, frontendu i Atlasu powyżej mierzą aktualny kod (kolumnę
„Po”). Dla kolumny „Przed” uruchomiono te same nowe skrypty i fixture na
izolowanych kopiach modułów z `128de1a`. Aby powtórzyć porównanie, należy
utworzyć osobny checkout tej rewizji, skopiować do niego odpowiednie skrypty
oraz `tests/helpers/atlas_refresh.cjs` dla Atlasu i użyć tych samych zależności,
parametrów oraz przeglądarki. Python musi importować `src` z tego checkoutu
(np. przez `PYTHONPATH`); helper Atlasu oczekuje w nim `.venv/bin/python`.
Benchmarki API i usług zawierają porównanie z algorytmem referencyjnym,
a monitoring pobiera wskazaną rewizję przez `--compare-ref`.

## Zakres przeglądu i zachowane mechanizmy

| Obszar | Ustalenie |
|---|---|
| Indeksy, blokady i migracje | Usunięto N+1 bez przebudowy schematu; zachowane transakcje, wspólny `RLock` i kolejność migracji. |
| Rewizje katalogu i grafu | Zachowane unieważnianie, podpisane kursory i kontrola konfliktów. Zimny graf nadal wymaga ustalenia rewizji; nie ukrywa się tego cache o niepełnych zależnościach. |
| Historia, monitoring i teczki | Zachowane checkpointy, receipt, retencja, niezmienne kopie i rozdzielenie danych źródłowych od interpretacji. |
| Kolektory i HTTP | Zachowane cache, timeouty, retry/backoff, ograniczenia domen i limity dostawców. Nie wydłużano okresów odświeżania. |
| Raster i 3D | Zachowane lazy Cesium, renderowanie na żądanie, ograniczone kolejki/cache oraz dekodowanie poza pętlą API; bez zmiany LOD, geometrii i jakości obrazu. |
| Kolej i maska morska | Istnieją cache profili/odcinków i indeks maski morskiej; nie dodawano drugiego archiwum ani uproszczonych pozycji. |
| Pozostałe warstwy frontendu | Zachowano aktualizacje różnicowe autobusów, sygnatury GFM, kontrolę rewizji i anulowanie starych odpowiedzi. |
| Pobieranie w Analizie | Zachowane deduplikacja, TTL, współdzielenie źródeł i limity GIOŚ; ukryta karta nie rozpoczyna nowych odczytów. |

## Weryfikacja

Nowe regresje obejmują liczbę operacji SQL/DOM, równoważność treści API,
granice i otwory PRG, wszystkie wierzchołki dołączonych pierścieni, DST,
korekty `null`, sensory i indeksy GIOŚ, kolejność i liczniki komunikatów,
paginację grafu, zmianę geometrii oraz niezależność danych kolejki od
późniejszych zmian wywołującego. Wyniki czasowe benchmarków nie są progami
zaliczenia testów.

Pełny pierwszy przebieg 3D ujawnił niestabilne oczekiwanie w teście POV:
stałe 600 ms nie obejmowało czasu trwającej odpowiedzi i kolejnego timera
odświeżania. Błąd odtworzono na bazowym `128de1a`, opóźniając jedną
syntetyczną odpowiedź o 1500 ms. Test czeka teraz najwyżej 5 s na faktyczny
następny odczyt i zachowuje wszystkie asercje: dalsze odpytywanie, identyczny
czas obserwacji, odblokowanie POV i właściwy kierunek kamery. Ten sam
scenariusz z opóźnieniem przechodzi. Nie zmieniano kodu kamery, harmonogramu
produkcyjnego ani tolerancji położenia/kierunku.

Pierwszy pełny przebieg 2D przeszedł w 89 z 90 przypadków. Jedyny błąd
dotyczył rzeczywistego zasłonięcia zamknięcia popupu IODA przez przycisk
„Widok 3D”, co potwierdził `elementFromPoint` także na `128de1a`.
Poprawiono CSS, zachowując oryginalne sprawdzenia trafienia w przycisk,
widoczności treści i zamknięcia dotykiem. Test dodatkowo sprawdza powrót
kontrolek po zamknięciu popupu.

Wyniki końcowe:

- Python: **1215 passed**, 131,29 s. Trzy istniejące ostrzeżenia dotyczą
  kompatybilności Starlette/httpx i georeferencji syntetycznych rastrów.
- JavaScript/Node: **408 passed**, bez błędów.
- Ruff i `git diff --check`: bez błędów.
- Pełny pierwszy przebieg 3D: **29/30 passed**; opisany wyżej test POV
  po poprawce oczekiwania przeszedł osobno zarówno normalnie, jak i przy
  celowym opóźnieniu odpowiedzi. Pozostałych 29 przypadków nie powtarzano.
- Pełny pierwszy przebieg 2D: **89/90 passed**, 399,03 s. Po poprawce
  popupu ponowiono cały zestaw IODA: **5/5 passed**, 18,64 s. Pozostałe
  scenariusze były zielone w pełnym przebiegu.
- Samodzielny test jakości pozycji: **passed** — mapa, popup, filtry,
  historia, odświeżanie, błędy źródła oraz desktop/mobile na izolowanym DEMO.

Regresje przeglądarkowe wykorzystują Chromium, izolowane bazy i dane offline.
Nie jest to walidacja dostępności bieżących dostawców ani zgodności
Safari/Firefox. Przegląd kodu i wyniki testów nie zastępują pomiarów przyszłych
obciążeń produkcyjnych; do ich porównywania pozostają skrypty benchmarków.
