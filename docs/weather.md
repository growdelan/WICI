# Pogoda na mapie — IMGW i Open-Meteo, 14.10.2026

Osobne warstwy „Wiatr” i „Opady”, domyślnie odznaczone. Wybór „Pomiar / Prognoza” dotyczy obu warstw. Pogoda jest niezależna od dnia publikacji komunikatów. Wybór „Obszar danych” ogranicza punkty na mapie oraz zapytania prognozy. Nie tworzy ostrzeżeń ani nowych ocen zagrożenia.

## Widok

Strzałki wskazują dokąd wieje wiatr: źródłowy kierunek meteorologiczny „z” przeliczany przez dodanie 180°. Kolory prędkości (km/h): <10 niebieski, 10–30 zielony, 30–50 pomarańczowy, ≥50 czerwony. Są to progi wizualizacji, nie stopnie ostrzeżeń IMGW. Dokładne kolory opisuje legenda UI. Zero oznacza ciszę (koło); brak wartości lub kierunku nie tworzy strzałki. Strzałki są ograniczane do widocznego obszaru i jednej na komórkę 38 pikseli, aby nie zasłaniały mapy; przybliżenie pokazuje więcej punktów.

Opady mają niezależne półprzezroczyste symbole punktowe: >0–1, 1–5 i ≥5 mm. Są sumą opadu całkowitego, także śniegu. IMGW: ostatnie 10 minut zakończone w czasie parametru. Open-Meteo: godzina poprzedzająca oznaczoną godzinę. Rozmiar koła jest symbolem ilości, nie powierzchnią opadu ani interpolacją/radarem. Zero i brak pomiaru nie mają koła; popup strzałki nadal pokazuje zero versus brak. Nie tworzymy ciągłego pola deszczu między stacjami.

Kliknięcie strzałki lub koła pokazuje wartości, osobne czasy wiatru, kierunku, porywów i opadu, czas pobrania oraz źródło. W trybie pomiaru „Najnowszy pomiar w zestawie” nie oznacza czasu każdej stacji. Prognoza ma suwak 48 kolejnych godzin i odtwarzanie w odstępie 1,1 sekundy. Pierwsza klatka to bieżąca pełna godzina UTC. Czasy prezentowane w Europe/Warsaw; kolejne godziny pozostają jednoznaczne w UTC.

Opcjonalne animowane smugi przemieszczają się lokalnie przy strzałkach zgodnie z kierunkiem wiatru. Nie interpolują ciągłego pola między punktami, a prędkość animacji jest ilustracyjna. Preferencja ograniczonego ruchu systemu wyłącza ciągłą animację smug. Ukrycie mapy lub wyłączenie warstw zatrzymuje animację, odtwarzanie oraz timer pobierania. Animacja i suwak nie pobierają nowych danych.

## Źródła i cache

`GET /api/weather?mode=measurement|forecast`, tylko lokalny backend. Nie przyjmuje współrzędnych ani adresów dostawcy; zapytania kierowane do stałych oficjalnych endpointów. Pobieranie dopiero po włączeniu warstwy na widocznej mapie. Cache w pamięci, osobna blokada dla każdego trybu, bez archiwizacji w SQLite. W konfiguracji `[sources.weather_imgw]` lub `[sources.weather_forecast]`, `enabled = false` wyłącza dane.

IMGW: [publiczne /meteo](https://danepubliczne.imgw.pl/api/data/meteo/), cały bieżący zestaw, współrzędne stacji i indywidualne czasy parametrów. Cache 10 minut. Prędkości m/s przeliczone na km/h; brak danych nie jest zerem. Odczyty starsze niż 2 godziny lub ponad 15 minut w przyszłości są pomijane jako wartości bieżące, zachowując ich czas. Kierunek z czasu różniącego się od prędkości o ponad 10 minut nie tworzy wektora. Jednostki i interpretacja czasu UTC opierają się na [oficjalnym kodzie wykresów telemetrycznych IMGW](https://hydro.imgw.pl/chunk-QT3I3CPR.js): jednostka wiatru `m/s`, czasy telemetryczne parsowane jako UTC. Jest to wniosek z konwencji oficjalnego interfejsu; [apiinfo](https://danepubliczne.imgw.pl/apiinfo) nie opisuje jednostek i strefy dla każdego pola `/meteo`. Dostawca może zmieniać kontrakt. Widoczne oznaczenia pochodzenia/przetworzenia wymagane przez regulamin zachowano.

Open-Meteo: [Forecast API](https://open-meteo.com/en/docs), 63 punkty w siatce ~70 km przyciętej do lokalnej granicy PRG. To rozstaw naszej wizualizacji, nie rozdzielczość modelu. Współrzędne są punktami zapytania, dostawca dobiera komórki modeli. Cztery zmienne: prędkość, kierunek, porywy na 10 m i opad całkowity. 48 godzin w jednym zapytaniu wielu lokalizacji, cache 1 godzina. Jednostki i zgodność czasu/rozmiaru każdej tablicy są walidowane. Model best_match, bez deklarowania czasu wydania modelu. Publiczny endpoint bez klucza jest do użytku niekomercyjnego, dane CC BY 4.0 i obowiązkowa atrybucja. [Limity i zasady](https://open-meteo.com/en/pricing). Wielolokalizacyjne zapytanie nie musi odpowiadać jednemu rozliczanemu wywołaniu; cache, cztery zmienne i niewielka siatka ograniczają użycie.

Odpowiedzi ograniczone do 4 MiB, bez przekierowań, identyfikujący User-Agent. Błąd nie usuwa poprzedniego zestawu; UI jawnie pokazuje nieaktualność. Minimalny backoff 5 minut, HTTP 429 respektuje Retry-After w ramach limitu 24 godzin. Bez gwarancji SLA. Nieudany odczyt nie potwierdza braku wiatru/opadu. W trybie demo dane są deterministycznie syntetyczne, jawnie opisane, bez połączeń do dostawców.

## Weryfikacja

Kontrolowana próba live 14.10.2026: oba źródła poprawnie odczytane; IMGW 672 stacje z co najmniej jedną świeżą wartością, Open-Meteo 63 punkty × 48 godzin. Liczby dotyczą konkretnego odczytu. Nie zapisano prób do bazy live.

Testy backendu obejmują jednostki, braki, stare porywy, czas/kierunek, błędne tablice prognozy, ograniczenie odpowiedzi, cache, współbieżność, powtarzający się backoff, Retry-After i demo. Testy Node obejmują kierunek wektora/animacji, zero versus brak, oddzielny opad, suwak/odtwarzanie, wyścigi odpowiedzi, ukrywanie, błędy i ograniczony ruch. Endpoint sprawdzony z konfiguracją wyłączenia i kontrolą pochodzenia. Kontrola przeglądarkowa korzysta z syntetycznego demo, w tym szczegółów stacji i prognozy.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Wydanie v0.6.0: pełny zestaw 233 testów Python i 43 testów JavaScript oraz Ruff, składnia JS i kontrola diff.

## Wybór województwa

Opcjonalny parametr `voivodeship` w `/api/weather` przyjmuje dwucyfrowy kod TERYT jednego z 16 województw albo pustą wartość (cała Polska). Nieprawidłowy kod zwraca 422. Prognoza pobiera tylko punkty siatki wewnątrz regionu; cache jest osobny dla każdego regionu i kraju (maksymalnie 17 zakresów). Blokada i backoff pozostają wspólne dla dostawcy. IMGW nadal ma jeden krajowy cache, a przeglądarka filtruje punkty lokalnie. Przy awarii prognozy poprzednie dane pochodzą wyłącznie z cache wybranego zakresu, z ich pierwotnym czasem. Zmiana regionu unieważnia wcześniejsze odpowiedzi prognozy. [Wspólny zakres mapy](regions.md).
