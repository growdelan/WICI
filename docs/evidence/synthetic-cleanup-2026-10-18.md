# Weryfikacja porządkowania próbek — 18.10.2026

Wyniki dotyczą bieżących zmian roboczych, bez żądań do usług dostawców:

- `uv run --locked pytest -q`: **772 passed**, trzy ostrzeżenia (deprecjacja Starlette/httpx i dwa syntetyczne rastry bez georeferencji).
- `node --test --test-concurrency=1 tests/*.cjs`: **193 passed**, zero błędów i pominięć. Playwright/Chromium udostępniono przez `NODE_PATH`; `WICI_UI_URL` wskazywał osobną instancję DEMO na loopback z tymczasowym katalogiem danych dla testu jakości pozycji. Instancję zatrzymano po przebiegu.
- Ruff dla `src`, `tests` i obu generatorów próbek: poprawny.
- Generatory uruchomione ponownie nie zmieniły żadnego pliku próbek; wszystkie JSON parsują się poprawnie. Syntetyczne PDF sprawdzono także przez renderowanie stron.
- `uv build`: sdist i wheel poprawne. Sprawdzono brak usuniętych materiałów oraz katalogów roboczych w sdist, obecność syntetycznych próbek i generatorów, a także LICENSE i THIRD_PARTY_NOTICES.md w wheel.
- Lokalne odnośniki Markdown i `git diff --check`: poprawne.

Syntetyczna zawartość GIOŚ ujawniła rekurencję `render → popup auto-pan → moveend → render`. Zabezpieczenie przed ponownym wejściem usuwa przepełnienie stosu; istniejący test przeglądarkowy zachował sprawdzanie pomiarów, popupu, odświeżania, telefonu i braku błędów JavaScript.

To weryfikacja offline kodu i próbek, nie potwierdzenie bieżącej dostępności ani wszystkich wariantów danych dostawców. Historia pierwotnego repozytorium nie została przepisana i nie jest dołączona do tej kopii. Ta kopia rozpoczyna nową historię Git.
