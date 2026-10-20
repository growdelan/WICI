# Regionalna jakość pozycji lotniczych / GNSS

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Warstwa WICI pokazuje anomalie **deklarowanej jakości pozycji**, jako pośredni i niepełny sygnał możliwych problemów GNSS. Nie mierzy widma radiowego, nie rozpoznaje przyczyny, jammingu ani spoofingu i nie jest oficjalnym ostrzeżeniem. Geometria oznacza komórkę obserwacji, nie lokalizację nadajnika. Próg detektora nie jest progiem bezpieczeństwa lotu.

## Bieżące źródło od 18.10.2026 — adsb.fi

Samoloty i kolektor korzystają ze wspólnego endpointu `https://opendata.adsb.fi/api/v3/lat/52.05/lon/19.2/dist/250`, z tym samym cache 10 s, filtrem PRG, polami jakości i heurystyką. [Dokumentacja i warunki](https://github.com/adsbfi/opendata): dostęp publiczny bez klucza, limit 1 żądanie/s, użytek osobisty i niekomercyjny oraz obowiązkowa atrybucja adsb.fi. Dostępność poszczególnych pól pozostaje zależna od odpowiedzi; brak pola nie oznacza dobrej jakości. Brak gwarancji ciągłości i pełnego pokrycia. Współdzielenie cache zachowuje dotychczasową częstotliwość kolektora bez osobnego pobierania drugiego dostawcy.

Migracja 011 zapisuje pochodzenie każdej nowej próbki: dostawcę, endpoint i trwały identyfikator okresu źródła. Zmiana dostawcy lub endpointu rozpoczyna nowy okres oraz rozgrzewkę, także przy powrocie do wcześniej używanego dostawcy. Zwykły restart zachowuje ten sam okres i jego tło. Tło oraz dwa sąsiednie okna oceny muszą pochodzić z jednego okresu; okno obejmujące zmianę źródła nie podlega ocenie ani nie tworzy tła.

Wcześniejsze rekordy nie mają wiarygodnego pochodzenia i mogły już mieszać dostawców. Migracja zachowuje ich wskaźniki, daty i lokalizacje, oznacza je jako „nieustalone źródło” i wyłącza z ocen oraz tła. Pozostają szare i dostępne do przeglądania, ale ich dawnych klasyfikacji nie odtwarzamy. Pierwsze uruchomienie po migracji wymaga zbudowania nowego tła, minimum około 40 min przy wystarczającej próbie. Wiek bieżących obserwacji i stan źródła dotyczą wyłącznie aktywnego okresu, a spóźniony zapis poprzedniego okresu nie nadpisuje aktualnego statusu. Historia może zawierać dane ADSB.lol / ODbL 1.0; zachowano ich atrybucję. Kod nie zawiera klienta ani fallbacku do starego API. Autorskie syntetyczne fixture wspólnego formatu readsb znajdują się w `tests/fixtures/aircraft/`.

## Format i znaczenie wskaźników

Bieżący kontrakt opisują [dokumentacja adsb.fi](https://github.com/adsbfi/opendata) i [JSON upstream readsb](https://github.com/wiedehopf/readsb/blob/dev/README-json.md). Używany jest endpoint v3 opisany powyżej; parametr promienia jest w milach morskich. Okrąg obejmuje też obszary poza Polską, więc WICI stosuje lokalne granice PRG. Opis upstream objaśnia format, ale nie gwarantuje dostępności każdego pola w konkretnej odpowiedzi.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

| Pole | Znaczenie i ograniczenia |
|---|---|
| `nac_p` | Deklarowana kategoria dokładności pozycji. Niska wartość to słaba/nieokreślona dokładność, nie pomiar błędu ani przyczyny. Zero jest raportowaną kategorią nieokreślonej dokładności, odrębną od braku pola. |
| `nic` | Kategoria integralności pozycji; jej interpretacja zależy od wersji i bitów uzupełniających. Zero nie oznacza dobrej jakości. |
| `rc` | Promień ograniczenia integralności w metrach, wyprowadzony z NIC i bitów dodatkowych. To nie niezależne potwierdzenie NIC ani zmierzony błąd. Samo RC=0 nie kwalifikuje raportu jako dobrego. |
| `sil` / `sil_type` | Deklarowany poziom integralności źródła i interpretacja na godzinę/próbkę lub nieznana. Nie wskaźnik bieżących zakłóceń; tylko dostępność w szczegółach, bez udziału w klasyfikacji. |
| `version` | Wersja ADS-B 0/1/2. Detektor przyjmuje tylko 1/2; brak, 0 i zarezerwowane wartości nie są porównywane. |
| `type` | Źródło pozycji. Detektor przyjmuje `adsb_icao`/`adsb_other`; MLAT, TIS-B, ADS-C, Mode-S, nieznane i estymowane źródła są poza detekcją. Dodatkowo listy `mlat` i `tisb` mogą wskazać pochodzenie pól lat/lon, nawet przy innym `type`. |
| `gpsOkBefore` | Eksperymentalny znacznik upstream wcześniejszej dobrej jakości; według readsb udostępniany krótko (15 min) po utracie/pogorszeniu. Nie jest diagnozą przyczyny; obecność jest kontekstem, nie głosem w detektorze. |
| `lastPosition` | Opcjonalny obiekt z ostatnią pozycją i wiekiem po utracie aktualnej pozycji. Udokumentowany w readsb, jego obecność zależy od odpowiedzi API. Testowany syntetycznie; wyłącznie niepewny kontekst. |

Każde pole może być nieobecne, nieaktualizowane równocześnie z pozycją, błędnie deklarowane przez awionikę lub przetworzone przez dostawcę. API nie daje wieku każdego wskaźnika. Nie można traktować NIC, RC, NACp jako trzech niezależnych czujników. Aktualna dobra kategoria nie wyklucza spoofingu. Raportowane współrzędne też mogą być błędne; przypisanie do komórki nie jest niezależną weryfikacją położenia. Wyposażenie, konfiguracja transpondera, manewry, warunki propagacji i zmienne pokrycie odbiornikami mogą wpływać na obserwacje.

## Zbieranie i trwałość

Sekcja `[position_quality]` w konfiguracji: `enabled=false`, `interval_seconds=60` (60–300; większe wartości, w tym 600, są odrzucane, ponieważ pomijają sąsiednie okna 5 min), `retention_hours=72` (50–168). Aktywność `sources.aircraft` jest warunkiem pobierania. Użytkownik włącza kolektor świadomie; zaznaczenie warstwy nie włącza sieci ani kolektora. Przy wyłączonym kolektorze endpoint historii tylko czyta zapis; istniejąca warstwa samolotów nadal może samodzielnie pobierać bieżące pozycje.

Po włączeniu kolektor jest zadaniem lifespan aplikacji live, działa bez przeglądarki i niezależnie od mapy. Korzysta z dokładnie tej samej instancji AircraftService co samoloty: jeden lock, cache 10 s, timeout do 10 s, limit odpowiedzi 4 MiB, brak przekierowań, maksymalnie 10 tys. rekordów, backoff błędu co najmniej 60 s, Retry-After dla 429 (liczba sekund lub data, maksymalnie doba). Nie ma dodatkowego endpointu ani zapytań o historię. Cache samolotów jest publikowany przed przekazaniem surowego snapshotu do kolejki kolektora. Kolektor otrzymuje dane niezależnie od filtra świeżości mapy samolotów. Cache hit nie dodaje ponownie tej samej odpowiedzi do kolejki. Pełne 10 s cache liczy się od publikacji odpowiedzi.

SQLite (`var/live/app.sqlite3`, migracje 010/011): pierwszy raport danego identyfikatora ICAO w minucie czasu źródła i danym okresie dostawcy wygrywa (`INSERT OR IGNORE`). To downsampling, może pominąć krótką zmianę wewnątrz minuty. Powtórzone payloady i duplikaty identyfikatorów nie zwiększają próby. Przechowywane są komórka, województwo lokalizacji, wskaźniki i flagi kwalifikacji; bez callsignów/rejestracji i tras. Identyfikator jest potrzebny do liczenia różnych maszyn, nie pozwala wykluczyć zmiany/duplikowania adresów przez nadajniki. Nieobecne pola pozostają nieobecne; nieprawidłowe wartości są null. Czasy prób, sukcesu i początek zbierania są trwałe. Restart nie tworzy historii i nie zeruje próbki. Awaria zapisu próbek, retencji lub statusu jest izolowana od cache i odpowiedzi warstwy samolotów. Kolektor zachowuje status błędu zapisu w pamięci, pozostaje aktywny i ponawia transakcję; błąd znika po udanym zapisie, jeśli w międzyczasie nie wystąpiła nowsza awaria. Przy niedostępnej bazie nie da się zagwarantować utrwalenia samego statusu błędu.

Zapis live wykonuje pojedynczy worker przez `asyncio.to_thread`, na własnym połączeniu SQLite. Pętla asyncio i wspólna blokada repozytorium nie czekają na transakcje kolektora. Jedna transakcja obejmuje próbki, retencję i zapamiętany status źródła; timeout oczekiwania na blokadę SQLite wynosi 50 ms. Po niepowodzeniu worker ponawia zapis co około 1 s, bez żądania do adsb.fi. Te wartości dotyczą oczekiwania na blokadę, nie gwarantują czasu pracy dysku.

Kolejka przechowuje maksymalnie **dwa oczekujące snapshoty oraz jeden aktualnie przetwarzany**. Przepełnienie odrzuca najstarszy oczekujący snapshot, zachowując nowsze obserwacje. API i UI pokazują liczbę oczekujących zapisów i pominiętych snapshotów od uruchomienia procesu; liczniki te nie są trwałą historią awarii. Długotrwała awaria zapisu może powodować luki — to świadomy limit pamięci, nie gwarancja archiwizacji wszystkich pobranych odpowiedzi. Ponawiana próbka zachowuje oryginalny czas odczytu i kwalifikację względem niego, zamiast udawać nową obserwację. Starszy zapis w tle nie nadpisuje nowszego stanu źródła w pamięci; w bazie aktualizacja statusu również jest chroniona czasem próby.

Zamykanie aplikacji odłącza producenta, przerywa oczekiwanie na kolejne ponowienie i kończy bieżące ograniczone próby. Snapshoty, których nie da się wtedy zapisać, są pomijane zamiast blokować zamknięcie aż do zwolnienia zewnętrznej blokady.

Retencja usuwa starsze wiersze przy zapisie, starcie i odczycie. Okresowe utrzymanie w workerze działa również przy cache hit i podczas `Retry-After`, bez tworzenia fikcyjnych prób HTTP. Filtr odczytu nie zwraca danych poza retencją nawet wtedy, gdy blokada uniemożliwia fizyczne usunięcie wierszy. Limit czasu i wielkości wejścia ograniczają liczbę wierszy; SQLite może zachować przydzielone strony pliku do ponownego użycia. Nie jest to usługa systemowa: zbieranie kończy się z zatrzymaniem aplikacji. Brak zapisanych wcześniejszych danych i luki pozostają brakami. Demo używa osobnej bazy `var/demo`, deterministycznych syntetycznych raportów przez ten sam normalizator i agregator oraz żadnych żądań sieciowych.

## Metoda v1 (heurystyka, bez kalibracji GNSS)

1. Pozycje w granicach Polski przypisywane są do komórek 0,5° szerokości × 1° długości (~56 × 68 km w środkowej Polsce), do okien UTC po 5 min i województwa punktu obserwacji. Prostokąt może wychodzić poza Polskę/województwo; to siatka agregacji, nie granica zjawiska. Filtr województwa przelicza próbę tylko z jego obserwacji.
2. Do detekcji kwalifikuje się bezpośredni ADS-B v1/v2 z aktualną pozycją (wiek względem czasu aplikacji ≤60 s), co najmniej jednym poprawnym NACp/NIC lub dodatnim RC. Raporty naziemne i kategorie B/C są wyłączone. Pogorszenie: **NACp <7 lub NIC <6 lub RC >1852 m**. To celowo prosta, jawna granica słabszej deklaracji jakości/integralności, nie standard operacyjny GNSS. NIC/RC są zależne i tworzą jeden warunek OR. Nie ma wag „potwierdzeń” dla kilku pól jednego raportu. Wersje 1 i 2 mają wspólny pragmatyczny próg; zmiana wyposażenia floty pozostaje czynnikiem zakłócającym.
3. W każdym oknie samolot ma jeden głos: jest pogorszony, jeśli ≥50% jego zakwalifikowanych raportów jest pogorszonych. Raportowane są również udział pogorszonych raportów, liczba raportów i dostępność każdego pola; detektor używa udziału **samolotów**, aby częstotliwość raportowania jednej maszyny nie udawała wielu potwierdzeń.
4. Minimalna próba to **5 różnych samolotów w każdym z dwóch kolejnych okien**. W obu ≥60% maszyn ma pogorszenie (co najmniej 3/5). Ogranicza to wpływ jednego transpondera; nie gwarantuje niezależności sprzętu ani odbiorników. Samoloty mogą powtarzać się pomiędzy oknami — to test utrzymywania się, nie nowe niezależne potwierdzenia.
5. Tło to średni udział pogorszonych maszyn z wystarczających okien tej samej komórki w poprzednich 2 h, z wyłączeniem bieżącego i poprzedniego. Wymagane **≥6 okien po ≥5 maszyn**; wzrost względem tła w bieżącym oknie **≥30 punktów procentowych**. Minimum około 40 min od początku pełnych obserwacji; przy małym ruchu znacznie dłużej. To lokalne, krótkookresowe tło, nie klimatologia ani importowana historia. Długie pogorszenie może wejść do tła i przestać być wykrywane.
6. Niepełne okno, brak tła lub próby daje „za mało danych”. Z wystarczającą próbą i bez spełnienia wszystkich warunków: „brak wykrytej anomalii przy wystarczającej próbie”. To wynik tej heurystyki, nie potwierdzenie zdrowego GNSS. Wykrycie wymaga zakończenia okna (opóźnienie do ~10 min dla utrzymywania się).

Nieaktualna pozycja / `lastPosition` trafia wyłącznie do niepewnego kontekstu. Brak pozycji jest zapisywany bez przypisania komórki i widoczny w liczniku ogólnym. Znane pozycje poza Polską są odrzucane; samolotu bez pozycji nie da się pewnie przypisać do kraju. Nie odtwarza się trasy ani lokalizacji z odbiornika (`rr_lat`/`rr_lon`). **Istnieje silne obciążenie selekcją:** zapytanie przestrzenne może już po stronie API usuwać maszyny bez świeżej pozycji. Zapis przed filtrem WICI zmniejsza dodatkową utratę, ale nie odzyskuje samolotów nieobecnych w odpowiedzi. Cisza, spadek liczby samolotów, brak pól i awaria API nigdy nie tworzą anomalii. Mały ruch oznacza brak możliwości oceny.

## UI, czas i stany

Osobna, domyślnie niezaznaczona warstwa w sekcji lotniczej: historia 24/48 h, wybór okna, agregaty komórek, szczegóły liczebności, udziałów, tła, niepewnego kontekstu i dostępności pól. Czas wyświetlany Europe/Warsaw (w tym DST); okna zapisane UTC. Zakres kończy się teraz dla bieżącego dnia, a dla wcześniejszego dnia o następnej północy w Warszawie. Nie oznacza odtworzenia historycznego stanu pozostałych warstw WICI. Domyślny tryb śledzi najnowsze zakończone okno; ręczny wybór pozostaje przy kolejnych odświeżeniach. Przycisk „Najnowsze okno” przywraca śledzenie. Zmiana dnia, województwa lub długości historii rozpoczyna nowy zakres. Błąd odczytu lokalnego API pozostaje widoczny także przy zmianie okna i znika dopiero po udanej odpowiedzi.

Stany wyniku komórki to anomalia / brak wykrycia przy próbie / za mało danych. Odrębnie widoczny stan źródła: kolektor wyłączony, brak pierwszego odczytu, poprawny odczyt, błąd lub dane nieaktualne (wiek ostatniego sukcesu > max(180 s, 3 interwały)). Świeży odczyt API bez nowych kwalifikowanych obserwacji nie maskuje wieku danych: nagłówek uwzględnia również wiek ostatniej kwalifikowanej obserwacji względem końca wybranego zakresu. Brak takich obserwacji daje za mało danych. Błąd ma pierwszeństwo nad nieaktualnością w nagłówku. Historyczne klasy są zachowane podczas błędu źródła, ale mapa ma przerywany brązowy obrys i ostrzeżenie, że nie opisuje aktualnej sytuacji. Nie ma syntetycznego „zielonego” w pustej komórce. Wiek odczytu, czas ostatniej próby i czas obserwacji są pokazane osobno.

Odczyt i agregacja historii są wykonywane przez `asyncio.to_thread`, na osobnym połączeniu SQLite, bez trzymania blokady repozytorium aplikacji podczas dużego odczytu. Test z 300 000 raportów (48 h i 2 h tła po 100 samolotów/min) zatrzymuje czytnik i potwierdza równoczesną odpowiedź `/api/health` oraz zapis nowych próbek. Nie jest to limit liczby raportów ani gwarancja czasu odpowiedzi na każdym sprzęcie.

## Weryfikacja i granice

`tests/test_position_quality.py`: skupisko wielu maszyn, stały wadliwy transponder, duplikaty, brak kontra zero, wersje i źródła, MLAT/TIS-B na poziomie pól, niepewna lokalizacja, mały ruch, Retry-After, współdzielenie, kolektor bez mapy, offline demo/wyłączenie, restart, retencja, źródło i nieaktualność, filtry API i loopback. `tests/position_quality_ui.cjs`: deterministyczne regresje odświeżania, ręcznego wyboru, błędów API, odzyskania odczytu i wyścigów zmiany filtrów (uruchamiane także przez pytest). `tests/position_quality_browser.cjs`: rzeczywista przeglądarka offline, mapa, szczegóły, 24/48 h, dzień, województwo, ukrywanie warstwy i brak żądań zewnętrznych; zegar Chromium przesuwa okresy odświeżania, sprawdzając śledzenie nowych okien, ręczny wybór i utrzymanie błędu do odzyskania API.

Live nie został zweryfikowany jako detector GNSS na oznaczonym zbiorze rzeczywistych incydentów. Testy syntetyczne nie potwierdzają trafności ani skuteczności tej heurystyki na rzeczywistych incydentach. Wynik należy zawsze interpretować jako ograniczoną obserwację raportów lotniczych.


Wynik weryfikacji implementacji 17.10.2026: `pytest -q` — **563 zaliczone** (jedno ostrzeżenie zależności Starlette/httpx), Ruff i `git diff --check` bez błędów. Test nowej warstwy i ogólny `scripts/check_atlas_ui.cjs` przeszły w Chromium z blokadą ruchu zewnętrznego. Zrzuty sprawdzono wizualnie; test ogólny obejmuje 1366, 768, 390 i 320 px. Zaktualizowano również starą asercję liczby grup w smoke teście (interfejs miał już 9 grup przed tą zmianą).

Polecenia do ponowienia (Playwright jest opcjonalną zależnością środowiska developerskiego; wskaż `NODE_PATH`, jeśli nie jest zainstalowany globalnie):

```sh
uv run pytest -q
uv run ruff check src/wici tests/test_position_quality.py
# Uruchom osobną instancję DEMO na loopback; wpisz jej port w URL.
WICI_UI_URL=http://127.0.0.1:8773 node tests/position_quality_browser.cjs
WICI_UI_URL=http://127.0.0.1:8773 node scripts/check_atlas_ui.cjs
```

Test przeglądarkowy nowej warstwy zapisuje obrazy w `tmp/quality-ui/` (tworzy katalog automatycznie). Nie uruchamiaj smoke testów przeciw live. Udany audyt API nie jest testem trafności detekcji na rzeczywistych incydentach GNSS.


Po poprawkach przeglądu sprawdzono dodatkowo: odczyt samolotów i cache przy SQLite tylko do odczytu, przeżycie zadania kolektora i automatyczne wznowienie zapisu, bezpieczny zapis statusu podczas awarii API, odrzucenie interwału 600 s, wykrycie przy granicznych 60/300 s, niezależny odczyt 300 000 raportów bez blokowania zdrowia i zapisu oraz odświeżanie UI z przesuwanym zegarem Chromium. Wynik pełnego zestawu po poprawkach: **560 testów**, jedna znana uwaga Starlette/httpx; Ruff, testy przeglądarkowe warstwy i atlasu oraz `git diff --check` przechodzą.


Regresja blokady zapisu używa rzeczywistego `BEGIN IMMEDIATE` na drugim połączeniu. Zatrzymuje również worker przed SQL i sprawdza, że cache, `/api/health`, `/api/communications` i heartbeat pętli pozostają dostępne przed dokończeniem zapisu. Następnie sprawdza rzeczywistą awarię transakcji, status API przy nadal zajętej bazie, limit kolejki i licznik pominięć, odzyskanie zapisu bez pobrania źródła oraz zamknięcie przy ponownej blokadzie. W pomiarze lokalnym odpowiedzi samolotów zajęły do około **5 ms**, zdrowia **3 ms**, komunikatów **44 ms**, historii **65 ms**, zamknięcie workera **67 ms**. To wynik pojedynczego testu na tym sprzęcie, nie gwarancja opóźnień. Osobne testy obejmują retencję podczas backoffu i pełny czas cache po wolnym pobraniu HTTP.

Końcowa weryfikacja po rozdzieleniu zapisu: **563 testy zaliczone**, regresje Node i Chromium oraz pełny smoke test atlasu przechodzą; Ruff i `git diff --check` bez błędów. Pozostaje znane ostrzeżenie zależności Starlette/httpx.
