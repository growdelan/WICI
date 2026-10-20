# Model danych i decyzji

SQLite przechowuje bieżący stan i kolejne istotne wersje. Pliki `migrations/NNN_*.sql` są stosowane w transakcjach według `PRAGMA user_version`; nieznana nowsza wersja lub błąd migracji przerywa start bez resetu danych. Włączono klucze obce, WAL i ograniczone oczekiwanie na blokadę. Repozytorium chroni połączenie blokadą w obrębie jednego procesu; serwer pracuje z jednym workerem. Operacje HTTP nie należą do transakcji zapisu.

## Encje

| Tabela | Znaczenie |
|---|---|
| `sources` | Kontrakt i stan dostępu adaptera, interwał, terminy, wynik, pokrycie i walidatory HTTP. |
| `fetch_runs` | Wynik konkretnej próby, liczby rekordów, rzeczywisty zakres, bez pełnych odpowiedzi w logach. |
| `documents` | Unikalne `(source_id, identity_key)`, kanoniczny URL, pierwsze i ostatnie sprawdzenie. |
| `document_versions` | Kolejny numer, SHA-256 istotnej treści i pól, oczyszczony tekst, źródłowe czasy i wersja parsera. |
| `events` | Walidowany JSON bieżącego rekordu, osobne osie statusów, wersja, oczekująca kontrola i docelowe połączenie. |
| `event_evidence` | Konkretna wersja dokumentu, ścieżki wspieranych pól, fragment, relacja i znane pochodzenie pierwotne. |
| `event_revisions` | Pełny stan rekordu i dowodów, różnica, aktor, czas i powód. |
| `review_items` | Aktualna propozycja oraz zadania `pending`, `approved`, `rejected`, `linked`, `superseded`. |
| `operator_actions` | Dziennik publikacji, korekt, odrzucenia, powiązania i rozdzielenia. |
| `app_state` | Małe wartości lokalnego stanu systemu. |

Pola złożone są małymi strukturami Pydantic: `EventData`, `Location`, `OccurredTime`. Rodzaj (`warning/event/context`), podstawa informacji, spójność, przebieg wydarzenia, ważność ostrzeżenia i stan publikacji są niezależne. Nie ma liczbowego wyniku wiarygodności ani ryzyka.

## Wersje, kontrola i pochodzenie

Skrót porównywany jest wyłącznie z ostatnią wersją. A → B → A tworzy trzy wersje; identyczne ponowne pobranie aktualizuje tylko `last_checked_at`. Skrót nie obejmuje czasu pobrania. Wyjątkowa korekta parsera nie staje się automatycznie nową wersją, jeśli wynik i istotne pola się nie zmieniły. Tożsamość nie wynika z podobieństwa tytułów i miejsc.

Opisowe materiały oraz niejednoznaczne propozycje kierowane są do kontroli. Zmiana źródła nie nadpisuje zaakceptowanego tekstu: poprzedni opis ma `pending_review`. Nowsza wersja dokumentu oznacza stare zadanie jako `superseded`. Akceptacja sprawdza wersję zadania, bieżącą wersję dokumentu oraz oczekiwaną wersję wydarzenia w jednej transakcji. Powtórzona akceptacja zwraca konflikt. Pola poprawione przez operatora nie są nadpisywane kolejną automatyczną aktualizacją.

Dowód wskazuje utrwalony, oczyszczony tekst; nie jest zrzutem całej witryny. Znane pochodzenie przedruku jest oddzielne od liczby dokumentów. `independent_confirmation` wymaga ręcznej notatki i co najmniej dwóch różnych udokumentowanych źródeł pierwotnych. Sprostowanie wymaga konkretnego twierdzenia i notatki; nie usuwa automatycznie całego wydarzenia.

Powiązanie kopiuje wszystkie dowody na rekord docelowy, zachowując wcześniejszy snapshot w historii rekordu połączonego. Kolejne pobranie trafia na ten sam cel. Rozdzielenie przenosi wybrany podzbiór dokumentów wraz z wersjami i dowodami do nowego rekordu; zapisuje przyczynę i historię obu stron. Nie stanowi cofania bazy. Zbiorczy dokument może pozostać dowodem kilku rekordów tylko po świadomej decyzji operatora o wspieranych fragmentach.

## Czas, geometria i filtry

Znane momenty muszą mieć strefę; zapis czasu systemowego jest UTC. `occurred_time` zachowuje precyzję, oryginalną informację i założenie strefy. Sama data pozostaje datą. `processing/time.py` rozwiązuje „wczoraj” względem publikacji w Warszawie i zwraca niepewność dla powtórzonej lub nieistniejącej godziny zmiany sezonowej. Nie przypisuje czasu zdarzenia na podstawie pobrania.

Ważność ostrzeżenia jest obliczana z przedziału `[valid_from, valid_until)`. Odwołanie ma pierwszeństwo. Upływ ważności zmienia etykietę na `expired`; nie ustawia przebiegu wydarzenia na `ended`. Brak dokumentu w odpowiedzi nie usuwa rekordów i nie stanowi dementi.

Lokalizacje mają oddzielne role: miejsce wydarzenia, obszar ostrzeżenia i obszar powiadomienia. Kod administracyjny pozostaje tekstem z zerami wiodącymi. Brak geometrii nie usuwa rekordu z listy i nie tworzy zastępczego punktu. Mapa korzysta z lokalnych referencji geometrii.

Domyślna lista zawiera aktywne/zapowiedziane ostrzeżenia niezależnie od wieku oraz wydarzenia opublikowane lub istotnie zmienione w ostatnich siedmiu dniach. Kontekst jest widoczny po wyborze rodzaju. Historia dopuszcza wycofane i wygasłe rekordy; zakresy to 1, 7 i 30 dni. Lista zwraca `{items,total,limited}`. Pobiera stan i metadane w dwóch zapytaniach, a teksty dowodów dopiero po otwarciu karty.

## Weryfikacja

`tests/test_core.py` używa wyłącznie syntetycznych dokumentów, stałego zegara i tymczasowej bazy. Pokrywa identyczne pobrania, A → B → A, niejawne nadpisanie operatora, nieaktualne akceptacje, ćwiczenia, sprostowania, pochodzenie przedruku, połączenie i rozdzielenie wraz z następnym pobraniem, precyzję dat i DST, stare aktywne ostrzeżenie, brak geometrii oraz restart i odczyt ręcznej kopii wykonanej po zamknięciu bazy.
