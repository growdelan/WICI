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

Bez nowych zależności ani klucza. `[sources.ukraine] enabled = false` wyłącza integrację; domyślnie backend jest dostępny na żądanie, a przełącznik warstwy i rejestracja historii są wyłączone. Konfigurację zmienia się w istniejącym `config.local.toml`, po czym wymaga restartu. Wersja 0.32.0 dodaje migrację 018 i osobny, jawnie włączany kolektor historii alarmów.

Lokalne API: `GET /api/ukraine`, `GET /api/ukraine/alerts`, `GET /api/ukraine/geometry`. Pobieranie wyłącznie ze stałych adresów HTTPS, walidacja JSON i geometrii, limity rozmiaru, timeout, cache i backoff/Retry-After. Doniesienia pozostają w pamięci. Alarmy i ostatnie granice zasilają katalog Analizy, a historia alarmów powstaje po osobnym włączeniu rejestracji. Ukrycie mapy i wyłączenie warstwy zatrzymuje odpytywanie tego widoku oraz unieważnia spóźnione odpowiedzi. Jawnie włączony kolektor historii działa dalej w procesie WICI. Demo zwraca brak danych tej warstwy i nie pozwala uruchomić rejestracji ani żądań do NEPTUN.

Snapshoty mają cache 15 s na komponent, geometrie 24 h. Limit odpowiedzi: 2 MiB dla alarmów/doniesień, 4 MiB dla geometrii. Pojedynczy odczyt ma limit całkowity 15 s i timeout bezczynności do 10 s. Wspólna blokada współdzieli cache między kartami; UI dopuszcza 35 s na pierwsze lokalne żądanie, uwzględniając kolejkę. Błędy mają niezależny backoff, a HTTP 429 respektuje Retry-After do 24 h. Starszy czas źródłowego snapshotu nie zastępuje nowszego; równy czas zmiany alarmów jest dozwolony. Zduplikowane klucze geometrii nie wybierają arbitralnego obszaru. Alarmy po ponad 90 s bez udanego odczytu stają się szare; punkty znikają po 420 s lub przy nieaktualnym odczycie. To reguły prezentacji WICI, nie stwierdzenie odwołania alarmu.

Nie jest to kompletne źródło wszystkich ataków: API nie zapewnia katalogu potwierdzonych uderzeń, ofiar ani szkód. Brak alarmu lub doniesienia w odpowiedzi nie potwierdza bezpieczeństwa. W sprawach bezpieczeństwa obowiązują oficjalne sygnały alarmowe.

Przeglądarka ponawia odczyt granic po 24 h od najstarszego `fetched_at` zwróconego przez backend, przy najbliższym odświeżeniu aktywnej warstwy lub jej wznowieniu. Błąd odnowienia zachowuje poprzednie granice i umożliwia kolejną próbę. Testy `tests/ui_ukraine.test.cjs` obejmują wygaśnięcie cache, nowe klucze alertów, wznowienie warstwy oraz awarię odczytu.

## Weryfikacja

Testy rozszerzenia 0.32.0: `tests/test_ukraine_history.py`, `tests/test_ukraine_collector.py`, `tests/test_workspace_ukraine.py`, `tests/ukraine_workspace_ui.test.cjs` i `tests/ukraine_workspace_browser.cjs`. Przeglądarkowa fixture korzysta z izolowanej bazy i jawnie syntetycznych alarmów; nie archiwizuje bieżących alarmów ani nie zmienia bazy użytkownika. Wyniki pełnej regresji: [weryfikacja Analizy](analysis-workspace-verification.md).

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

## Analiza: historia alarmów i porównanie regionów (v0.32.0)

1. Otwórz **Analiza** i wybierz **Kraj → Ukraina**. Katalog pokaże regiony i zarejestrowane epizody alarmów. Filtry pozwalają wybrać obwód oraz rejon. Rejony bez rozpoznanego obwodu są dostępne przy wyborze wszystkich obwodów.
2. Rozwiń **Ukraina · rejestracja historii alarmów** i włącz **Rejestruj historię alarmów Ukrainy**. Opcja zapisuje się w SQLite i wznawia kolektor po restarcie WICI w trybie LIVE. Rejestracja trwa także po przejściu do innej zakładki; kończy się po wyłączeniu opcji albo zatrzymaniu aplikacji. Okres niedziałania aplikacji pozostaje luką.
3. Zaznacz **Porównaj** przy maksymalnie pięciu regionach. **Obserwuj** zapisuje region na trwałej liście, niezależnie od rejestracji historii.
4. Wybierz **Porównaj ostatnie 24 h** lub własny przedział do 30 dni. Przesuwaj wspólny kursor albo uruchom **Odtwórz**: mapa i porównywane wiersze pokażą stan zapisany dla tej chwili. Kliknięcie odcinka alarmu otworzy kartę epizodu.
5. Porównaj liczbę zarejestrowanych epizodów, zaobserwowany czas alarmu, najdłuższy znany ciągły odcinek i pokrycie zapisu. Statystyki dotyczą całego wybranego przedziału; kolumna stanu dotyczy kursora. Nie sumuj statystyk obwodu i jego rejonów.
6. Przełącz **Strefa czasu** między Warszawą, Kijowem i UTC. Zmiana strefy nie przesuwa wybranej chwili. Zapisane stanowisko zachowuje regiony, filtry, przedział i strefę; jego otwarcie nie włącza kolektora.

Czerwony i żółty zachowują znaczenia NEPTUN. Neutralny pełny odcinek oznacza brak alarmu według poprawnego odczytu, a kreskowanie — brak obserwacji. Po 45 sekundach bez kolejnego poprawnego pobrania pokrycie historii kończy się, nawet jeśli ostatni bieżący stan pozostaje świeży przez 90 sekund. Błąd i częściowa odpowiedź nie zamykają epizodu. Koniec alarmu jest przedziałem między ostatnim odczytem z alarmem a pierwszym pełnym odczytem bez niego; ten niepewny odcinek nie zwiększa zaobserwowanego czasu alarmu.

Karta odróżnia `source_since` dostawcy od pierwszej i ostatniej obserwacji WICI. Korekty stanu, powodów i czasu źródłowego zostają w rewizjach. To historia lokalnych odczytów od włączenia rejestracji; brak wcześniejszych danych nie jest automatycznie uzupełniany. Geometria przy odtwarzaniu jest ostatnim znanym obrysem, a nie historyczną wersją granic.

Retencja wynosi 30 dni. Czyszczenie działa przy starcie, nowych odczytach i co godzinę, także przy wyłączonej rejestracji; odczyty historii od razu respektują granicę retencji. Minimalna obserwacja graniczna i tożsamość nadal otwartego epizodu mogą pozostać w bazie do zachowania ciągłości, ale nie są udostępniane jako dawna historia. Przy ponad 12 000 zmianach jednego regionu API prosi o zawężenie zakresu zamiast pomijać zmiany.

Publiczny identyfikator regionu ma postać `ua_region:neptun:{oblast|raion}:{oryginalny klucz}`, epizodu — `civil_alert:neptun:{UUID}`. Alarm i geometria łączą się po dokładnym kluczu i poziomie administracyjnym. Powiązanie rejonu z obwodem korzysta z dokładnego klucza lub jednoznacznej pełnej nazwy obwodu podanej przez źródło (`parent_basis`); nie stosuje podobieństwa nazw ani transliteracji. Sprawdzenie formatu źródła 23.10.2026 potwierdziło, że geometrie rejonów nie zawierają nadrzędnego obwodu.

`UkraineService` współdzieli cache i backoff pomiędzy Sytuacją, Analizą i kolektorem. Endpoint `/api/ukraine/alerts` pobiera tylko alarmy. Hook po rzeczywistym odczycie przekazuje go do `UkraineCollector`, który szereguje zapis w wątku poza pętlą HTTP, bez scalania przejść alarmu. Cache nie dopisuje obserwacji. Błąd SQLite jest zgłaszany w statusie i pozostawia lukę.

Nieudany zapis granic jest ponawiany lokalnie z opóźnieniem od 1 do 60 sekund, również przy wyłączonej rejestracji alarmów, bez kolejnego pobrania od dostawcy. Osobny błąd geometrii pozostaje widoczny do udanego zapisu. Nowe odczyty spoza zakończonego przedziału nie unieważniają jego szczegółów ani stronicowania. Wyjątkiem jest informacja zmieniająca zapisany okres, np. późniejsze potwierdzenie końca alarmu, którego niepewny przedział przecina analizowany zakres; zmiany bieżącej geometrii również wymagają odświeżenia zestawu.

API Analizy: `GET /api/workspace/ukraine/regions`, `GET/PUT /api/workspace/ukraine/recording` (`{"enabled":true}`), `POST /api/workspace/ukraine/replay` (`refs`, `from`, `to`). Katalog, karty, odtwarzanie i zapisane widoki czytają SQLite i nie pobierają historii od dostawcy. Dotychczasowe API Sytuacji i doniesienia NEPTUN zachowują swoje działanie.
