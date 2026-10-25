# Relacje i graf powiązań — v0.34.0

Graf w **Analizie** pozwala rozpocząć pracę od wybranych obiektów, rozwijać
ich otoczenie i sprawdzić podstawę każdej relacji. Korzysta z lokalnego katalogu
i zapisanej historii. Eksploracja grafu nie odpytuje dostawców i nie rozpoczyna
rejestracji tras lub alarmów.

## Rozpoczęcie eksploracji

W karcie wybierz **Pokaż powiązania** albo otwórz graf wybranych przypięć
w teczce. Możesz także wyszukać dodatkowy obiekt w panelu grafu. Na komputerze
dostępne są widoki **Mapa / Graf / Mapa + graf**, a na telefonie
**Tabela / Mapa / Graf**. Tabela może pokazywać wynik katalogu albo węzły grafu.

Wybór węzła otwiera wspólną kartę obiektu. Obiekty znalezione w grafie mogą
być poza filtrami katalogu; ich dodanie nie zmienia tych filtrów.
Mapa pokazuje dostępne lokalizacje i geometrie, bez zastępowania braku pozycji
umownym punktem. Przypięte oraz zapisane obiekty bez aktualnego wpisu katalogu
pozostają jawnymi niedostępnymi węzłami.

Wybierz węzeł i rozwiń jego sąsiadów. Wynik jest stronicowany po 50 obiektów,
z licznikami pokazanych i niewczytanych powiązań. Można filtrować typy relacji
i ich pochodzenie. Układ hierarchiczny lub wokół obiektu jest odtwarzany na
wyraźne polecenie; przesunięte węzły zachowują swoje pozycje.

Wyróżnienie ścieżki dotyczy wyłącznie aktualnie widocznego grafu. Brak takiej
ścieżki nie oznacza braku powiązania w całym katalogu. Ukrywanie węzła nie
kasuje obiektu ani jego relacji.

## Typy i podstawa relacji

| Relacja | Podstawa |
|---|---|
| Komunikat → obszar PRG | Przypisanie wybranej wersji komunikatu, z rolą obszaru ostrzeżenia lub powiadomienia. |
| Stacja → województwo | Kod/nazwa ze źródła lub wyliczenie lokalizacji w granicach PRG; metoda jest jawna. |
| Powiat → województwo | Hierarchia kodów lokalnego PRG. |
| Rejon Ukrainy → obwód | Jednoznaczny klucz lub nazwa rodzica ze źródła NEPTUN. |
| Epizod alarmu → region | Identyfikator regionu zapisanego epizodu. |
| Samolot/statek → województwo | Lokalizacja konkretnego dostępnego raportu pozycji w granicach PRG. |
| Obiekt ↔ obiekt | Ręczne powiązanie analityka w konkretnej teczce, z obowiązkowym uzasadnieniem. |

Relacje mają kategorię **źródłowa**, **wyliczona** lub **analityczna**.
Styl linii, etykieta oraz legenda rozróżniają te kategorie. Szczegóły połączenia
pokazują jego podstawę, dostawcę, dostępny adres źródłowy i kontekst czasu.
Wspólny obszar nie tworzy bezpośredniej relacji przyczynowej. Graf nie łączy
obiektów automatycznie na podstawie podobnych nazw lub kolorów.

## Znaczenie czasu

Hierarchie oraz metadane lokalizacji stacji opisują aktualny katalog.
Dla jawnie wybranej wersji komunikatu graf korzysta z przypisań tej wersji.
Granice PRG i geometrie Ukrainy nie są historyczną rekonstrukcją.

Relacja transportu wskazuje konkretny raport, jego czas i pozycję. W trybie
bieżącym obowiązuje aktualność raportu; w przedziale wykorzystywany jest zapis
trasy. Kursor nie interpoluje luk ani nie przenosi pozycji przez przerwę.
Bez raportu przy danym kursorze nie ma relacji z obszarem dla tej chwili.

Alarmy zachowują czasy lokalnych obserwacji oraz niepewny koniec epizodu.
Powiązanie epizodu z regionem nie jest potwierdzeniem aktywnego alarmu przez
cały niepewny okres. Luki pokrycia nadal oznaczają nieznany stan.
Przedziały są półotwarte `[od, do)`. Znormalizowane czasy zapisuje się w UTC,
a prezentacja korzysta z wybranej strefy Warszawa, Kijów lub UTC.

## Relacje analityczne w teczkach

W sekcji powiązań teczki wybierz dwa różne obiekty z przypięć lub bieżącego
grafu i podaj uzasadnienie. Opcjonalnie wskaż notatkę lub zapisany materiał
z tej samej teczki. Relacja jest symetryczna; odwrócenie końców nie tworzy
drugiej relacji tej samej pary. Każda pozostaje interpretacją analityka.

Edycja i usunięcie sprawdzają rewizję. Konflikt w innym oknie nie nadpisuje
szkicu. Historia zachowuje kolejne treści i informację o usunięciu relacji.
Zniknięcie obiektu z katalogu nie usuwa uzasadnienia ani zapisanych etykiet.
Usunięcie powiązanej notatki lub materiału jest oznaczane jako niedostępny
dowód; nie zamienia relacji w fakt źródłowy.

Przełącznik **Pokaż usunięte powiązania i ich historię** udostępnia historię
także po usunięciu relacji. Rewizja zachowuje treść i numer wersji notatki
oraz nazwę i SHA-256 materiału stanowiącego podstawę w chwili zmiany.

## Roboczy graf i niezmienna kopia

**Zapisz układ grafu** przechowuje konfigurację teczki: obiekty, filtry,
pozycje węzłów, ukryte węzły, układ i kontekst czasu. Otwarcie roboczego grafu
odczytuje aktualnie dostępne lokalne dane i stosuje zapisaną konfigurację.

**Zapisz kopię grafu** tworzy niezmienny materiał w teczce. Serwer ponownie
zbiera dane na podstawie selekcji i sprawdza własną rewizję grafu, obejmującą
również obiekty spoza filtrów katalogu. Kopia zachowuje widoczne dane węzłów,
relacje, pochodzenie, uzasadnienia, układ oraz informację o niepełnym otoczeniu.
Pozostaje czytelna po retencji źródeł i restarcie. Czytnik kopii nie wykonuje
zapytania o bieżący graf. Dotychczasowe materiały v0.33.0 pozostają bez zmian.

Limity to 20 obiektów początkowych, 200 węzłów, 500 połączeń i 500 ręcznych
relacji w jednej teczce. Kopia zachowuje limit 5 MiB. Ograniczenie liczby
połączeń oraz niewczytani sąsiedzi są jawnie oznaczani; duże otoczenie należy
zawęzić. Węzły lub połączenia spoza zapisanego fragmentu nie stają się częścią
kopii przez sam fakt istnienia w katalogu.

Pojedyncze otoczenie ma dodatkowy limit 5000 kandydatów. Jego przekroczenie
zwraca jawny błąd wymagający zawężenia eksploracji, bez niejawnego pomijania
wyników. Filtry rodzaju i pochodzenia ograniczają sprawdzane rodzaje powiązań.

## Architektura

`relation_models.py` waliduje selektory, rewizje, kontekst i pozycje.
`workspace_relations.py` odczytuje istniejące projekcje oraz utrzymuje relacje
analityczne i konfiguracje grafów. API `/api/workspace/graph/query`
i `/graph/neighbors` działa lokalnie; mutacje teczek korzystają z ochrony
CSRF/Origin. Rewizja grafu jest niezależna od rewizji zapytania katalogowego.

Migracja `020` dodaje relacje i historię ich zmian, konfiguracje grafów oraz
rozszerza rodzaje materiałów o `graph`. Zachowuje bajty istniejących JSON-ów,
ich SHA-256 oraz blokadę aktualizacji. Nowe kopie grafu mają schemat 2;
dotychczasowe materiały zachowują schemat 1.

`workspace-graph.js` zarządza eksploracją i lokalnym rendererem Cytoscape.js.
`workspace-dossier-relations.js` obsługuje powiązania i grafy teczki,
a dotychczasowe moduły zachowują mapę, tabelę, karty i oś czasu.
Renderer pochodzi z przypiętej paczki npm Cytoscape.js 3.34.4 na MIT;
nie korzysta z CDN. Pochodzenie i sumy kontrolne: `static/vendor/cytoscape/VENDOR.json`.

[Raport weryfikacji](analysis-relations-verification.md).
