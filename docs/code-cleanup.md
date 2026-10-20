# Przegląd i porządkowanie aplikacji — 13.10.2026

Aktualizacja 18.10.2026: próbki są syntetyczne, kopie źródłowe i zbędne raporty usunięto, a grupa `pdf-check` i PyMuPDF zostały usunięte. Poniższe dawne liczby zależności i opisy narzędzi dokumentują wcześniejszy stan.

Usunięto kod obsługujący wycofany tryb redakcyjny: API `/api/events` i `/api/review`, akceptację/korektę/odrzucenie/scalanie/rozdzielanie, budowanie kandydatów, gate publikacji, struktury EventData/Candidate/OccurredTime, formularze, kolejkę, wybór wcześniejszego trybu, nieskuteczne filtry i ich CSS. Repozytorium zapisuje teraz dokumenty i wersje, bez tworzenia wydarzeń, zadań operatora lub decyzji modeli. Interfejs ma tylko Sytuację i Źródła.

Usunięto legacy parser JSON IMGW oraz zależność PDF adaptera od niego. Zniknęły metadane `auto_publish`, priorytet redakcyjny, generowane skróty i klasyfikacja propozycji w adapterach; pozostały dane faktycznie odczytane ze źródła i diagnostyka. Śledzenie znanych aktywnych PDF opiera się na aktualnych metadanych dokumentów, bez tabel dawnych wydarzeń. Dla HTML usunięto niewykorzystywane śledzenie ostrzeżeń; zachowano zadany zakres list ostatnich siedmiu dni. Spójny User-Agent WICI jest też używany do sprawdzania robots.

Dawny etap porządkowania usunął nieużywane zależności i parsery. Aktualne próbki są syntetyczne; historyczne kopie źródłowe i PyMuPDF usunięto 18.10.2026.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Po uproszczeniu nadal waliduje się źródłowe czasy, obszary i limity tekstu. Oryginały PDF i historia mają sprawdzony `original_url`; obcy adres w polu pochodzenia nie zastępuje wydawcy. Spóźniony PDF zapisuje się w historii bez cofania widoku; odwołanie ma natychmiastowy status wydawcy, bez operatora. Wersja parserów źródeł została podniesiona, więc pierwszy odczyt po tej zmianie może zapisać wersję z uproszczonymi metadanymi również przy niezmienionej treści.

## Ponowny audyt — 17.10.2026, WICI 0.16.0

Punktem odniesienia był czysty commit `d33845c`. Sprawdzono śledzony kod Python, JS, HTML i CSS, zasoby, skrypty oraz zależności. Kandydatów ze skanu AST i wyszukiwania odwołań weryfikowano w historii Git i testach; brak zwykłego wywołania nie wystarczał do usunięcia walidatora, callbacka, endpointu czy pola zapisanego w bazie. Zakres zmian jest niewielki, ponieważ duży wycofany mechanizm redakcyjny usunął już commit `84afc85`.

### Usunięte elementy i dowody

| Element | Dowód zbędności |
|---|---|
| Trzy słowniki z `kind/category/title/summary` w awaryjnych ścieżkach `sources/imgw.py` i `sources/imgw_pdf.py` | Pochodziły z `1868e77`. Od `84afc85` funkcja `sources.normalize.document()` odrzuca wszystkie cztery klucze whitelistą, więc efektem zawsze był pusty słownik. Zastąpiono je `{}`. Pełne wyniki przed i po są identyczne dla 12 przypadków i 151 dokumentów, w tym dziewięciu rzeczywistych PDF i wszystkich trzech zmienionych ścieżek: nieznanej nazwy, nieczytelnego PDF i niepełnej sekcji. Diagnostyka i `contract_validated=False` pozostają. |
| `auto_publish_count` w `scripts/check_sources.py` | Metrykę dodano w `1868e77`, ale `84afc85` usunął jej pole wejściowe `fields.auto_publish` z adapterów. Nie ma aktywnych odbiorców metryki w repozytorium; jedyny zapis poza skryptem to historyczny raport usunięty podczas porządkowania próbek. Usunięto wyłącznie tę metrykę, pozostawiając status, dostępność, liczbę dokumentów, komunikat i pokrycie. |
| CSS `.empty-icon` | Ostatni element usunięto przy wprowadzeniu Atlas w `040223e`; brak tworzenia tej klasy w JS. |
| CSS `.page-heading label` | Etykieta filtra `review-state` zniknęła wraz z trybem redakcyjnym w `84afc85`; obecny nagłówek Źródeł zawiera tekst. |
| CSS `.filter-options>label` — dwa wystąpienia; `.filters>label:has(#province)`; `.filters>.check` | Od `040223e` te kontrolki znajdują się wewnątrz `.filter-options-body`. Selektory bezpośrednich dzieci nie pasują do obecnej struktury. Zachowano działające reguły `.filter-options-body>label` i `.filters>.daily-controls`. |
| Zmienne CSS `--amber` i `--blue` | `--amber` zadeklarowano w `1868e77`, bez konsumenta w historii. Ostatnie `var(--blue)` zniknęło w `040223e`. Brak odwołań także przez JS, `getPropertyValue`, `setProperty` i zasoby. |
| SVG `<symbol id="signal">` w `static/icons.svg` | Ostatni odnośnik zastąpiło obecne logo w `45a0246`. Wszystkie dziewięć obecnych odnośników SVG wskazuje osiem zachowanych symboli. |

Wyszukiwanie obejmowało również klasy i style tworzone dynamicznie, odnośniki SVG, testy i skrypty. Wszystkie pięć unikalnych usuniętych selektorów CSS miało zero dopasowań zarówno w HTML, jak i w pięciu rzeczywistych stanach DOM: mapa z dynamicznymi kartami, rozwinięte filtry, szczegóły z historią, dynamiczne karty Źródeł oraz telefon 320 px. Usunięcie CSS i symbolu SVG zmniejszyło zasoby o 565 bajtów.

### Aktualizacja istniejących sprawdzeń

- `tests/test_runtime.py::test_request_limit` korzysta teraz z istniejącego `/api/sources/rso/refresh`, zamiast wycofanego w `84afc85` `/api/review/1/resolve`. Nadal wymaga odpowiedzi 413 dla 65 537 bajtów; zabezpieczenia i test pozostają aktywne.
- `scripts/check_atlas_ui.cjs` oczekuje ośmiu obecnych grup warstw. Pięć było poprawne przy wprowadzeniu Atlas, ale kolejne grupy dodały kolej (`7f979f7`), autobusy (`4209c54`) i zobrazowania (`d33845c`). Skrypt zachowano i uruchomiono z powodzeniem.

### Zależności i elementy zachowane

Nie usunięto żadnego pakietu: wszystkie osiem zależności runtime ma rzeczywiste importy. FastAPI obsługuje API, Uvicorn uruchamia serwer, HTTPX transport, BeautifulSoup adaptery HTML i indeks IMGW, Pydantic walidację, pypdf parser PDF, websockets AIS, a `gtfs-realtime-bindings` jest importowane jako `google.transit` w integracji autobusów. To ostatnie nie jest nieużywane mimo braku importu pod nazwą pakietu.

Stan historyczny sprzed porządkowania próbek: grupa `dev` jest używana przez testy i lint; `pytest-asyncio` ładuje plugin przez entrypoint i `asyncio_mode=auto`. Grupa `geo` służy generatorom lokalnych granic i obszaru wodnego, `pdf-check` odtwarzaniu oraz redakcji i renderowaniu próbek PDF. Hatchling pozostaje backendem budowania. Wszystkie 36 pakietów w grafie `uv.lock` jest osiągalnych; brak osieroconych wpisów. Opcjonalna zależność używana wyłącznie przez narzędzie developerskie nie jest z tego powodu zbędna.

Pozostawiono historyczne migracje i tabele, zgodność dawnych konfiguracji `[llm]`, uzupełnianie starego syntetycznego demo, walidatory i callbacki wywoływane przez biblioteki. Zachowano też `brand/mark.svg` jako źródłowy wariant znaku, pełny Leaflet i zasoby geograficzne. Brak podstaw do usuwania nazwanych funkcji lub całych modułów JS/backendu. Nie zmieniono limitów, blokad, ochrony Host/Origin/CSRF, izolacji demo, minimalizacji danych, kontroli URL ani obsługi nieaktualnych danych i spóźnionych odpowiedzi. Nie modyfikowano konfiguracji z kluczami ani baz w `var/`.

### Wyniki weryfikacji

| Sprawdzenie | Wynik |
|---|---|
| `uv run --locked pytest -q` przed i po | **461 passed** w obu przebiegach; po zmianach 6,48 s. |
| `node --test tests/ui_*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs tests/buses_ui.cjs tests/imagery_ui.cjs` przed i po | **93 passed**, zero błędów, pominięć i anulowanych testów. |
| `uv run --locked ruff check .`, `uv lock --check`, `git diff --check`, `node --check scripts/check_atlas_ui.cjs` | Wszystkie poprawne. |
| Porównanie parserów IMGW przed i po | Identyczne pełne wyniki dla **12 przypadków / 151 dokumentów**. Dodatkowo 100 istniejących testów źródeł, PDF i repozytorium przeszło przed końcowym pełnym zestawem. |
| `check_sources.main()` offline z czterema adapterami i MockTransport | Statusy success/partial/error, dostępność, 0–3 dokumentów, komunikaty, pokrycie oraz zgodność stdout i JSON poprawne; bez usuniętej metryki, rzeczywistej sieci i zapisu historycznego raportu. |
| `scripts/check_atlas_ui.cjs` w Chromium na odizolowanym DEMO | Filtry, daty, szczegóły/historia, osiem grup warstw, odtwarzanie pogody i Źródła poprawne. Szerokości 1440, 1366, 768, 390 i 320 px; zero błędów JS i żądań zewnętrznych. |
| CLI na osobnym porcie i katalogu tymczasowym | Start i pięć komunikatów demo poprawne; druga instancja odrzucona bez zatrzymania pierwszej; SIGINT bez tracebacka; restart zachował rekordy; port zwolniony. Własne procesy zatrzymane. |

Pozostało jedno istniejące ostrzeżenie Starlette o użyciu HTTPX przez TestClient. Nie jest ono dowodem zbędności HTTPX, używanego przez aplikację. Testy integracji korzystały z lokalnych fixture i atrap; audyt nie potwierdza bieżącej dostępności zewnętrznych dostawców ani pełnego pokrycia wszystkich możliwych zachowań.

## Naprawa uruchamiania na istniejącej bazie LIVE — 17.10.2026

Po audycie użytkownik zgłosił `Database schema is newer than this application`. Lokalna baza LIVE ma `user_version=8`, a kod po wcześniejszym przywróceniu czystego `main` zawierał tylko migracje `001`–`004`. Poprzednie sprawdzenia nowych baz i odizolowanego demo nie wykrywały tego lokalnego stanu. Kontrola odrzucająca nieobsługiwaną nowszą bazę zadziałała prawidłowo i pozostaje bez zmian.

Przywrócono wyłącznie historyczne migracje `005_observations.sql`, `006_ground_motion.sql`, `007_night_lights.sql` i `008_ground_motion_provenance.sql`. Pierwsze trzy odzyskano dokładnie z lokalnego obiektu Git `9f83d1ed2da8acf0e09b05d7fd635f1502243e81`; treść czwartej pochodzi z zachowanego zapisu jej tworzenia w lokalnej historii pracy. Łańcuch `001`–`008` odtwarza wszystkie 69 obiektów rzeczywistego schematu LIVE z identycznym SQL po normalizacji białych znaków. Nie odtwarzano dawnych kolektorów ani interfejsów, nie obniżano wersji bazy i nie kasowano tabel.

W bazie pozostały również aktywne wpisy wycofanych źródeł. Scheduler pomija teraz nieobsługiwane identyfikatory w planowaniu i widoku Źródeł, zamiast próbować uruchamiać brakujące adaptery. Rekordy historyczne pozostają w bazie. Istniejący test harmonogramu sprawdza pomijanie takiego źródła i zachowanie jego rekordu. Test starego rejestru modeli buduje rzeczywisty schemat v2; nowe testy obejmują migrację v4/v7 do v8, ponowne otwarcie v8 oraz zachowanie metadanych i danych. Odrzucanie nieznanego schematu v99 nadal jest testowane.
