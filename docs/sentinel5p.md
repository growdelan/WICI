# Sentinel-5P — regionalne smugi NO₂, SO₂ i aerozoli

Warstwa służy do przeglądu regionalnego rozkładu wielkości atmosferycznych nad Polską i jej sąsiadami. Jest niezależna od dnia publikacji komunikatów. Można jednocześnie oglądać stacje GIOŚ: zachowują własne jednostki, legendę i czasy pomiarów. WICI nie oblicza wspólnego wskaźnika ani zgodności tych źródeł.

> Obserwacja satelitarna atmosfery w skali regionalnej. Nie opisuje jakości powietrza przy konkretnej ulicy i nie dowodzi emisji z pojedynczego zakładu.

Brak sygnału nie oznacza czystego powietrza. Warstwa nie przypisuje źródeł emisji ani nie klasyfikuje smug jako przemysłowych lub transgranicznych. Wartości kolumnowe nie są przeliczane na przyziemne µg/m³, indeks GIOŚ, PM10 ani PM2,5.

## Uruchomienie i obsługa

W `config.local.toml` ustaw `enabled = true` w pojedynczej sekcji `[sources.sentinel5p]`. Gdy oba pola `client_id` i `client_secret` są puste, backend może wykorzystać istniejącą parę OAuth z `[sources.sentinel2]`. Można podać osobną pełną parę. Niepełna para nie uruchamia domyślnego zastępstwa. Sekrety i tokeny pozostają na backendzie.

Jeśli nie masz klienta, utwórz konto [CDSE](https://dataspace.copernicus.eu/) i klienta backendowego w [Sentinel Hub Dashboard](https://shapps.dataspace.copernicus.eu/dashboard/), User Settings → OAuth clients. [Instrukcja uwierzytelniania](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html). Po zmianie konfiguracji uruchom WICI ponownie.

W panelu warstw włącz Sentinel-5P, wybierz NO₂, SO₂ lub UVAI, dzień obserwacji UTC i dostępną obserwację. Regulacja przezroczystości nie zmienia wartości. Warstwa jest domyślnie wyłączona; dane pobierane są na żądanie. Wybrany dzień nie jest automatycznie zastępowany innym. Demo `uv run --locked python -m wici --demo` pokazuje wyłącznie jawnie syntetyczne dane, bez dostępu do sieci i bez wymogu OAuth.

## Kontrakt dostawcy

Oficjalne dokumenty sprawdzono 17.10.2026. Dostęp: OAuth2 `client_credentials`, token z `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`; `POST https://sh.dataspace.copernicus.eu/catalog/v1/search` i `POST https://sh.dataspace.copernicus.eu/process/v1`. [Aktualne ścieżki API](https://dataspace.copernicus.eu/news/2026-3-9-api-path-structure-updates-sentinel-hub-services).

Kolekcja i `input.data.type`: `sentinel-5p-l2`. Catalog pozwala filtrować `s5p:type`, `s5p:timeliness` i `sat:absolute_orbit`. WICI wykorzystuje następujące pola:

| Parametr | Pasmo Process | Wielkość i jednostka |
| --- | --- | --- |
| NO₂ | `NO2` / `MOL_M2` | Troposferyczna kolumna NO₂, mol/m² |
| SO₂ | `SO2` / `MOL_M2` | Kolumna SO₂, mol/m²; ograniczenie profilu poniżej |
| UVAI | `AER_AI_354_388` / `INDEX` | Indeks aerozolowy UV z pary 354/388 nm, bezwymiarowy |

API udostępnia `dataMask`, a jakość filtruje przez `processing.minQa`, w procentach, **włącznie z progiem**. Nie udostępnia osobnego pasma `qa_value` ani niepewności retrievalu. `CLOUD_FRACTION` należy do produktu CLOUD; nie jest maską chmur gazu. Obsługiwane są mozaiki `SIMPLE` i `ORBIT`, a nie `TILE`; `ORBIT` zwraca m.in. `sentinel5pProductId`. Wybór najnowszego piksela to `mostRecent`; domyślna preferencja trybu przy tym samym czasie to RPRO, OFFL, NRTI. [Kontrakt S5P Sentinel Hub](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S5PL2.html). Produkty różnych typów wymagają osobnych odczytów. [Ograniczenie produktów](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel5P.html).

## Jakość i interpretacja

| Parametr | Zalecenie produktu | Próg WICI `minQa` | Chmury i ograniczenia |
| --- | --- | --- | --- |
| NO₂ | `qa_value > 0.75` | 76, czyli ≥ 0,76 | Zalecenie usuwa m.in. sceny z cloud radiance fraction > 0,5, część śniegu/lodu i problematyczne retrievale. |
| SO₂ | `qa_value > 0.5` dla głównej kolumny V2.x | 51, czyli ≥ 0,51 | Od V2.x QA uwzględnia kryteria jakości; nie dodajemy dawnego filtra chmur z V1 ani S2. |
| UVAI | `qa_value > 0.8` | 81, czyli ≥ 0,81 | Próg ogranicza m.in. sun glint; chmury i ich cienie mogą nadal wytwarzać duże dodatnie i ujemne wartości. |

Źródła zaleceń: [NO₂ PUM 4.5.0, §8.6](https://sentiwiki.copernicus.eu/__attachments/a_9a684b9fae014dbd44f68f924be68b04ef2a8740ab3a4a756a2b18393c06a80b/S5P-KNMI-L2-0021-MA%20-%20Sentinel-5P%20Level%202%20Product%20User%20Manual%20Nitrogendioxide%202025-4.5.0.pdf), [SO₂ Readme 2.13, §3.1](https://sentiwiki.copernicus.eu/__attachments/a_1c515ea1eb8d682bb41fe537204387fcfcef88984d20f7c7e754f2f0bd4ddfd1/S5P-MPC-BIRA-PRF-SO2-02.08.00-2.13.pdf), [UVAI Readme 2.11, §3.1 i §4.1](https://sentiwiki.copernicus.eu/__attachments/a_65bf3003ee8242fcff7d7a2de36b83ddefef4e7980523b096c68b56ca5876e23/S5P-MPC-KNMI-PRF-AER-AI-Sentinel-5P-UV-Aerosol-Level-2-Product-Readme-2.11.pdf).

Progi WICI są jawnym, konserwatywnym odwzorowaniem ścisłych nierówności na całkowite procenty API; natywne QA jest przechowywane jako bajt ze skalą 0,01. Nie korzystamy z ogólnego domyślnego progu 50 dla UVAI. QA nie jest prawdopodobieństwem prawdziwości pomiaru i nie usuwa wszystkich artefaktów. Nie zastosowano niezależnego filtra zachmurzenia całej sceny.

Produkty SO₂ z procesora V1 są pomijane z jawną liczbą i komunikatem. Wymagają dodatkowych kryteriów śniegu/lodu, AMF, chmur i kąta zenitalnego Słońca, których ten kanał nie udostępnia. Dla historycznych dni należy wybrać dostępny produkt V2+ (np. RPRO); WICI nie przedstawia samego QA > 0,5 jako wystarczającego filtra V1.

**SO₂ — profil i wysokość.** Główne pole oryginalnego L2 `sulfurdioxide_total_vertical_column` opisuje scenariusz zanieczyszczonej warstwy granicznej i korzysta z profilu a priori TM5. Osobne pola dla profili o grubości 1 km przy powierzchni oraz na wysokościach 3, 7 i 15 km i retrieval wysokości SO₂ są innymi produktami. [SO₂ PUM 02.08.00, opis głównego pola na s. 42](https://sentiwiki.copernicus.eu/__attachments/a_9c2a17cc51b3f091c8a3128747750648a8ad11921ec3d0d6ea0ea6bad93310b4/S5P-L2-DLR-PUM-400E%20-%20Sentinel-5P%20Level%202%20Product%20Use%20Manua%20Sulphur%20Dioxide%202025-02.08.00.pdf). **Publiczny kontrakt Sentinel Hub nie wskazuje jednoznacznie mapowania pasma `SO2` na te warianty. WICI nie deklaruje potwierdzonej wysokości 1, 3, 7 ani 15 km i nie mierzy wysokości smugi.** To nierozstrzygnięte ograniczenie kanału dostępu; ocena ilościowa wymaga potwierdzenia mapowania przez dostawcę lub pracy na oryginalnym NetCDF.

**UVAI — znane przesunięcie.** Readme 2.11 z 23.01.2026 opisuje dodatnie przesunięcie około 0,2 punktu dla 354/388 nm w wersji 2.09.01 od końca listopada 2025, niewychwytywane przez QA. Zapowiedziano poprawkę na IV kwartał 2026; samo zapowiedzenie nie potwierdza jej wdrożenia. WICI nie odejmuje arbitralnej korekty. Wyniki służą przeglądowi jakościowemu, nie precyzyjnemu porównywaniu trendów między wersjami procesora.

[Komunikat Sentinel Online z 13.10.2026](https://sentinels.copernicus.eu/view-data-product/-/asset_publisher/hnTU9TvUYa5r/content/copernicus-sentinel-5-precursor-s5p-products-improvement-4) zapowiada na 10.11.2026 procesory NL-L2 03.00.00 (m.in. NO₂/UVAI) i UPAS 03.00.01 (m.in. SO₂). Na dzień tego audytu to przyszła zmiana; nie zakładamy zachowania jakości wszystkich przyszłych wersji bez ponownego sprawdzenia dokumentacji.

Ujemne poprawne retrievale są zachowywane, a zero nie oznacza NoData. Dla SO₂ zalecenie pozostawiania wartości ujemnych wynika także z Readme §4.1: ich usunięcie zmienia statystykę szumu. Odrzucanie przez maskę pozostaje osobną operacją od wyboru kolorów. Luki nie są uzupełniane interpolacją.

Nominalna skala NO₂ przy nadirze wynosi około 3,5 × 5,5 km od sierpnia 2019 (wcześniej około 3,5 × 7 km). Rozmiar i kształt footprintu zależą od produktu i geometrii skanowania. Kwadrat na zreprojektowanej mapie nie jest oryginalnym footprintem; powiększenie i nearest-neighbour nie dodają rozdzielczości. [NO₂ PUM, opis instrumentu](https://sentiwiki.copernicus.eu/__attachments/a_9a684b9fae014dbd44f68f924be68b04ef2a8740ab3a4a756a2b18393c06a80b/S5P-KNMI-L2-0021-MA%20-%20Sentinel-5P%20Level%202%20Product%20User%20Manual%20Nitrogendioxide%202025-4.5.0.pdf).

## Czas, dostępność i pochodzenie

Dzień UTC odnosi się do obserwacji satelity, nie publikacji komunikatów. NRTI, OFFL i RPRO są trybami przetwarzania, a nie stanem odświeżenia WICI. Około trzech godzin jest celem publikacji NRTI opisanym w dokumentacji produktu; nie jest gwarancją dostępności w Sentinel Hub ani SLA WICI. Codzienne pokrycie geometryczne nie gwarantuje użytecznych danych każdego dnia. Opóźnienie publikacji, pojawienie się produktu w kanale dostępu, lokalny czas pobrania i wiek obserwacji są różnymi wielkościami.

Wybór opiera się na identyfikatorze i przedziale obserwacji produktu, z jawnym trybem. Jeśli dostawca nie potwierdzi żądanego produktu w metadanych renderu, wynik nie może być przedstawiony jako ta obserwacja. Sam ograniczony przedział czasu nie dowodzi wyłącznego pochodzenia pikseli. `ORBIT` może grupować sceny; jego metadane należy sprawdzać po renderze. [Funkcje evalscript i ograniczenie `preProcessScenes`](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Evalscript/Functions.html).

Process traktuje koniec zapytania jako włączony do przedziału. WICI odejmuje od niego 1 ms, aby nie dołączyć sąsiedniej granuli zaczynającej się dokładnie na końcu wybranej obserwacji. Dotyczy to obu odczytów QA; wyświetlane czasy i identyfikator produktu pozostają oryginalne. Kontrola dokładnie jednego produktu w metadanych odpowiedzi nadal obowiązuje.

## Zakres lokalny i odporność

Stały obszar to 12–26°E i 48–56°N: Polska z buforem sąsiednich państw. WICI nie pobiera całego globu ani dowolnie dużych wycinków. Jedno wyszukanie obejmuje dokładnie jeden dzień UTC, od 30.04.2018 do dzisiaj. Starsze wersje procesorów mają inne ograniczenia; sam początek zakresu nie gwarantuje dostępności produktu. Raster 200 × 190 w EPSG:3857 jest próbkowany najbliższym sąsiadem w skali około 5 km; zoom nie uruchamia pobierania bardziej szczegółowego obrazu.

Lokalne API: `GET /api/sentinel5p/status`, `GET /api/sentinel5p/search?parameter=no2|so2|aer_ai&day=YYYY-MM-DD` i `GET /api/sentinel5p/render` z tymi parametrami oraz `identifier` z wyszukania. Klient nie przekazuje dowolnego URL ani evalscriptu. Render korzysta z dwóch odczytów tej samej obserwacji: bez minimalnego QA (`minQa=0`) i z progiem produktu. Pozwala to oddzielić ważną wartość od odrzucenia jakościowego. Rozróżnienie braku pokrycia i wewnętrznego NoData wykorzystuje także geometrię katalogową: jest przybliżeniem footprintu, nie niezależną maską natywnych pikseli. Udział ważnych danych opisuje siatkę wyjściową, nie liczbę niezależnych pomiarów.

Cache pamięci: do 12 odpowiedzi przez 600 s; rejestr do 300 wyborów przez 1200 s. Współdzielone zapytania, maksymalnie 2 zadania dostawcy równolegle i 8 zadań oczekujących/aktywnych; 25 s na HTTP, 75 s na całą operację, do 8 MiB odpowiedzi. Nie ma archiwizacji rastrów ani okresowego pobierania. Błędy konfiguracji, autoryzacji, limitu i awarii dostawcy mają osobne stany. Wyłączenie warstwy lub zmiana wyboru unieważnia spóźnioną odpowiedź klienta; nie może ona ponownie pokazać poprzedniego obrazu.

## Dostęp, limity konta i atrybucja

[Kwoty CDSE General Users](https://documentation.dataspace.copernicus.eu/Quotas.html), sprawdzone 17.10.2026: 10 000 żądań i 10 000 PU na miesiąc; 300 żądań i 300 PU na minutę. Są to osobne limity całego konta, współdzielone także z Sentinel-2 i innymi klientami. Nie są gwarancją liczby obrazów ani dostępności. Aktualne zużycie sprawdza się w Dashboard. [Sentinel Hub `Retry-After`](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/RateLimiting.html) jest liczony w milisekundach; lokalne API podaje sekundy. Serwer tożsamości korzysta ze standardowego HTTP Retry-After.

Dane Sentinel podlegają zasadom free/full/open i [warunkom CDSE](https://dataspace.copernicus.eu/terms-and-conditions), bez gwarancji jakości lub ciągłości usługi. Przetworzone rzeczywiste obrazy oznaczamy `Contains modified Copernicus Sentinel data [rok obserwacji]`, processed with Sentinel Hub / CDSE; WICI dobiera produkt, filtruje jakość, reprojektuje i nadaje kolory. [Wytyczne atrybucji CDSE](https://documentation.dataspace.copernicus.eu/FAQ.html). Syntetyczne demo nie jest danymi Copernicus. Nie przypisujemy surowym danym osobnej licencji CC.

## Weryfikacja implementacji — 17.10.2026

Rzeczywista próba użyła istniejącego backendowego klienta CDSE z konfiguracji Sentinel-2, włączając Sentinel-5P tylko w pamięci procesu. Nie zmieniono `config.local.toml`, nie uruchomiono wdrożenia ani autostartu. Końcowy udany przebieg: jeden token OAuth, trzy zapytania Catalog i sześć odczytów Process (po dwa progi jakości dla jednego produktu każdego parametru). Wcześniejsze małe próby diagnostyczne zweryfikowały strukturę `scenes.orbits[].tiles` i składnię evalscriptu obsługiwaną przez dostawcę.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).

Wyniki pomiarów i procentowe zestawienia dawnych produktów usunięto. Próba nie potwierdza opóźnienia publikacji NRT ani kompletności wszystkich dni i wersji produktu.

Powtórzenie próby jest świadomym, ograniczonym użyciem limitów konta:

```sh
uv run python scripts/check_sentinel5p.py --day 2026-10-15 --use-existing-cdse
```

Bez `--use-existing-cdse` skrypt wymaga włączonego źródła w konfiguracji; flaga nie zapisuje konfiguracji. Skrypt nie zastępuje dnia innym i przerywa po błędzie autoryzacji, uprawnień lub limitu konta. Wynik trafia do `docs/evidence/sentinel5p` (można zmienić przez `--output`).

Weryfikacja offline obejmuje kontrakt jednostek i QA, kompletne maski, prawidłowe zero i wartości ujemne, georeferencję, niezgodny produkt/czas/mozaikę, cache/LRU/TTL, współdzielenie i anulowanie zadań, limity rozmiaru i współbieżności, OAuth, Retry-After i awarie. Demo i test lokalnego API używają transportu odrzucającego wszelkie żądania sieciowe.

Polecenia sprawdzające:

```sh
uv run pytest -q
node --test tests/ui*.cjs tests/*_ui.cjs
uv run ruff check .
NODE_PATH=/sciezka/do/node_modules node --test tests/sentinel5p_browser.cjs tests/sentinel2_browser.cjs tests/gios_browser.cjs
```

Ostatnie polecenie wymaga lokalnie dostępnego Playwright/Chromium. Testy tworzą tymczasowe instancje na loopback i zatrzymują je po zakończeniu. Nie konfigurują usługi systemowej.

### Regresja sąsiadujących granuli — 17.10.2026

Test z dwiema granulami i inkluzywnym filtrem czasu odtwarzał błąd przed poprawką; po niej przechodzi dla obu odczytów (`minQa=0/76`), zachowując pełny przedział pochodzenia. Zestaw Sentinel-5P: **53 testy Python i 20 testów Node**, Ruff i `git diff --check` bez błędów.
