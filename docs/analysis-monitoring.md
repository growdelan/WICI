# Własne obszary, reguły i zdarzenia — v0.35.0

W **Analizie** przyciski **Obszary**, **Reguły** i **Zdarzenia** prowadzą od
wyboru miejsca i warunku do zapisanej podstawy wykrycia. Wszystko pozostaje
lokalne; nie ma skryptów użytkownika ani powiadomień zewnętrznych.

## Obszary

Wybierz **Obszary → Narysuj obszar**, kształt i nazwę. Wielokąt kończysz
przyciskiem kończącym rysowanie, prostokąt wyznaczasz dwoma narożnikami,
a koło środkiem i punktem promienia. Możesz zmienić opis i kolor oraz edytować
współrzędne lub ponownie narysować granice. Dostępne są powielanie,
archiwizacja, historia i lista aktualnie dostępnych obiektów wewnątrz.

Własny obszar jest odrębnym typem katalogu (`custom_area:<uuid>`), dostępnym
na mapie, w kartach, teczkach i grafie. Nie zastępuje obszarów PRG. Punkty
na granicy należą do obszaru. Wielokąt jest oceniany według rzeczywistego
kształtu, koło według odległości geodezyjnej, a nie ramki otaczającej.
Geometrie przecinające południk 180° i obszary polarne nie są obsługiwane.

Każdy zapis ma rewizję. Archiwizacja zachowuje historię. Zmiana granic
rozpoczyna nową ocenę powiązanych reguł; oczekujące raporty ze starego okresu
nie są oceniane jako nowe przekroczenia zmienionej granicy. Dawne zdarzenia
i zapisane materiały zachowują pierwotną geometrię.

Kolejność odbioru jest zapamiętywana przed kolejką zapisu, niezależnie od
zegara źródła. Dotyczy to również raportów oczekujących w pamięci.

## Reguły i podgląd

Regułę utworzysz w panelu **Reguły**, z karty lub własnego obszaru.
Podaj nazwę, opis, priorytet, szablon i dane warunku. Przed włączeniem wybierz
jawnie tryb źródła:

- **Ocena dostępnych danych** reaguje na nowe obserwacje zapisane przez
  działające już kolektory. Samo włączenie tej reguły nie uruchamia dodatkowego
  pobierania stacji lub transportu.
- **Monitoring w tle** korzysta ze wspólnych usług, cache i limitów źródeł
  także po opuszczeniu Analizy lub zamknięciu przeglądarki. Serwer WICI
  i komputer muszą działać. Wyłączona integracja lub brak wymaganego klucza
  nadal ogranicza dostępność danych.

Kilka reguł dla tego samego źródła lub czujnika współdzieli odczyt.
Komunikaty korzystają z dotychczasowego schedulera. Reguła alarmów Ukrainy
nie włącza samoczynnie odrębnego archiwum historii alarmów.
Wolne pobieranie jednego zasobu nie wstrzymuje oceny zapisanych danych
ani niezależnych źródeł. Regułę można wyłączyć także po archiwizacji jej obszaru.

| Szablon | Wymagany wybór | Znaczenie |
|---|---|---|
| Transport | Własny obszar, samolot/statek lub typ, wejście/wyjście | Kolejne wiarygodne raporty pozycji; bez zgadywania wyjścia po zniknięciu. |
| Próg pomiaru | Stacja, konkretny czujnik, parametr, jednostka, próg i opcjonalny próg powrotu | Własny próg, niezależny od oficjalnego indeksu GIOŚ; NULL nie jest zerem. |
| Nowy komunikat | Obszar administracyjny PRG i opcjonalne źródła | Nowa publikacja lub istotna nowa wersja z przypisaniem do tego obszaru. |
| Alarm Ukrainy | Region NEPTUN | Zmiana znanego stanu lub pierwsza obserwacja aktywnego alarmu. |

Pierwszy punkt wewnątrz obszaru oznacza **zaobserwowano wewnątrz**;
nie dowodzi wejścia przez granicę. Po przerwie obserwacji lub awarii źródła
ciągłość jest nieznana. Alarm zaobserwowany po luce nie otrzymuje pozornego
dokładnego czasu rozpoczęcia. Żaden brak odpowiedzi nie oznacza odwołania.

Próg jest przekroczony dla wartości **większej** od ustawionego progu.
Próg powrotu może być niższy, aby ograniczyć powtarzanie przy wahaniach.
Powtarzany raport nie tworzy kolejnego zdarzenia. Korekta pomiaru lub nowa
wersja komunikatu jest odrębną podstawą. Zmiana reguły rozpoczyna nową rewizję
oceny, a wcześniejsze zdarzenia zachowują pierwotną definicję.

**Przetestuj na historii** odczytuje zachowane lokalne dane z wybranego
przedziału i pokazuje przykładowe trafienia oraz informacje o pokryciu.
Podgląd nie dopisuje zdarzeń ani nie zmienia checkpointu bieżącej reguły.
Brak zachowanych raportów nie dowodzi braku zjawiska. Wynik ma jawny limit;
przy dużym zbiorze zawęź przedział lub obiekt.

## Skrzynka

Panel **Zdarzenia** filtruje po regule, własnym obszarze, typie obiektu,
priorytecie, czasie obserwacji, stanie warunku przy wykryciu i stanie obsługi.
Czasy wejściowe filtrów są opisane jako UTC.

Każde zdarzenie zachowuje dwa czasy: obserwacji i wykrycia przez WICI.
Szczegóły pokazują regułę i rewizję, geometrię obszaru, rzeczywisty raport,
pomiar lub wersję publikacji oraz ograniczenia i pochodzenie. Dokładność
administracyjna komunikatu pozostaje administracyjna; nie potwierdza
zagrożenia w dowolnym małym wielokącie.

Obsługa przebiega **Nowe → Przyjęte → Zamknięte**. Te czynności i komentarze
mają osobny audyt oraz kontrolę rewizji. Zamknięcie nie zmienia wyniku
warunku i nie uruchamia kolejnego zdarzenia. Stan warunku zapisany w zdarzeniu
dotyczy jego podstawy; bieżącą diagnostykę odczytasz w regule.

Dostępne są przejście do czasu obserwacji, pokazanie obiektu i obszaru na
mapie oraz otwarcie grafu. Nawigacja i odtwarzanie nie oceniają reguł.
Zdarzenie zapisane w teczce jest niezmiennym materiałem ze źródłową podstawą,
kopią reguły i obszaru, komentarzami i historią obsługi z chwili zapisu.
Pozostaje czytelne po retencji danych lub późniejszej edycji reguły.
Wykrycie nie tworzy ręcznej relacji analitycznej.

## Trwałość i diagnostyka

Migracja **021** zachowuje dotychczasowy katalog, historie stacji,
obserwowane, historię Ukrainy i dokładne bajty oraz SHA-256 starych materiałów.
Dodaje obszary, rewizje, reguły, trwały strumień obserwacji, stany i checkpointy
oceny, skrzynkę i audyt. Zdarzenie i checkpoint są zapisywane razem.

Worker działa poza odczytem tabeli i renderowaniem mapy. Surowe raporty
transportu trafiają do oddzielnej kolejki przed łączeniem aktualizacji
katalogu. Przeciążenie i problemy zapisu są jawne; brak ciągłości nie jest
przedstawiany jako wyjście z obszaru. Restart ponawia nieprzetworzone zapisy,
nie pobiera automatycznie brakujących obserwacji z okresu wyłączenia.

Limity: **100 obszarów**, **50 aktywnych reguł**, **90 dni zdarzeń**.
Strumień roboczy ma ograniczoną pojemność; nie jest drugim pełnym archiwum
pozycji. Lokalne historie stacji, tras i Ukrainy zachowują dotychczasową
retencję. Materiały w teczkach pozostają trwałe, z limitem 5 MiB na kopię.

Stan monitora: `GET /api/workspace/monitor/status`. API obszarów, reguł,
podglądu i zdarzeń znajduje się pod `/api/workspace/areas`, `/rules`,
`/rules/preview`, `/events`. Zapisy korzystają z dotychczasowej ochrony
Host/Origin/CSRF. Konflikt rewizji zwraca 409; odczytaj nową wersję,
zachowując swój szkic do świadomego ponowienia.

[Raport weryfikacji](analysis-monitoring-verification.md).
