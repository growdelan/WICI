# Ukraina — alerty NEPTUN

Badanie i integracja: 17.10.2026. Osobna, domyślnie wyłączona warstwa WICI, niezależna od polskich komunikatów, dnia publikacji i województwa. Włączenie obejmuje mapą Polskę i Ukrainę; kolejne odświeżenia zachowują wybrany widok.

## Wynik badania

[NEPTUN Developers](https://neptun.in.ua/developers) udostępnia REST, WebSocket i SDK bez klucza. WICI korzysta z bieżących alarmów `/api/v1/alerts` oraz doniesień `/api/v1/threats`; granice `/oblasts.geojson` i `/raions.geojson` umożliwiają kolorowanie obszarów. `areaOnly` oznacza zgłoszenie dla obwodu, którego centroid nie jest pozycją obiektu. `advisory` oznacza obserwację informacyjną. WICI nie korzysta z prognozowania ruchu ani animacji SDK.

Według [rejestru źródeł NEPTUN](https://neptun.in.ua/dzherela), alarmy pochodzą oddzielnie z UkraineAlarm, a doniesienia z otwartych kanałów Telegram. Dostawca nie ma własnych radarów i opisuje nierówne pokrycie regionów. WICI przekazuje alarm za pośrednictwem agregatora; nie sprawdza go niezależnie w UkraineAlarm. Zgłoszenie drona/rakiety nie jest potwierdzeniem trafienia ani skutków ataku.

[Warunki API](https://neptun.in.ua/api-terms) dopuszczają bezpłatny użytek komercyjny i niekomercyjny, wymagają widocznego odnośnika obok danych i zachowania informacji o ograniczeniach. Minimalny odstęp REST wynosi 5 s. Nie ma gwarancji dokładności, kompletności ani ciągłości. WICI używa odstępu 15 s i wspólnego cache backendu.

Opis [kolorów NEPTUN](https://neptun.in.ua/blog/kolory-na-karti-tryvoh) odróżnia czerwony alarm od żółtego ostrzeżenia lub częściowego alarmu. Powody `reasons` pozostają tekstem dostawcy: brak zamkniętego słownika nie uzasadnia własnej klasyfikacji. Oficjalny [SDK](https://neptun.in.ua/sdk/neptun.esm.js) używa 420 s do oznaczania starych doniesień. Nie jest to gwarancja rzeczywistego czasu trwania zagrożenia.

## Próba dostępu i rozbieżności kontraktu

Ograniczony odczyt 17.10.2026 zwrócił HTTP 200 dla obu endpointów i geometrii. Pierwsza próbka zawierała 66 rejonów i 4 obszary obwodowe alarmów oraz 18 doniesień. To chwilowe liczby, nie opis obecnej sytuacji ani test kompletności.

Geometrie zawierały 27 obszarów obwodowych i 136 rejonów, odpowiednio około 162 kB i 630 kB. Klucze były unikalne i wszystkie alarmy z próbki miały odpowiednik. Rzeczywiste klucze są ukraińskie, np. `вінницька`, a przykład dokumentacji pokazuje transliterację ASCII. Implementacja łączy wyłącznie rzeczywiste klucze z odpowiednią kolekcją, bez zgadywania na podstawie podobnej nazwy rejonu.

Odpowiedź alarmów zawiera też `version`, `updatedAt`, `level`, `reasons`, których starszy przykład nie opisuje w całości. `updatedAt` nie jest udokumentowanym heartbeat: czas zmiany stanu pozostaje oddzielony od czasu udanego pobrania. Doniesienia mają `serverTime` dla snapshotu oraz `updatedAt` dla poszczególnych wpisów.

Nie znaleziono odrębnej licencji ani proweniencji geometrii w plikach NEPTUN. Są odczytywane przez cache w czasie działania; nie są dołączane do repozytorium. Przykłady testowe są syntetyczne, a nie kopią bieżących pozycji.

## Zachowanie i interpretacja

- Granice administracyjne Ukrainy oraz obszary alarmów są niezależne od granic PRG i ostrzeżeń IMGW. Czerwony/żółty kolor zachowuje znaczenie NEPTUN; nieznany poziom jest neutralny.
- Doniesienia mają osobne oznaczenia i szczegóły: typ, czas, położenie opisowe oraz dostępne informacje o jakości. Punkty są pokazywane wyłącznie w granicach Ukrainy. Brak pasującej geometrii lub wiarygodnej pozycji pozostaje widoczny jako ograniczenie, bez punktu zastępczego.
- `areaOnly` nie staje się punktem; `advisory` nie otrzymuje czerwonego alarmu. Nie wyświetlamy przewidywanych tras, kierunków, miejsc startu ani szacowanych miejsc uderzeń.
- Starzenie i błąd źródła są jawne. Błąd nie zamienia poprzednich danych w komunikat o braku alarmów. Nieaktualne doniesienia tracą oznaczenie bieżącej pozycji.
- Nazwy i opisy źródłowe mogą być ukraińskie. UI i objaśnienia są polskie; nie ma automatycznego tłumaczenia przez model.

## Uruchamianie i zasoby

Bez nowych zależności, klucza, migracji bazy i autostartu. `[sources.ukraine] enabled = false` wyłącza integrację; domyślnie backend jest dostępny na żądanie, ale przełącznik warstwy jest wyłączony. Konfigurację zmienia się w istniejącym `config.local.toml`, po czym wymaga restartu.

Lokalne API: `GET /api/ukraine`, `GET /api/ukraine/geometry`. Pobieranie wyłącznie ze stałych adresów HTTPS, walidacja JSON i geometrii, limity rozmiaru, timeout, cache i backoff/Retry-After. Dane pozostają w pamięci, bez archiwum zdarzeń. Ukrycie mapy i wyłączenie warstwy zatrzymuje odpytywanie oraz unieważnia spóźnione odpowiedzi. Demo zwraca jawny brak danych tej warstwy, bez żądań do NEPTUN.

Snapshoty mają cache 15 s na komponent, geometrie 24 h. Limit odpowiedzi: 2 MiB dla alarmów/doniesień, 4 MiB dla geometrii. Pojedynczy odczyt ma limit całkowity 15 s i timeout bezczynności do 10 s. Wspólna blokada współdzieli cache między kartami; UI dopuszcza 35 s na pierwsze lokalne żądanie, uwzględniając kolejkę. Błędy mają niezależny backoff, a HTTP 429 respektuje Retry-After do 24 h. Starszy czas źródłowego snapshotu nie zastępuje nowszego; równy czas zmiany alarmów jest dozwolony. Zduplikowane klucze geometrii nie wybierają arbitralnego obszaru. Alarmy po ponad 90 s bez udanego odczytu stają się szare; punkty znikają po 420 s lub przy nieaktualnym odczycie. To reguły prezentacji WICI, nie stwierdzenie odwołania alarmu.

Nie jest to kompletne źródło wszystkich ataków: API nie zapewnia katalogu potwierdzonych uderzeń, ofiar ani szkód. Brak alarmu lub doniesienia w odpowiedzi nie potwierdza bezpieczeństwa. W sprawach bezpieczeństwa obowiązują oficjalne sygnały alarmowe.

Przeglądarka ponawia odczyt granic po 24 h od najstarszego `fetched_at` zwróconego przez backend, przy najbliższym odświeżeniu aktywnej warstwy lub jej wznowieniu. Błąd odnowienia zachowuje poprzednie granice i umożliwia kolejną próbę. Testy `tests/ui_ukraine.test.cjs` obejmują wygaśnięcie cache, nowe klucze alertów, wznowienie warstwy oraz awarię odczytu.

## Weryfikacja

Końcowa weryfikacja 17.10.2026:

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Polecenia do ponowienia:

```sh
uv run --locked pytest -q
node --test tests/ui*.cjs tests/*_ui.cjs
uv run --locked ruff check .
NODE_PATH=/sciezka/do/node_modules node --test tests/ukraine_browser.cjs
# Jawna próba sieciowa, cztery odczyty dostawcy i sprawdzenie lokalnego cache:
uv run --locked python scripts/check_ukraine.py
```

Skrypt sieciowy zapisuje wyłącznie metadane, liczniki i wyniki dopasowania; nie archiwizuje bieżących pozycji ani treści. Próby dostępu nie są niezależnym potwierdzeniem sytuacji, jakości lokalizacji ani pełnego pokrycia Ukrainy.
