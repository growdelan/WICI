# GIOŚ — jakość powietrza

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Warstwa „Jakość powietrza GIOŚ” znajduje się w grupie „Pogoda” i jest domyślnie wyłączona.
Jest bieżąca, niezależna od dnia publikacji; wspólny wybór obszaru ogranicza stacje. Wybierz stację, parametr i stanowisko;
kliknięcie stacji na mapie także wybiera ją do szczegółów. Lista zawiera również stacje bez
prawidłowych współrzędnych. Dla każdego z PM10, PM2,5, NO₂, SO₂, O₃, CO i benzenu szczegóły
wskazują dostępność. Kilka stanowisk jednego parametru pozostaje osobno do wyboru.

Wyniki godzinowe są pokazywane w tabeli, w oknie zwracanym przez bieżącą usługę (od ostatniej
pełnej godziny do trzeciej doby wstecz). Nie jest to archiwum. Dane trafiają wyłącznie do pamięci
procesu; kolektor komunikatów i SQLite nie zapisują pomiarów.

## Kontrakt źródła i jednostki

Zweryfikowano 17.10.2026 oficjalną [stronę API](https://powietrze.gios.gov.pl/pjp/content/api),
[OpenAPI](https://api.gios.gov.pl/pjp-api/v3/api-docs) i rzeczywiste odpowiedzi czterech usług:

| Zasób | Ścieżka pod `https://api.gios.gov.pl/pjp-api/v1/rest/` | Pole odpowiedzi | Limit GIOŚ |
| --- | --- | --- | --- |
| Stacje | `station/findAll` | `Lista stacji pomiarowych` | 2/min |
| Stanowiska | `station/sensors/{stationId}` | `Lista stanowisk pomiarowych dla podanej stacji` | 1500/min |
| Wyniki | `data/getData/{sensorId}` | `Lista danych pomiarowych` | 1500/min |
| Indeks | `aqindex/getIndex/{stationId}` | `AqIndex` (obiekt) | 1500/min |

To JSON-LD v1, bez zgodności ze starym API; wycofanych adresów nie używamy.
Paginacja `page` od 0, `size=500` (maksimum OpenAPI), koniec według `totalPages`.
Link `next` potrafi wskazywać nieistniejącą stronę nawet dla jednej strony, dlatego nie steruje pobieraniem.
Każda strona musi mieć zgodną liczbę stron; limit bezpieczeństwa to 20 stron i 500 rekordów na stronę.
Dla `AqIndex` zachowujemy własny czas danych źródłowych i obliczenia.

**Wszystkie stężenia API są w µg/m³, także CO.** Nie przeliczamy CO na mg/m³ jak mapa portalu.
Zero jest wynikiem. Null jest brakiem pomiaru, pusta lista jest pustą odpowiedzią.
Stanowiska manualnego nie zgadujemy z pustych danych: rozpoznajemy odpowiedź v1
`API-ERR-100003` ze wskazaniem typu manualnego. Lista stanowisk nie zawiera typu pomiaru;
UI ujawnia go po zapytaniu o wyniki. Zgodnie z dokumentacją wyniki manualne są dostępne dopiero
po 4–8 tygodniach przez usługę archiwalną; warstwa jej nie odpytuje.

[Regulamin GIOŚ](https://powietrze.gios.gov.pl/pjp/content/terms_of_service) dodatkowo
wskazuje pobieranie danych nie częściej niż dwa razy na godzinę. Przyjmujemy konserwatywnie
30-minutowy cache dla wyników i indeksu tego samego zasobu; techniczne limity minutowe
chronią pobieranie stron i różnych zasobów. Lokalny UI może odczytywać cache co 5 min.
Atrybucja używa wymaganego określenia „GIOŚ - EKOINFONET”; informujemy o wyborze fragmentu
(stacje i stanowiska) oraz przetworzeniu formatu i czasu, bez zmiany wartości stężenia.

## Czasy i aktualność

Opis OpenAPI usługi bieżącej wskazuje lokalny CEST (UTC+02) latem i CET (UTC+01) zimą.
Metadane odpowiedzi indeksu również deklarują czas lokalny. Zachowujemy surowe `source_time`;
jednoznaczny czas Europe/Warsaw normalizujemy do UTC w `observed_at`. Przeglądarka wyświetla
Europe/Warsaw. Gdy źródło poda offset, respektujemy go. Dla godziny jesiennego cofnięcia zegara
bez offsetu i nieistniejącej godziny wiosennej nie wybieramy arbitralnie `fold`: czas UTC oraz
wiek pozostają nieustalone, a surowy zapis i wartość są dostępne w tabeli.

Najnowszy poprawny wynik to maksimum jednoznacznego czasu wśród niepustych wartości,
nie pierwszy rekord. Nowszy null nie odmładza starszej wartości. Wartości z nieustalonym czasem
są policzone osobno i nie uczestniczą w wyborze najnowszej. Pomiar oraz indeks starszy niż
3 h jest nieaktualny; czas ponad 15 min w przyszłości jest oznaczony. To progi aplikacji,
nie normy jakości powietrza. Wiek backend przelicza także przy odczycie z cache, a UI co minutę.
Czas pobrania jest odrębny dla wykazu, stanowisk, wyników i indeksu. Odczyt starszy niż dwukrotność
TTL lub zachowany po awarii ma oznaczenie nieaktualności. Odświeżenie cache nie zmienia czasu pomiaru.

## Stężenie a indeks

Punkty są kolorowane według **oficjalnego indeksu ogólnego GIOŚ**, niezależnie od wybranego
zanieczyszczenia. Nie przeliczamy stężenia na indeks. Legenda korzysta z kolorów portalu
[GIOŚ](https://powietrze.gios.gov.pl/pjp/current?lang=pl), odczytanych 17.10.2026:

| Kategoria GIOŚ | Kolor |
| --- | --- |
| Bardzo dobry (0) | `#57b108` |
| Dobry (1) | `#b0dd10` |
| Umiarkowany (2) | `#ffd911` |
| Dostateczny (3) | `#e58100` |
| Zły (4) | `#e50000` |
| Bardzo zły (5) | `#990000` |
| Brak aktualnego indeksu | `#bfbfbf` |

Szary oznacza brak indeksu, oczekiwanie na odpowiedź, błąd, indeks starszy niż 3 h, nieustalony
czas (w tym DST) lub czas ponad 15 min w przyszłości. Wiek oceniamy według czasu danych
źródłowych indeksu, także podczas korzystania z cache. Dymek i szczegóły pokazują kategorię
oraz osobno czas danych, obliczenia i pobrania. Brak indeksu oznacza nieznaną jakość powietrza. Nie wyliczamy własnego
indeksu, przekroczeń norm dobowych/rocznych z godziny ani interpolacji między stacjami.

## Backend, limity i awarie

`GiosService` jest jeden na proces, współdzielony przez lokalne żądania.
Lokalne API: `GET /api/gios` oraz `?kind=sensors|data|index&id=…`. Identyfikatory są dodatnimi
liczbami 64-bitowymi. API odrzuca obce Origin i Sec-Fetch-Site, zgodnie z hydrologią.
Konfiguracja `[sources.gios] enabled = true` używa wspólnego mechanizmu `Config.enabled`;
`false` wyłącza sieć dla GIOŚ. Timeout pojedynczego połączenia bierze się z konfiguracji globalnej, maksymalnie 30 s; całe pobranie ma limit 60 s.
Wszystkie połączenia GIOŚ wykonuje backend, bez klucza i bez przekierowań.

- Cache stacji 24 h; stanowisk 6 h; wyników i indeksu 30 min; odpowiedzi manualnej 24 h.
- Cztery równoległe pobrania, współdzielone blokady eliminujące równoległe pobieranie tego samego zasobu.
- Najwyżej 1024 zasoby w LRU; stałe 32 blokady, brak narastających blokad dla dowolnych identyfikatorów.
- Limit lokalny stacji 2/min, pozostałych usług konserwatywnie 120/min każda (poniżej limitu GIOŚ).
- Maksymalnie 2 MiB rozpakowanej odpowiedzi na stronę; wymagany JSON lub JSON-LD.
- Backoff od 5 min do 1 h. Błędy HTTP 4xx (z wyjątkiem 429) oraz niepełne odpowiedzi mają backoff osobny dla zasobu; awarie transportu i usługi — wspólny dla danej usługi. Stan błędów zasobów jest ograniczony do 1024 wpisów i kasowany po udanym odczycie.
- 429 respektuje `Retry-After` w sekundach lub dacie HTTP; współbieżne odpowiedzi zawsze zachowują najdłuższy termin blokady.
- Awaria zachowuje poprzedni poprawny odczyt, jego czas pobrania i czas pomiaru; stan `error` jest jawny.
- Błędne pojedyncze rekordy dają `partial` i licznik odrzuceń. Całkowicie obcy schemat jest błędem.
- Niepełna paginacja nie zastępuje poprawnego cache; bez wcześniejszego odczytu zwracamy jawny fragment `partial`, bez zapisu do cache. `empty`, `missing`, `manual`, `partial` i `error` są odrębne.

Przeglądarka pobiera wykaz tylko dla aktywnej warstwy na widocznej mapie. Indeksy pobiera
wyłącznie dla stacji z prawidłowymi współrzędnymi w aktualnych granicach widoku Leaflet.
Wybór stacji nie uruchamia osobnego pobierania indeksu poza tą kolejką; stacja bez lokalizacji
pozostaje na liście, ale jej indeks nie jest pobierany. Stanowiska pobiera dla wybranej stacji,
szereg tylko dla wybranego stanowiska.

Kolejka indeksów dopuszcza najwyżej dwa żądania jednocześnie i odstęp co najmniej 600 ms
między startami pobrań logicznych (najwyżej 100/min w jednym kliencie). Backend nadal wspólnie egzekwuje
limit 120/min dla usługi indeksu, cztery równoległe pobrania, blokady i 30-minutowy cache
między klientami. Informacja `service_retry_after_seconds` z lokalnego API zatrzymuje całą
kolejkę na czas backoffu źródła, w tym `Retry-After`. Frontend zachowuje do 1024 wyników;
ponowne wejście stacji w widok używa cache do upływu TTL pobrania, bez odmładzania źródła.
Przesuwanie mapy zatrzymuje kolejkę; po zakończeniu ruchu granice są sprawdzane ponownie,
a żądania, które opuściły widok, są anulowane. Spóźnione odpowiedzi nie zmieniają kolorów. Nie ma masowego pobierania
sensorów w Polsce. Wyłączenie warstwy lub ukrycie mapy/karty zatrzymuje timery; tokeny generacji
ignorują spóźnione odpowiedzi. AbortController anuluje żądania przy ukryciu warstwy oraz zmianie wyboru; wspólny klient HTTP nie ponawia anulowanych żądań. Odświeżanie zachowuje wybór, otwarty dymek i rozwiniętą tabelę. Błąd połączenia z lokalnym API zachowuje również pomiar uzyskany przez równoległe żądanie tego samego wyboru — z pierwotnym czasem pobrania i oznaczeniem błędu.
Demo pozostaje całkowicie offline i zwraca `disabled`, niezależnie od konfiguracji.

## Weryfikacja

Syntetyczne próbki i pochodzenie: [tests/fixtures/gios](../tests/fixtures/gios/README.md).
`uv run pytest tests/test_gios.py` sprawdza schemat, jednostki, czas/DST, zero/null, manualne
stanowiska, paginację, częściowe rekordy, błędy transportu, rozmiar, cache, współbieżność i lokalne API.
`node --test tests/ui_gios.test.cjs` sprawdza cykl życia, spóźnione odpowiedzi i zachowanie szczegółów.
`node --test tests/gios_browser.cjs` wymaga Playwright/Chromium. Uruchamia własny serwer
z tymczasową bazą, offline demo oraz osobnym klientem MockTransport GIOŚ. Weryfikuje prawdziwy
Leaflet, formularze, tabelę, odświeżanie dymka i mobilną szerokość 390 px; nie korzysta z danych użytkownika.

Źródło danych: **GIOŚ - EKOINFONET**, Państwowy Monitoring Środowiska. Wyniki są **niezweryfikowane i mogą ulec zmianie**.

## Próba LIVE i wyniki

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Ograniczenia: dane są godzinowe i niezweryfikowane; 30-minutowy cache może opóźniać
pojawienie się nowej godziny. Nie rozstrzygamy jesiennego DST bez offsetu. Lista nie podaje
typu stanowiska, więc przy kilku stanowiskach (np. manualnym i automatycznym PM10)
trzeba wybrać właściwe stanowisko. Stanowiska spoza siedmiu obsługiwanych parametrów
pozostają poza widokiem wyników. Nie zapisujemy archiwum. Weryfikacja mobilna obejmuje Chromium,
nie fizyczne urządzenia ani wszystkie silniki przeglądarek.

## Regresje po przeglądzie

Naprawiono trzy scenariusze, odtworzone przez testy przed zmianą kodu:

- Równoległe pobranie po wyborze stanowiska i odświeżanie okresowe: poprawny pomiar, jego czas
  oraz tabela i dymek pozostają widoczne po błędzie drugiego żądania. Test obejmuje obie kolejności sukcesu.
- Odpowiedź 400/403/404 dla jednego zasobu: inne zasoby pozostają dostępne, również z cache;
  ponawianie błędnego zasobu podlega osobnemu backoffowi. Test obejmuje wyniki, stanowiska i indeks.
- Dwie równoległe odpowiedzi 429 z różnym `Retry-After`: obowiązuje dłuższa blokada,
  niezależnie od kolejności odpowiedzi; próba przed jej upływem nie dociera do źródła.

Łącznie dodano 13 przypadków regresyjnych (11 Python i 2 Node). Ponownie przeszła pełna
regresja Python/Node oraz testy Chromium GIOŚ i hydrologii; Ruff i kontrola diffu bez uwag.

## Kolorowanie indeksu w widoku mapy

Podczas ponownego równoległego uruchomienia Chromium wystąpił pojedynczy timeout istniejącego testu hydrologii przy usuwaniu pustego wykazu; test GIOŚ przeszedł. Hydrologia uruchomiona samodzielnie oraz oba testy uruchomione kolejno (`--test-concurrency=1`) przeszły. [Diagnostyka nieudanego przebiegu](evidence/gios-browser-parallel-timeout.txt); [końcowy przebieg seryjny](evidence/gios-browser-tests.txt).

## Regionalny widok i postęp

Wybór „Obszar danych” filtruje punkty i listę stacji według granic PRG. Kolejka indeksów obejmuje jedynie stacje widoczne na mapie i wewnątrz regionu; zmiana regionu anuluje poprzednie prace, zachowując krajowy cache listy stacji i indeksy. Panel pokazuje odczytane indeksy względem liczby stacji w aktualnym widoku. Stacje bez współrzędnych pozostają dostępne przy wyborze całej Polski. Zachowano kolory oficjalnego indeksu, szary brak lub nieaktualność, limity współbieżności, cache i Retry-After. [Szczegóły zakresu i ładowania](regions.md).
