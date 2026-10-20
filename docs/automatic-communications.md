# Automatyczne komunikaty i mapa — 13.10.2026

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Aktualne, późniejsze zlecenie użytkownika zastępuje zatwierdzanie komunikatów modelem lub przez operatora. Oryginalny PRD i wcześniejsze dowody pozostają historyczne. Usunięto aktywną integrację modeli: klienta Decisions, workera, loader klucza, płatne skrypty i odpowiadające im testy. Usunięto prywatny plik klucza używany przez WICI. Stara sekcja `[llm]` w konfiguracji jest ignorowana, więc nie reaktywuje wywołań. Historyczne decyzje, rozliczenia i interpretacje w SQLite zachowano; migracja 003 jest nadal potrzebna do zgodnego odczytu istniejących baz. Nie ma wywołań OpenAI ani kosztów modeli.

## Droga komunikatu

Istniejący scheduler odczytuje cztery dotychczasowe oficjalne źródła. Adapter rozpoznaje kontrakt, sprawdza dostęp i oczyszcza tekst przed zapisem. SQLite zachowuje dokument, wersje, tożsamość i daty. Nowy widok jest odczytem najnowszych zapisanych dokumentów — nie potrzebuje rekordu zatwierdzonego wydarzenia. Nowy materiał, zmiana, odwołanie i ćwiczenie pojawiają się bez ręcznej decyzji; treść komunikatu pozostaje oczyszczonym cytatem wydawcy. Odrzucenie dawnej interpretacji nie usuwa dokumentu źródłowego z tego widoku. Nie przywracamy zminimalizowanych danych osobowych, operacyjnych ani szczegółowych pozycji służb.

Domyślny widok live: publikacje i aktualizacje dla wybranego dnia Europe/Warsaw. Przy braku dat źródłowych jawnie używa pierwszego lokalnego odczytu. Opcjonalnie dzisiejszy widok obejmuje także obowiązujące/zapowiedziane IMGW i komunikaty w znanym oknie publikacji RSO; w live opcja domyślnie wyłączona. Nie uznajemy okna RSO za fizyczną ważność zagrożenia. W demo opcja jest włączona, żeby scenariusz obejmował ostrzeżenia z poprzedniego dnia. Nieznane czasy pozostają nieznane. Tematy to lokalne etykiety nawigacji, bez prognozowania przebiegu i niezależnej oceny sytuacji.

Wybór wcześniejszego dnia pokazuje zapisane dokumenty według publikacji/aktualizacji, w aktualnej zapisanej wersji. Szczegóły zawierają wszystkie zachowane wersje. To lokalne archiwum dokumentów, nie rekonstrukcja mapy lub stanu wiedzy w danej chwili; nie pobiera brakujących dni z internetu.

## Mapa i kolory

- Tylko rozpoznane kody administracyjne z lokalnego PRG. RSO wykorzystuje metadane województw, IMGW obszary tabeli ostrzeżenia. Brak kodu nie powoduje tworzenia zastępczego miejsca zdarzenia.
- RCB: tylko nazwa województwa jawnie wymieniona w klauzuli „województwo/woj.”, z obsługą typowych odmian polskich nazw. Takie oznaczenie jest obszarem powiadomienia, nie miejscem ataku/kolizji ani zagrożeniem obejmującym całe województwo. Niewykryty obszar pozostaje na liście.
- Karteczka województwa jest uchwytem nawigacji w centrum granic na mapie. Punkt nie jest przedstawiany jako miejsce zdarzenia. Kliknięcie pokazuje listę komunikatów obszaru; wybranie pozycji otwiera treść, oryginał, daty i wersje.
- Powiadomienia niebieskie. Rozpoznane stopnie IMGW 1/2/3: żółty/pomarańczowy/czerwony; wygasłe i odwołane obszary IMGW szare. Przy wielu ostrzeżeniach obszaru kolor odpowiada najwyższemu znanemu, niewygasłemu i nieodwołanemu stopniowi. Nie wyliczamy własnego ryzyka.
- Równoważne dokumenty powiatowe IMGW grupują się wyłącznie przy identycznym PDF, czasie wydania, treści, ważności, stopniu i statusie. To grupowanie UI, nie scalenie dokumentów ani utrata historii.

Po przeglądzie kodu usunięto wcześniejszy tryb interpretacji, kolejkę i formularze redakcyjne. Pozostają wyłącznie automatyczne komunikaty oraz źródła. Historyczne tabele w SQLite zachowano bez nowych zapisów; szczegóły i aktualne wyniki: [code-cleanup.md](code-cleanup.md).

## API

`GET /api/communications`: parametry `date=YYYY-MM-DD`, `voivodeship`, `source_id`, `communication_type` (`warning/notice/exercise`), `category`, `include_active`, `limit` (1–1000). Odpowiedź `items/total/limited`; każdy rekord zawiera identyfikator dokumentu, źródło, tytuł, pełny oczyszczony opis, daty, wersję, lokalizacje i jawne oznaczenia. `selection_basis` wskazuje publikację, aktualizację lub włączenie starszego komunikatu przez okno/ważność. `display_window` RSO jest odrębne od fizycznej ważności. Dopuszczamy tylko cztery źródła z zapisanym `contract_validated=true` i `access_allowed=true`.

`GET /api/communications/{document_id}`: aktualny komunikat i historia źródłowych wersji. Nie zatwierdza interpretacji i nie tworzy nowego wydarzenia. Endpointy `/api/events`, `/api/review` i akcje redakcyjne usunięto. Historia źródeł zawiera `original_url` przypisany danej wersji; odnośnik jest ograniczony do zweryfikowanego formatu wydawcy.

## Dowody pierwszej próby automatycznych komunikatów (przed porządkowaniem)

Szczegółowe wyniki historycznego odczytu live usunięto 18.10.2026. Ponowne sprawdzenie zapisuje wyniki lokalnie w `tmp/live-checks/`.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

264 testy Python i 6 JS przechodzi, Ruff i składnia JS poprawne, `uv lock --check` bez zmiany 34 pakietów. Usunięte testy dotyczyły usuniętej integracji modeli; zastąpiono je 36 próbami nowego widoku. Wśród nich 18 syntetycznych scenariuszy RSO (zastąpiły wcześniejsze rzeczywiste próbki), zachowanie dosłownej treści i warunków, zero decyzji modeli, cztery źródła, aktualizacja/odrzucenie interpretacji/dedup/restart, dzień Warsaw, osobne okno RSO, brak wyimaginowanej lokalizacji, jawne nazwy województw RCB, kontrakt/limit/404/niepoprawna data, odziedziczona konfiguracja LLM, zachowanie dawnego rozliczenia, tematy i negacja ćwiczeń, stopień/odwołanie i ścisłe grupowanie PDF. Dotychczasowe testy parserów i jakości MVP nadal przechodzą. Jedyny warning pochodzi z upstream Starlette TestClient.

## Granice i pominięte próby

Automatycznie pokazujemy poprawnie odczytane i oczyszczone komunikaty w ustalonym zakresie źródeł. Awaria dostępu, zmiana kontraktu, brak opublikowanego tekstu lub lokalizacji nie zostają ukryte ani zastąpione zgadywaniem. SG ma liczne zminimalizowane materiały — widok pokazuje bezpieczny odnośnik i metadane zamiast szczegółów operacji. Automatyczne tematy i wykrywanie nazw województw to ograniczone reguły, nie pełne rozumienie dowolnego języka. Zachowana dosłowna treść pomaga odczytać zastrzeżenia niezależnie od etykiety.

Nie wykonano długoterminowego pilota, porównania wydajności dla 10k dokumentów nowego endpointu ani przeglądu wizualnego każdego stopnia IMGW na dzisiejszych ostrzeżeniach (zestaw był pusty). Nie odtwarzamy brakujących danych z przerw ani historycznej mapy. Wymagane jest samodzielne uruchomienie aplikacji; nie dodano autostartu ani wdrożenia. Brak materiałów nie oznacza braku zagrożeń. Oficjalne pochodzenie i zgodność cytatu nie są niezależnym potwierdzeniem zdarzenia.
