# IODA — problemy łączności internetowej

WICI pokazuje **anomalie dostępności internetu wykryte przez IODA** (Georgia Tech Internet Intelligence Lab). Detekcja nie ustala cyberataku, sabotażu, cenzury ani przyczyny technicznej. Nie jest oficjalnym ostrzeżeniem polskich służb. Brak detekcji nie potwierdza prawidłowej dostępności internetu. Poziomy kraj, region i ASN mogą opisywać to samo zjawisko; liczba rekordów nie jest liczbą niezależnych awarii.

## Zweryfikowany kontrakt

Audyt 17.10.2026 obejmował [oficjalne API v2](https://api.ioda.inetintel.cc.gatech.edu/v2/), specyfikację osadzoną w Swagger UI i rzeczywiste odpowiedzi źródła. Nie był testem na danych syntetycznych. Poniższy opis zachowuje ustalenia techniczne dotyczące kontraktu i mapowania.

Od 18.10.2026 `tests/fixtures/ioda/` zawiera autorskie syntetyczne próbki przygotowane od zera do testowania kontraktu, błędów i historii. Wcześniejsze odpowiedzi, zapisane zapytania i kopię OpenAPI usunięto z bieżącej wersji. Dawny raport live ograniczono do informacji o wykonanym sprawdzeniu i usunięciu danych. Wcześniejsze kopie pozostały w dawnych commitach pierwotnego repozytorium. Ta kopia ma nową historię, bez tych commitów. [Pochodzenie obecnych fixture](../tests/fixtures/ioda/README.md).

- `GET /entities/query`: envelope `type=entities.lookup`, `metadata`, `requestParameters`, `error`, `data`, `copyright`. Jednostka: `type`, `code`, `name`, `attrs`. Kraj `entityType=country&entityCode=PL`. Regiony `entityType=region&relatedTo=country/PL`. ASN: `entityType=asn&relatedTo=country/PL&search=5617`, następnie **dokładne** dopasowanie kodu. API odrzuca połączenie `entityCode` z `relatedTo`; nie jest ono używane przez kolektor.
- Strony zaczynają się od **0**, `limit` określa rozmiar. Nie ma pola „następna strona”. Krótsza strona kończy odczyt; pełna trzecia strona oznacza niepełne pokrycie. Sprawdzono, że `page=1` może zwrócić pusty wynik dla kraju PL, choć strona 0 go zawiera.
- `GET /outages/events`: parametry `from`, `until` w sekundach Unix UTC, `entityType`, `entityCode` (również lista oddzielona przecinkami), `page`, `limit`, `extendWindow`. WICI ustawia `format=ioda&includeAlerts=true&overall=false&orderBy=time/asc`. Rekord: `entity`, `from`, `until`, `score`, `alerts`, `datasource`, `method`. Event API stanowi podstawowy zbiór detekcji, nie surowe alerty.
- `GET /outages/alerts`: envelope `outages.alerts`; rekord `entity`, `datasource`, `method`, `time`, `level`, `condition`, `value`, `historyValue`. Wartość i odniesienie mają jednostkę sygnału, a poziom jest etykietą IODA. Alerty są kontekstem; nie tworzą dodatkowych zdarzeń WICI.
- `GET /datasources/`: aktualne identyfikatory i jednostki. Wykresy używają **bgp** (`Visible /24s`), **ping-slash24** (`Up /24s`) i **merit-nt** (`Unique Source IPs`). Historyczna nazwa `ucsd-nt` w opisie API nie jest współczesnym identyfikatorem teleskopu. Zmiana jednostek powoduje widoczny częściowy błąd kontraktu.
- `GET /signals/raw/{entityType}/{entityCode}`: `from`, `until`, `datasource`, `maxPoints=288`. `data` jest tablicą grup tablic serii; seria zawiera `entityType`, `entityCode`, `entityName`, `entityFqid`, `datasource`, `subtype`, `from`, `until`, `step`, `nativeStep`, `values`. Próbka i ma czas `from + i*step`. Null oznacza brak pomiaru, nie zero. Granice serii mogą być wyrównane poza żądane okno, a API może zwrócić więcej punktów niż `maxPoints`. Parser dopuszcza do 600 wartości w serii; UI pokazuje do 288 punktów. Przyszłe próbki są pomijane. Krok i natywny krok są zapisywane i pokazywane; nie obiecujemy surowej rozdzielczości ani konkretnego algorytmu agregacji przy `step>nativeStep`.

### Znaczenie zakończenia i wskaźnika

Sprawdzono także [kod oficjalnego poprzednika API](https://github.com/CAIDA/ioda-api/tree/5e3d1df365bb8be75753726e517561f2f09b70b5), `OutagesEventsService::buildEvents` i `OutagesEventNormalizer`. Kod jest dowodem implementacji poprzednika, nie gwarancją niezmienności aktualnej usługi. Format CODF ma `location`, `start`, `duration`, `status`, `fraction`, `score`, `overlaps_window`; `status=0` bywa stałą, a `duration` może kończyć się na granicy zapytania. Nie używamy tych pól do ogłaszania końca.

WICI uznaje `ended_at` wyłącznie wtedy, gdy w tym samym zdarzeniu istnieje alert **normal** dokładnie w `until`. W przeciwnym razie zapisuje `source_until`, lecz zakończenie pozostaje **niepotwierdzone**. Aktualizacja może zmienić długość i wskaźnik. Brak rekordu w następnym oknie, częściowa odpowiedź i błąd nigdy nie zamykają zdarzenia. Brak identyfikatora zdarzenia w API: lokalny klucz jest hashem `(typ, kod, datasource, method, from)`. Zachowujemy pełny payload i pochodzenie, zamiast wymyślać identyfikator źródłowy.

`score` jest wskaźnikiem IODA: całką spadku sygnału w procentach po minutach, według implementacji źródła; nie procentem użytkowników bez internetu. Przy `overall=false` nie mnożymy wskaźników między sygnałami ani nie sumujemy poziomów kraju/regionu/ASN w „liczbę awarii”. `until` i score mogą zależeć od okna zapytania.

## Zakres i geometria

Domyślnie kraj PL, wszystkie regiony zwrócone przez relację do PL (obecnie 16 województw i „Unknown Region in Poland”) oraz ASN 5617, 12741, 12912. Lista ASN jest konfigurowalna, maksymalnie osiem unikalnych numerów. Każdy musi przejść wyszukanie relacji do `country/PL`. Brak potwierdzenia to widoczny błąd zakresu; brak sieci na ograniczonej liście nie oznacza braku anomalii w tej sieci. Powiązanie ASN z Polską nie ogranicza jego pomiarów do terytorium Polski. Metadane są trwałe, odświeżane po 24 h. Nie pobieramy listy całego świata ani pełnej listy polskich ASN.

Mapowanie zostało przejrzane po nazwie IODA, potwierdzonym `attrs.country_code=PL` i nazwie lokalnego województwa PRG. Kod IODA **nie jest** kodem TERYT. Funkcja `geometry_ref` wymaga zgodności wszystkich trzech pól; zmieniona nazwa lub kraj blokują mapowanie. Test sprawdza istnienie wszystkich identyfikatorów w lokalnych granicach.

| IODA | Nazwa IODA | PRG/TERYT |
|---|---|---|
|3288|Warmian-Masurian|28|
|3289|Pomeranian|22|
|3290|Lower Silesian|02|
|3291|West Pomeranian|32|
|3292|Lubusz|08|
|3293|Greater Poland|30|
|3294|Kuyavian-Pomeranian|04|
|3295|Silesian|24|
|3296|Łódź|10|
|3297|Masovian|14|
|3298|Świętokrzyskie|26|
|3299|Podlachian|20|
|3300|Lublin|06|
|3301|Subcarpathian|18|
|3302|Opole|16|
|3303|Lesser Poland|12|

Region 4849 i inne nieznane mapowania pozostają na liście. ASN nigdy nie otrzymuje geometrii ani punktu siedziby operatora. Wypełnienie obszaru jednostki pokazuje poziom agregacji pomiarów, nie zasięg utraty wszystkich łączy. Fiolet oznacza detekcję bez potwierdzonego końca; przerywany fiolet dodatkowo wskazuje alert starszy niż godzinę. Potwierdzone zakończenie ma szare wypełnienie i wyraźny przerywany obrys. To zapis zakończonej detekcji w wybranym oknie, nie oznaczenie bieżącej awarii. Status jest też zapisany tekstowo w szczegółach, na liście i w dymku. Brak oznaczenia nie stanowi potwierdzenia sprawnej łączności.

## Pobieranie, trwałość i odporność

`Scheduler` uruchamia źródło `ioda` przez cały czas działania aplikacji live, niezależnie od warstwy i widoczności okna. Interwał 300 lub 600 s jest interwałem odczytu WICI; nie interwałem pomiarów ani gwarancją czasu publikacji IODA. Demo nie uruchamia sieci.

Każdy cykl ponownie czyta nakładające się 48 h, z `extendWindow=1209600` (14 dni) dla zdarzeń i alertów rozpoczynających się poza oknem. To obejmuje opóźnione dane i aktualizacje wielu trwających detekcji. Nie jest pełnym archiwum; zdarzenia rozpoczęte wcześniej niż rozszerzone okno mogą nie otrzymać aktualizacji. Stan zakończenia pozostaje wtedy niepotwierdzony. Kolektor wykonuje zapytania sekwencyjnie we wspólnym semaforze schedulera (2 źródła). Limit: 60 żądań/cykl, 3 strony po 100 rekordów na zbiór, odpowiedź do min(config.max_response_bytes, 4 MB), timeout z konfiguracji. Prawidłowe strony są zapisywane przed kolejnym zapytaniem. Błędny rekord nie usuwa innych rekordów. Niepełna paginacja jest błędem pokrycia, nie sukcesem pełnego odczytu.

HTTP 429 natychmiast kończy cykl, zapisuje błąd i respektuje `Retry-After` (sekundy lub HTTP-date; do 24 h), inaczej 600 s. Ręczne odświeżenie również respektuje aktywny Retry-After. Scheduler stosuje wykładniczy backoff do 3600 s, powiększany o Retry-After. Timeout, HTTP 5xx, błędny JSON/kontrakt i limit rozmiaru zachowują poprawne wcześniejsze zapisy. Nie tworzą detekcji. Zapisany `next_due_at` i licznik błędów przetrwają restart. Przerwane zadanie zapisuje niepełny/błędny odczyt.

Migracja **009** dodaje wyłącznie osobne tabele `ioda_entities`, `ioda_events`, `ioda_alerts`, `ioda_samples`. Jest transakcyjna i nie modyfikuje historii publikacji ani wycofanych integracji. Event jest aktualizowany przez stabilny klucz; alert przez jednostkę/sygnał/metodę/czas; próbka przez jednostkę/sygnał/czas/krok. Null nie zastępuje istniejącego poprawnego pomiaru ani jego czasu pobrania, natywnego kroku i pochodzenia. Czas kolejnej próby oraz brak nowych pomiarów są raportowane osobno w stanie źródła i ostatniego cyklu. Przechowujemy źródłowe metadane, miary i payload zdarzenia/alertu, URL i parametry zapytania, czasy odpowiedzi źródła, czas pomiaru, pobrania i pierwszego zapisu. Snapshoty sygnałów na nachodzących siatkach są redukowane po czasie dopiero podczas odczytu widoku; rzeczywisty krok pozostaje jawny.

Retencja podczas cyklu: próbki, alerty i fetch_runs 30 dni; zdarzenia usuwa się, gdy `source_until` i ostatni odczyt są starsze niż 30 dni. Metadane pozostają jako słownik dla historii. Nie usuwa się danych przy samym uruchomieniu aplikacji; wyłączona aplikacja nie prowadzi monitoringu.

## API WICI i interfejs

`GET /api/ioda?hours=24|48&date=YYYY-MM-DD&level=country|region|asn&voivodeship=14&limit=500` czyta wyłącznie SQLite. Zwraca listę z pełnymi szczegółami i miarami, jednostki i wykresy zapisanych sygnałów oraz status źródła. Błędne okno/poziom/przyszła data to 422. Limit listy 500 jest jawnie oznaczony.

Warstwa „Problemy łączności internetowej” jest domyślnie wyłączona. Jej włączenie ukrywa na mapie obszary i karteczki komunikatów, aby ich kolory nie mieszały się z IODA; lista publikacji pozostaje dostępna. Opcja „Pokaż też komunikaty i ostrzeżenia na mapie” przywraca wspólny widok i zachowuje wybór przy odświeżaniu. Wybranie publikacji z listy również włącza wspólny widok. Wyłączenie IODA przywraca obszary i karteczki. Osobna warstwa rysowania utrzymuje obrysy IODA nad obszarami komunikatów niezależnie od kolejności odświeżania. Legenda opisuje stany bez używania zielonego „OK”. Szerokość dymka dopasowuje się do mapy także na telefonie i po zmianie rozmiaru okna.

Warstwa ma listę, rozwijane szczegóły, poziom, okno 24/48 h (domyślnie 48 h) i wybór jednostki dla wykresów (również gdy nie ma zdarzeń). Legenda na mapie pokazuje wybrane okno z datami, liczbę detekcji z geometrią oraz liczbę rekordów dostępnych tylko na liście. Pusty wynik ma jawny komunikat; przy pustych 24 h przycisk „Sprawdź 48 godzin” rozszerza zakres na żądanie. Odświeżanie zachowuje wybrane okno. Wynik zawierający wyłącznie ASN lub rekordy bez geometrii wyjaśnia, dlaczego mapa pozostaje bez oznaczeń. Błąd odczytu zapisów WICI jest widoczny także w legendzie i nie zastępuje ostatnich danych pustym wynikiem. Czasy są formatowane w **Europe/Warsaw**. Wybrany dzień publikacji **wyznacza koniec okna IODA**: dziś do teraz, dawniej do końca dnia w Warszawie; samo okno ma 24/48 godzin czasu upływającego także podczas zmiany DST. Zdarzenia przecinają przedział `[start,end)`. Filtr województwa jest ścisły: wyłącznie zweryfikowany region; kraj, ASN i region bez mapowania są wtedy wykluczane. Historia pokazuje lokalnie zapisane aktualne wersje; nie kompletny zbiór IODA ani dawny stan wiedzy.

Stan odczytu i stan pomiarów są oddzielne:

- `success` oznacza wszystkie wybrane zapytania poprawne; `partial` zachowanie części danych z błędami; `error` awarię odczytu; wyłączenie konfiguracji to oddzielny stan dostępu.
- Źródła pokazują ostatnią próbę, pełny sukces, pokrycie i częściowe błędy, ostatni **niepusty** pomiar oraz jego wiek, a także liczbę par jednostka/sygnał dostępnych, nieaktualnych, bez pomiarów i z błędem.
- Próg aktualności pomiaru: 1 h (lokalna polityka WICI, nie SLA źródła). Ostatnia aktualna próbka jednego sygnału nie potwierdza kompletności pozostałych. Wykres każdej jednostki/sygnału ma własny czas i stan odczytu. Brak nowych pomiarów nie kasuje historii; widok wyjaśnia, że prezentuje zachowane dane.
- Świeżość odczytu: pełny sukces w ciągu `3*interval_seconds+120`, według istniejącej polityki schedulera. Poprawne pobranie może zawierać stare pomiary. Sama stara detekcja nie dowodzi trwającego problemu.
- Pusta lista zdarzeń, brak pomiarów, nieaktualny pomiar i awaria API są odrębne. Żaden z nich sam nie jest dowodem poprawnego działania łączności.

## Demo i weryfikacja

Demo tworzy syntetyczne anomalie kraju, województwa i ASN, jednostkę bez danych oraz nieaktualne źródło. Wszystkie zdarzenia mają `synthetic=true`, oznaczenie DEMO i syntetyczne pochodzenie. Ponowne seedowanie i restart zachowują trzy rekordy. Nie używa odpowiedzi live jako scenariusza demo.

Testy Python: `uv run pytest -q`; Node i realne Chromium: `NODE_PATH=<runtime>/node_modules node --test --test-concurrency=1 tests/*.cjs`; Ruff: `uv run ruff check src tests`; diff: `git diff --check`. Weryfikacja integracji z 17.10.2026: 541 testów Python i 121 testów Node/Chromium; Ruff i kontrola diffu były poprawne. Testy przeglądarkowe uruchomiono sekwencyjnie, aby uniknąć zależności istniejącego testu hydrologii od kolejności zakończenia żądań przy zatrzymanym zegarze. Testy obejmują kontrakt, null, mapowanie, ASN bez punktu, klucz/deduplikację/aktualizację, restart i migrację z historią, granice czasu/DST, paginację od zera i limit, 429/Retry-After, timeout/5xx/rozmiar, częściowy odczyt, pracę schedulera bez UI i offline demo. Test przeglądarkowy IODA sprawdza szczegóły, mapę, brak geometrii ASN, filtry, brak pomiarów, stary stan, widok Źródła oraz desktop/mobile. Regresje obejmują zachowanie wartości i jej pochodzenia po null (także po restarcie), późniejszą aktualizację do zera oraz zachowanie otwartych szczegółów, fokusu i tego samego dymka Leaflet przy zmienionych i niezmienionych danych podczas minutowego odświeżania. Jawne zamknięcie jest respektowane, a rekord usunięty przez filtr nie pozostawia warstwy ani dymka. Regresja widoczności obejmuje zakończoną detekcję starszą niż 24 h: domyślne 48 h z widocznym wypełnieniem, jawny pusty wynik 24 h, rozszerzenie zakresu przyciskiem oraz zachowanie wyboru podczas odświeżania. Pozostałe testy pokrywają regresję komunikatów i warstw.

Weryfikacja po zastąpieniu próbek 18.10.2026: `uv run --locked pytest -q` — **772 testy przeszły**; `node --test tests/ioda_browser.cjs` z `NODE_PATH` wskazującym biblioteki runtime — **5 testów przeglądarkowych IODA przeszło**. `uv run --locked ruff check src tests` oraz budowanie sdist i wheel zakończyły się powodzeniem. Sprawdzono również zawartość archiwów: sdist zawiera dziewięć syntetycznych plików JSON IODA i oczyszczony raport, bez usuniętej kopii OpenAPI i dawnych snapshotów; wheel nie zawiera fixture ani raportów.

17.10.2026 wykonano również ograniczone sprawdzenie live, niezależne od testów offline. Od 18.10.2026 [notatka o tym sprawdzeniu](evidence/ioda-live-2026-10-17.json) nie zawiera rzeczywistych odpowiedzi, metadanych jednostek ani liczebności detekcji, alertów i pomiarów. Nie stanowi już zachowanego zestawu danych do odtworzenia tamtej próby. Aktualne testy korzystają z syntetycznych fixture; ich wyniki nie są dowodem bieżącej dostępności API.

Regresje wizualne obejmują także przejścia świeży alert → stary alert → potwierdzony koniec bez wymiany warstwy lub dymka, rozdzielenie komunikatów i IODA, świadome przywrócenie wspólnego widoku oraz dostępny przycisk zamknięcia dymka na ekranie 390 px.

## Atrybucja i warunki

Źródło: **IODA, Georgia Tech Internet Intelligence Lab**, [serwis](https://ioda.inetintel.cc.gatech.edu), [opis](https://ioda.inetintel.cc.gatech.edu/about/), [API](https://api.ioda.inetintel.cc.gatech.edu/v2/). Każda odpowiedź API zawiera: **Copyright © 2021–2025 Georgia Tech Research Corporation. All Rights Reserved.** Oryginalne pole `copyright` zachowujemy z pochodzeniem. Dane przetwarzamy do lokalnej prezentacji, bez przejmowania oznaczeń źródła.

W publicznej dokumentacji API, stronie projektu i stronie About nie znaleziono jednoznacznej licencji danych ani opublikowanego limitu SLA/żądań. Nie przypisujemy danych do CC ani domeny publicznej. Licencja kodu CAIDA/ioda-api nie jest licencją współczesnych danych Georgia Tech; kodu tego nie kopiujemy do aplikacji. Lokalny odczyt publicznego API nie jest deklaracją prawa do redystrybucji czy komercyjnego wykorzystania danych. Przed takimi zastosowaniami należy ustalić warunki z zespołem IODA. WICI zachowuje atrybucję, linki, ogranicza zapytania i honoruje odmowy dostępu.
