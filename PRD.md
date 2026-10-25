# WICI — indeks wymagań

Aktualny stan: lokalne MVP ukończone, rozszerzone na zlecenie użytkownika o automatyczny widok oficjalnych komunikatów i mapę dnia, bez modeli i obowiązkowego zatwierdzania. Nazwa projektu i pakietu: `WICI` / `wici`.

- [Bieżące zachowanie, zakres, bezpieczeństwo i ograniczenia](docs/automatic-communications.md).
- [Stan implementacji i weryfikacji](docs/implementation-status.md).
- [Stanowisko analityczne — etap 1](docs/analysis-workspace.md) — wdrożony katalog obiektów, karty oraz wspólna mapa, tabela i oś czasu; [plan](docs/plan-stanowisko-analityczne-etap-1.md) i [raport weryfikacji](docs/analysis-workspace-verification.md).
- [Analiza obiektów ruchomych](docs/analysis-moving-objects.md) — samoloty i statki w katalogu, obserwowane, karty sesji oraz wspólne odtwarzanie do pięciu zapisanych tras.
- [Własne obszary, reguły i skrzynka zdarzeń — v0.35.0](docs/analysis-monitoring.md) — rewizje geometrii, cztery szablony, jawny monitoring w tle, trwała podstawa zdarzeń i zapis w teczkach.
- [Uruchamianie](README.md).
- [Archiwum ukończonych etapów](docs/archive/README.md).
- [Oryginalny PRD MVP v1.0 z 11.10.2026](docs/archive/PRD.md).

Oryginalne PRD zachowano w archiwum bez zmiany treści. Opisują bazowy MVP i dawną nazwę `polska-osint`; późniejsze zmiany zakresu i wycofany eksperyment modeli są opisane oddzielnie. Archiwalne dokumenty i raporty nie stanowią nowego zlecenia ani bieżącej instrukcji uruchamiania.

Rozszerzenie z 13.10.2026: [minimalna integracja NASA FIRMS](docs/firms.md), jako osobna warstwa obserwacji satelitarnych. Kolejne rozszerzenie: [prognoza FWI EFFIS](docs/effis.md) na dziś/jutro/pojutrze, bez obszarów spalonych.

Nadal obowiązują: cztery dotychczasowe źródła komunikatów oraz warstwy NASA FIRMS i EFFIS, lokalny stos Python/uv/FastAPI/SQLite/Leaflet/PRG, minimalizacja danych, tylko loopback, odizolowane demo offline, ręczne uruchamianie, brak wdrożenia, autostartu i instalacji globalnych.

Rozszerzenie z 14.10.2026: [pogoda na mapie](docs/weather.md) — pomiary IMGW i prognoza Open-Meteo, strzałki kierunku wiatru, osobna warstwa opadu, suwak czasu i animacja.

Rozszerzenie z 14.10.2026: [radar historii opadów RainViewer i zwijany panel warstw](docs/radar.md).

Rozszerzenie z 15.10.2026: [kolej PolishTrainsGTFS](docs/trains.md) — stacje, bieżące kursy i opóźnienia oraz trasa po kliknięciu. Kolejne rozszerzenie: szacowane pozycje z aktualizowanych godzin i geometrii, jawne oznaczenie szacunku i wieku danych oraz wykluczenie nieaktualnych danych, odwołań i objazdów bez geometrii.

Rozszerzenie z 17.10.2026: [Ukraina — alerty NEPTUN](docs/ukraine.md), opcjonalna warstwa granic, obszarów alarmowych i osobno doniesień o zagrożeniach powietrznych. Po włączeniu mapa obejmuje Polskę i Ukrainę. Bieżące dane przez backend, bez klucza i historii, z jawną aktualnością, pochodzeniem i ograniczeniami agregatora; demo pozostaje offline.


## Stanowisko analityczne — etap 1 (22.10.2026)

Wdrożenie obejmuje katalog czterech typów obiektów, wspólny wybór mapy/tabeli/karty, oś czasu, lokalną historię stacji i nazwane konfiguracje. Sytuacja zachowuje istniejące warstwy i zapis tras. [Zakres i zasady użytkowania](docs/analysis-workspace.md), [projekt](docs/plan-stanowisko-analityczne-etap-1.md), [weryfikacja](docs/analysis-workspace-verification.md).
