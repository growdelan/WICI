# Hydrologia IMGW w WICI

Aktualizacja 18.10.2026: bieżące testy korzystają z autorskich próbek syntetycznych. Kopie źródłowe i dane z dawnych raportów usunięto; [opis zestawu](../tests/fixtures/README.md). Wcześniejsze sprawdzenia live były osobnymi próbami, a nie dowodem pochodzenia obecnych fixture.

Bieżąca warstwa w grupie „Pogoda” panelu „Warstwy mapy”. Dwa niezależne przełączniki: **Wodowskazy** oraz **Ostrzeżenia hydrologiczne**. Nie wymaga klucza. Domyślnie wyłączone w UI; dostęp można wyłączyć przez `[sources.hydro_imgw] enabled = false`. Źródłowe API w demo zwraca `disabled` i nie pobiera sieci. Tryb Analiza ma osobny, jawnie syntetyczny scenariusz wodowskazów w bazie demo.

## Źródła i weryfikacja

Oficjalne [apiinfo IMGW](https://danepubliczne.imgw.pl/apiinfo) wskazuje:

- [hydro JSON](https://danepubliczne.imgw.pl/api/data/hydro/) — lokalizacja, nazwa, rzeka, województwo, stan wody, temperatura, przepływ, osobne czasy i progi stacji;
- [warningshydro JSON](https://danepubliczne.imgw.pl/api/data/warningshydro/) — zjawisko, stopień, treść, uwagi, prawdopodobieństwo, biuro, numer, publikacja, okres oraz opisy i kody zlewni.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

`hydro2/` zwrócił pustą odpowiedź HTML; nie jest używany jako fallback. Nie zmieniono istniejącego adaptera meteorologicznych PDF ani kolektora publikacji. Hydrologia zachowuje osobny cache usług na żądanie. Nowe odczyty wodowskazów zasilają także lokalny katalog i 14-dniową historię trybu Analiza; wykaz ostrzeżeń hydrologicznych pozostaje w dotychczasowej warstwie.

## Czas i znaczenie danych

Pomiary mają osobne daty: `stan_wody_data_pomiaru`, `przeplyw_data`, `temperatura_wody_data_pomiaru`. Daty bez offsetu są przyjmowane jako UTC, zgodnie z dotychczasową konwencją pomiarów IMGW w WICI. **API nie deklaruje strefy w polach ani w odczytanej dokumentacji apiinfo; jest to jawne założenie integracji**, pokazane również w legendzie. Zachowywane jest pole `source_time`. Nie należy utożsamiać czasu pobrania z czasem pomiaru. Interfejs wyświetla daty w Europe/Warsaw.

Ostrzeżenia używają czasu urzędowego Europe/Warsaw. Potwierdzono numer 131 biura w Gdyni przez porównanie JSON z [oficjalnym TXT](https://danepubliczne.imgw.pl/data/current/ost_hydro/GDYN_WHPL11202610161850.TXT): publikacja 16.10.2026 20:48, ważność 16.10 20:49 – 18.10 18:00. JSON podaje dodatkowo sekundy. Rekord i TXT zgadzają się co do numeru, stopnia, treści i minut ważności. Niejednoznaczne lub nieistniejące czasy podczas zmiany DST nie są zgadywane; ważność jest wtedy nieznana. `9999-12-31 23:59:59` oznacza brak określonego końca, bez wyświetlania daty roku 9999. Kod stopnia `-1` prezentowany jest jako brak stopnia (w próbie: susza), a nie ujemny stopień zagrożenia.

Próg ostrzegawczy/alarmowy stacji porównywany jest z aktualnym stanem wody; kolory nie reprezentują stopnia ostrzeżenia. Stan wody jest wyrażony w cm względem wodowskazu, a nie jako wysokość n.p.m. Przepływ: m³/s, temperatura: °C. Brak wartości pozostaje brakiem danych; zero jest poprawną wartością. Pomiar starszy niż 3 godziny, bez daty lub ponad 15 minut w przyszłości nie służy do aktualnej oceny progu. To progi świeżości WICI, nie gwarancja harmonogramu IMGW.

## Odporność i ograniczenia

Osobne cache i blokady dla dwóch źródeł; pobranie najwyżej co 300 sekund, dopiero po włączeniu odpowiedniej warstwy na widocznej mapie. Interfejs wstrzymuje odświeżanie po ukryciu mapy lub dokumentu i ignoruje spóźnione odpowiedzi. Starzenie pomiarów i upływ ważności ostrzeżeń są oceniane także podczas korzystania z cache. Przeglądarka aktualizuje oznaczenia co minutę. Odczyt źródła starszy niż 10 minut jest dodatkowo oznaczany jako nieaktualny.

Stałe adresy HTTPS, bez przekierowań, timeout konfiguracji, najwyżej 4 MiB i 5000 rekordów, wymagany JSON. Błędne rekordy są pomijane z licznikiem i statusem częściowym; nieznany schemat całej niepustej odpowiedzi jest błędem. Pusta tablica jest poprawnym pustym wykazem, nie błędem połączenia. Awaria zachowuje ostatni poprawny odczyt z jego pierwotnym czasem i wyraźnym ostrzeżeniem; po błędzie kolory progów są neutralne. Backoff co najmniej 300 sekund, HTTP 429 respektuje Retry-After (maksymalnie doba). Brak odczytu nie oznacza braku zagrożenia.

Wykaz ostrzeżeń nie zawiera geometrii zlewni ani powiązania ze stacjami. WICI pokazuje pełne opisy i kody w filtrowanej liście, bez zgadywania zasięgu na mapie. Najpierw widoczne są aktywne ostrzeżenia ze stopniem, potem bez stopnia; ważność każdego rekordu jest jawna. Źródło nie podaje czasu wygenerowania całego wykazu ani osobnej daty modyfikacji rekordu, więc świeży HTTP 200 nie dowodzi aktualności treści. Stare daty publikacji ostrzeżeń bez końca same w sobie nie dowodzą wygaśnięcia. Brak SLA i gwarancji pełnego pokrycia.

Testy offline: `tests/test_hydro.py`, `tests/ui_hydro.test.cjs`; autorskie syntetyczne rekordy i opis pochodzenia w `tests/fixtures/imgw_hydro/`. Obejmują jednostki i czas, brak danych, lokalizacje, progi, suszę bez końca, DST, cache, współbieżność, awarie, limit odpowiedzi, retry, demo, lokalne API oraz starzenie i wyłączanie warstw w UI.

## Regresje interfejsu

Wodowskazy używają osobnego panelu Leaflet `hydroStations` nad obszarami publikacji. Znaczniki są aktualizowane po ID; okresowe przeliczenie aktualności i pobranie nowych danych zachowują otwarty dymek oraz aktualizują jego treść. Usunięcie stacji z wykazu lub wyłączenie warstwy zamyka jej dymek. Synchronizacja wywoływana przez główne odświeżanie aplikacji zachowuje termin istniejącego minutowego timera aktualności.

`node --test tests/ui_*.test.cjs` obejmuje testy tożsamości timera, znaczników i otwartego dymka. Dodatkowy test pełnej aplikacji z rzeczywistym, lokalnie dołączonym Leaflet:

```sh
NODE_PATH=/sciezka/do/node_modules node --test tests/hydro_browser.cjs
```

Wymaga Playwright i zainstalowanego Chromium. Sam uruchamia i zatrzymuje serwer demo na wolnym porcie, używa tymczasowej bazy oraz blokuje zewnętrzną sieć. Przechwytuje wyłącznie odpowiedzi hydrologii; rzeczywisty `app.js`, główny harmonogram, API demo, granice i Leaflet pozostają aktywne. Przyspieszony zegar sprawdza starzenie pomiaru i wygaśnięcie ostrzeżenia pomiędzy pobraniami, kliknięcie wodowskazu po ponownym narysowaniu i podniesieniu obszarów publikacji, zachowanie dymka przy pobraniu i błędzie oraz zamknięcie po usunięciu stacji.

## Katalog i historia w trybie Analiza

`hydro_station:imgw:<id_stacji>` identyfikuje stację niezależnie od zmiany jej nazwy. Katalog, tabela, mapa i karta korzystają z zapisanych danych. Historia dopisuje się przy nowych pobraniach używanej usługi; samo przesuwanie kursora i odczyt karty nie wywołują IMGW. Odczyty cache nie tworzą rewizji. Zmiany wartości A → B → A są zachowywane, NULL oznacza lukę, a progi w karcie historycznej pochodzą z odpowiedzi zapisanej razem z pomiarem. Brak dostępnego historycznego progu nie jest uzupełniany bieżącym progiem stacji.

Retencja wynosi 14 dni. Nieznane lub przyszłe daty są zachowane oddzielnie od poprawnego szeregu i nie stają się sztucznym zdarzeniem w chwili pobrania. Błąd źródła i częściowy wykaz zachowują katalog oraz pomiary; status zapisu i źródła pozostaje widoczny. [Model przechowywania](data-model.md#stanowisko-analityczne-migracje-015016), testy `tests/test_workspace_history.py` i `tests/test_workspace_integration.py`.
