# Analiza — samoloty, statki i porównanie tras

Rozszerzenie stanowiska analitycznego o obiekty ruchome. Korzysta z istniejących
źródeł adsb.fi i AISStream oraz lokalnego zapisu tras; nie tworzy drugiego kolektora.

## Katalog i karta

W **Analizie** wybierz typ **Samoloty** lub **Statki**. Wyszukiwanie obejmuje nazwę,
znak wywoławczy, rejestrację, ICAO, MMSI oraz dostępne IMO. Karta pokazuje dostępne
metadane źródłowe, aktualność pozycji i zapisane sesje obserwacji. Metadane są
bieżącym katalogiem — nie archiwum każdej dawnej nazwy lub rejestracji.

Tożsamości katalogowe mają postać `aircraft:icao:48abcd` i `ship:mmsi:261000001`.
Nie-ICAO adresy ADS-B oznaczone `~` pozostają w dotychczasowej warstwie Sytuacji;
nie trafiają do przestrzeni identyfikatorów ICAO w Analizie.

Zakres źródeł pozostaje taki sam: samoloty nad Polską, jednostki AIS na Bałtyku,
w cieśninach duńskich i Kattegacie. Filtr województwa może wykluczyć statki na morzu;
do ich przeglądania wyczyść ograniczenie województwa. Pozycje poza pokryciem źródła
nie oznaczają zakończenia rejsu, lądowania ani zatrzymania obiektu.

W przedziale filtr województwa korzysta z ostatniego zapisanego punktu tego obiektu
w wybranym okresie. W bieżącym katalogu korzysta z ostatniej znanej lokalizacji.
Przy więcej niż 1000 zlokalizowanych obiektów w wyniku zawierającym transport mapa
pokazuje ograniczony zestaw i informuje o limicie; tabela nadal stronicuje całość.

## Oznaczenia na mapie

Analiza używa tych samych ikon i kolorów co Sytuacja, zarówno dla pozycji bieżących,
jak i podczas odtwarzania: sylwetki samolotu oraz symbolu statku obróconego według
raportu kierunku. Samoloty z oznaczeniem wojskowym źródła są brązowe; pozostałe
ikony samolotów są granatowe. Statki mają kolory według deklarowanego typu AIS:
fioletowy dla kodu 35, morski dla typów cywilnych i szary dla nieustalonych.
Brak kodu 35 nie potwierdza cywilnej przynależności. Nieustalony kierunek statku
zachowuje okrągły symbol z głównej mapy.

Najechanie na ikonę pokazuje nazwę lub znak wywoławczy, klasyfikację i prędkość;
kliknięcie otwiera kartę obiektu. Obwódka zaznaczenia zachowuje kolor klasyfikacji.
Legenda **Samoloty i statki · oznaczenia na mapie** wyjaśnia symbole.

Paski na statku oznaczają raport starszy niż pięć minut. W historii wiek raportu
jest liczony względem kursora, a kierunek pochodzi z zapisanego punktu. Klasyfikacja,
nazwa i rejestracja pozostają metadanymi bieżącego katalogu; odtwarzanie nie
rekonstruuje ich dawnych wersji. Kolory linii tras i wykresów identyfikują obiekty
porównania niezależnie od kolorów ikon.

## Obserwowane i nagrywanie

Przypięcie obiektu do **obserwowanych** zapisuje wybór w SQLite. Lista przeżywa
odświeżenie strony i restart aplikacji. Filtr obserwowanych nadal uwzględnia
pozostałe filtry katalogu.

Nieobserwowane obiekty bez zachowanych sesji znikają z katalogu po siedmiu dniach
od ostatniego znanego raportu, przy kolejnym odczycie danego źródła. Zapisane na
liście obserwowanych tożsamości pozostają w katalogu również bez świeżej pozycji.

Obserwowanie i zapis trasy są niezależnymi działaniami. Dodanie do listy nie
rozpoczyna nagrywania. W karcie można jawnie rozpocząć lub zakończyć zapis przez
istniejący serwis tras. Zamknięcie karty, przejście do Sytuacji czy usunięcie z listy
obserwowanych nie zatrzymuje aktywnego zapisu.

Nadal obowiązuje limit 20 aktywnych sesji, siedmiodniowa retencja punktów oraz
wymóg działającej aplikacji i dostępu do źródła. Nie pobieramy wcześniejszej
historii dostawcy. Szczegóły: [trasy obserwacji](tracking.md).

## Porównywanie i wspólny czas

Dodaj do porównania od jednego do pięciu samolotów lub statków i ustaw przedział.
Możesz użyć ostatnich 24 godzin albo wybrać własny zakres. Na wspólnej osi czasu
przesuwaj kursor lub uruchom odtwarzanie. Mapa, tabela porównania i wartości w karcie
korzystają z tego samego czasu. Przycisk pokazania tras dopasowuje mapę; samo
odtwarzanie nie przejmuje kamery.

W trybie przedziału mapa i wartości przy kursorze przedstawiają obiekty dodane do
porównania. Pozostałe obiekty katalogu można dołączyć przyciskiem „Porównaj”.

Wykresy pokazują prędkość w km/h i dostępną wysokość samolotów w metrach. Każdy
obiekt ma własny kolor. Źródłowa prędkość statku w węzłach jest przeliczana na km/h
na potrzeby porównania. Brak wartości nie jest zerem.

Kursor wybiera ostatni rzeczywiście zapisany raport nie późniejszy niż wskazana
chwila i należący do przedziału `[od, do)`. Po 120 sekundach bez raportu samolotu
lub 900 sekundach dla statku pokazujemy lukę. Granice sesji, jawne przerwy i
niewiarygodne skoki zachowują rozdzielenie linii. Nie ma interpolowania pozycji
ani zastępowania brakujących punktów historycznych pozycją bieżącą.

Odczyt porównania jest dokładny i ograniczony do 12 000 zapisanych punktów na obiekt.
Po przekroczeniu limitu trzeba zawęzić przedział. Maksymalna szerokość zapytania
wynosi 14 dni, ale retencja samych tras nadal wynosi 7 dni. Wyświetlenie zakresu
nie oznacza pełnego pokrycia; dane istnieją tylko dla nagrywanych sesji.

Zapisane stanowisko przechowuje także identyfikatory obiektów porównania. Otwarcie
stanowiska nie uruchamia nagrywania i samo nie włącza dostawców.

## Aktualność i praca w tle

Aktywne typy samolotów/statków w bieżącej Analizie odczytują istniejące lokalne API
co 10 sekund. Ukrycie karty, opuszczenie Analizy lub przejście do przedziału
historycznego wycofuje to zapotrzebowanie. Aktywne zapisy tras nadal działają po
stronie serwera. Cache i połączenie AIS pozostają współdzielone ze Sytuacją.

Błąd dostawcy, wyłączenie i zniknięcie obiektu z odczytu nie usuwają jego historii
ani wpisu na liście obserwowanych. Aktualna mapa nie przypisuje mu fikcyjnej
pozycji. Ostatni znany raport jest oddzielony od aktualnej pozycji. Błąd lokalnego
zapisu katalogu jest widoczny jako problem utrwalania, odrębny od błędu źródła.

## Architektura

- Migracja `017_moving_workspace.sql` rozszerza typy katalogu, zachowując istniejące
  pomiary, czujniki, indeksy i relacje obszarów. Dodaje listę obserwowanych i stan
  źródeł transportowych.
- `moving_ingestion.py` przenosi zapis projekcji poza pętlę sieciową. Kolejka
  przechowuje najwyżej najnowszy oczekujący odczyt każdego z dwóch źródeł;
  nagrywanie punktów nadal należy do `TrackingService`.
- `workspace_moving.py` buduje katalog i karty z odczytów oraz istniejących tabel
  `object_tracks` / `object_track_points`. Zapytania Analizy nie odpytują dostawców.
- `workspace-motion.js` obsługuje wspólny czas, przerwy, porównanie i wykresy.
  Istniejący stan Analizy rozdziela otwartą kartę od listy porównywanych obiektów.

Historia alarmów Ukrainy, teczki analiz, graf powiązań i reguły powiadomień pozostają
osobnymi kolejnymi etapami.

[Raport weryfikacji i polecenia testów](analysis-moving-objects-verification.md).
