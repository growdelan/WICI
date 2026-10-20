# Obszar danych i postęp warstw

Wybór „Obszar danych” nad dniem publikacji obejmuje komunikaty i warstwy mapy. Dostępna jest cała Polska oraz wszystkie 16 województw. Wybrany kod TERYT zapisujemy lokalnie jako `wici.region.v1`. Przy uruchomieniu odtwarzamy go przed pierwszym pobraniem danych zależnych od regionu. Nieprawidłowa wartość lub zablokowana pamięć przeglądarki oznacza całą Polskę.

Granice pochodzą z dołączonego PRG. Punkty filtrujemy według wielokątów (z uwzględnieniem wysp i otworów), a warstwy mapy przycinamy do ich granic. Podkład, granice administracyjne, obrys kraju oraz dymki zachowują własną prezentację. Zmiana regionu kadruje mapę, zamyka stary dymek i przerysowuje warstwy z posiadanych danych. Powrót do całej Polski przywraca dane krajowe.

## Co przyspiesza wybór województwa

| Dane | Zakres pobierania |
| --- | --- |
| GIOŚ | Wspólny, długo cache’owany wykaz stacji; indeksy tylko dla widocznych stacji wewnątrz regionu. Stanowiska i pomiary na żądanie. |
| Prognoza Open-Meteo | Wyłącznie punkty siatki przypisane do wybranego województwa; osobny cache dla każdego regionu i kraju. |
| FIRMS, IODA, jakość pozycji, Sentinel-5P | Korzystają z istniejących parametrów regionu i ograniczeń swoich serwisów. |
| GFM | Zapytanie przestrzenne obejmuje przecięcie widocznego prostokąta mapy z granicami regionu. Po przesunięciu mapy poza region nie wykonujemy zapytania. |
| Zobrazowania i Sentinel-2 | Punkt wyszukiwania musi leżeć w wybranym regionie. |
| IMGW, GDDKiA i krajowe źródła transportu | Dostawca udostępnia pełny zestaw; zachowujemy wspólny cache i filtrujemy punkty lokalnie. |
| Rastry i kafelki | Widoczne dane przycinamy do granicy; nie zastępuje to regionalnego API dostawcy. |

Wybór regionu nie sprawia, że każdy dostawca zwróci mniejszą odpowiedź. Największą różnicę daje ograniczenie kolejki indeksów GIOŚ i siatki prognozy. Krajowe przetwarzanie monitora GFM nadal działa we wspólnym cache; wybór regionu ogranicza wynik przestrzenny dla przeglądarki. Ręczny odczyt GFM nadal ma limit obszaru 0,5° — przybliż mapę. Próba historyczna Kłodzka zachowuje swój stały obszar.

## Postęp

Panel „Postęp warstw” pokazuje osobno każdą wybraną warstwę: ładowanie i liczbę zapytań, zakończenie, dane częściowe, błąd albo wstrzymanie. Dane pojawiają się niezależnie od pozostałych źródeł. GIOŚ podaje dodatkowo liczbę odczytanych indeksów stacji w bieżącym widoku i pasek postępu. Zakończenie odczytu nie jest potwierdzeniem kompletności lub aktualności danych — obowiązują komunikaty konkretnego źródła.

Zachowano limity GIOŚ: maksymalnie dwa indeksy w toku, starty co najmniej 600 ms od siebie, cache i przerwy Retry-After. Szary punkt nadal oznacza brak aktualnego oficjalnego indeksu. Zmiana regionu anuluje starą kolejkę; odpowiedzi ze starego zakresu nie zmieniają aktualnego postępu, także po przejściu A → B → A.

Zmiana regionu podczas wyszukiwania zobrazowań lub Sentinel-2 usuwa punkt leżący poza nowym obszarem, wyniki i geometrię. Spóźniony sukces lub błąd nie przywraca galerii ani nie przesuwa mapy. Sentinel-2 przerywa również wyszukiwanie i oba rendery porównania. Punkt mieszczący się w nowym obszarze (np. po rozszerzeniu na Polskę) pozostaje ważny. Odrzucone kliknięcie poza regionem nie nadpisuje wcześniej wybranego poprawnego miejsca.

## Weryfikacja offline

Testy Node obejmują geometrię, zapis i awarie localStorage, przycinanie nowych paneli mapy, niezależny postęp, błędy transportu, zmianę regionu w kolejce GIOŚ, prognozę, GFM i wyścigi odpowiedzi zobrazowań/Sentinel-2. Testy Python sprawdzają regionalne zapytania i cache prognoz, wspólny cache IMGW, backoff, zachowanie danych po awarii i walidację kodów API. `tests/region_browser.cjs` uruchamia izolowane demo i rzeczywisty Chromium: odtworzenie regionu, indeksy tylko dla właściwych stacji, niezależne ładowanie, rzeczywisty hit-test przyciętej geometrii, telefon i zmianę regionu podczas obu wyszukiwań.
