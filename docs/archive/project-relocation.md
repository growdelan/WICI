# Przeniesienie projektu i nazwa WICI

12.10.2026, na zlecenie użytkownika. Zawartość dawnego `polska-osint/` przeniesiono do głównego katalogu repozytorium `WICI/`. Zmieniono nazwę dystrybucji na `wici`, pakiet na `src/wici`, importy, skrypty, nazwy loggerów, tytuł aplikacji i interfejsu oraz bieżące ścieżki i komendy w dokumentacji.

Komendy z katalogu głównego:

```sh
uv sync --locked
uv run --locked python -m wici
uv run --locked python -m wici --demo
```

Sześć istniejących plików danych/logów z `var/` przeniesiono bez zmian, porównując SHA256 przed i po operacji. Lokalne generowane środowiska z dawnymi absolutnymi ścieżkami usunięto i odtworzono `.venv` przez `uv sync --locked --offline`. Lockfile odświeżono offline: zmieniła się nazwa projektu, bez zmiany zależności.

Po przeniesieniu pełny zestaw: 140 testów zaliczonych, jeden znany upstream warning Starlette/httpx; Ruff poprawny. Rzeczywisty start demo/restart/SIGINT i zwolnienie portu sprawdzono skryptem `scripts/verify_system.py`, aktualny wynik w `../evidence/system-check.json`.

Oryginalny PRD oraz historyczne wyniki pozostały zapisem wymagań i wcześniejszych prób. Mogą zawierać dawną nazwę/ścieżkę; nie są instrukcją bieżącego uruchamiania. Poprzedni wynik CLI zachowano jako `../evidence/system-check-before-rename.json`. Zmiana nazwy i katalogu nie usuwa opisanej w `../implementation-status.md` blokady pełnego odbioru live.
