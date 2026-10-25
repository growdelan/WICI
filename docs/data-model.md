# Model danych WICI

SQLite w trybach live i demo zachowuje dokumenty źródłowe oraz ich kolejne wersje. Migracje `001`–`019` są transakcyjnym łańcuchem schematu; błędna lub nowsza nieobsługiwana wersja przerywa start bez resetu danych. Klucze obce, WAL i wspólna blokada repozytorium chronią zapis kolektora oraz kolejki historii stacji. Pobieranie HTTP odbywa się poza transakcją.

## Aktywne tabele

| Tabela | Rola |
|---|---|
| `sources` | Stan dostępu, interwał, ostatni wynik, zakres i następna próba. |
| `fetch_runs` | Wyniki pobierania i liczby rekordów; szczegóły zachowywane przez 30 dni. |
| `documents` | Tożsamość `(source_id, identity_key)`, URL, pierwszy/ostatni odczyt i aktualna wersja. |
| `document_versions` | Oczyszczony tytuł/tekst, metadane, czasy źródła, SHA256 i wersja parsera. |
| `app_state` | Ostatni tick schedulera, wykrywanie przerw w pracy oraz ostatni zakres i błędy IODA. |
| `ioda_entities` / `ioda_events` / `ioda_alerts` / `ioda_samples` | Osobny słownik i historia detekcji oraz sygnałów dostępności internetu; opis poniżej. |

Pozostałe tabele (`events`, `event_evidence`, `event_revisions`, `review_items`, `operator_actions`, `model_decisions`) zachowują historię wcześniejszego produktu. Nie ma już kodu tworzącego ani zatwierdzającego te rekordy, ich API lub formularzy. Nie usuwa się ich podczas sprzątania kodu. Weryfikacja porównuje liczby i SHA256 całych tabel przed/po rzeczywistym pobieraniu.

Migracja `004` dodaje aktywne obserwacje FIRMS. Migracje `005`–`008` zachowują zgodność z bazami rozszerzonymi przez później wycofane integracje obserwacji, EGMS i nocnych świateł. Pozostają jako historia schematu, bez przywracania tych integracji do interfejsu lub kolektorów. Scheduler pomija niewspierane identyfikatory źródeł w planowaniu i API źródeł, zachowując ich rekordy oraz powiązane dane w bazie.

## Dokument i wersje

`Document` waliduje adres HTTP(S), źródłowe czasy ze strefą, granice długości i metadane `SourceMetadata`/`SourceArea`. Metadane obejmują obszary administracyjne, jawne okno/ważność i stopień ostrzeżenia. Przejrzane źródła są jedynym wejściem kolektora. HTML i potencjalnie wrażliwe treści oczyszcza się przed zapisem. Metadane parserów nie zawierają nowych propozycji interpretacji, statusów zatwierdzania ani notatek operatora.

Identyczny ponowny odczyt aktualizuje czas sprawdzenia i transportowy URL, bez dodatkowej wersji. A → B → A tworzy trzy wersje. Zmiana transportowego PDF z tym samym ostrzeżeniem nie jest zmianą jego treści. Spóźnione starsze wydanie PDF trafia do historii bez cofania bieżącego widoku; kolejne powtórzenie tego starego wydania nie tworzy duplikatu. Numery lokalnych wersji oznaczają kolejność zapisu, a nie numery wersji nadane przez wydawcę.

Odwołanie lub zmiana źródła aktualizuje komunikat bez decyzji operatora. Historia przechowuje poprzedni tekst oraz bezpieczny odnośnik do fizycznego PDF właściwego danej wersji. Obce adresy w polu pochodzenia nie zastępują URL wydawcy. Brak dokumentu w odpowiedzi i awaria źródła nie kasują danych.

## Widok dnia, czas i mapa

Lista łączy aktualne dokumenty z wybranym dniem publikacji/aktualizacji Europe/Warsaw; przy braku dat używa jawnie oznaczonego pierwszego odczytu. Archiwum nie rekonstruuje historycznej mapy. Status IMGW wynika z jawnych dat i odwołania; nie ustala fizycznego końca zjawiska. RSO ma osobne okno udostępniania komunikatu. Brak dat nie jest zastępowany czasem pobrania.

Mapa używa rozpoznanych kodów PRG, z rolą obszaru ostrzeżenia lub powiadomienia. Nie tworzy miejsca incydentu na podstawie siedziby służby lub środka województwa. Karteczka województwa służy nawigacji; rekord bez geometrii pozostaje na liście. Szczegóły zachowania i publicznych endpointów: [automatic-communications.md](automatic-communications.md).

## IODA (migracja 009)

Niezależne tabele: `ioda_entities` (typ/kod/nazwa/zweryfikowane metadane), `ioda_events` (klucz typu/kodu/sygnału/metody/początku, miary, źródłowa granica czasu, potwierdzony alertem normal koniec lub NULL, pełny payload i pochodzenie, czasy pomiaru/pobrania/pierwszego zapisu, flaga synthetic), `ioda_alerts` (źródłowe wartości i odniesienia z czasem, metodą, pochodzeniem), `ioda_samples` (jednostka/sygnał/czas/krok, wartość nullable, nativeStep, pobranie i pochodzenie). Nie używają wycofanych tabel obserwacji ani redakcji. Scheduler używa istniejących `sources`, `fetch_runs`; ostatni zakres i częściowe błędy w `app_state.ioda_run`.

Deduplikacja i aktualizacja nie opierają się na zmiennej długości zdarzenia. Nie ma identyfikatora upstream event: zachowany payload i klucz pochodny są jawnie rozróżnione. Brak rekordu nie zamyka zdarzenia; NULL pomiaru nie zeruje poprzedniej wartości. Retencja pomiarów/alertów 30 dni; zdarzenia wymagają też 30 dni od ostatniego pobrania. Historia pozostaje lokalną najnowszą zapisaną reprezentacją, bez rekonstrukcji dawnego stanu wiedzy. Szczegóły semantyki i mapowania: [ioda.md](ioda.md).

## Stanowisko analityczne (migracje 015–016)

Migracja `015` dodaje projekcję `catalog_objects`, przypisania `catalog_object_areas`, stan projekcji `workspace_meta` i nazwane konfiguracje `workspace_views`. Trwałe odwołania mają postać `communication:<documents.id>`, `hydro_station:imgw:<id>`, `air_quality_station:gios:<id>` i `area:prg:<kod>`. Zmiana nazwy stacji nie zmienia jej tożsamości. Komunikaty nadal przechowują treść i wersje w dotychczasowych tabelach; projekcja wskazuje aktualną wersję i aktualizuje się w tej samej transakcji. Idempotentne uzupełnienie projekcji przy starcie nie tworzy wersji dokumentów. Zapisywane widoki zawierają walidowaną konfigurację, `schema_version` i rewizję do kontroli równoczesnych zmian.

Migracja `016` dodaje:

| Tabela | Znaczenie |
|---|---|
| `station_sensors` | Trwałe powiązanie stanowiska GIOŚ ze stacją i parametrem; dwa stanowiska PM10 pozostają odrębne. |
| `station_measurements` | Wartość nullable, jednostka, źródłowy i rozstrzygnięty czas, pobranie, rewizja, jakość czasu, pochodzenie i progi dostępne w odpowiedzi. |
| `station_index_observations` | Oficjalny indeks GIOŚ wraz z osobnymi czasami danych i obliczenia; nie wynika z wybranej substancji. |
| `workspace_source_runs` | Wynik nowego pobrania zasobu, liczby rekordów i kompletność odpowiedzi; bez surowych odpowiedzi i kluczy. |
| `station_observation_keys` | Skrót tożsamości oraz pierwszy czas odczytu próbki o nieznanym lub przyszłym czasie; uniemożliwia odnawianie retencji przez powtarzanie tej samej błędnej próbki. |

Ograniczona kolejka przyjmuje wyłącznie nowe odpowiedzi istniejących usług na żądanie. Cache nie dopisuje próbek i nie odmładza czasu pobrania. Zapis korzysta z tego samego połączenia SQLite i `RLock`; zapytania stanowiska analitycznego czytają lokalną bazę. Błąd lub przepełnienie kolejki jest widoczne w `/api/workspace/status`. Błąd sieci i częściowa lista nie usuwają katalogu ani poprawnych pomiarów. Dopiero pełny poprawny wykaz może oznaczyć stację jako nieobecną w bieżącym katalogu, zachowując jej rekord.

Klucz obserwacji obejmuje obiekt, stanowisko, parametr i źródłowy czas. Zmiany A → B → A tworzą trzy niezmienne rewizje; `is_current` wskazuje ostatnią rewizję tej obserwacji, umożliwiając zliczanie jej raz na osi czasu. NULL pozostaje jawnym brakiem wartości. Historyczne progi i czas pobrania rewizji nie są zastępowane bieżącymi. Próby ze złym lub przyszłym czasem nie trafiają do poprawnych szeregów. Retencja wartości wynosi 14 dni od czasu obserwacji, a dla czasów błędnych/przyszłych — od pierwszego pobrania; minimalne skróty tożsamości pozostają po usunięciu wartości, aby kolejne kopie nie wydłużały retencji. Lokalny worker usuwa przeterminowane wartości przy starcie, zapisie nowej odpowiedzi i co godzinę podczas pracy aplikacji, również bez pobierania źródeł.

Historia obejmuje odczyty wykonane na żądanie i może mieć luki. Metadane oraz geometria stacji opisują ostatni znany katalog. Przesunięcie kursora nie rekonstruuje historycznej lokalizacji ani stanu wiedzy całej mapy. [Plan i zakres pierwszego etapu](plan-stanowisko-analityczne-etap-1.md).

## Historia alarmów Ukrainy (migracja 018)

Migracja rozszerza typy katalogu o `ua_region` i `civil_alert`. Przebudowa ograniczenia CHECK zachowuje dokumenty, przypisania obszarów, sensory, pomiary, indeksy oraz listę obserwowanych z migracji 017. Klucze obce pozostają włączone.

| Tabela | Znaczenie |
|---|---|
| `workspace_ukraine_state` | Trwała decyzja o rejestracji, czasy ostatnich odczytów, wersja źródła, stan i przyczyna luki. |
| `workspace_ukraine_regions` | Oryginalny klucz, poziom regionu, jawne pochodzenie powiązania z obwodem, ostatnia geometria i bieżący stan. |
| `workspace_ukraine_episodes` | Lokalna tożsamość epizodu, pierwsza/ostatnia obserwacja, czas źródła i niepewny przedział zakończenia. |
| `workspace_ukraine_runs` | Rzeczywiste pełne odczyty oraz znaczniki przerw; powtórzenie cache nie tworzy pokrycia. |
| `workspace_ukraine_observations` | Niezmienne zmiany stanu, powodów i czasu źródłowego z przypisaniem do odczytu i epizodu. |

`ukraine_history.py` projektuje dane i oblicza przedziały wraz z pokryciem; nie wykonuje HTTP. Baza przechowuje czas UTC. Domyślna rejestracja jest wyłączona; lista obserwowanych i konfiguracje widoków nie zmieniają tej opcji. Granice regionów pozostają cache danych pobranych podczas działania aplikacji i nie są dystrybuowane z pakietem. [Semantyka i użycie](ukraine.md#analiza-historia-alarmów-i-porównanie-regionów-v0320).

## Teczki analiz (migracja 019)

| Tabela | Znaczenie |
|---|---|
| `workspace_dossiers` | Nazwa, opis, rewizja i czasy utworzenia/zmiany teczki. |
| `workspace_dossier_pins` | Unikalny w teczce identyfikator obiektu, etykieta i źródło z chwili przypięcia. |
| `workspace_dossier_notes` | Tekst użytkownika z własną rewizją oraz czasami utworzenia i edycji. |
| `workspace_dossier_materials` | Niezmienna kopia danych z kontekstem wyboru, czasem zapisu, rozmiarem i SHA-256. |

Klucze obce wiążą zawartość wyłącznie z teczką. Brak kaskady od katalogu
i tabel historii pozwala zachować przypięcia oraz materiały po retencji
pomiarów, tras i alarmów. Trigger zabrania aktualizacji zapisanej kopii;
użytkownik może ją usunąć lub utworzyć nowy materiał. Notatki pozostają
oddzielone od informacji źródłowych. Zmiany zawartości podnoszą rewizję teczki,
chroniąc jej edycję i usunięcie przed nadpisaniem równoległej pracy.

Serwer zbiera materiał pod blokadą repozytorium z istniejących metod odczytu,
sprawdza zgodność zapytania i rewizji, doczytuje strony historii oraz zapisuje
JSON atomowo. Kopia nie zależy od działającego kontekstu zapytania po restarcie.
Dotychczasowe schematy dokumentów, obserwowanych, rejestracji i zapisanych
stanowisk pozostają bez zmian. [Zakres i obsługa](analysis-dossiers.md).
