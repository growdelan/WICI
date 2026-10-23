# Stan WICI — 13.10.2026

Aktualny tryb: automatyczne komunikaty czterech oficjalnych źródeł, bez modeli i bez zatwierdzania. Zapisane komunikaty trafiają do widoku dnia, na listę i — jeśli mają rozpoznany obszar — na lokalną mapę PRG z karteczkami województw. Pełna oczyszczona treść, oryginały i wersje są dostępne w szczegółach. Dawny tryb interpretacji, jego API i formularze zostały usunięte; historyczne tabele SQLite są zachowane.

Próba live po porządkowaniu 13.10: wszystkie cztery źródła `success`, 22 publikacje/aktualizacje dnia, 19 z obszarem. IMGW zwróciło poprawny pusty zestaw. Wynik nie gwarantuje ciągłej dostępności ani kompletnego pokrycia sytuacji. Szczegóły i pominięte próby: [automatyczne komunikaty](automatic-communications.md).

Weryfikacja: 154 testy Python i 6 JS przechodzi; Ruff, składnia JS i `uv lock --check` poprawne. Start live, offline demo, restart, SIGINT, zajęty port i zachowanie danych sprawdzone. W przeglądarce zweryfikowano mapę, karteczkę, treść i archiwum dnia bez „Load failed”. Procesy testowe zatrzymano.

Usunięto aktywną integrację OpenAI, płatne skrypty i prywatny plik klucza używany przez WICI. Historyczne decyzje w SQLite zachowano. Dawna konfiguracja `[llm]` jest ignorowana.

## Dokumenty

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Braki: brak długoterminowego pilota, benchmarku 10k dla nowego endpointu komunikatów, rekonstrukcji historycznej mapy i przeglądu wszystkich kolorów stopni IMGW na dzisiejszych ostrzeżeniach (zestaw pusty). Źródła mogą być niedostępne lub zmienić format; brak danych i lokalizacji jest jawny. Zachowano tylko loopback, ręczne uruchamianie i izolowane demo offline.

## Rozszerzenie NASA FIRMS — 13.10.2026

Minimalna warstwa obserwacji satelitarnych wdrożona poza komunikatami: trzy produkty VIIRS, Polska według PRG, odświeżanie 15 min, okno 24/48 h, trwała lokalna historia, stan częściowych odczytów i ochrona lokalnego klucza. 161 testów Python, 9 Node, Ruff i składnia JS poprawne. Szczegółowy zakres i dowody: [firms.md](firms.md).

## Rozszerzenie EFFIS — 13.10.2026

Wdrożono osobną warstwę prognozy zagrożenia pożarowego ECMWF FWI na dziś/jutro/pojutrze z oficjalną legendą i datą prognozy. Obrazy i legenda przez lokalny backend, cache godzinny, kontrola kompletności PNG, demo offline. Obszary spalone poza zakresem. 173 testy Python i 13 Node, Ruff i składnia JS poprawne; kontrola live trzech dat oraz UI bez błędów. Szczegóły: [effis.md](effis.md).

## EUMETSAT LI AFA — 14.10.2026

Dodano publiczną warstwę wykrytej aktywności wyładowań EUMETView: kolorowe obszary, oficjalna legenda, selektor pięciominutowych okresów z ostatniej dostępnej godziny, odczyt piksela po kliknięciu, jawny wiek danych i ograniczenia interpretacji. Bez konta i klucza, cache, kontrolowane ponowienia, demo offline. Zweryfikowano rzeczywiste puste i niepuste obrazy oraz szczegóły w przeglądarce. Pełna regresja 264 Python / 54 JS i Ruff. [Kontrakt i dowód LIVE](lightning.md).

## Samoloty ADSB.lol — 14.10.2026

Dodano warstwę „Lotnictwo → Samoloty” z ikonami kierunku ruchu i szczegółami po kliknięciu: znak wywoławczy, rejestracja, typ, wysokość barometryczna, prędkość względem ziemi i wiek pozycji. Odświeżanie i cache backendu 10 sekund, zatrzymanie poza widoczną mapą lub po wyłączeniu warstwy, demo offline. Granice PRG, pozycje starsze niż 2 minuty usuwane, jawne błędy i ograniczenia pokrycia. Próba LIVE przetworzyła 66 pozycji; dymek sprawdzono w przeglądarce na danych testowych. Testy obejmują jednostki, geografię, cache, współbieżność, błędy źródła i zatrzymanie timerów.


## Statki AISStream — 14.10.2026

Wdrożono minimalną warstwę „Bałtyk → Statki AIS”, wspólny strumień na żądanie, konfigurację sekretu i szczegóły jednostek. Odczyt live potwierdził dane polskiego wybrzeża i kompresję. Testy obejmują backend, ochronę klucza, bezczynność i cykl UI; kontrola w przeglądarce potwierdziła znaczniki oraz dymek. [Plan wykonany, wyniki i ograniczenia](ships.md).

Zawężenie statków: lokalna maska wody EEA/VLIZ, Bałtyk i cieśniny duńskie z Kattegatem, bez Morza Północnego, Skagerraku i dróg śródlądowych. 350 testów Python przechodzi; żywy strumień potwierdził 124 pozycje zgodne z maską. [Pochodzenie granic i walidacja](ships.md#dane-granic-akwenów).

## Kolej PolishTrainsGTFS — 15.10.2026

Dodano warstwę „Kolej → Stacje, kursy i opóźnienia”: zgrupowane stacje w Polsce, odjazdy ze stacji, godziny planowe i aktualizowane, podpisane opóźnienia oraz rozkładowa trasa i postoje po wyborze kursu. Cache rozkładu 6 h / aktualizacji 120 s, odczyty tylko dla aktywnej widocznej warstwy. Nieaktualność wynika z czasu źródła (>10 min), błędów odświeżania lub nieważnego rozkładu. Bez szacowanych pozycji i archiwizacji, demo bez sieci.

Próba LIVE: 2926 stacji, 33 028 kursów w rozkładzie; pierwsze przygotowanie ok. 4,5 s, tablica Warszawy Centralnej ok. 16 ms, wybrana trasa ok. 7 ms. Rozkład i aktualizacje wymagają ok. 0,5 GiB RAM na proces. W przeglądarce na wąskim widoku potwierdzono tablicę Zalesia Górnego, opóźnienie kursu 12132/3 Radomir, geometrię, listę postojów i powrót do odjazdów. Poprawiono propagację kliknięcia i pozycjonowanie dymka przy dopasowaniu trasy.

Weryfikacja: 367 testów Python, 69 testów Node, dodatkowy test cyklu statków i Ruff przechodzą. Testy kolejowe obejmują cache i współbieżność, awarie, starzenie źródła, rollback czasu, dni kursowania i DST, opóźnienia przyjazdów/odjazdów, odwołania, objazdy oraz cykl życia UI. [Kontrakt, ograniczenia i zasoby](trains.md).

## Szacowane pozycje pociągów — 15.10.2026

Rozszerzono warstwę kolejową o romby ze znakiem pociągu i stałym „≈”, dymki „POZYCJA SZACOWANA · nie GPS”, wiek źródła oraz osobny czas oszacowania. Położenie wynika z aktualizowanych godzin i zgodnych odległości GTFS na prawdziwej geometrii trasy, bez ekstrapolowania po wygaśnięciu danych. Odwołania, objazdy bez aktualnej geometrii, brak odpowiednich godzin lub dopasowania trasy i nieaktualność/błąd źródła wykluczają znaczniki. Odczyt i cache pozycji 15 s, ważność maks. 30 s i do końca odcinka/czasu świeżości źródła. UI kontroluje wygaśnięcie co sekundę i odrzuca spóźnione odpowiedzi po wstrzymaniu warstwy.

Próba LIVE potwierdziła ponad 650 szacunków, pierwsze przygotowanie ok. 6 s i kolejne przeliczenie ok. 0,32 s. W przeglądarce sprawdzono etykiety, wiek danych, trasę i powrót z trasy oraz całkowite usunięcie znaczników po wyłączeniu szacunków; bez błędów konsoli. Weryfikacja: 385 testów Python, 75 testów Node, dodatkowy test cyklu statków i Ruff przechodzą. [Algorytm, ograniczenia i wyniki](trains.md#szacowane-pozycje-pociągów).

Poprawki po przeglądzie: odwołanie, objazd lub brak geometrii odczytane ze stacji albo szczegółów kursu usuwają właściwy znacznik według kursu i dnia rozpoczęcia. Oczekujące odpowiedzi są unieważniane; ta sama lub starsza wersja danych nie przywraca odrzuconej pozycji. Dodano rozróżnienie odwołania całego kursu od pominiętego postoju oraz regresje obu sposobów otwierania szczegółów, spóźnionej odpowiedzi, ponownego odczytu cache i odzyskania pozycji z nowszego źródła. Weryfikacja po poprawkach: 386 Python / 80 Node, test cyklu statków, Ruff i `git diff --check` przechodzą.


## v0.13.0 — autobusy Szczecina

Bieżąca warstwa ZDiTM Szczecin bez klucza i historii: filtr linii, szczegóły pojazdu, kierunek, przystanki, opóźnienie i wiek pozycji. Pobieranie tylko na widocznej mapie, współdzielony cache, ETag/304 i obsługa limitów źródła. Szare znaczniki po 60 sekundach lub błędzie odświeżania; pozycje starsze niż 120 sekund znikają. Demo pozostaje offline.

Poprawka po przeglądzie: otwarte szczegóły zachowują przewinięcie przy aktualizacji wieku i nowych danych pojazdu, również podczas przebudowy okienka przez Leaflet. Test regresji odtwarza reset przewinięcia; próba w prawdziwej przeglądarce potwierdziła zachowanie pozycji po kolejnych aktualizacjach.

Weryfikacja wydania: 406 testów Python, 83 testy Node, Ruff i `git diff --check` przechodzą. Odczyt LIVE potwierdził dane autobusów. Osobno sprawdzono EUMETSAT: poprawne metadane, mapa i legenda w uruchomionym WICI; kod wyładowań pozostaje bez zmian.


## v0.14.0 — autobusy Krakowa, Poznania i Warszawy

Wspólny wybór Szczecina, Krakowa, Poznania i Warszawy z osobnym filtrem linii, centrowaniem, źródłem i stanem dostawcy. Backend izoluje cache, błędy i konfigurację miast. Kraków odczytuje autobusowe zestawy MPK/Mobilis; Poznań filtruje tramwaje na podstawie GTFS. Statyczne indeksy są pamięciowe, bez geometrii i pełnego stop_times. Warszawa korzysta z nowego portalu danych i klucza wyłącznie w nagłówku żądania backendu. Brak klucza nie blokuje innych miast. Bez historii przejazdów i bez sieci w DEMO.

Weryfikacja wydania: 439 testów Python, 83 testy Node, Ruff, kontrola pliku zależności i `git diff --check` przechodzą. Izolowana instancja LIVE oraz prawdziwa przeglądarka potwierdziły zmianę miast, filtr linii, źródła, szczegóły, zachowanie przewinięcia po aktualizacji oraz szerokość mobilną. W próbie około 17:48 15.10.2026 widoczne były około 150 autobusów Szczecina, 600 Krakowa, 310 Poznania i 1560 Warszawy. To próbki, nie gwarancja pokrycia. Kraków okresowo zwracał błędy części źródeł; dostępne pozycje pozostawały widoczne z ostrzeżeniem. Warszawa nie udostępnia w tym odczycie opóźnień, modeli i kierunków docelowych. Poznań nie dostarczał identyfikatorów przystanków w pozycjach; brak nazw następnych przystanków jest jawny. [Zakres i konfiguracja](buses.md).


Poprawka po przeglądzie v0.14.0: błędy `zlib.error` podczas dekompresji GTFS są obsługiwane przy pierwszym pobraniu i odświeżaniu indeksu. Uszkodzone archiwum jednego operatora nie blokuje drugiego operatora Krakowa; pozostaje ostrzeżenie, cache i odstęp przed ponowieniem. Dwa warianty testu z rzeczywiście uszkodzonym strumieniem DEFLATE potwierdzają izolację awarii i odzyskanie pełnych danych po poprawnym odczycie.

## v0.15.0 — kolory statków AIS i przewijana legenda

Statki mają trzy kolory według deklarowanego typu AIS: fioletowy dla wojskowych (wyłącznie kod 35), morski dla rozpoznanych typów cywilnych i szary dla nieustalonych. Typy niejednoznaczne, zarezerwowane i brak typu pozostają nieustalone. Klasyfikacja jest widoczna w legendzie, podpowiedzi i szczegółach jednostki. Brak kodu 35 nie oznacza, że jednostka jest cywilna; AIS nie potwierdza przynależności. Pozycje starsze niż 5 minut otrzymują paski, zachowując kolor kategorii.

Legenda mapy ma wysokość ograniczoną do obszaru mapy, przewijanie oraz stale widoczny nagłówek. Sprawdzono zwijanie i ponowne rozwijanie, także po przewinięciu, w oknach 1280×560 i 1024×480 px.

Weryfikacja wydania: 439 testów Python, 83 testy Node, Ruff, kontrola diffu i spójności pliku zależności zakończone powodzeniem.


## v0.16.0 — zobrazowania po katastrofach

Warstwa Copernicus EMS Rapid Mapping wyszukuje materiały dla miejsca wskazanego na mapie lub jej środka. Pokazuje datę wykonania zobrazowania, osobną datę produktu, źródło, przybliżone zasięgi AOI oraz miniatury produktów kartograficznych. Kliknięcie miniatury otwiera materiał źródłowy, a kliknięcie znacznika miejsca otwiera dymek bez ponownego wyszukiwania. Pobieranie tylko na żądanie, bez klucza API, ze współdzielonym cache i limitami czasu/rozmiaru; demo pozostaje offline. Katalog jest przeszukiwany w ograniczonym zakresie, opisanym w [dokumentacji integracji](imagery.md).

Weryfikacja wydania: 461 testów Python, 93 testy Node, Ruff, spójność pliku zależności i kontrola diffu zakończone powodzeniem. Próba rzeczywistych danych dla Kłodzka potwierdziła 8 produktów EMSR756 i pobranie podglądu JPEG. Testy obejmują wybór miejsca, spóźnione odpowiedzi, wyłączanie warstwy, dymek znacznika, odnośniki do źródła, błędy katalogu, limity i tryb demo.

## v0.16.1 — porządki i uruchamianie na istniejącej bazie

Przywrócono historyczny łańcuch migracji `005`–`008`, aby aplikacja mogła otworzyć zachowane bazy w wersji 8 po cofnięciu eksperymentalnych integracji. Kontrola odrzucająca nowsze nieobsługiwane schematy pozostaje aktywna. Scheduler pomija niewspierane źródła przy planowaniu i w widoku Źródeł, zachowując ich rekordy historyczne. Migracje nie przywracają wycofanych kolektorów ani warstw interfejsu.

Usunięto trzy słowniki metadanych IMGW odrzucane przez dalszy kod, nieaktualną metrykę `auto_publish_count`, martwe selektory CSS, dwie zmienne kolorów i zastąpiony symbol SVG. Zaktualizowano sprawdzenia limitu żądania i liczby grup warstw. Zależności pozostają używane; nie usuwano pakietów ani zabezpieczeń. Dowody odwołań, historia i zakres zachowanych mechanizmów znajdują się w [raporcie porządków](code-cleanup.md).

Weryfikacja: 464 testy Python, 93 testy Node, Ruff, spójność pliku zależności i kontrola diffu poprawne. Chromium potwierdził interfejs przy pięciu szerokościach, bez błędów JS i żądań zewnętrznych w demo. Porównanie IMGW dało identyczne wyniki dla 151 dokumentów. Start aplikacji na odizolowanej kopii rzeczywistej bazy LIVE udostępnił 528 komunikatów z działającym schedulerem, bez sieci. Schemat odpowiada wszystkim 69 obiektom bazy; dane i SHA256 oryginalnego pliku pozostały bez zmian. Testy obejmują uaktualnienie v2/v4/v7, ponowne otwarcie v8 i odrzucenie nieobsługiwanej wersji. Dostępności dostawców zewnętrznych nie sprawdzano ponownie.


## v0.18.0 — jakość powietrza GIOŚ

Dodano niezależną, domyślnie wyłączoną warstwę „Jakość powietrza GIOŚ” w grupie „Pogoda”.
Backend obsługuje aktualne API v1 JSON-LD bez klucza, paginację i osobne stany błędów,
wyników pustych/null oraz stanowisk manualnych. Stacje i stanowiska pozostają na liście
również przy braku współrzędnych lub wybranego parametru. Szczegóły pokazują stężenie,
jednostkę i czas pomiaru, jego wiek, adres stacji oraz tabelę godzinową.

Punkty korzystają z oficjalnego indeksu ogólnego GIOŚ i jego sześciu kolorów, z legendą.
Brak, błąd lub nieaktualny indeks oznaczany jest szaro; stężenia pozostają osobne od indeksu.
Indeksy pobierane są wyłącznie dla stacji w widoku mapy, z kolejką, cache 30 min,
ograniczeniem współbieżności i respektowaniem najdłuższego Retry-After. Wyłączenie lub
ukrycie warstwy i przesunięcie mapy zatrzymuje pobieranie oraz odrzuca spóźnione odpowiedzi.
Zachowujemy surowe czasy źródła, rozdzielamy pomiar, obliczenie indeksu i pobranie,
a niejednoznacznych godzin DST nie rozstrzygamy arbitralnie. Demo pozostaje offline.

Poprawki po przeglądzie: błąd pojedynczego zasobu nie blokuje innych stanowisk;
współbieżne odpowiedzi nie skracają backoffu, a błąd równoległego odświeżania nie usuwa
poprawnego pomiaru. Dane użytkownika i kolektor komunikatów pozostają bez zmian;
nie dodano trwałego archiwum pomiarów.

Weryfikacja: 509 testów Python, 104 Node i dwa testy Chromium (GIOŚ i hydrologia,
końcowy przebieg seryjny) zakończyły się powodzeniem; Ruff i kontrola diffu bez uwag.
Jeden równoległy przebieg hydrologii miał timeout; samodzielne i seryjne powtórzenie przeszły.
Ograniczona próba LIVE potwierdziła 288 stacji, 14 stanowisk stacji 52, indeks, 56 wyników PM10
oraz odpowiedź manualną. Wyniki są niezweryfikowane i mogą ulec zmianie; cache może opóźnić
pojawienie się nowej godziny. [Pełny kontrakt, ograniczenia i dowody weryfikacji](gios.md).


## v0.19.0 — problemy łączności internetowej IODA

Dodano niezależną, domyślnie wyłączoną warstwę IODA dla Polski, zweryfikowanych regionów i ograniczonej listy ASN powiązanych z Polską. Kolektor działa w tle co 300/600 s; migracja 009 i repozytorium SQLite zachowują zdarzenia, alerty, próbki i pochodzenie. API `/api/ioda` udostępnia lokalną historię, szczegóły i sygnały dla okna 24/48 h. UI rozróżnia brak zdarzeń, brak pomiarów, stare dane i błąd źródła; nie przypisuje przyczyny ani statusu ostrzeżenia służb. Regiony mają jawne mapowanie do PRG; ASN pozostają bez geometrii.

Odporność obejmuje limity czasu, rozmiaru, paginacji i liczby zapytań, częściowe błędy, backoff oraz Retry-After także po restarcie. Demo jest syntetyczne i całkowicie offline. Poprawki po review zachowują wartość i jej pochodzenie przy nowym null oraz otwarte szczegóły, fokus i dymki podczas minutowego odświeżania.

Weryfikacja wydania z 17.10.2026: **541 testów Python, 121 testów Node/Chromium**, Ruff i `git diff --check` przechodziły. Końcowy zestaw przeglądarkowy uruchomiono sekwencyjnie. Niezależny przegląd nie zgłosił nowych problemów. Wykonano także ograniczone sprawdzenie live. 18.10.2026 usunięto z bieżącej wersji jego dane źródłowe i wyniki pomiarów oraz skopiowane odpowiedzi i OpenAPI; fixture IODA przygotowano od zera jako autorskie dane syntetyczne. Wcześniejsze kopie pozostały wyłącznie w historii pierwotnego repozytorium, której nie przeniesiono do tej kopii.

Zakres, retencja, świeżość, kontrakt i atrybucja: [ioda.md](ioda.md). Notatka o dawnym sprawdzeniu live i usunięciu jego danych: [ioda-live-2026-10-17.json](evidence/ioda-live-2026-10-17.json). Po aktualizacji do v0.19.0 wymagany był restart aplikacji; migracja jest automatyczna i nie resetuje dotychczasowej historii.


## v0.20.0 — regionalna jakość pozycji / GNSS

Wdrożono opcjonalny kolektor ADSB.lol współdzielący pobieranie z samolotami, SQLite z deduplikacją i retencją, detekcję komórek 5-minutowych z głosami różnych samolotów i lokalnym tłem oraz osobną warstwę historii 24/48 h. Audyt rzeczywistej odpowiedzi potwierdził częściową dostępność wskaźników; nie potwierdza skuteczności rozpoznawania GNSS. Demo syntetyczne i wyłączony kolektor nie pobierają danych. [Metoda, dowody i weryfikacja](position-quality.md). Kolektor i warstwa są domyślnie wyłączone. Nie jest to potwierdzenie jammingu/spoofingu ani oficjalne ostrzeżenie.


Poprawki po przeglądzie: awarie SQLite kolektora nie przerywają cache samolotów, status awarii pozostaje dostępny w pamięci, a kolektor ponawia zapis. Interwał ograniczono do 60–300 s. UI śledzi najnowsze zakończone okno z możliwością ręcznego przeglądania i powrotu przyciskiem; błędu odczytu nie usuwa zmiana okna. Historia jest liczona w wątku roboczym z osobnym połączeniem SQLite. Weryfikacja: **560 testów Python**, regresje Node i Chromium (także przesuwanie zegara, awaria odczytu i odzyskanie), test współbieżnego odczytu 300 000 próbek oraz pełny smoke test atlasu na czterech rozmiarach ekranu. Demo nadal offline, Ruff i `git diff --check` bez błędów.


Odseparowanie zapisu SQLite: cache samolotów jest publikowany bez czekania na zapis. Worker ma własne połączenie, timeout blokady 50 ms, ponawianie niezależne od sieci i kolejkę dwóch oczekujących snapshotów. UI pokazuje kolejkę i pominięcia. Test z rzeczywistym `BEGIN IMMEDIATE` potwierdza dostępność cache, zdrowia i odczytów repozytorium, obsługę błędów HTTP, ograniczoną kolejkę, zapis po odblokowaniu bez nowego pobrania i szybkie zamknięcie pod blokadą. Retencja działa także podczas `Retry-After`, bez aktualizowania czasu próby źródła.

Wynik końcowy po odseparowaniu zapisu: **563 testy Python**, regresje Node/Chromium i smoke test atlasu na czterech rozmiarach ekranu przechodzą. Ruff i `git diff --check` bez błędów. Pod blokadą `BEGIN IMMEDIATE` odczyt samolotów około 5 ms, zdrowia 3 ms, historii 65 ms (lokalny pomiar testowy).


## v0.21.0 — zalania satelitarne Copernicus GFM

Dodano osobną, domyślnie wyłączoną warstwę GFM, niezależną od Rapid Mapping i dnia publikacji komunikatów. Tryb automatyczny przegląda Polskę w oknie 48 h, sprawdza katalog co 10 min przy aktywnej warstwie i stopniowo odczytuje natywne produkty Sentinel-1. Na poziomie kraju pokazuje lokalizacje grup wykryć, po przybliżeniu rzeczywistą geometrię pikseli 20 m; dymki zachowują czas obserwacji, pochodzenie i jakość. Archiwum pozwala wybrać obszar, daty i obserwację, a próba Kłodzka wczytuje sprawdzony produkt z września 2024 jednym kliknięciem. Wodowskazy i ostrzeżenia IMGW pozostają dostępne jednocześnie.

Wymagane maski wody referencyjnej i wykluczeń oraz NoData ograniczają interpretację detekcji. Nowsza poprawna ocena zastępuje starszą; zmiana wersji metadanych zachowuje poprzednią ocenę do udanego odczytu. Wyłączenie warstwy i ukrycie widoku anuluje żądanie oraz jego ponowienia. Odczyt HTTP Range ma limity transferu, czasu, liczby żądań i cache, wspólną blokadę oraz backoff/Retry-After. Kosztowne operacje odbywają się w wątkach. Błędy natywnych callbacków GDAL są bezpiecznie przenoszone do warstwy Pythona, a geometria powstaje z jawnie georeferencyjnych danych. Demo jest offline; bez migracji bazy, autostartu i globalnej instalacji.

Weryfikacja: **637 testów Python, 129 testów Node, 5 scenariuszy GFM Chromium (desktop/mobile/szeroki ekran)** oraz Ruff. Próby rzeczywistych produktów z 15.09.2024 i 17.10.2026 potwierdzają odczyt, maski i położenie; nie są walidacją terenową powodzi. Pełny kraj może mieć niepełne pokrycie, brakujące maski lub ograniczony wynik; pierwsze odczyty trwają kilka minut. [Instrukcja, ograniczenia i dowody](gfm.md).


## v0.22.0 — Sentinel-2 — przed / po

Dodano osobną, domyślnie wyłączoną warstwę wizualnego porównania Sentinel-2 L2A RGB 10 m. Wybór punktu w Polsce, wycinki 2/4/6 km, własne daty UTC, filtr zachmurzenia i jawny wybór dwóch obserwacji z Catalog API CDSE. Process API renderuje wybrane produkty do wspólnej siatki EPSG:3857 ze stałymi parametrami RGB; backend sprawdza produkt, czas i geometrię, odrzucając niezgodne rendery i mozaiki. Suwak obsługuje mysz, dotyk i klawiaturę, a maski SCL 20 m i NoData pomagają interpretować pokrycie oraz jakość.

OAuth i token pozostają w backendzie; konfiguracja `[sources.sentinel2]` jest opcjonalna. Pobieranie wyłącznie na żądanie, ograniczone cache, deduplikacja, limity kolejki, współbieżności, czasu i transferu, obsługa 401/403/429/503 oraz Retry-After. Demo działa całkowicie offline i jest oznaczone jako syntetyczne. Poprawki po przeglądach i zgłoszeniu użytkownika obejmują tożsamość obserwacji demo po zmianie dat, kontrolkę mieszczącą się w panelu przy 700–900 px oraz wybieranie punktu nad karteczkami i innymi warstwami interaktywnymi. Znacznik punktu jest widoczny ponad innymi obiektami.

Weryfikacja: **670 testów Python, 119 testów UI Node, 7 scenariuszy Chromium Sentinel-2** (desktop, telefon z dotykiem, 700/800/900 px, wybór punktu), Ruff, zgodność lockfile i `git diff --check`. Dane z historycznej próby LIVE usunięto. Nie jest to automatyczne wykrywanie zmian; sezon, oświetlenie i chmury wpływają na interpretację. Brak migracji bazy, wdrożenia i autostartu. [Instrukcja i kontrakt](sentinel2.md), [raport implementacji](sentinel2-implementation.md), [dowody wydania](evidence/sentinel2/).


## v0.23.0 — Sentinel-5P — atmosfera regionalna

Dodano osobną, domyślnie wyłączoną warstwę regionalnych kolumn NO₂/SO₂ i indeksu UVAI: własny dzień UTC, wybór konkretnej obserwacji, legendy z jednostkami, widoczność i maski jakości. Catalog i Process CDSE obsługuje backendowy OAuth, również z istniejącej konfiguracji Sentinel-2. Zapytania są wykonywane na żądanie, z ograniczeniami obszaru, czasu, transferu, kolejki i cache. Progi jakości są osobne dla produktów; zachowano prawidłowe zera i wartości ujemne. GIOŚ pozostaje niezależny, a demo jest syntetyczne i offline.

Poprawka po przeglądzie wyklucza sąsiednią granulę przez skrócenie końca przedziału Process o 1 ms, zachowując oryginalne czasy i rygorystyczną walidację pochodzenia. Test odtwarza wcześniejszy błąd dla obu odczytów QA. Wyniki dawnych pomiarów usunięto z dokumentacji.


## v0.24.0 — Ukraina — alerty NEPTUN — 17.10.2026

Dodano opcjonalną, domyślnie wyłączoną warstwę granic Ukrainy, alarmów obwodów/rejonów i osobnych doniesień o zagrożeniach powietrznych. Włączenie kadruje Polskę i Ukrainę. Bez klucza, wyłącznie na żądanie widocznej mapy, z pamięciowym cache, niezależnymi błędami, limitem czasu/rozmiaru, Retry-After i ochroną przed starszym snapshotem. `areaOnly` nie tworzy punktu, `advisory` pozostaje neutralne; stare dane nie sugerują aktualnej pozycji ani odwołania alarmu. Atrybucja NEPTUN i legenda są dostępne również przy zamkniętym panelu warstw.

## v0.24.2 — diagnostyka pobierania samolotów — 18.10.2026

Przy przerywanym połączeniu z ADSB.lol przeglądarka ma 15 sekund na odebranie odpowiedzi lokalnego API, a całe pobieranie źródła jest ograniczone do 10 sekund. Komunikaty rozróżniają brak lokalnego serwera, timeout, błędy HTTP (w tym limit 429) i nieprawidłowe lub stare dane. Backend zapisuje przyczynę do logu, a odpowiedź podaje czas do kolejnej próby; zachowano cache i odświeżanie 10 sekund, przerwy po błędach, Retry-After oraz usuwanie starych pozycji. Testy obejmują całkowity limit czasu, utrzymanie diagnostyki podczas przerwy i powrót po awarii.

## v0.24.3 — domyślnie zwinięte warstwy mapy — 18.10.2026

Sekcja „Pogoda” w panelu „Warstwy mapy” jest domyślnie zwinięta. Wszystkie 13 sekcji warstw użytkownik rozwija samodzielnie. Sprawdzono brak atrybutu `open` we wszystkich grupach warstw oraz poprawność diffu.

## v0.25.1 — regionalne ładowanie i przywrócenie poprawek — 18.10.2026

Na bazie v0.25.0 przywrócono wspólny wybór województwa lub całej Polski, lokalne zapamiętywanie zakresu, filtrowanie punktów i przycinanie warstw do PRG oraz niezależny postęp odczytu każdej wybranej warstwy. Zachowano WICI Noc, style Atlas, licznik głównych warstw i poprawki interfejsu tej wersji.

GIOŚ ogranicza kolejkę indeksów do stacji w regionie i widocznym kadrze, zachowując oficjalne kolory, szary brak aktualnego indeksu, cache i limity API. Prognoza pobiera regionalną siatkę z osobnym cache i wspólnym backoff; krajowe źródła pozostają współdzielone i są filtrowane lokalnie. GFM używa przecięcia kadru z regionem i odświeża geometrię przy zmianie poziomu szczegółowości. Spóźnione odpowiedzi nie nadpisują komunikatów, postępu ani wyników dla nowego województwa, także po A → B → A. Zobrazowania i Sentinel-2 unieważniają punkt poza nowym regionem, wyniki i trwające porównania; ważny punkt pozostaje zachowany.

Weryfikacja: **779 testów Python, 197 testów Node**, Ruff i `git diff --check`. **16 scenariuszy Chromium** GFM, GIOŚ, hydrologii, wyboru regionu i Sentinel-2 oraz kontrola WICI Noc obejmują desktop i telefon. Kontrola motywu sprawdza 7 szerokości w obu motywach, kontrast, trwałość ustawień, tożsamość mapy i niezmienione piksele rastrów. Scenariusz pomiaru pikseli jawnie wybiera całą Polskę, aby zapamiętany region nie przycinał syntetycznego rastra testowego. Próby są offline i nie mierzą szybkości dostawców LIVE. [Zakres i ograniczenia](regions.md).

## v0.25.2 — zmiana źródła samolotów na adsb.fi — 18.10.2026

Bieżąca warstwa i współdzielony kolektor jakości pozycji korzystają z publicznego endpointu adsb.fi v3. Zachowano cache i odświeżanie 10 s, filtrowanie PRG, flagę wojskową, jednostki i wiek pozycji, obsługę timeoutów/Retry-After oraz tryb demo offline. Atrybucja i aktywna dokumentacja wskazują adsb.fi i warunki osobistego, niekomercyjnego użytku. Zachowano oznaczenie ADSB.lol/ODbL dla wcześniejszej lokalnej historii.

## v0.25.3 — pokrycie obrazów Sentinel-2 — 18.10.2026

Wyszukiwanie domyślnie pokazuje pełny zasięg katalogowy; częściowe i nieznane pokrycie wymaga odznaczenia filtra. Wyniki podają liczbę ukrytych obserwacji i ostrzegają o niepełnym lub nieznanym zasięgu. Rzeczywiste NoData jest liczone po renderze osobno dla obu stron; ostrzeżenie z procentem braków pozostaje przy suwaku po zamknięciu panelu warstw. Pełny footprint nie gwarantuje kompletu danych ani braku chmur. Zachowano cache katalogu, jawny wybór obserwacji i odrzucanie spóźnionych odpowiedzi.

Weryfikacja offline: **787 testów Python, 182 testy UI Node, 9 scenariuszy Chromium** oraz dwa scenariusze pokrycia w ciemnym motywie. Uwzględniono regresje zmiany dat demo, wskazywania punktu i szerokości 700/800/900 px. Ruff i `git diff --check` poprawne. [Szczegóły i ograniczenia](sentinel2.md).

## v0.25.4 — izolacja pochodzenia obserwacji lotniczych — 18.10.2026

Migracja 011 zachowuje wcześniejsze próbki jako historię o nieustalonym pochodzeniu, poza oceną i tłem. Nowe próbki zapisują okres dostawcy i endpointu; zmiana źródła, również powrót do poprzedniego, wymaga nowej rozgrzewki. Restart tego samego źródła zachowuje okres i status. Mieszane okna są wyłączone z oceny i tła, spóźniony zapis starszego okresu nie nadpisuje stanu bieżącego, a stare obserwacje nie maskują wieku nowych danych. Dymki pokazują pochodzenie i wyłączenia. Kod używa wyłącznie adsb.fi; usunięto stare nazwy fixture i pozostały adres starego endpointu z aktywnej dokumentacji. Atrybucja istniejącej historii pozostaje zachowana.

Regresje: zmiana źródła przy różnym udziale pogorszenia, rzeczywista anomalia po nowej rozgrzewce, powrót do dostawcy, restart, wspólne okno i deduplikacja, opóźniony zapis/status oraz migracja mieszanej bazy bez zgadywania pochodzenia. Weryfikacja: **792 testy Python**, **182 testy UI Node** i regresje cyklu życia warstwy, Chromium dla warstwy jakości oraz pełnego atlasu na czterech szerokościach. Ruff i `git diff --check` poprawne; testy offline na tymczasowych bazach, bez zmiany lokalnej historii live.

## v0.25.5 — porównania Sentinel-2 między latami — 18.10.2026

Osobne zakresy „Od/Do” dla „przed” i „po” pozwalają porównać np. 2020 i 2026. Każda lista ma własny zakres do 366 dni i limit 50 wyników przed filtrowaniem pokrycia; odstęp między wybranymi obserwacjami może wynosić wiele lat. Błąd jednej listy nie usuwa wyniku drugiej, a zmiana dat usuwa stare porównanie i blokuje spóźnione odpowiedzi. Zachowano pełne pokrycie jako domyślny filtr i ostrzeżenia o rzeczywistych brakach obrazu.

Weryfikacja offline: **793 testy Python**, **187 testów UI Node** i **11 scenariuszy Chromium**, w tym porównania 2020 → 2026 i 2021 → 2026, cache, zmiana dat, regionu i szerokości 700/800/900 px. Porównania między latami przeszły też w ciemnym motywie na komputerze i telefonie. Ruff i `git diff --check` poprawne. [Dokumentacja i ograniczenia](sentinel2.md).

## v0.26.0 — śledzenie samolotu w 3D — 19.10.2026

Warstwa samolotów oferuje „Podążaj w 3D”: kamerę zewnętrzną z regulacją odległości i obrotem oraz pierwszą osobę zgodną z kursem wyświetlanej pozycji. Lokalny CesiumJS, autorski model samolotu, globus WGS84, granice PRG, siatka i podpisy miast działają bez konta, kluczy i CDN. Opcjonalny OpenStreetMap jest osobno włączany. Powierzchnia pozostaje uproszczona, bez rzeźby terenu i budynków.

Oba widoki współdzielą odczyt adsb.fi co 10 s. Animacja odtwarza raporty z opóźnieniem 12 s, interpolacją i predykcją ograniczoną do 5 s; utrata świeżych danych zatrzymuje ruch. Poprawki po review obejmują zatrzymanie pętli po awarii renderera, zachowanie ruchu przy niskim FPS, odblokowanie POV według faktycznie wyświetlanego kursu i zachowanie kadru Atlasu przy dużym zoomie. Popup poza kadrem jest zamykany przy powrocie, z fokusem na mapie; zwykłe działanie popupu zostaje przywrócone. Wyjście zwalnia viewer i zasoby WebGL.

Weryfikacja: **800 testów Python**, **227 testów Node** i **10 scenariuszy Chromium** przeszło, w tym regresja kadru przy zoomie 14, błędy renderowania, opóźniony kurs, cykl życia i telefon w obu motywach. Osobno przeszły regresje Atlasu i WICI Noc w siedmiu szerokościach, Ruff, składnia JS, manifest Cesium i powtarzalność modelu. Próby 3D korzystały z danych syntetycznych i odizolowanego backendu DEMO, bez rzeczywistych połączeń zewnętrznych. Safari, Firefox i usługi LIVE nie były weryfikowane. [Obsługa, dokładność i wyniki](aircraft3d.md).

## v0.27.0 — śledzenie autobusów w 3D — 19.10.2026

Autobusy Szczecina, Krakowa, Poznania i Warszawy korzystają ze wspólnego widoku 3D: kamery zewnętrznej 15–500 m oraz pierwszej osoby około 2,2 m nad uproszczoną powierzchnią. Autorski model autobusu jest ustawiony zgodnie z kursem. Nie ma dodatkowego pollera ani pomiaru wysokości; odtwarzanie jest opóźnione o 12 s, bez przewidywania dalszej jazdy. Brakujący namiar można oszacować z przesunięcia netto co najmniej 10 m, także przy wolnej jeździe, z jawnym oznaczeniem w HUD. Brak źródłowej prędkości pozostaje brakiem danych.

Przełączanie między autobusami i samolotami pozostawia jednego właściciela kamery. Zmiana miasta, niepasująca linia, wyłączenie warstwy, region lub opuszczenie Atlasu zamykają scenę i zwalniają GPU. Ukrycie karty wstrzymuje pracę; nieaktualne raporty i błędy zatrzymują ruch. Powrót zachowuje kadr Atlasu, również gdy popup autobusu opuścił ekran przy dużym zoomie. [Obsługa i ograniczenia](buses3d.md).

Poprawka po review: przy śledzeniu bez filtra linii tytuł, nazwa encji i etykieta modelu aktualizują się wspólnie po przyjęciu nowego raportu. Zmiana podczas ładowania silnika pozostaje widoczna także po późniejszym błędzie źródła. Regresja zachowuje tę samą encję, model i viewer, sprawdza obie kamery oraz odrzucenie spóźnionego raportu; potwierdzono RED → GREEN.

Weryfikacja po poprawce etykiety: ponownie przeszło **800 testów Python**, **257 testów Node** i **18/18 scenariuszy Chromium** dla autobusów i samolotów. Regresje obejmują etykietę przy zmianie linii bez filtra, wolną jazdę bez namiaru, jitter i przerwy GPS, rzeczywistą orientację glTF, opóźnione odblokowanie POV, oba aktywne feedy, zmianę linii raportowaną przez źródło, cykl życia i kadr przy zoomie 14. Ponownie przeszły Ruff, JS, lockfile, manifest Cesium i oba modele; wcześniejsze kontrole Atlasu i WICI Noc również zakończyły się powodzeniem. Niezależny przegląd poprawki bez dalszych usterek. Próby offline, z danymi syntetycznymi; bez testów usług LIVE, Safari i Firefox.


## v0.28.0 — przełącznik komunikatów i pamięć checkboxów — 20.10.2026

Przełącznik „Komunikaty i ostrzeżenia” w panelu warstw steruje karteczkami, kolorowaniem obszarów i legendą podstawowej nakładki. Wyłączenie pozostaje skuteczne przy odświeżaniu danych, zmianie dnia i wyborze publikacji; wybór ukrytego komunikatu nie przesuwa mapy. Główny przełącznik ma pierwszeństwo nad opcją wspólnego widoku IODA.

Wybory checkboxów są zapisywane lokalnie w przeglądarce i przywracane przed inicjalizacją warstw. Obejmuje to opcje pomocnicze i podkład 3D oraz włączanie radaru i wiatru przyciskiem odtwarzania. Archiwum nie nadpisuje preferencji filtra komunikatów udostępnianych dziś. Błąd lub niedostępność pamięci nie blokuje aplikacji; wybory pozostają wtedy w pamięci bieżącej strony.

Weryfikacja zmian interfejsu: **266 testów Node i 9 scenariuszy Chromium** przeszło. Nowe regresje obejmują przełączanie nakładki, odświeżenie strony, uruchomienie zapamiętanej warstwy, IODA, zmianę dnia i szerokość 320 px. Sprawdzono również istniejące regresje IODA i podkładu OSM w 3D. Testy przeglądarkowe korzystały z odizolowanego serwera demo i danych syntetycznych.

## v0.29.0 — zapis tras samolotów i statków — 20.10.2026

Przycisk „Śledź trasę” uruchamia zapis wybranego samolotu lub statku w lokalnej bazie. Mapa pokazuje zaznaczenie i przebytą trasę, a panel obserwacji pozwala przewijać i odtwarzać historię. Kolektor działa także bez otwartej karty i wznawia aktywne obserwacje po restarcie WICI. Limit to 20 aktywnych obserwacji i 7 dni historii; przerwy pozostają jawne i nie są uzupełniane.

Symbole zachowują kolory klasyfikacji samolotów i wszystkich trzech kategorii AIS podczas śledzenia i odtwarzania. Klasyfikacja jest utrwalana razem z obserwacją. „Wyjdź ze śledzenia” kończy aktywny zapis wybranego obiektu, usuwa jego trasę i zaznaczenie, zwija panel i zapamiętuje brak wyboru po odświeżeniu. Historia pozostaje dostępna na liście.

Weryfikacja: **838 testów Python, 283 testy Node i 2 scenariusze Chromium** przeszły. Testy obejmują migracje bazy, zapis bez przeglądarki, restart, retencję, przerwy, trzygodzinną historię, kolory, wyjście ze śledzenia i ponowne otwarcie zapisanej trasy. Przegląd kodu bez uwag; próby przeglądarkowe korzystały z odizolowanego serwera i danych syntetycznych. Bez testów usług LIVE, Safari i Firefox. [Obsługa i ograniczenia](tracking.md).

## v0.30.0 — stanowisko analityczne, etap 1 — 22.10.2026

Zakładka „Analiza” udostępnia katalog komunikatów, wodowskazów IMGW, stacji GIOŚ i obszarów PRG. Mapa, tabela i oś czasu mają wspólny zakres oraz wybór obiektu. Karty pokazują pochodzenie, jednostki, braki danych, wersje komunikatów i lokalną historię stacji. Przedział i kursor nie zmieniają się przy odświeżeniu; zapisane stanowiska odtwarzają filtry, czas, kamerę i układ.

Addytywne migracje 015/016 wprowadzają projekcję katalogu i 14-dniową historię odczytów na żądanie. Korekty oraz brak pomiaru pozostają jawne, a oficjalny indeks GIOŚ jest niezależny od stężenia substancji. Wspólny manager odczytów zachowuje cache i limity. Przejście między Sytuacją i Analizą zachowuje ustawienia Atlasu oraz aktywny zapis tras. [Instrukcja](analysis-workspace.md).

Weryfikacja: **880 testów Python, 322 testy Node, 2 nowe scenariusze Chromium i 27 istniejących scenariuszy Chromium** zaliczonych, w tym ponowne próby po poprawkach preferencji, regionu i GIOŚ. Ruff, składnia JS, lockfile i diff poprawne. Dla miliona pomiarów p95 lokalnego zapytania po rozgrzaniu wyniosło 54,99 ms, a pierwsze zapytanie 2204,74 ms. Testy offline na tymczasowych bazach; bez weryfikacji usług LIVE, Safari i Firefox. [Raport, polecenia i ograniczenia](analysis-workspace-verification.md).

## v0.31.0 — Analiza samolotów i statków — 23.10.2026

Na branchu `codex/wici-analysis-moving-objects` katalog Analizy obejmuje samoloty
i statki. Karty udostępniają metadane, aktualność, zapisane sesje oraz rozpoczęcie
i zakończenie zapisu. Trwała lista obserwowanych jest niezależna od nagrywania.
Można porównać do pięciu obiektów na zsynchronizowanej mapie, tabeli i osi czasu,
z wykresami prędkości i wysokości. Kursor korzysta wyłącznie z zapisanych raportów;
luki i granice sesji pozostają widoczne. [Instrukcja](analysis-moving-objects.md).

Migracja 017 zachowuje istniejący katalog i historię stacji. Ograniczona kolejka
projekcji korzysta ze wspólnych odczytów adsb.fi/AISStream; dotychczasowy kolektor
tras nadal odpowiada za zapis punktów. Błędy utrwalenia są widoczne, a zajęta baza
nie zatrzymuje odpowiedzi istniejącej warstwy samolotów na czas oczekiwania SQLite.

Weryfikacja obejmuje pełny zestaw Python/Node, cztery nowe i piętnaście wcześniejszych
scenariuszy Chromium, budowę paczki oraz kontrolę migracji i regresji.
Testy automatyczne są offline, na tymczasowych bazach. Osobna próba LIVE potwierdziła
odczyt adsb.fi/AISStream, obserwowanie, zapis i wspólne odtwarzanie dwóch obiektów.
Safari i Firefox nie były sprawdzane. [Wyniki, polecenia i ograniczenia](analysis-moving-objects-verification.md).
