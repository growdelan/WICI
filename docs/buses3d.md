# Śledzenie autobusu w 3D

Włącz **Warstwy mapy → Komunikacja miejska → Autobusy miejskie**, wybierz miasto i kliknij numer linii na mapie. **Podążaj w 3D** jest dostępne dla poprawnej pozycji nie starszej niż 60 s, przy działającym odczycie źródła. Brak wysokości albo kierunku nie blokuje kamery zewnętrznej.

**Kamera zewnętrzna** oferuje odległość 15–500 m (domyślnie 70 m) oraz obrót wokół schematycznego autobusu. **Pierwsza osoba** umieszcza wirtualne oko około 2,2 m nad uproszczoną powierzchnią, lekko poniżej horyzontu, zgodnie z wyświetlanym kierunkiem jazdy. Model własnego autobusu jest wtedy ukryty. Nie jest to obraz z kamery ani odtworzenie wnętrza rzeczywistego pojazdu.

## Kierunek, czas i zatrzymanie

Szczecin i dostępne raporty GTFS mogą dostarczać namiar `bearing`. Gdy go brakuje, WICI może szacować kierunek kamery po przesunięciu netto o co najmniej 10 m od przyjętego punktu odniesienia. Działa to także przy kilku małych raportach podczas wolnej jazdy; punkt odniesienia wygasa po 60 s. HUD oznacza wynik jako **„Kurs szacowany z pozycji”**. Postój i drobny jitter zachowują ostatni znany kierunek; sam pierwszy raport bez namiaru nie wystarcza do POV. Przycisk pierwszej osoby odblokowuje się dopiero wtedy, gdy znany kierunek ma faktycznie odtwarzana próbka, również między odczytami API. Nie jest zastępowany kierunkiem północnym. Prędkość nie jest wyliczana z pozycji: brak pomiaru nadal oznacza „Prędkość nieznana”.

Widok korzysta z istniejącego `/api/buses?city=…` i jego zwykłego harmonogramu; nie tworzy drugiego pollera. Maksymalnie 32 raporty wybranego pojazdu pozostają w pamięci widoku. Oś odtwarzania jest opóźniona o 12 s; po dwóch raportach pozycja i kierunek są interpolowane. Między punktami nie dopasowujemy pojazdu do dróg ani rozkładu jazdy. Na zakrętach obraz może przecinać narożniki. Autobus zatrzymuje się na ostatnim odtwarzanym punkcie, **bez ekstrapolacji dalszej jazdy**, także gdy źródło podaje prędkość.

Duplikaty i raporty cofające czas nie zastępują przyjętego toru. Przerwa ponad 60 s lub niefizyczny skok rozpoczyna nowy odcinek; kierunek nie jest szacowany przez taką przerwę. Brak autobusu w odpowiedzi, błąd odczytu i utrata aktualności zatrzymują ruch. Po 60 s raport jest nieaktualny także bez nowego odczytu. Nowe dane tego samego pojazdu mogą wznowić śledzenie. Zmiana miasta izoluje identyczne numery pojazdów i odrzuca spóźnione odpowiedzi poprzedniego miasta.

## Powierzchnia i powrót do Atlasu

Autobus korzysta z powierzchni elipsoidy WGS84 na umownej wysokości 0. To położenie renderowania, **nie pomiar wysokości GPS**. Wzgórza, mosty, wiadukty, tunele, budynki i rzeczywiste pochylenie drogi nie są odwzorowane. Model to autorski, ogólny autobus około 12 m, a nie typ przypisany do pojazdu u dostawcy. Zera wysokości nie pokazujemy w telemetrii jako pomiaru.

Silnik Cesium, workery, model i zasoby są lokalne. Ten sam viewer, modal i mechanizm ładowania obsługują [samoloty](aircraft3d.md); otwarcie kolejnego pojazdu usuwa poprzedni viewer. Pozostałe warstwy nie przejmują jego kamery. Domyślny podkład jest lokalny; **OpenStreetMap (online)** można osobno włączyć, z widoczną atrybucją. Obowiązują istniejące CSP i warunki dostawcy, bez nowych zewnętrznych origin, kont i kluczy.

**Wróć do Atlasu** lub Escape zwalnia zasoby WebGL i zachowuje kadr, warstwy oraz filtry mapy. Popup nie przesuwa Atlasu podczas 3D, również przy dużym zoomie. Popup poza kadrem jest zamykany przy powrocie, a fokus trafia na mapę; pozostający w kadrze zachowuje fokus przycisku. Pierwotne automatyczne przesuwanie popupu jest przywracane. Wyłączenie autobusów, niedostępność miasta, zmiana miasta, niepasujący filtr linii, zmiana regionu i przejście do Źródeł zamykają widok. Ukrycie karty wstrzymuje animację i odczyty. Błąd renderera lub utrata GPU zatrzymuje scenę do ponownego otwarcia, pozostawiając działający powrót.

Przy filtrze **Wszystkie linie** zmiana linii tego samego pojazdu aktualizuje tytuł i etykietę modelu bez ponownego otwierania 3D. Działa to także podczas POV i ładowania silnika; starszy raport nie cofa przyjętej etykiety. Przy wybranej konkretnej linii pojazd przechodzący na inną linię zamyka śledzenie zgodnie z filtrem.

## Zasoby i weryfikacja

Model `src/wici/static/models/bus.gltf` jest generowany przez `python scripts/build_bus_model.py`, z własnych prymitywów geometrii wspólnych z modelem samolotu. `--check` sprawdza faktyczne bufory, indeksy, normalne, wymiary, koła na powierzchni i powtarzalność bajtów. Nos ma oś +X, góra +Y, jednostką jest metr. Nie użyto zewnętrznych modeli ani tekstur.

```sh
uv run --locked pytest -q
uv run --locked ruff check .
node --test tests/*.test.cjs tests/aircraft_ui.cjs tests/ships_ui.cjs
node tests/buses_ui.cjs
node --test --test-concurrency=1 tests/aircraft3d_browser.cjs tests/buses3d_browser.cjs
python scripts/vendor_cesium.py --check
python scripts/build_aircraft_model.py --check
python scripts/build_bus_model.py --check
git diff --check
```

Testy wymagające Chromium korzystają z opcjonalnego Playwright, rzeczywistego lokalnego Cesium/WebGL i danych syntetycznych przechwytywanych przez przeglądarkę. Backend DEMO ma zablokowaną sieć zewnętrzną. Próby nie mierzą dostępności usług miejskich ani pokrycia GPS. Zrzuty i raporty trafiają do ignorowanych katalogów `tmp/buses3d-evidence/` i `tmp/aircraft3d-evidence/`. Safari i Firefox nie są objęte tym przebiegiem.

Weryfikacja z 19.10.2026 po poprawce etykiety: ponownie przeszło **800 testów Python**, **257 testów Node** (w tym 30 testów ruchu autobusów), osobny cykl życia warstwy autobusów oraz **18/18 scenariuszy Chromium** dla autobusów i samolotów. Nowa regresja, potwierdzona RED → GREEN, sprawdza aktualizację etykiety bez filtra linii na tej samej encji, modelu i viewerze, w obu kamerach oraz podczas ładowania silnika zakończonego błędem źródła; starszy raport nie cofa przyjętej etykiety. Przebieg 3D obejmuje też rzeczywiście załadowany model i jego kierunek w świecie, estymowany kurs na opóźnionej osi czasu, duplikaty i cofnięte raporty, zatrzymanie i odzyskanie danych, jeden renderer przy obu aktywnych warstwach, zmianę miasta/linii/regionu, ukrycie karty, anulowanie ładowania, brak WebGL oraz telefon w obu motywach. Przy zoomie 14 aktualizacje 3D i powrót zachowały kadr Atlasu z tolerancją poniżej 1 piksela; przywrócono także autoPan i fokus. Osobno przeszły smoke test Atlasu na czterech szerokościach i WICI Noc na siedmiu szerokościach w obu motywach. Po poprawce ponownie sprawdzono Ruff, składnię JS, spójność lockfile, manifest Cesium, powtarzalność obu modeli i `git diff --check`. Niezależny przegląd poprawki nie wykazał dalszych usterek.
