# Odtwarzanie lotu i radaru w 3D

W zwykłym trybie WICI wybierz samolot na mapie albo podaj adres ICAO.

- **Z mapy**. Włącz **Sytuacja → Warstwy → Lotnictwo → Samoloty**, kliknij ikonę i wybierz **Odtwórz ostatni odcinek w 3D**. To samo działanie jest dostępne w karcie bieżącej pozycji samolotu w **Analizie**. WICI użyje adresu ICAO i dostępnego znaku wywoławczego tego lotu.
- **Po ICAO**. W **Warstwy → Lotnictwo** wpisz sześć znaków 0–9 lub A–F i wybierz **Przygotuj odcinek 3D**. Wyszukiwanie obejmuje ostatni dostępny odcinek tej maszyny nad Polską, również po jej zniknięciu z mapy. Wielkość liter jest dowolna. Numer z biletu i rejestracja samolotu to inne identyfikatory.

WICI pobiera historię ADS-B i dopasowuje do niej obrazy RainViewer z ostatnich około dwóch godzin. Ostatnia dostępna pozycja z pasującym radarem może być wcześniejsza niż pozycja widoczna teraz na mapie. Do otwarcia odcinka potrzeba co najmniej pięciu minut pozycji z wysokością oraz dwóch różnych klatek radaru z tego okresu. Przy braku historii wybierz **Zbieraj od teraz**. Serwer będzie zapisywał nowe pozycje tego samolotu z adsb.fi i pasujące obrazy radaru. Możesz zamknąć panel lub kartę w przeglądarce. Proces WICI i połączenie ze źródłami muszą działać, aby przybywały próbki. Po restarcie aplikacji zbieranie może zostać wznowione w czasie ważności sesji.

W otwartym panelu widać liczbę pozycji i klatek. Po zebraniu pierwszego pełnego odcinka zapis się kończy i otwiera się odtwarzacz. Do zamkniętego panelu wrócisz przez **Sprawdź stan** w Lotnictwie lub ponowny wybór tego samego samolotu. WICI może zbierać cztery maszyny jednocześnie. Czeka do 10 minut na pierwszą użyteczną pozycję i do 30 minut łącznie na odcinek z radarem. Przy niedostępności źródła możesz ponowić próbę, a jeżeli masz już zapis dla tego wyboru, otworzyć go z podaną datą. W konfiguracji WICI muszą być włączone źródła `aircraft` i `radar`. Do wyszukiwania po ICAO możesz pozostawić warstwy mapy wyłączone.

Wynik dla każdej maszyny znajduje się osobno w `var/live/flight-replay/aircraft/<icao>/`. Przycisk **Otwórz zapisany lot z radarem w 3D** nadal otwiera zapis przygotowany wcześniej w `var/live/flight-replay/`. Po przygotowaniu odcinka samo odtwarzanie działa lokalnie.

## Sterowanie

- **Cała trasa** pokazuje geometrię przelotu i położenie względem opadów. **Podążaj** przenosi kamerę za samolot. Zmiana widoku zachowuje czas odtworzenia.
- **Suwak** pozwala przejść do konkretnej sekundy, również do momentu sprzed zmiany klatki radaru. Linia nad suwakiem pokazuje profil wysokości, a bursztynowe kreski oznaczają chwile zmiany obrazu radaru. Licznik przy przycisku odtwarzania podaje czas od początku i długość zapisu. **Odtwórz** uruchamia przebieg z wybraną prędkością. Użyj **Pauza**, żeby przyjrzeć się ustawieniu samolotu i opadów.
- **Czas lotu i czas radaru** mają różne znaczenia. Pozycja pomiędzy sąsiednimi raportami jest interpolowana, z przerwą przy odstępie większym niż 120 sekund. Dla kursora czasu wybierana jest ostatnia wcześniejsza lub równoczesna klatka. Klatka starsza niż 15 minut jest oznaczana jako niedostępna.
- Kamera pokazuje model samolotu na podstawie zapisanych współrzędnych i wysokości. W historii adsb.lol wysokość jest geometryczna. W opcji „Zbieraj od teraz” wysokość jest barometryczna według adsb.fi. Kurs opisuje ruch nad ziemią. Nachylenie i przechylenie prawdziwego samolotu pozostają nieznane.
- Lasy, pola, rzeki i zabudowę pod trasą pokazuje lokalna mozaika satelitarna Polski z 2021 r. Czas wyświetlany na osi odnosi się do odtwarzanego lotu, a przy radarze widać godzinę wybranej klatki w UTC.
- Radar pokazuje odbiciowość na mapie pod samolotem. Czas klatki odnosi się do wygenerowania kompozytu. Przezroczysty obszar może oznaczać brak echa lub brak pokrycia. Na podstawie obrazu nie można przypisać opadów do konkretnej wysokości ani określić przyczyny manewru.

## Ręczne przygotowanie lub przeniesienie zapisu

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

Funkcja **Śledź trasę** zapisuje oddzielne obserwacje w lokalnej bazie WICI od chwili rozpoczęcia śledzenia. Skrypt do odtwarzania z radarem dobiera starsze punkty z historii dostawcy, także dla lotu, którego użytkownik wcześniej nie śledził.

Źródła i warunki wykorzystania opisano w [wykazie dostawców](../THIRD_PARTY_NOTICES.md#lokalne-nagranie-lotu-i-radaru). Dla oznaczeń czasowych radaru obowiązuje [opis kompozytów RainViewer](https://www.rainviewer.com/api/weather-maps-api.html).
