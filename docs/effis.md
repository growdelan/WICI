# Zagrożenie pożarowe EFFIS — 13.10.2026

Minimalne rozszerzenie WICI na zlecenie użytkownika: osobna warstwa prognozy FWI z wyborem dziś, jutro i pojutrze. Obszary spalone pozostają poza zakresem.

## Znaczenie i prezentacja

Warstwa przedstawia indeks Fire Weather Index modelu ECMWF, udostępniany przez EFFIS / Copernicus Emergency Management Service. Indeks opisuje warunki pogodowe sprzyjające pożarom i ich rozwojowi. Nie jest procentowym prawdopodobieństwem pożaru, obserwacją aktywnego pożaru ani oficjalnym ostrzeżeniem IMGW. Model ma rozdzielczość około 8 km; powiększenie mapy nie zwiększa dokładności prognozy.

Wybór dnia jest zakotwiczony w bieżącej dacie serwera w Europe/Warsaw. Jest niezależny od historycznej daty publikacji komunikatów i filtrów listy. UI pokazuje datę, której dotyczy prognoza, oraz czas pobrania. Serwis WMS nie udostępnia jednoznacznego czasu wydania modelu; aplikacja nie zastępuje go datą odczytu.

Oficjalna legenda źródła ma sześć klas: niskie (FWI < 11,2), umiarkowane (11,2–21,3), wysokie (21,3–38), bardzo wysokie (38–50), ekstremalne (50–70), bardzo ekstremalne (> 70). Kolory i progi pochodzą z legendy WMS, nie ze stopni IMGW. Zachowujemy oryginalną grafikę legendy, a polskie nazwy objaśniają jej klasy.

Prognoza znajduje się nad podkładem PRG i pod komunikatami, wykryciami FIRMS oraz karteczkami. Obraz obejmuje prostokąt Polski i najbliższe otoczenie (`14,49,24.2,55`), nie jest przycięty do granicy państwa. Granice PRG pozostają odniesieniem; warstwa nie przypisuje jednej klasy całemu województwu. Przezroczystość ułatwia równoczesne oglądanie komunikatów.

## Zweryfikowany kontrakt źródła

Aktualna [strona usług EFFIS](https://forest-fire.emergency.copernicus.eu/applications/data-and-services) kieruje ECMWF na `https://maps.effis.emergency.copernicus.eu/gwis` i warstwę `ecmwf.fwi`. Starszy przykład `ecmwf007.fwi` pod `/effis` nie jest podstawą tej integracji. Oficjalny skrypt strony `effis_data_services.js` używa WMS 1.1.1, `GetMap`, jawnego `TIME=YYYY-MM-DD` i stylu domyślnego.

WICI pobiera obraz w EPSG:3857, dopasowany do projekcji mapy Leaflet, oraz oficjalny `GetLegendGraphic`. Adres i parametry źródła są stałe po stronie backendu; przeglądarka otrzymuje wyłącznie lokalne adresy obrazów. Nie zmieniamy CSP i nie otwieramy ogólnego proxy do dowolnych URL. Sam rozległy zakres TIME w GetCapabilities (`2018–2099`) nie potwierdza, że istnieje prognoza dla każdego dnia.

Demo pozostaje offline. Brak prognozy, błąd sieci lub wczytania obrazu/legendy jest jawnie oznaczony. Warstwa z poprzedniego dnia nie zastępuje nieudanej prognozy innego dnia. Status sukcesu UI wymaga wczytania zarówno mapy, jak i legendy.

## Źródła i atrybucja

- [Opis prognoz i modelu](https://forest-fire.emergency.copernicus.eu/about-effis/technical-background/fire-danger-forecast).
- [Usługi i dostępne dane](https://forest-fire.emergency.copernicus.eu/applications/data-and-services).
- [Licencja EFFIS](https://forest-fire.emergency.copernicus.eu/about-effis/data-license): domyślnie CC BY 4.0 dla treści UE, z zastrzeżeniami wskazanymi przez dostawcę. W UI wskazujemy źródło, a integracja oznacza lokalne ograniczenie zasięgu, projekcję i przezroczystość.

## Weryfikacja

Kontrolowana próba 13.10.2026 potwierdziła HTTP 200, poprawne obrazy PNG i niepuste kolory prognozy dla 13, 14 i 15 października, w EPSG:3857; oficjalna legenda także poprawna. Jest to wynik konkretnego odczytu, nie gwarancja dalszej dostępności usług.

## Pobieranie, cache i API

Pobieranie odbywa się na żądanie widocznej warstwy. UI odświeża lokalny widok co minutę; backend przechowuje komplet poprawnej mapy i legendy dla konkretnego dnia przez godzinę w pamięci. Odczyt z cache zachowuje rzeczywisty czas poprzedniego pobrania. Po restarcie obrazy pobiera się ponownie; ten minimalny etap nie archiwizuje prognoz. Błąd jest zapamiętany na pięć minut, aby ograniczyć powtarzanie nieudanych żądań. Brak własnego klucza i nowych zależności.

`GET /api/effis?day=YYYY-MM-DD` zwraca dostępność, dzień prognozy, model, czas pobrania, `issued_at: null`, granice i lokalne URL mapy/legendy. Akceptowane są tylko trzy bieżące dni Europe/Warsaw. `/api/effis/map?day=...` oraz `/api/effis/legend?day=...` serwują PNG z tego samego zestawu cache. Odpowiedzi WMS mają limity rozmiaru, weryfikację kompletności PNG i odrzucanie całkowicie przezroczystej mapy. Nie dopuszczamy przekierowań.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).
