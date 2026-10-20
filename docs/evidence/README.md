# Wyniki sprawdzeń bez kopii danych źródłowych

18.10.2026 usunięto z bieżącego drzewa historyczne raporty JSON i zrzuty zawierające lub mogące zawierać rzeczywiste odpowiedzi, dokumenty, pomiary i warstwy dostawców. Usunięto również zbędne kopie zrzutów demo. Zachowano lokalne logi testów, inwentaryzację licencji i oczyszczoną notatkę IODA. Historyczne logi nie są wynikiem aktualnego przebiegu.

Nie przenoszono dawnych treści do nowych próbek ani nie oznaczano rzeczywistych danych jako syntetycznych. Obecne fixture są autorskie, generowane offline; zobacz [opis zestawu](../../tests/fixtures/README.md).

Skrypty `check_*` zapisują nowe próby live domyślnie w ignorowanym `tmp/live-checks/`, a testy przeglądarkowe w `tmp/browser-evidence/`. Plików z tych katalogów nie należy dołączać do publikowanej paczki bez odrębnego sprawdzenia zawartości i praw.

Usunięcie bieżących plików nie usuwa ich z wcześniejszych commitów, tagów ani opublikowanych wcześniej archiwów. Historia pierwotnego repozytorium nie jest dołączona do tej kopii.
