# Odtwarzanie lotu i radaru w 3D

W zwykłym trybie WICI otwórz **Sytuacja → Warstwy → Lotnictwo → Odtwórz lot z radarem w 3D**. Możesz otworzyć zapis przy wyłączonej warstwie bieżących pozycji samolotów. Odtwarzacz czyta jeden lokalny epizod z katalogu `var/live/flight-replay/`. Po pobraniu epizodu pozycje, obrazy radarowe i scena odtwarzacza są dostępne lokalnie. Pozostałe funkcje aplikacji live mają własne źródła i harmonogramy.

- **Cała trasa** pokazuje geometrię przelotu i położenie względem opadów. **Podążaj** przenosi kamerę za samolot. Zmiana widoku zachowuje czas odtworzenia.
- **Suwak** pozwala przejść do konkretnej sekundy, również do momentu sprzed zmiany klatki radaru. Linia nad suwakiem pokazuje profil wysokości, a bursztynowe kreski oznaczają chwile zmiany obrazu radaru. Licznik przy przycisku odtwarzania podaje czas od początku i długość zapisu. **Odtwórz** uruchamia przebieg z wybraną prędkością. Użyj **Pauza**, żeby przyjrzeć się ustawieniu samolotu i opadów.
- **Czas lotu i czas radaru** mają różne znaczenia. Pozycja pomiędzy sąsiednimi raportami jest interpolowana, z przerwą przy odstępie większym niż 120 sekund. Dla kursora czasu wybierana jest ostatnia wcześniejsza lub równoczesna klatka. Klatka starsza niż 15 minut jest oznaczana jako niedostępna.
- Kamera pokazuje model samolotu na podstawie zapisanych współrzędnych i wysokości. W zapisie z adsb.lol wysokość jest geometryczna, a kierunek odpowiada ruchowi nad ziemią. Nachylenie i przechylenie prawdziwego samolotu pozostają nieznane.
- Lasy, pola, rzeki i zabudowę pod trasą pokazuje lokalna mozaika satelitarna Polski z 2021 r. Czas wyświetlany na osi odnosi się do odtwarzanego lotu, a przy radarze widać godzinę wybranej klatki w UTC.
- Radar pokazuje odbiciowość na mapie pod samolotem. Czas klatki odnosi się do wygenerowania kompozytu. Przezroczysty obszar może oznaczać brak echa lub brak pokrycia. Na podstawie obrazu nie można przypisać opadów do konkretnej wysokości ani określić przyczyny manewru.

## Przygotowanie lub przeniesienie zapisu

W katalogu projektu wykonaj:

```sh
uv run --locked python scripts/capture_flight_replay.py
```

Skrypt dobiera kandydatów na podstawie bieżących pozycji nad Polską i szuka odcinka ze śladem adsb.lol, dostępną wysokością i co najmniej dwiema klatkami RainViewer. Poszukiwanie jest ograniczone do bieżącego okna historii radarowej. Dostępność zależy od źródeł i ruchu w chwili uruchomienia. Znany identyfikator samolotu możesz przekazać przez `--icao`, a znak wywoławczy przez `--callsign`. Pełny opis parametrów podaje `--help`.

Adres ICAO identyfikuje maszynę, która może w ciągu dnia wykonać kilka lotów. Skrypt pobiera jej historię pozycji z adsb.lol i rozdziela raporty m.in. przy zmianie znaku wywoławczego, lądowaniu lub przerwie ponad dwie minuty. Długość odtworzenia wynika z czasu pierwszego i ostatniego punktu odcinka nad Polską, dla którego są dostępne dane radarowe.

Do skopiowania gotowego zapisu wystarczą `episode.json` i podkatalog `tiles/` z tego samego epizodu. Import przeprowadza walidację i działa offline:

```sh
uv run --locked python scripts/capture_flight_replay.py --import-episode /sciezka/do/katalogu-nagrania
```

Poprawny zapis staje się bieżącym epizodem dopiero po przygotowaniu kafelków. Przy błędzie poprzedni epizod pozostaje dostępny. Po zmianie epizodu zamknij i otwórz odtwarzacz. Do powrotu do konkretnego nagrania zachowaj kopię jego katalogu. Kopia repozytorium Git zawiera kod odtwarzacza i skrypt przygotowania danych. Katalog `var/` jest lokalny. Tryb demonstracyjny WICI izoluje dane użytkownika.

Ta wersja obsługuje jeden przygotowany epizod. Funkcja **Śledź trasę** zapisuje oddzielne obserwacje w lokalnej bazie WICI od chwili rozpoczęcia śledzenia. Skrypt do odtwarzania z radarem dobiera starsze punkty z historii dostawcy, także dla lotu, którego użytkownik wcześniej nie śledził.

Źródła i warunki wykorzystania opisano w [wykazie dostawców](../THIRD_PARTY_NOTICES.md#lokalne-nagranie-lotu-i-radaru). Dla oznaczeń czasowych radaru obowiązuje [opis kompozytów RainViewer](https://www.rainviewer.com/api/weather-maps-api.html).
