# Syntetyczne próbki WICI

Bieżący zestaw zawiera autorskie dane testowe na MIT, przygotowane od zera na podstawie kontraktów używanych przez kod. Nie są to zanonimizowane odpowiedzi API ani kopie dokumentów dostawców. Pomiary, treści zdarzeń, podmioty i przebiegi są fikcyjne. Nazwy pól, jednostki, identyfikatory formatów i adresy API służą testom zgodności. Nazwy i kody administracyjne pochodzą z lokalnego słownika PRG, którego odrębne warunki opisuje THIRD_PARTY_NOTICES.md.

- `scripts/prepare_synthetic_fixtures.py`: RSO, RCB, SG, GDDKiA, IMGW hydro, GIOŚ, ADS-B i GFM. Obraz GFM to autorska szachownica, nie zobrazowanie satelitarne. Identyfikator historycznego presetu GFM pozostał jako stała kontraktu UI, bez kopii jego danych.
- `scripts/prepare_imgw_pdf_fixtures.py`: dokumenty PDF, teksty, metadane i oczekiwane wartości scenariuszy. Wyłącznie pypdf; bez PyMuPDF, sieci, fontów zewnętrznych i obrazów źródłowych.
- `ioda/`: wcześniej przygotowane autorskie próbki kontraktu IODA.

Generatory uruchamia się przez `uv run --locked python scripts/<nazwa>.py`. Testy nie pobierają danych dostawców. Wyniki testów syntetycznych nie dowodzą bieżącej dostępności usług ani pełnej zgodności ze wszystkimi rzeczywistymi wariantami dokumentów.

18.10.2026 usunięto poprzednie odpowiedzi, pełne HTML/PDF, rendery, kopie OpenAPI oraz zbędne historyczne próbki i raporty. Starszych kopii ani historii pierwotnego repozytorium nie przeniesiono do tej kopii.
