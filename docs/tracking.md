# Trasy obserwacji samolotów i statków

## Obsługa

1. Włącz warstwę **Samoloty** albo **Statki AIS**, kliknij obiekt i wybierz **Śledź trasę**.
2. Panel **Trasy obserwacji** pokazuje wybraną obserwację. Obiekt na mapie otrzymuje oznaczenie zaznaczenia, a linia pokazuje zapisane pozycje do wskazanego czasu.
3. Suwak pozwala wrócić do wcześniejszej chwili. Odtwarzanie i wybór prędkości ułatwiają przegląd kilku godzin. Tryb bieżący wraca do najnowszego raportu; dopisywanie nowych pozycji nie przesuwa ręcznie ustawionego czasu historii.
4. Lista obserwacji pozwala przełączać się między zapisanymi samolotami i statkami. Na mapie oglądasz trasę jednego wybranego obiektu; pozostałe aktywne obserwacje nadal są zapisywane.
5. **Zakończ zapis** kończy obserwację, zachowując historię. Ponowne rozpoczęcie śledzenia tego obiektu tworzy kolejną obserwację.
6. **Wyjdź ze śledzenia** kończy aktywny zapis wybranego obiektu, usuwa jego trasę i zaznaczenie z mapy oraz zwija panel. Historia pozostaje na liście. Po odświeżeniu strony podgląd nie otwiera się ponownie samoczynnie; można wrócić do niego przez wybór zapisanej obserwacji.

Historia tras jest niezależna od dnia publikacji i wybranego województwa. Zapisana trasa może wykraczać poza aktualnie wybrany region mapy.

## Kiedy trwa zapis

Wybranie „Śledź trasę” uruchamia zbieranie po stronie lokalnego serwera. Wyłączenie warstwy, przejście do Źródeł, ukrycie lub zamknięcie karty nie zatrzymuje zapisu. Proces WICI musi działać, komputer musi pozostać aktywny i mieć dostęp do źródła. Po restarcie WICI wznawia aktywne obserwacje z bazy SQLite.

Zamknięcie aplikacji, uśpienie komputera, brak internetu, brak raportów lub wyjście obiektu poza obsługiwany obszar powoduje przerwę. Nie ma pobierania wcześniejszej historii od dostawcy ani uzupełniania przerw. Pierwszy punkt to dostępny raport wybranego obiektu w chwili rozpoczęcia obserwacji; czas raportu może być wcześniejszy od kliknięcia.

Przechowywane są punkty z ostatnich **7 dni**. Zakończone obserwacje starsze niż 7 dni są usuwane. Limit wynosi **20 aktywnych obserwacji**. Historia znajduje się w `var/live/app.sqlite3` i jest objęta zwykłą kopią zapasową WICI. DEMO nie uruchamia zbierania rzeczywistych tras.

## Znaczenie trasy i czasu

- Samolot jest identyfikowany przez adres ICAO/hex, statek przez MMSI. Znak wywoławczy, nazwa i rejestracja są etykietami; ich zmiana nie rozdziela obserwacji.
- Kolektor sprawdza najnowsze dostępne raporty co około 10 sekund. Współdzieli cache samolotów i połączenie AIS z istniejącymi warstwami. Nie zapisuje wszystkich wiadomości dostawcy.
- Czas punktu pochodzi z raportu źródłowego. Powtórzone i starsze raporty nie dodają fikcyjnego ruchu ani nie odmładzają pozycji.
- Odtwarzanie pokazuje zapisane pozycje. Odcinki łączą kolejne raporty i nie odtwarzają dokładnych manewrów między pomiarami. Przerwy oraz niewiarygodne skoki pozycji rozdzielają linię na osobne fragmenty.
- Pozycja historyczna jest oznaczona inaczej niż pozycja bieżąca. Ostatni zapis może być nieaktualny; czas raportu i stan zbierania pozostają widoczne.
- Symbol samolotu zachowuje kolor z warstwy źródłowej: pomarańczowy dla oznaczonych jako wojskowe. Klasyfikacja jest zapisywana razem z obserwacją i pozostaje dostępna po ponownym otwarciu strony oraz przy odtwarzaniu; kolor ramki wskazuje tryb śledzenia.
- Symbol statku również zachowuje kolor swojej klasyfikacji AIS: fioletowy dla kodu 35, morski dla typów cywilnych i szary dla nieustalonych. Typ AIS jest zapisywany z obserwacją, więc te same kolory obowiązują podczas odtwarzania i po ponownym otwarciu strony. Brak kodu 35 nie potwierdza cywilnej przynależności jednostki.
- Pokrycie pozostaje takie jak w warstwach źródłowych: samoloty nad Polską, statki w obsługiwanym obszarze Bałtyku i cieśnin duńskich z Kattegatem. Brak raportu nie oznacza zatrzymania obiektu.

Samoloty: [adsb.fi](https://adsb.fi/), użytek osobisty i niekomercyjny. Statki: [AISStream](https://aisstream.io/), wymagany lokalny klucz. Dotychczasowe warunki dostawców pozostają w [dokumentacji źródeł](sources.md).

## Lokalny interfejs API

- `GET /api/tracks` — zapisane obserwacje i okres przechowywania.
- `POST /api/tracks` — rozpoczęcie obserwacji: `{"kind":"aircraft","object_id":"48abcd"}` albo `{"kind":"ship","object_id":"261000001"}`. Pozycje są odczytywane z serwisu WICI; klient nie przesyła współrzędnych do archiwum. Ponowne rozpoczęcie już aktywnej obserwacji zwraca ten sam zapis.
- `GET /api/tracks/{id}` — obserwacja i jej zapisane punkty w kolejności czasu.
- `POST /api/tracks/{id}/stop` — zakończenie zapisu bez usuwania historii.

Odczyty zachowują ochronę przed obcym pochodzeniem, a operacje zapisu wymagają istniejącego tokenu CSRF WICI. Migracja bazy dodaje tabele historii bez zmiany wcześniejszych danych.

Obserwacje utworzone przed zapisem klasyfikacji samolotu lub typu AIS statku początkowo mają ją nieznaną. Aktywne obserwacje uzupełniają ją przy kolejnym odczycie źródła; dawne zakończone trasy zachowują nieznaną klasyfikację.

## Weryfikacja

```sh
uv run --locked pytest -q tests/test_tracking.py tests/test_tracking_api.py
node --test tests/ui_tracking*.test.cjs
node --test tests/tracking_browser.cjs
```

Ostatnia komenda wymaga Playwright i Chromium; w razie potrzeby ustaw `NODE_PATH` na katalog z pakietem `playwright`. Test uruchamia własny serwer w tymczasowym katalogu, używa rzeczywistego API, SQLite i Leaflet oraz syntetycznych źródeł. Blokuje połączenia zewnętrzne i nie używa lokalnej konfiguracji ani kluczy.

Regresje obejmują zapis bez otwartej karty, wznowienie po restarcie, zachowanie historii po zakończeniu zapisu, trzygodzinną trasę z przerwą, przewijanie i tempo odtwarzania, niezmienność wybranego czasu podczas nowych odczytów, filtrowanie duplikatów, kolory samolotów i wszystkich trzech kategorii AIS, granice regionu, CSRF oraz telefon w motywie nocnym. Obrazy i raport z testu przeglądarki trafiają do ignorowanego katalogu `tmp/tracking-evidence/`.
