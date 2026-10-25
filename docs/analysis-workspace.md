# Stanowisko analityczne — etap 1

Zakładka **Analiza** otwiera katalog obiektów, tabelę, mapę i oś czasu. Korzysta z tej samej mapy Leaflet i tej samej lokalnej bazy co widok Sytuacja. Szczegółowy projekt: [plan etapu 1](plan-stanowisko-analityczne-etap-1.md).

Kolejne rozszerzenie dodaje [samoloty, statki, obserwowane i wspólne odtwarzanie tras](analysis-moving-objects.md). Poniższy opis czasu stacji i pomiarów dotyczy nadal pierwszego etapu; zasady czasu obiektów ruchomych opisano osobno.

Wersja 0.32.0 dodaje [historię alarmów Ukrainy i porównanie regionów](ukraine.md#analiza-historia-alarmów-i-porównanie-regionów-v0320): katalog regionów i epizodów, obserwowane regiony oraz wspólny kursor mapy, tabeli i pasów alarmów. Formularz i prezentację czasu można przełączyć między Warszawą, Kijowem i UTC; zapis pozostaje w UTC.

Wersja 0.33.0 dodaje [teczki analiz](analysis-dossiers.md): notatki, przypięte obiekty i niezmienne kopie wybranego materiału, które pozostają dostępne po upływie retencji historii źródłowej.

## Praca z katalogiem

1. Wybierz typy: komunikaty czterech oficjalnych źródeł, wodowskazy IMGW, stacje jakości powietrza GIOŚ lub obszary PRG. Możesz połączyć kilka typów.
2. Zawęź nazwę lub identyfikator, źródło i województwo. Wyszukiwanie obsługuje polskie znaki także w zapisie bez znaków diakrytycznych. Powiat jest obiektem katalogu; zakres danych w tym etapie obejmuje kraj albo województwo.
3. Kliknij wiersz lub punkt mapy. Wspólny wybór otworzy kartę z identyfikatorem, danymi, pochodzeniem i historią. Dla nakładających się obszarów wybierz obiekt z listy w dymku.
4. Przycisk **Pokaż na mapie** dopasowuje kamerę. Odświeżenia danych i przesuwanie kursora czasu zachowują położenie mapy.

Tabela stronicuje wynik; mapa przedstawia cały wynik zapytania. Przy ponad 1000 obiektów z geometrią przechodzi do grup według typu i województwa. Wybór grupy zawęża katalog. Rekord bez geometrii nadal jest dostępny w tabeli i karcie; nie otrzymuje umownego punktu. Zliczenia histogramu oznaczają zdarzenia/pomiary, a tabeli — obiekty.

Na małym ekranie użyj przełącznika **Tabela / Mapa**. W „Zakres i układ” zmienisz szerokość tabeli, widoczne kolumny i uwzględnianie rekordów bez geometrii lub pomiarów. Motywy dzienny i nocny są wspólne z resztą aplikacji. Escape zamyka kartę i przywraca fokus do wyboru obiektu.

## Znaczenie czasu

**Bieżące** pokazuje dzisiejsze publikacje/aktualizacje oraz rozpoznane obowiązujące lub zapowiedziane ostrzeżenia IMGW i obecnie udostępniane komunikaty RSO. Dla stacji pokazuje ostatnie zapisane pomiary wraz z ich aktualnością. Okno udostępniania RSO nie oznacza czasu trwania zagrożenia.

**Przedział** ogranicza publikacje/aktualizacje, opcjonalnie przecinające go okresy ważności/udostępniania i pomiary stacji. Formularz czasu domyślnie używa Warszawy; koniec jest wyłączny (`[od, do)`). Dni zmiany czasu mogą mieć 23 lub 25 godzin. Nieistniejąca godzina jest odrzucana, a powtórzona jesienna godzina wybiera wcześniejsze wystąpienie. Obszary administracyjne są bezczasowe i nie wytwarzają zdarzeń histogramu.

Kliknięcie koszyka histogramu zawęża przedział, zachowując szersze tło osi. Kursor dotyczy **wybranej stacji**: jej karty, wybranego wiersza i wyróżnionego punktu. Pozostałe stacje nadal przedstawiają przegląd okresu. Wartość przy kursorze to ostatnia zapisana próbka nie późniejsza od kursora i mieszcząca się w przedziale. Brak próbki jest jawnym brakiem danych. Przy stronicowanej historii należy najpierw doczytać jej strony, aby kursor miał pełny zestaw próbek.

Ręczny przedział i kursor pozostają na miejscu podczas odświeżania. Do bieżącego zakresu wrócisz przyciskiem **Bieżące**. Aktualna treść komunikatu i metadane/geometria stacji pozostają aktualnym katalogiem; archiwum wersji pozwala otworzyć dawną treść komunikatu. Ten etap nie rekonstruuje historycznego stanu całej mapy.

## Historia i źródła

Historia stacji powstaje z rzeczywistych odczytów IMGW/GIOŚ na żądanie i jest przechowywana przez 14 dni. Czyszczenie działa przy starcie oraz co godzinę, więc fizyczne usunięcie starego rekordu może nastąpić do godziny po granicy retencji. Samo przeszukiwanie lokalnego katalogu nie odpytuje dostawców. Aktywacja typu stacji wczytuje metadane; w trybie bieżącym aktywni odbiorcy współdzielą odczyty i cache z Atlasem. Ukrycie karty przeglądarki wstrzymuje nowe pobrania. Indeksy GIOŚ zachowują limit dwóch równoległych odczytów i co najmniej 600 ms pomiędzy startami. Wyniki dla czujnika są pobierane po jego wyborze i odświeżane według TTL; w historii można użyć przycisku pobrania dostępnych danych źródłowych.

Korekty pomiarów zachowują osobne rewizje, także przy zmianie A → B → A. `null` oznacza brak pomiaru, nigdy zero. Czas obserwacji, czas pobrania i surowy czas źródła mają odrębne znaczenie. Nieznany lub zbyt odległy przyszły czas jest oznaczany i nie tworzy poprawnego szeregu czasowego. Niepełny odczyt nie usuwa wcześniej znanych stacji. Błąd zapisu historii jest widoczny; Analiza korzysta z danych zapisanych w bazie.

Próg wodowskazu w historii jest progiem zapisanym razem z obserwacją. Oficjalny indeks GIOŚ jest odrębny od stężenia wybranej substancji. Czujniki tej samej substancji na jednej stacji mają osobne identyfikatory i przebiegi.

Demo zawiera wyraźnie oznaczone syntetyczne stacje, lukę i dwa czujniki PM10. Nie wykonuje odczytów sieciowych. Warstwy Sytuacji zachowują swoje checkboxy podczas przełączenia na Analizę; aktywne zapisy tras nie są kończone. Samoloty i statki są dostępne także jako typy katalogu Analizy, natomiast pozostałe warstwy i rastry pozostają w **Sytuacji**.

## Zapisane stanowiska

„Zapisane stanowiska” zapisują nazwę, filtry, sortowanie, kolumny, układ, kamerę i opcjonalny wybrany obiekt. Zakres można zapisać jako bezwzględny albo względny wobec czasu otwarcia. Dane pomiarowe pozostają w swoim archiwum; konfiguracja nie jest kopią danych.

Otwarcie stanowiska przywraca jego region i kamerę. Samo przywrócenie wybranego obiektu nie włącza dodatkowych dostawców. Aktualizacja sprawdza rewizję konfiguracji; po równoczesnej zmianie w innym oknie trzeba wczytać nową wersję. Automatyczne zapamiętanie układu w przeglądarce jest oddzielne od nazwanych konfiguracji w SQLite.

## Architektura i kontrola

- `workspace_repository.py` utrzymuje projekcję katalogu przy zapisie dokumentu oraz idempotentne uzupełnienie przy starcie. Oryginalne dokumenty i wersje pozostają źródłem treści.
- `station_history.py` zapisuje znormalizowane odpowiedzi przez ograniczoną kolejkę i wspólną blokadę/połączenie SQLite.
- `workspace_service.py` przygotowuje spójne wyniki, paginację, histogram, karty, historię i konfiguracje. Rewizja danych i zamrożony zegar zapytania chronią przed mieszaniem stron po zmianie danych.
- `workspace_api.py` udostępnia `/api/workspace/query`, `/objects/{ref}`, `/objects/{ref}/timeline`, `/status` i `/views`. Dotychczasowe API zachowano. Mutacje i POST odczytowy wymagają istniejącej ochrony CSRF/Origin.
- Moduły `workspace-*.js` rozdzielają stan, zapytania, prezentację i wspólne pobieranie źródeł. Stan zamiaru użytkownika nie zawiera uchwytów mapy ani zapytań sieciowych.

Migracje 015 i 016 są addytywne. Model tabel: [data-model.md](data-model.md). Polecenia regresji i wyniki wydajności: [raport etapu 1](analysis-workspace-verification.md).
