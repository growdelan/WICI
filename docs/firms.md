# NASA FIRMS w WICI — minimalna integracja, 13.10.2026

Rozszerzenie na zlecenie użytkownika: osobna warstwa satelitarnych wykryć dla Polski. Nie zmienia obserwacji w oficjalne komunikaty ani w potwierdzone interwencje straży pożarnej.

## Zakres i konfiguracja

Trzy produkty VIIRS NRT: `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `VIIRS_SNPP_NRT`. Co 900 sekund podczas pracy aplikacji kolektor pobiera CSV z oficjalnego [API obszaru FIRMS](https://firms.modaps.eosdis.nasa.gov/api/area/). Prostokąt `14,49,24.2,55` jest wstępnym zakresem; środek każdego wykrytego piksela jest następnie filtrowany według dostarczonych lokalnych granic województw PRG i przypisywany do województwa. Uproszczenie PRG może wpłynąć na punkty przy granicy. Nie dodano zależności GIS podczas pracy aplikacji.

Pobierane są trzy dni kalendarzowe UTC, aby obsłużyć pełne ruchome 48 godzin również po północy. Zapytania nie pobierają świata ani archiwum. Rekordy przechowują współrzędne, czas obserwacji UTC, produkt, satelitę, instrument, źródłową pewność wykrycia i FRP w MW. Nominalna rozdzielczość VIIRS to 375 m; punkt wskazuje środek piksela, nie precyzyjne źródło pożaru ani jego powierzchnię.

Skopiuj ustawienia wyłącznie do pomijanego przez Git `config.local.toml`:

```toml
[sources.firms]
enabled = true
interval_seconds = 900
map_key = "TWÓJ_KLUCZ"
```

Klucz pozostaje lokalny, jest maskowany w reprezentacji konfiguracji i w logach HTTPX. API/UI pokazują publiczny URL NASA bez klucza. Przykład wersjonowany nie zawiera prawdziwego klucza. Bez klucza pobieranie jest wyłączone. Demo pozostaje offline. Weryfikacja sieciowa nie jest częścią zwykłych testów.

## Mapa, historia i świeżość

Osobny przełącznik „Satelitarne wykrycia pożarów” i okno 24/48 godzin. Punkty mają odrębny styl; kliknięcie pokazuje czas w Europe/Warsaw, wiek obserwacji względem aktualnego zegara, satelitę, pewność wykrycia, FRP i województwo. Filtr województwa i dzień są współdzielone z widokiem komunikatów; pozostałe filtry komunikatów nie ograniczają obserwacji.

Dla dzisiaj koniec okna to aktualny czas. Dla wcześniejszego dnia — koniec dnia kalendarzowego w Europe/Warsaw. Historia jest lokalna: pokazuje zapisane obserwacje, nie odtwarza stanu wiedzy z wcześniejszej chwili i nie pobiera brakujących dat. Jedno wykrycie nie tworzy kolejnego rekordu przy każdym odświeżeniu; obserwacje z różnych satelitów pozostają osobnymi pomiarami. Liczba punktów nie jest liczbą odrębnych pożarów.

Źródło `firms` w „Źródłach” ma stan odczytu, ostatnią próbę, ostatni kompletny sukces i zakres produktów. Pusty poprawny CSV jest sukcesem odczytu, nie dowodem braku pożarów. Częściowa awaria produktów jest jawnie oznaczona; uzyskane poprawne rekordy zostają zapisane. Błąd nie usuwa historii. Odświeżanie działa tylko podczas uruchomienia, a po przerwie aplikacja wykonuje jeden zaległy odczyt.

`GET /api/fires?hours=24|48&date=YYYY-MM-DD&voivodeship=XX&limit=2000`: zapisane obserwacje oraz `items`, `total`, `limited`, `window_start`, `window_end`, `hours`. Limit jest jawny; można zawęzić województwo lub okno. Dane przechowywane w osobnej tabeli SQLite `fire_observations`; migracja 004 zachowuje dotychczasowe dokumenty i historię.

## Ograniczenia źródła

Według [NASA](https://firms.modaps.eosdis.nasa.gov/) dane globalne są dostępne zwykle w ciągu trzech godzin **od obserwacji**, a nie od początku pożaru. Polling co 15 minut nie zmienia częstotliwości przelotów. Obserwacja sprzed kilku godzin nie potwierdza, że pożar nadal trwa.

[Wykrycie anomalii cieplnej](https://firms.modaps.eosdis.nasa.gov/map2/) może odpowiadać pożarowi, wypalaniu roślinności lub innym źródłom ciepła, w tym przemysłowym. Chmury, dym oraz rozmiar/intensywność zjawiska mogą uniemożliwić detekcję. Brak punktów nie oznacza braku zagrożenia. Warstwa nie zastępuje informacji PSP ani systemu alarmowego. EFFIS, MODIS, analiza dymu, grupowanie w kompleksy pożarów i automatyczne alarmy pozostają poza tym wdrożeniem.

## Weryfikacja

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).
