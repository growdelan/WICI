# Kolej — PolishTrainsGTFS

Bieżąca warstwa „Kolej → Stacje, kursy i opóźnienia” na mapie WICI. Bez konta i klucza API. Fioletowe punkty oznaczają stacje. Osobne romby ze znakiem pociągu pokazują wyłącznie szacowane położenie kursów.

## Korzystanie

Włącz warstwę, kliknij stację, a następnie wybierz kurs, aby zobaczyć przebieg trasy i postoje. Kursy dotyczą bieżącego czasu, niezależnie od dnia publikacji i filtra województwa. Pierwsze wczytanie obejmuje rozkład ZIP i aktualizacje JSON i może potrwać kilkadziesiąt sekund. Kolejne odczyty korzystają ze wspólnego pamięciowego cache backendu: rozkład przez 6 godzin, aktualizacje przez 120 sekund. UI odświeża dane co minutę tylko przy aktywnej warstwie na widocznej mapie. Po wyłączeniu, ukryciu karty lub przejściu do Źródeł odczyty ustają. Backend nie pobiera danych w tle. Cache znika po zatrzymaniu aplikacji.

Godziny są prezentowane w strefie Europe/Warsaw. Brak aktualizacji oznacza „rozkład planowy”, a nie potwierdzenie punktualności. Opóźnienia są wyliczane z aktualizowanych i planowych godzin konkretnego postoju. Trasa pochodzi ze statycznego rozkładu; nie potwierdza rzeczywistego przejazdu ani aktualnego objazdu. Gdy źródło oznacza objazd, WICI nie rysuje niepotwierdzonego przebiegu trasy i nie dopasowuje nowych numerów kolejności postojów do starego rozkładu. Szacowane pozycje są osobną, wyraźnie oznaczoną częścią warstwy, opisaną poniżej.

## Szacowane pozycje pociągów

Po włączeniu kolei opcja „Szacowane pozycje pociągów” pokazuje romby ze znakiem pociągu. Każdy znacznik i jego dymek są oznaczone jako **POZYCJA SZACOWANA · nie GPS**. Dymek podaje kurs, przewoźnika, odcinek i wiek danych źródłowych; wybranie trasy pokazuje postoje kursu. Sam czas wyliczenia szacunku nie zastępuje czasu aktualizacji danych.

Backend wyznacza położenie wzdłuż geometrii rozkładowej, pomiędzy postojami z dostępnymi aktualizowanymi godzinami przyjazdu i odjazdu. Zakłada równomierny ruch pomiędzy tymi godzinami; w czasie postoju szacunek pozostaje przy stacji. Nie jest to pomiar ani potwierdzenie, że skład faktycznie jedzie. Nagłe zatrzymanie, sygnalizacja lub opóźnienie niedostarczone jeszcze przez źródło mogą dawać znaczny błąd.

Znacznik nie powstaje dla samego rozkładu bez odpowiednich aktualizacji. Do dopasowania trasy służą zgodne odległości `shape_dist_traveled` zapisane przez dostawcę dla postojów i geometrii. Pomijane są niejednoznaczne lub niespójne godziny, odwołane kursy, brak geometrii lub zgodnego przypisania postojów do trasy oraz objazdy, dla których źródło nie udostępnia aktualnego przebiegu. Pozycje są ograniczone do Polski według granic PRG. Brak znacznika nie oznacza braku pociągu.

Odczyt i przeliczenie pozycji następują co 15 sekund tylko na aktywnej widocznej mapie. Aktualizacje dostawcy nadal korzystają ze wspólnego cache 120 sekund. Przy danych starszych niż 10 minut, błędzie odświeżania lub nieważnym rozkładzie backend zwraca pustą listę pozycji. UI także usuwa znaczniki po błędzie pobrania i sprawdza ich ważność co sekundę, niezależnie od kolejnego odczytu. Ważność szacunku kończy się najpóźniej po 30 sekundach od wyliczenia, na końcu aktualnego odcinka lub po przekroczeniu wieku źródła 10 minut — zależnie od tego, co nastąpi wcześniej. Przeglądarka nie dopisuje dalszego ruchu po wygaśnięciu szacunku.

Odwołanie lub objazd rozpoznane w tablicy stacji albo szczegółach kursu usuwają jego szacunek niezależnie od sposobu otwarcia dymka. Dotyczy to konkretnego kursu i dnia rozpoczęcia. Oczekujące odpowiedzi pozycji są unieważniane, a ta sama lub starsza wersja danych nie może przywrócić odrzuconego znacznika; może go przywrócić nowsza aktualizacja źródła. Samo pominięcie postoju jest odróżniane od odwołania całego kursu.

## Źródła i ograniczenia

- [Katalog danych i warunki](https://mkuran.pl/gtfs/).
- [Statyczny rozkład GTFS ZIP](https://mkuran.pl/gtfs/polish_trains.zip): stacje, przewoźnicy, kursy, postoje, kalendarz i geometria tras.
- [Aktualizacje JSON](https://mkuran.pl/gtfs/polish_trains/updates.json): zmiany godzin, statusy kursów i postojów, czas aktualizacji źródła.
- [Kod źródłowy i znane problemy](https://github.com/MKuranowski/PolishTrainsGTFS).

Dostawca przetwarza dane PKP PLK; pokrycie nie obejmuje całej kolei w Polsce. Pociągi międzynarodowe i zastępcza komunikacja autobusowa mogą mieć niepełne lub błędne dane. Identyfikatory kursów zmieniają się między wersjami rozkładu. Numery peronów i torów w JSON pochodzą z rozkładu i nie potwierdzają bieżących zmian; WICI nie prezentuje ich jako aktualnych informacji peronowych.

Dostawca ostrzega o zatrzymywaniu aktualizacji nawet na ponad godzinę. WICI sprawdza czas źródła, a nie tylko powodzenie HTTP. Dane starsze niż 10 minut oraz ostatnie dane po błędzie odświeżania są oznaczane jako nieaktualne. Ostrzeżenie starzeje się również w otwartej karcie przeglądarki. Brak kursów nie oznacza braku ruchu ani braku utrudnień.

## Konfiguracja

Domyślnie integracja jest dostępna; pobieranie rozpoczyna dopiero włączenie warstwy. Aby ją wyłączyć, ustaw w `config.local.toml`:

```toml
[sources.trains]
enabled = false
```

Po zmianie konfiguracji uruchom WICI ponownie. Demo nie pobiera danych kolejowych z internetu. Dane nie tworzą archiwum przejazdów ani historii opóźnień.

## Dostęp HTTP

Próba 15.10.2026 potwierdziła pełny odczyt JSON i ZIP przez `httpx`. Domyślny `Python-urllib/3.12` był odrzucany HTTP 403 / Cloudflare 1010; jawny identyfikator aplikacji działał. WICI korzysta ze wspólnego klienta `httpx`; zapytania kolejowe jawnie wysyłają `User-Agent: WICI/1.0 (PolishTrainsGTFS)`. Dostępność może się zmienić.

## API i zasoby

- `GET /api/trains/positions`: bieżące szacunki z czasem wyliczenia, czasem źródła i terminem ważności; nigdy nie zwraca nieaktualnych pozycji.
- `GET /api/trains/stations`: zgrupowane stacje w Polsce i stan aktualności.
- `GET /api/trains/stations/{station_id}`: odjazdy z ostatnich 30 minut i najbliższych 3 godzin, maksymalnie 100; dymek pokazuje pierwszych 30 z jawną informacją o ograniczeniu.
- `GET /api/trains/trips/{trip_id}?start_date=YYYY-MM-DD`: postoje i geometria konkretnego kursu w dniu rozpoczęcia. Godziny po północy są przypisane do właściwego dnia kursowania GTFS.

Stałe adresy dostawcy, brak przekierowań, ograniczenie pobrania do 48 MiB na plik i sumy rozpakowanych plików do 240 MiB. ZIP nie jest rozpakowywany na dysk. Parsowanie dużych plików działa w wątku roboczym, a równoczesne odczyty współdzielą jedno odświeżenie. W próbie z 15.10.2026 proces z pełnym rozkładem i aktualizacjami zajmował około 0,5 GiB RAM. Przy wymianie rozkładu stary i nowy zestaw chwilowo współistnieją; warto pozostawić około 1 GiB zapasu pamięci. Błędy nie kasują ostatniego poprawnego zestawu; ponowienia są ograniczone czasowo.

### Weryfikacja szacunków — 15.10.2026

Próba LIVE zwróciła 664 szacunki; pierwsze pobranie wraz z przygotowaniem rozkładu trwało około 6 s, ponowne przeliczenie po 16 s około 0,32 s, odczyt z pamięci około 0,4 ms w bezpośrednim wywołaniu usługi. Proces z rozkładem i szacunkami zajmował około 545 MiB RAM. Wynik zależy od liczby kursów i danych dostawcy. Dodatkowa próba przez HTTP potwierdziła 661 szacunków i poprawne otwarcie trasy. W przeglądarce sprawdzono stałe oznaczenie „≈”, ostrzeżenie „nie GPS”, osobny wiek danych, przejście do trasy i powrót do pozycji.

Testy offline obejmują ruch po zakrzywionej geometrii, postój, powtarzające się miejsca na trasie, brak aktualizacji, błędne czasy i odległości, pozycje poza Polską, odwołania, objazdy, wygaśnięcie źródła, błędy pobrania, wymianę danych podczas obliczeń oraz limity cache. UI usuwa wygasłe znaczniki i blokuje spóźnione odpowiedzi po wyłączeniu lub błędzie źródła.
