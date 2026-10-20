# Zobrazowania po katastrofach

Warstwa wyszukuje materiały dla miejsca wskazanego kliknięciem mapy lub przyciskiem wyboru środka mapy. Otoczenie wyszukiwania wynosi około 10 km. Katalogi są niezależne od filtrów publikacji i województwa; materiały mogą pochodzić z poprzednich lat. Przesuwanie mapy nie uruchamia wyszukiwania.

## Źródła i znaczenie podglądów

- **Copernicus EMS Rapid Mapping**: publiczny katalog aktywacji i ich obszarów zainteresowania (AOI). Podglądy są miniaturami produktów kartograficznych, a nie surowymi zdjęciami satelitarnymi. Data pozyskania zobrazowania jest oddzielona od daty produktu; brak daty wykonania jest jawny. [Opis produktów](https://mapping.emergency.copernicus.eu/about/rapid-mapping-manual/product-overview/what-is-delivered-in-a-product/), [zasady cytowania](https://mapping.emergency.copernicus.eu/about/citation-guidelines/).

Wyniki i obrysy są pomocą w znalezieniu materiałów, nie potwierdzeniem katastrofy. Prostokąt zasięgu może obejmować miejsce bez rzeczywistych pikseli obrazu. Brak materiału, błąd źródła i częściowy wynik są osobnymi stanami. Wyszukiwanie obejmuje do 4 najbliższych aktywacji Copernicus o środku w odległości do 400 km. Wynik zawiera do 12 materiałów przecinających prostokąt otoczenia miejsca; nie stanowi pełnego przeszukania archiwów.

## Dostęp i konfiguracja

Bez konta i klucza API. Domyślnie integracja jest dostępna, a warstwa na mapie wyłączona. Wyłączenie backendu: `[sources.imagery] enabled = false` w `config.local.toml`, następnie restart. W demonstracji integracja nie łączy się z siecią.

API lokalne: `GET /api/imagery?lat=50.43&lon=16.65` oraz `GET /api/imagery/preview/{id}`. Podglądy przechodzą przez backend; endpoint nie przyjmuje dowolnych URL. Metadane i obrazy mają limit 4 MiB. Cache wyników: do 32 miejsc na 15 minut (błędy na 2 minuty), katalog i szczegóły aktywacji na 30 minut; do 8 obrazów na 30 minut. Brak trwałej archiwizacji. Limity czasu pobierania ograniczają oczekiwanie na katalog i podglądy. Przeglądarka używa lokalnych adresów obrazów; CSP pozostaje bez dodatkowych hostów.

## Atrybucja i weryfikacja

Copernicus Emergency Management Service, identyfikator aktywacji i produktu oraz odnośnik do źródła przy wyniku. Oryginalne oznaczenia pozostają w podglądach produktów.

15.10.2026 sprawdzono rzeczywiste odpowiedzi: katalog Copernicus udostępniał aktywację EMSR756 dotyczącą powodzi w Polsce. Pobrano też rzeczywiste podglądy: JPEG Copernicusa. Daty Copernicusa bez strefy czasowej pokazujemy jako dzień kalendarzowy, bez zgadywania godziny. Dostępność katalogów nie zapewnia bieżącego pokrycia każdego miejsca.

Testy: `tests/test_imagery.py` (dostawcy, cache, podglądy i błędy), `tests/test_imagery_api.py` (lokalne API i demo), `tests/imagery_ui.cjs` (wybór miejsca i cykl życia UI).

W Copernicus kliknięcie miniatury lub „Otwórz materiał źródłowy” otwiera stronę źródłową z materiałami aktywacji. Lokalna miniatura służy wyłącznie podglądowi na karcie i nie jest powiększonym produktem.
