# Teczki analiz — v0.33.0

Teczka gromadzi materiał dotyczący jednego pytania lub tematu. W zakładce
**Analiza** otwórz **Teczki analiz**, utwórz teczkę i nadaj jej nazwę. Możesz
uzupełnić opis, przypinać obiekty, zapisywać notatki i zachowywać wybrane dane.
Teczki są lokalne, wspólne dla okien korzystających z tej samej bazy WICI.

## Obiekty, notatki i materiał

| Element | Co zachowuje | Co dzieje się po odświeżeniu źródła |
|---|---|---|
| Przypięty obiekt | Tożsamość i etykietę obiektu | Otwarcie prowadzi do bieżącej karty katalogu. |
| Notatka | Tekst użytkownika oraz czasy utworzenia i edycji | Pozostaje bez zmian; nie jest informacją od dostawcy danych. |
| Zapisany materiał | Kopię wybranych danych, kontekst czasu i pochodzenie | Zachowuje treść z chwili zapisu. |
| Zapisane stanowisko | Dotychczasowe filtry, układ, porównanie i kamerę | Ponownie odpytuje dane dostępne w lokalnym archiwum. |

Przypinanie obejmuje komunikaty, stacje IMGW i GIOŚ, obszary PRG, samoloty,
statki, regiony Ukrainy i epizody alarmów. Nie rozpoczyna rejestracji tras ani
alarmów i nie zmienia listy obserwowanych. Jeśli obiekt zniknie z katalogu,
przypięcie zachowuje jego identyfikator i nazwę oraz wskazuje niedostępność.
Zapisana wcześniej kopia materiału pozostaje czytelna.

Notatki można tworzyć, poprawiać i usuwać. Nazwy, opis oraz notatki są zwykłym
tekstem — znaczniki HTML nie są wykonywane. Edycja sprawdza rewizję: równoległa
zmiana w drugim oknie nie jest nadpisywana bez odczytania aktualnego stanu.

## Zapis wybranego materiału

Po wybraniu teczki i danych dostępne są trzy rodzaje zapisu:

1. **Karta obiektu** — dane wybranego obiektu, a dla komunikatu także wybrana
   wersja treści; dla stacji wybrany czujnik, parametr i pomiar przy kursorze.
2. **Historia obiektu** — dane z wybranego przedziału, wraz z jednostkami,
   rewizjami, jawnymi brakami wartości i czasami źródłowymi.
3. **Porównanie** — zapisane trasy wybranych samolotów/statków lub pasy alarmów
   wybranych regionów Ukrainy w danym przedziale.

Zapis odbywa się po stronie serwera z lokalnej bazy. Nie pobiera dodatkowych
danych od dostawców. Zmiana danych podczas pracy wymaga odświeżenia wyboru,
zanim powstanie kopia. Pusta historia oznacza brak zapisanych obserwacji;
nie jest dowodem braku ruchu lub alarmów. Zbyt obszerny materiał należy
ograniczyć do mniejszego przedziału — zapis nie pomija po cichu dalszych stron.

Wybrane obiekty muszą mieścić się w bieżącym zakresie katalogu. Jeżeli karta
została otwarta z przypięcia i jest poza zakresem albo część porównywanych
obiektów została odfiltrowana, włącz odpowiednie typy i popraw filtry przed
zapisem. Dzięki temu sprawdzana rewizja danych obejmuje cały wybór.

Otwarty materiał pokazuje zapisane dane, czas utworzenia kopii, zakres, kursor,
wybrany czujnik/parametr i pochodzenie. Zmiana filtrów lub kursora głównej
Analizy nie zmienia tej kopii. Szczegóły danych pozwalają sprawdzić także
informacje niewyświetlane w podstawowej karcie.

## Czas i trwałość

Czas wykonania kopii różni się od czasu pomiaru, raportu pozycji i publikacji.
Wszystkie są zachowywane zgodnie z istniejącą semantyką źródła. Wybrana strefa
prezentacji pozostaje częścią kontekstu; znormalizowane czasy i kontekst wyboru
zapisywane są w UTC. Oryginalne pola czasu źródła zachowują swój zapis, także
samą datę bez godziny. Przedział ma postać `[od, do)`, z wyłącznym końcem.

Kopia zachowuje aktualne metadane, lokalizację i dostępne geometrie katalogu:
współrzędne stacji/transportu i pobrane geometrie Ukrainy. Dla obszarów PRG
zachowuje identyfikatory obszarów, bez współrzędnych wielokątów. Zachowuje też
ograniczenia danych: luki rejestracji, niepewny koniec alarmu oraz rozdział
oficjalnego indeksu GIOŚ od stężeń substancji. Nie rekonstruuje historycznych
granic regionów ani dawnych metadanych samolotu. Nie archiwizuje kafelków mapy,
zewnętrznych stron ani plików PDF wskazanych odnośnikami.

Kopie materiału nie podlegają retencji pomiarów, tras i alarmów. Pozostają
w teczce aż do ich usunięcia albo usunięcia teczki. Usunięcie teczki usuwa
wyłącznie jej przypięcia, notatki i materiały; nie kasuje katalogu, historii
źródeł, obserwowanych ani zapisanych stanowisk. Teczki nie stanowią kopii
zapasowej całej bazy.

## Architektura

Addytywna migracja `019` dodaje osobne tabele teczek i ich zawartości.
Przypięcia oraz zapisane materiały nie mają kaskadowego powiązania z katalogiem,
więc czyszczenie historii źródłowej ich nie usuwa. Usługa `workspace_dossiers.py`
korzysta z istniejących odczytów katalogu, historii stacji, tras oraz alarmów
pod wspólną blokadą repozytorium.

Endpointy `/api/workspace/dossiers` obsługują teczki, ich przypięcia, notatki
i materiały. Mutacje korzystają z dotychczasowej ochrony CSRF/Origin. Klient
przekazuje selekcję, a serwer sam buduje kopię. Zapisany JSON ma wersję schematu,
czas utworzenia i skrót SHA-256; jego treści nie aktualizuje się przez API.
Skrót służy porównaniu treści kopii i nie jest podpisem dostawcy danych.

Limity lokalnej kolekcji to 100 teczek, po 500 przypięć i notatek oraz
100 materiałów w jednej teczce. Jedna kopia ma najwyżej 5 MiB; historia
obejmuje do 20 000 rekordów łącznie z oficjalnymi indeksami GIOŚ.
Porównanie obejmuje najwyżej pięć samolotów i statków łącznie oraz pięć
regionów Ukrainy. Limit 12 000 punktów dotyczy jednego obiektu we wszystkich
jego sesjach w wybranym przedziale. Przekroczenie limitu zwraca błąd bez
częściowego zapisu materiału.

Moduł `workspace-dossiers.js` obsługuje teczki i czytnik zapisanych materiałów.
Dotychczasowe moduły mapy, tabeli, osi czasu, obserwowanych i rejestracji
zachowują swoje zadania. [Raport weryfikacji](analysis-dossiers-verification.md).
