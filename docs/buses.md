# Autobusy miejskie

Bieżąca warstwa mapy obejmuje Szczecin, Kraków, Poznań i Warszawę. Wybór miasta i linii działa niezależnie od daty publikacji oraz województwa. Dane są pobierane dopiero dla aktywnego miasta na widocznej mapie, bez historii pozycji, plików obserwacji i zapisów do SQLite. Wyłączenie warstwy, przejście do Źródeł albo ukrycie karty zatrzymuje pobieranie z przeglądarki. Trwający odczyt backendu może dokończyć napełnianie współdzielonego cache. DEMO nie kontaktuje się z dostawcami.

## Obsługa

Włącz „Warstwy mapy → Komunikacja miejska → Autobusy miejskie”, wybierz miasto i użyj „Pokaż…” aby dopasować mapę. Wybór miasta usuwa poprzednie znaczniki, resetuje filtr linii i unieważnia oczekujące odpowiedzi. Numer linii na znaczniku otwiera szczegóły. Otwarte okienko zachowuje przewinięcie podczas aktualizacji. Pokrycie obejmuje dostępne w danym źródle pojazdy, również podmiejskie; brak znacznika nie dowodzi braku pojazdu.

Wiek wynika z czasu pozycji u dostawcy. Znaczniki starsze niż 60 sekund lub dane po błędzie odświeżania są szare, a starsze niż 120 sekund znikają także przy awarii. Czasy w interfejsie odnoszą się do bieżących danych. Nie odtwarzamy archiwalnego ruchu. Filtr linii zachowuje wybraną linię podczas odświeżania jednego miasta, także gdy chwilowo nie ma jej pojazdów.

Przycisk **„Podążaj w 3D”** w szczegółach pozycji do 60 s uruchamia kamerę zewnętrzną lub pierwszą osobę. Widok współdzieli lokalny silnik i obsługę powrotu do Atlasu z samolotami, korzystając z istniejącego odczytu autobusów. Bufor maksymalnie 32 raportów wybranego pojazdu istnieje tylko w pamięci otwartego widoku. Kierunek kamery może być szacowany z pozycji, ale brakująca prędkość nadal pozostaje nieznana. [Instrukcja, aktualność, źródła kierunku i ograniczenia powierzchni](buses3d.md).

## Źródła i znaczenie danych

| Miasto | Źródło | Szczegóły |
|---|---|---|
| Szczecin | [ZDiTM API v2](https://www.zditm.szczecin.pl/pl/zditm/dla-programistow/api-pojazdy) | JSON, linia, pojazd, kierunek kursu, operator, model, prędkość, opóźnienie i dostępne przystanki. CC0 1.0. |
| Kraków | [ZTP GTFS / GTFS-RT](https://gtfs.ztp.krakow.pl/) | Zestawy autobusowe A (MPK) i M (Mobilis), bez zestawu tramwajowego T. Kierunki i nazwy z rozkładu, prędkość z GPS przeliczana z m/s na km/h. Identyfikatory operatorów mają osobne przestrzenie. |
| Poznań | [ZTM GTFS-RT](https://www.ztm.poznan.pl/otwarte-dane/gtfs-rt/) i [GTFS](https://www.ztm.poznan.pl/otwarte-dane/gtfsfiles/) | Strumień zawiera także tramwaje; WICI wybiera tylko linie autobusowe na podstawie rozkładu. W obecnym odczycie brak prędkości i namiaru. |
| Warszawa | [Nowy portal danych miasta](https://dane.um.warszawa.pl/pl/datasets/f319f602-7292-4e8c-b3d1-f5898aa9a638) | Pozycje, numer linii i pojazdu, czas GPS. Źródło nie dostarcza w tym odczycie modeli, kierunków docelowych, prędkości ani opóźnień; pola pozostają puste. |

GTFS-RT: pozycje pochodzą z `VehiclePositions`, a opcjonalne opóźnienie z odpowiadającego przystanku w `TripUpdates`, przy dopasowaniu kursu i świeżych danych. Nie jest to gwarancja bieżącego opóźnienia całego przejazdu. Przystanek obecny (`STOPPED_AT`) nie jest podpisywany jako następny. Brak informacji oznacza „Brak danych”, nie punktualność. WICI nie oblicza prędkości z kolejnych pozycji i nie przewiduje przyjazdów.

Statyczne GTFS przechowujemy w pamięci do sześciu godzin: tylko indeksy linii, kursów, nazw przystanków i operatorów. Nie wczytujemy geometrii ani pełnego `stop_times`. Pobieranie archiwów, rozpakowanie tabel i liczba rekordów mają ograniczenia. Przy błędzie odświeżenia indeksu może być użyta poprzednia wersja z ostrzeżeniem. Awaria jednego operatora Krakowa nie usuwa poprawnych danych drugiego; stan częściowej awarii jest jawny.

Dla Poznania wskazujemy źródło, aktualność i przetworzenie zgodnie z [zasadami ZTM](https://www.ztm.poznan.pl/otwarte-dane/dla-deweloperow/). Publicznego dostępu pozostałych źródeł nie opisujemy jako licencji CC0; odnośniki do dostawców pozostają w panelu i na mapie.

## Warszawa i klucz

Integracja używa nowego portalu: `POST https://dane.um.warszawa.pl/api/action/get_ztm_lokalizacja_pojazdow` z JSON `{"type":1}`. To operacja odczytu. JWT jest przekazywany wyłącznie w nagłówku `Authorization` przez backend. Nie trafia do URL, odpowiedzi lokalnego API, interfejsu ani wiadomości błędów. Obsługiwane są rzeczywista odpowiedź w postaci tablicy oraz dokumentowana otoczka `result`.

Klucz z [formularza nowego portalu](https://dane.um.warszawa.pl/pl/key-api) wpisz do pomijanego przez Git `config.local.toml`:

```toml
[sources.buses_warsaw]
enabled = true
api_key = "TWOJ_KLUCZ"
```

Po zmianie wymagany jest restart. Brak klucza blokuje tylko Warszawę. Czas GPS bez strefy traktujemy jako Europe/Warsaw, z uwzględnieniem zmiany czasu. Niejednoznaczne lub nieistniejące godziny podczas zmiany czasu są pomijane zamiast zgadywania.

## API i weryfikacja

`GET /api/buses?city=szczecin|krakow|poznan|warszawa`; brak parametru zachowuje dotychczasowy Szczecin, nieznane miasto daje 422. Każdy dostawca ma własny cache, blokadę współbieżnych odczytów i obsługę błędów/limitów. Dostępne pola pojazdów są normalizowane do wspólnego kontraktu. Globalny `[sources.buses] enabled = false` wyłącza wszystko; osobne sekcje opisano w `config.example.toml`.

Testy offline: `tests/test_buses.py`, `tests/test_buses_gtfs.py`, `tests/test_buses_warsaw.py`, `tests/test_buses_api.py`, `tests/buses_ui.cjs`. Obejmują selekcję autobusów, źródłowy czas, brak klucza, sekrety, błędy i limity, rozkłady i protobuf, przełączanie miast oraz spóźnione odpowiedzi i zachowanie przewinięcia szczegółów.
