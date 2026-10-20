# Radar opadów i panel warstw — 14.10.2026

## Sprawdzone darmowe źródła

| Źródło | Dostęp i zakres | Wynik próby / wybór |
|---|---|---|
| RainViewer Weather Maps | Bez klucza, użytek osobisty i edukacyjny, obowiązkowa atrybucja; około 2 godziny historii co 10 minut. Brak prognozy radarowej od 2026 r., maksymalny zoom dostawcy 7 i limit 100 zapytań/IP/minutę. Bez SLA/potwierdzenia pełnego pokrycia | Wybrane do tego rozszerzenia; zapisane wyniki próby usunięto |
| IMGW — publiczne produkty radarowe | Oficjalne produkty CMAX/odbiciowości i SRI/natężenia, warunki IMGW; formaty i georeferencja wymagają odrębnego adaptera | Nie potwierdzono bieżącego kontraktu dla tej animacji; wynik nie dotyczy wszystkich usług IMGW |

Źródła zasad: [RainViewer API](https://www.rainviewer.com/api.html), [szczegółowe zmiany 2026](https://www.rainviewer.com/api/transition-faq.html), [format kafelków i czasu](https://www.rainviewer.com/api/weather-maps-api.html), [kolory](https://www.rainviewer.com/api/color-schemes.html), [katalog pokrycia](https://www.rainviewer.com/pl/coverage.html), [API IMGW i regulamin](https://danepubliczne.imgw.pl/apiinfo). Ogólne FAQ RainViewer zawiera niespójne starsze wzmianki o nowcast i braku limitów; przyjęto bardziej szczegółową stronę zmian 2026. Katalog pokrycia nie jest gwarancją dostępności każdego piksela w danym momencie.

## Widok i znaczenie

„Warstwy mapy” nad mapą zastępuje długi rząd sekcji. Domyślnie panel jest zwinięty. W środku trzy grupy: Pogoda, Pożary, Drogi. Zachowano dotychczasowe identyfikatory i przełączniki. „Opis i źródło” rozwija objaśnienia osobno. Podsumowanie „Wybrane” opisuje zaznaczone przełączniki, nie gwarantuje poprawnego odczytu źródeł. Zwijanie panelu/grupy nie wyłącza warstw; przejście do widoku Źródła lub ukrycie karty wstrzymuje pobieranie radaru i odtwarzanie. Panel dostosowuje się do wąskiego widoku i ma ograniczoną wysokość z przewijaniem.

Radar jest osobną, domyślnie wyłączoną warstwą. Zwykłe włączenie pokazuje najnowszą klatkę. „Odtwarzaj radar” włącza warstwę i zapętla dostępną historię; każda kolejna klatka pojawia się po załadowaniu kafelków. Suwak wybiera klatkę i wstrzymuje odtwarzanie; drugi suwak zmienia widoczność (opacity). Podczas ładowania pozostaje poprzedni kompletny obraz. Błąd kafelka zatrzymuje animację, zachowuje poprzedni obraz i pokazuje błąd; nie przedstawia częściowo pobranej klatki jako kompletnego odczytu.

Czas klatki jest **czasem generowania kompozytu**, nie dokładnym czasem każdego skanu radaru. Pokazujemy Europe/Warsaw. Oś czasu jest niezależna od dnia publikacji komunikatów i godzin prognozy Open-Meteo. Radar jest historią, nie prognozą. Punktowe opady IMGW/Open-Meteo nazwano „Opady punktowe”, żeby odróżnić je od obrazu radarowego.

Zachowano paletę Universal Blue, smoothing bez osobnego koloru śniegu, legendę jakościową odbiciowości dBZ i atrybucję RainViewer na mapie oraz w panelu. Kolory nie są sumą opadu w mm ani ostrzeżeniem. Przezroczystość może oznaczać brak echa lub brak danych. Obszar obejmuje prostokąt Polski i otoczenia, nie jest przycięty do granicy. Przybliżenie skaluje obrazy, nie zwiększa rozdzielczości.

## Pobieranie, limity i konfiguracja

`GET /api/radar` zwraca metadane i lokalne szablony adresów; `GET /api/radar/tiles/{time}/{z}/{x}/{y}.png` jest ograniczonym proxy. Pobieranie tylko po włączeniu radaru na widocznej mapie. Demo jawnie wyłącza radar, bez połączeń i bez udawania obrazów radarowych. `[sources.radar] enabled = false` wyłącza źródło.

Stałe hosty `api.rainviewer.com` i `tilecache.rainviewer.com`, brak przekierowań i dowolnych adresów klienta. Klatki muszą pochodzić z poprawnego manifestu i bieżącego okna; wspierane są hashowane ścieżki dostawcy, nie zgadywany adres na podstawie czasu. Obsługujemy wyłącznie zoom 3–6 i kafelki przecinające prostokąt Polski. Zoom 6 wymaga najwyżej sześciu obrazów na klatkę, czyli 78 dla 13 klatek. Wyższy zoom mapy skaluje te obrazy. To świadome ograniczenie małego lokalnego klienta względem zoomu 7 dostawcy.

Cache manifestu 5 minut, LRU do 128 obrazów w pamięci, bez historii na dysku/SQLite. Klucz cache zawiera ścieżkę dostawcy, aby korekta tego samego czasu klatki nie używała starego obrazu. Blokada kafelków zapobiega równoległym powielonym pobraniom. Limit odpowiedzi manifestu 64 KiB, PNG 512 KiB; weryfikacja typu i podstawowej struktury/rozmiaru obrazu. Lokalny budżet do 90 nowych zapytań/minutę z zapasem względem limitu 100/IP; cache nie zużywa tego budżetu. Licznik dotyczy tylko tej instancji, nie innych klientów używających tego samego publicznego IP. 401/403/429 uruchamiają backoff, 429 respektuje Retry-After w zakresie do 24 godzin. Awaria transportu kafelka wstrzymuje następne próby na 30 sekund. Brak odświeżenia oznacza zachowane/nieaktualne dane. Klatka starsza niż 30 minut jest jawnie oznaczona; starsze niż 3 godziny nie są serwowane.

## Weryfikacja

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Testy offline obejmują hosty/ścieżki i czas, limit Polski/zoomu, cache/coalescing, niepoprawne i zbyt duże PNG, awarię manifestu i zachowanie historii, lokalny limit, Retry-After, przerwę po awarii transportu oraz demo. Testy UI obejmują oczekiwanie na pełną klatkę, odtwarzanie i pauzę, suwak z natywnym ograniczeniem wartości, opacity, wyłączenie/ukrycie i późne odpowiedzi, błąd nowej klatki i zachowanie poprzedniej oraz niepobierające demo.
