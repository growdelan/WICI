# Weryfikacja v0.34.0 — relacje i graf

Data: 25.10.2026. Branch: `codex/wici-analysis-relations-v0340`.

## Testy automatyczne

| Zakres | Wynik |
|---|---|
| `uv run --locked pytest -q` | 1044 zaliczone; 3 ostrzeżenia bibliotek Starlette/Rasterio. |
| `node --test tests/*.test.cjs tests/*_ui.cjs` | 373 zaliczone. |
| Dotychczasowe scenariusze Chromium | 30 zaliczonych: Analiza, transport, Ukraina, teczki, tracking, widok 3D, GIOŚ i hydrologia. |
| Powtórka po końcowych poprawkach UI | 16 zaliczonych: Analiza, transport, Ukraina i teczki. |
| Nowe scenariusze Chromium grafu | 19 zaliczonych, w tym 9 regresji po sześciu niezależnych review; rzeczywiste lokalne API i SQLite oraz syntetyczne źródła. |
| Kontrole statyczne | Ruff, składnia zmienionych modułów JS, zgodność lockfile i brak błędów whitespace. |

Scenariusze przeglądarkowe korzystają z tymczasowych baz i portów oraz
blokują zewnętrzne żądania. Nie sterują pulpitem użytkownika.

Nowe testy backendu obejmują wszystkie osiem rodzajów obiektów, pochodzenie
relacji, rolę obszaru i konkretną wersję komunikatu, świeżość pozycji,
rzeczywiste luki tras, hierarchię i niepewność alarmów Ukrainy, stronicowanie,
rewizje niezależne od filtrów katalogu oraz ograniczenia rozmiaru.

Testy teczek sprawdzają symetrię relacji, obowiązkowe uzasadnienie, izolację
dowodów między teczkami, konflikty edycji, usunięcie i audyt historycznej
treści notatki. Sprawdzają również brakujące obiekty, zapis układu, kopię
odtwarzaną przez serwer, limit 5 MiB, zachowanie po retencji i restarcie oraz
ochronę CSRF/Origin. Migracja 019 → 020 zachowuje dokładne bajty i SHA-256
starych materiałów oraz blokadę ich aktualizacji.

Przegląd integracji doprowadził do poprawek z regresjami: rozwijanie kolejnych
stron sąsiadów, wybór historycznej wersji komunikatu wraz z jej geometrią,
ponowny zapis wczytanego układu i konflikt drugiego okna, sortowanie tabeli
grafu, pomiary wielu stacji na mapie przy wspólnym kursorze, odrzucanie
spóźnionych odpowiedzi oraz odtwarzanie i zamrożenie strefy czasowej.
Końcowa kontrola obrazu wykryła również zwężanie ikon węzłów po wyróżnieniu
ścieżki. Rozdzielono style węzłów i krawędzi oraz dodano regresję dla obu motywów.

## Poprawki po niezależnym review

Naprawiono trzy potwierdzone błędy P2:

- Wczytanie roboczego układu jest powiązane z tokenem nawigacji teczki.
  Zamknięcie i ponowne otwarcie tej samej teczki unieważnia poprzedni odczyt;
  jego sukces ani błąd nie przejmuje nowego dialogu.
- „Pokaż na mapie” przełącza również desktopowy tryb stanowiska na mapę
  i aktualizuje rozmiar Leaflet po odsłonięciu panelu.
- Filtrowanie węzłów zachowuje selektor i czas `as_of`. Renderer ponownie
  oznacza starsze niż pięć minut raporty statków względem kursora lub czasu
  odczytu grafu.

Trzy nowe scenariusze Chromium sprawdzają rzeczywiste przepływy UI:
spóźnioną odpowiedź sukcesu i błędu, zachowanie szkicu i fokusu po ponownym
otwarciu teczki oraz poprawne późniejsze wczytanie; widoczność i rozmiar mapy;
symbol faktycznego węzła Cytoscape dla starego i świeżego raportu, także
w przedziale czasu, po filtrowaniu typu i ukrywaniu węzłów.
W odizolowanej kopii źródeł cofnięto wyłącznie te trzy poprawki: wszystkie
trzy nowe scenariusze wtedy zawiodły. Z poprawkami wszystkie trzy przechodzą.

Po poprawkach ponowiono pełny zestaw: 1044 testy Pythona i 372 JavaScript
przeszły. Szerokie równoległe uruchomienie Chromium zakończyło się wynikiem
41/43: dwa wcześniejsze scenariusze (przypinanie do teczki i odtwarzanie tras)
przekroczyły 15-sekundowy limit oczekiwania. Powtórzono oba całe zestawy
sekwencyjnie, bez równoległego obciążenia testami WebGL: 10/10 przeszło,
w tym oba wcześniejsze timeouty. Łącznie wszystkie 43 różne scenariusze
przeszły; wynik szerokiego uruchomienia i powtórki opisano oddzielnie,
ponieważ nie był to jeden bezbłędny przebieg równoległy.

### Poprawki po drugim niezależnym review

- Przerwanie odświeżenia oznacza zachowany wynik jako wymagający ponownego
  odczytu. Powrót do grafu pobiera bieżący kontekst, również gdy stary wynik
  nadal istnieje. Do zakończenia odczytu dane grafu i możliwość zapisania
  kopii pozostają niedostępne.
- Wcześniejsza odpowiedź 404 nie blokuje jawnego wczytania układu. Jeśli inne
  okno utworzy pierwszy układ, zapis z rewizją 0 nadal poprawnie kończy się
  konfliktem; użytkownik może następnie jawnie wczytać cudzy zapis, zachowując
  własne pozycje do chwili tego wyboru. Kolejny zapis używa odczytanej rewizji.

Dodane dwa scenariusze Chromium sprawdzają anulowanie żądania i anulowanie
odświeżenia jeszcze przed wysłaniem żądania, przejście kursora z dostępnej
pozycji do rzeczywistej luki, blokadę zapisu starej kopii, ponowny odczyt oraz
konflikt pierwszego zapisu po lokalnym 404 z zachowaniem obu układów.
Oba przechodzą z poprawkami, a w odizolowanej kopii kodu po usunięciu tylko
tych dwóch poprawek oba zawodzą.

Końcowy przebieg po drugiej rundzie poprawek: **1044 testy Pythona,
372 JavaScript oraz 31 scenariuszy Chromium przeszło**. Chromium uruchomiono
sekwencyjnie: cały graf (15), dotychczasowa Analiza (3), transport (5),
Ukraina (3) i teczki (5). Ten przebieg nie zawierał timeoutów ani błędów.
Ruff, składnia JS, kontrola whitespace oraz budowa pakietu również poprawne.

### Odświeżenie po mutacji przy ukrytym grafie

Po trzecim review poprawiono wspólną ścieżkę odświeżania: żądanie odświeżenia
oznacza graf jako wymagający ponownego odczytu także wtedy, gdy panel jest
ukryty. Stary wynik nie jest udostępniany jako bieżący ani do zapisu kopii.
Po powrocie zapytanie odczytuje aktualne relacje, zachowując pozycje węzłów.

Nowy scenariusz Chromium usuwa relację z teczki podczas widoku mapy.
Sprawdza brak pobierania grafu w tle, blokadę zapisu kopii, zachowanie układu,
dokładnie jeden odczyt po powrocie i zniknięcie usuniętej krawędzi.
Test przechodzi z poprawką; w odizolowanej kopii kodu po cofnięciu wyłącznie
tej poprawki zawodzi na udostępnieniu starego wyniku do zapisania.

Po poprawce ponowiono pełny zestaw Pythona (**1044 zaliczone**, trzy znane
ostrzeżenia bibliotek), JavaScript (**372 zaliczone**) i sekwencyjną regresję
Chromium (**32/32**, bez timeoutów): graf (16), Analiza (3), transport (5),
Ukraina (3) i teczki (5). Ruff, składnia JS i kontrola whitespace poprawne.

### Zmiana teczki podczas pierwszego odczytu

Zmiana teczki uruchamia odświeżenie także przed otrzymaniem pierwszego
wyniku grafu. Dla widocznego grafu unieważnia wcześniejszą generację żądania
i pobiera nowy kontekst; dla ukrytego zachowuje konieczność odczytu po powrocie.

Nowa regresja Chromium wstrzymuje pierwszy odczyt bez teczki, przełącza dwie
teczki z różnymi relacjami, a następnie zwalnia spóźnione odpowiedzi.
Sprawdza selektor, relacje, możliwość zapisania kopii i zachowanie dialogu
ostatnio wybranej teczki. Scenariusz przechodzi z poprawką, a po cofnięciu
wyłącznie tej poprawki w odizolowanej kopii źródeł zawodzi.

Po poprawce wszystkie **1044 testy Pythona, 372 JavaScript i 33 scenariusze
Chromium przeszły**. Sekwencyjny przebieg przeglądarkowy obejmował cały graf
(17), Analizę (3), transport (5), Ukrainę (3) i teczki (5), bez timeoutów.
Ruff, składnia JS i kontrola whitespace także poprawne.

### „Pokaż na mapie” dla historycznego transportu bez porównania

Przycisk uwzględnia punkt z bieżącego wyniku grafu, gdy obiekt nie należy
do porównania tras. Sprawdza zgodność przedziału i kursora; dla porównywanych
obiektów nadal obowiązuje stan odtwarzanej trasy. Nie korzysta z pozycji LIVE
ani z poprzedniego kursora w razie braku historycznego punktu.

Zmiana czasu na widoku mapy unieważnia też ukryty graf i usuwa jego stare
markery. Nie uruchamia pobierania grafu w tle; nowy odczyt następuje po
powrocie do grafu. Zapobiega to pokazywaniu i użyciu poprzedniej pozycji
w czasie oczekiwania na aktualny kontekst.

Nowa regresja Chromium sprawdza samolot i statek bez porównania, centrowanie
na zapisanym punkcie przy kursorze, ostatni punkt przedziału bez kursora,
zmianę kursora podczas widoku mapy i rzeczywistą lukę obserwacji samolotu.
Sprawdza widoczność mapy, jej środek i zoom oraz brak automatycznego dodania
obiektu do porównania i brak cofnięcia do pozycji bieżącej/starej.
Scenariusz przechodzi z poprawkami. W odizolowanej kopii kodu oddzielne
cofnięcie obsługi punktu grafu i unieważniania czasu przy ukryciu powoduje
niepowodzenie tego testu w obu przypadkach.

Końcowe testy po poprawce: **1044 Python, 372 JavaScript i 34 scenariusze
Chromium przeszły**, bez timeoutów. Regresja przeglądarkowa obejmowała graf
(18), dotychczasową Analizę (3), transport (5), Ukrainę (3) i teczki (5).
Kontrole Ruff, składni JS i whitespace oraz budowa pakietu poprawne.

### Odtworzenie różnych zakresów przeglądu i filtrowania

Otwarcie zapisanego grafu przekazuje do wspólnej osi zarówno `overview_range`,
jak i `filter_range`. Oba zakresy są normalizowane z pól `from/to` lub
`start/end`. Zapisy bez zakresu przeglądu zachowują dotychczasowe zachowanie:
zakres przeglądu jest równy filtrowi.

Nowy test jednostkowy sprawdza godzinny zakres przeglądu z dziesięciominutowym
filtrem i kursorem w obu formatach nazw pól. Regresja Chromium wczytuje taki
układ z teczki, sprawdza stan wspólnej osi i selektor rzeczywistego wyniku API,
a następnie zapisuje go ponownie i potwierdza zachowanie obu zakresów,
kursora, strefy i pozycji węzłów. Oba nowe testy przechodzą z poprawką,
a po cofnięciu wyłącznie tej poprawki w odizolowanej kopii kodu oba zawodzą.

Po poprawce pełne zestawy zakończyły się powodzeniem: **1044 testy Pythona,
373 JavaScript i 35 scenariuszy Chromium**, bez timeoutów. Chromium uruchomiono
sekwencyjnie: graf (19), Analiza (3), transport (5), Ukraina (3) i teczki (5).
Kontrole Ruff, składni JS i whitespace oraz budowa pakietu poprawne.

### Końcowy niezależny przegląd

Po wszystkich poprawkach nowy subagent stosujący `review-agent` przejrzał
cały zakres względem merge-base `da21969764ad4d0079b159a48b4ead6c3bb08ab5`,
włącznie z nowymi plikami, migracją, backendem, interfejsem, testami
i dokumentacją. Wynik: **No findings.**

Przeszły dodatkowe celowane testy: 59 Python, 34 JavaScript i 9 scenariuszy
Chromium obejmujących wcześniejsze poprawki. Przegląd był tylko do odczytu,
na izolowanych bazach i syntetycznych dostawcach; nie obejmował ponownego
pobierania danych od rzeczywistych dostawców.

## Wydajność i interfejs

Test dużego otoczenia obejmuje 200 węzłów i 1200 sąsiadów. Odczyt relacji
obszaru korzysta z zapytań zbiorczych; test ogranicza liczbę instrukcji SQLite
do 1250. W pomiarze lokalnym wykonał się w około 0,25 s. To wynik środowiska
testowego, nie gwarancja czasu dla dowolnej bazy.

Przegląd przeglądarkowy obejmuje mapę i graf, wspólną kartę i tabelę,
ścieżki wyłącznie w widocznym fragmencie, ukrywanie węzłów, zapis i odtworzenie
pozycji, czytnik kopii oraz telefon w jasnym i ciemnym motywie. Listy węzłów
i połączeń pozwalają eksplorować graf także klawiaturą.

## Sprawdzenie na rzeczywistych danych

Wykonano odczyt rzeczywistej bazy `var/live/app.sqlite3` w trybie read-only
i utworzono jej tymczasową kopię. W kopii uruchomiono aplikację w trybie LIVE,
z wyłączonymi dostawcami i blokadą sieci. Oryginalna baza zachowała schemat
019; nie przeprowadzono migracji działającej instancji.

Sprawdzono stację **Warszawa, Al. Niepodległości**
(`air_quality_station:gios:530`) i relację źródłową do Mazowsza (`area:prg:14`).
W tymczasowej teczce zapisano relację analityczną i kopię grafu zawierającą
dwa węzły i dwa połączenia. Usunięcie relacji nie zmieniło kopii.

Były to zachowane prawdziwe dane źródłowe, bez nowego pobierania od GIOŚ.
W tej bazie nie było wcześniejszych materiałów teczek; zachowanie starych
materiałów potwierdzają osobne testy migracji i regresji.

## Pakiet i ograniczenia

Pakiet ma wersję 0.34.0. Renderer Cytoscape.js 3.34.4 jest dostarczany lokalnie
z licencją MIT i manifestem sum kontrolnych; kontrola
`python3 scripts/vendor_cytoscape.py --check` działa bez sieci.
`uv build` tworzy wheel i sdist. Zweryfikowano zgodność 23 zmienionych lub
nowych plików wykonawczych w wheel z kodem źródłowym, wersję metadanych oraz
obecność dokumentacji, migracji i licencji renderera w paczce źródłowej.

Graf opisuje dostępny lokalny katalog i historię, a nie pełną historyczną
rekonstrukcję granic lub dowód związku przyczynowego. Brak raportu pozycji
i luki alarmów pozostają jawne. Limity: 20 obiektów początkowych, 200 węzłów,
500 połączeń, 50 sąsiadów na stronę i 5000 kandydatów pojedynczego otoczenia.
Nieprzeczytani sąsiedzi i ograniczony wynik są oznaczane w interfejsie.

Działająca instancja LIVE nie była przełączana na nowy kod ani nowy schemat
podczas weryfikacji. Uruchomienie wersji 0.34.0 zastosuje migrację 020.
