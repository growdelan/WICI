# Model danych WICI

SQLite w trybach live i demo zachowuje dokumenty źródłowe oraz ich kolejne wersje. Migracje `001`–`009` są historycznym, transakcyjnym łańcuchem schematu; błędna lub nowsza nieobsługiwana wersja przerywa start bez resetu danych. Klucze obce, WAL, blokada repozytorium i jeden worker chronią zapis. Pobieranie HTTP odbywa się poza transakcją.

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
