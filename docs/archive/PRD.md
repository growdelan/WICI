# PRD — Polska: sytuacja i ostrzeżenia

## Lokalne MVP do zbudowania z pomocą Codex

**Wersja:** 1.0  
**Data:** 11 października 2026 r.  
**Status:** specyfikacja do implementacji na podstawie zaakceptowanych rekomendacji.  
**Forma produktu:** prywatna aplikacja lokalna, jeden użytkownik, ręczne uruchamianie.  
**Nazwa katalogu projektu:** `polska-osint`  
**Nazwa pakietu Python:** `polska_osint`

> **Instrukcja nadrzędna dla agenta implementującego:** przygotuj kompletny projekt i instrukcję jego samodzielnego uruchomienia. Nie wdrażaj go jako usługi, nie konfiguruj autostartu, nie publikuj w internecie i nie instaluj niczego globalnie. Użytkownik sam decyduje, kiedy uruchomić i zatrzymać aplikację. Ten dokument nie zleca przygotowania infrastruktury produkcyjnej.

---

## 1. Podstawa dokumentu i przyjęte decyzje

Dokument przekłada wcześniejszy raport badawczo-architektoniczny i zaakceptowane przez użytkownika rekomendacje na wymagania pierwszej implementacji. Nie powtarza całego badania i nie otwiera ponownie wyboru architektury.

### 1.1. Ustalenia zaakceptowane przez użytkownika

| Obszar | Obowiązująca decyzja |
|---|---|
| Przeznaczenie | Prywatny pilot, nie publiczny produkt i nie system służb alarmowych. |
| Obietnica produktu | Oficjalne ostrzeżenia i wybrane udokumentowane wydarzenia dotyczące Polski. Bez obietnicy kompletnego obrazu sytuacji. |
| Priorytet tematyczny | Granice i bezpieczeństwo; osobno ostrzeżenia dla mieszkańców. |
| Automatyzacja | Automatyczna publikacja jednoznacznych ostrzeżeń ustrukturyzowanych; kontrola komunikatów opisowych i przypadków niejednoznacznych. |
| Fundament | Własna niewielka aplikacja, nie fork gods-eye-view. |
| Architektura | Python, `uv`, FastAPI, SQLite, Leaflet, mapa 2D. |
| Źródła aktualności | IMGW — ostrzeżenia meteorologiczne; RSO; RCB; centralny serwis Straży Granicznej. |
| Geografia | PRG jako podstawowe granice i identyfikatory administracyjne. PRNG jedynie jako ewentualna pomoc, nie warunek MVP. |
| Modele językowe | Brak LLM, agentów analitycznych i ML w MVP. |
| Uruchamianie | Ręcznie, lokalnie na komputerze użytkownika. Brak wdrożenia, hostingu i stałej usługi. |

### 1.2. Doprecyzowania projektowe przyjęte w tym PRD

Wymagania dotyczące nazw pól, komend, domyślnych filtrów, interwałów, statusów i testów są **decyzjami projektowymi**, a nie deklarowanymi właściwościami zewnętrznych API. Agent ma je zrealizować bez dodawania funkcji na zapas.

Adresy źródeł i oceny dostępności pochodzą z wcześniejszego raportu. Przy tworzeniu tego dokumentu nie wykonano ponownej weryfikacji internetowej. Aktualne kontrakty integracji, zakres pobierania i warunki dostępu należy sprawdzić w etapie M0. Nie wolno przedstawiać adresu orientacyjnego jako przetestowanego API.

Pierwotny brief określał wiarygodność jako ważniejszą od szybkości, preferował prosty projekt rozwijany z Codex i wykluczał operacyjne śledzenie służb. Te ograniczenia pozostają w mocy. Późniejsza akceptacja użytkownika zamyka wybór rozwiązania; ten dokument stanowi już PRD, a nie kolejny raport porównujący warianty.

## 2. Cel produktu

Aplikacja ma pomagać odpowiedzieć na sześć pytań:

1. Co zostało oficjalnie zakomunikowane i dlaczego jest istotne?
2. Jakiego miejsca, obszaru zagrożenia lub obszaru powiadomienia dotyczy informacja?
3. Kiedy wydarzenie nastąpiło, kiedy je opisano i kiedy pobrała je aplikacja?
4. Na jakich dokumentach opiera się prezentowany opis?
5. Co zmieniono, odwołano albo zakwestionowano?
6. Czego nadal nie wiadomo i czy źródła są dostępne?

**Najważniejsza wartość:** jedna czytelna historia informacji z pochodzeniem, czasem i niepewnością — zamiast wielu podobnych linków albo efektownej, ale mylącej mapy.

**Główna zasada:** aplikacja pokazuje obraz dostępnych publikacji, nie dowodzi braku innych zdarzeń.

### 2.1. Użytkownik i podstawowy scenariusz

Jedynym użytkownikiem MVP jest właściciel projektu. Jest jednocześnie odbiorcą informacji i operatorem zatwierdzającym niejednoznaczne materiały. Nie potrzeba kont, ról organizacyjnych, rejestracji ani współdzielenia danych.

Użytkownik ręcznie uruchamia projekt, otwiera stronę lokalną, widzi zapisane dane i stan aktualizacji. Źródła odświeżają się podczas pracy aplikacji. Użytkownik może przeglądać mapę, zatwierdzać kandydatów do publikacji oraz sprawdzać zmiany. Po zatrzymaniu programu kolektory przestają pracować, a dane pozostają na dysku.

## 3. Granice zakresu MVP

### 3.1. Funkcje wymagane

| ID | Wymaganie |
|---|---|
| F01 | Pobieranie i normalizacja czterech wybranych źródeł, z jawnym stanem każdego adaptera. |
| F02 | Rozdzielenie dokumentu źródłowego od prezentowanego ostrzeżenia, wydarzenia lub informacji kontekstowej. |
| F03 | Automatyczna publikacja wyłącznie jednoznacznych ostrzeżeń ustrukturyzowanych spełniających reguły bezpieczeństwa. |
| F04 | Kolejka kontroli komunikatów opisowych, niejednoznacznych lokalizacji i zmian wymagających oceny. |
| F05 | Deduplikacja dokumentów, aktualizacja po stabilnym identyfikatorze oraz ostrożne łączenie informacji o wydarzeniach. |
| F06 | Mapa Polski 2D, lista rekordów, filtry i panel szczegółów ze źródłami. |
| F07 | Przybliżona lokalizacja jako przybliżenie, obszar jako obszar, brak lokalizacji bez wymuszonego punktu. |
| F08 | Historia istotnych zmian, odwołań, sprostowań i decyzji operatora. |
| F09 | Jawne rozróżnienie czasu zdarzenia, publikacji, aktualizacji, pobrania i ważności. |
| F10 | Obsługa błędów, pustych odpowiedzi, przerw w działaniu oraz wznowienia po restarcie. |
| F11 | Izolowany tryb demonstracyjny z danymi syntetycznymi, bez połączeń ze źródłami. |
| F12 | Testy krytycznych reguł, dokumentacja projektu i ręcznego uruchamiania. |

### 3.2. Poza zakresem

Nie implementować: hostingu, chmury, Docker Compose, Kubernetes, CI dla wielu systemów, autostartu, usług systemowych, rejestracji kont, wielu użytkowników, powiadomień push/SMS/e-mail, aplikacji mobilnej, globusa 3D, sterowania głosem, chatbota, LLM, analizy obrazów, social mediów, płatnych agencji, predykcji ML, bazy wektorowej, grafu wiedzy, Redis, Celery i mikroserwisów.

Nie dodawać do MVP kolejnych integracji: PSP, Policji, DORSZ, PAŻP, GDDKiA, granica.gov.pl, IMGW hydro, GIOŚ, FIRMS ani portali państw sąsiednich. Mogą być przyszłymi rozszerzeniami, ale nie wolno traktować ich jako zadań pierwszej wersji.

Nie zbierać i nie prezentować pozycji jednostek, patroli, tras operacyjnych ani wrażliwych danych osobowych. Nie budować detektora naruszeń przestrzeni powietrznej na podstawie ruchu obiektów lub spekulacji.

Nie budować kompletnego archiwum internetu ani kompletnego rejestru interwencji. Nie wdrażać wskaźnika „poziomu bezpieczeństwa Polski” lub rankingu niebezpiecznych powiatów na podstawie liczby publikacji.

## 4. Kontrakt lokalnego uruchamiania — bez wdrożenia

### 4.1. Sposób dostarczenia projektu

Rezultatem implementacji ma być katalog z kodem, zasobami, testami, plikiem blokady zależności i README. Nie jest wymagany instalator ani obraz kontenera.

Agent implementujący:

- może przygotować i testować projekt w swoim środowisku roboczym;
- nie instaluje globalnego Pythona, `uv`, Node.js, serwera baz danych ani innych narzędzi na komputerze użytkownika;
- nie zmienia ustawień systemu, firewalla, harmonogramu zadań ani przeglądarki;
- nie tworzy wpisów `cron`, `launchd`, `systemd`, usług Windows ani procesów utrzymywanych po zakończeniu pracy;
- nie otwiera tunelu, nie publikuje portu w sieci i nie wdraża aplikacji;
- po ewentualnych krótkotrwałych testach nie pozostawia uruchomionych procesów;
- nie uruchamia aplikacji „za użytkownika” jako części przekazania projektu.

### 4.2. Docelowe komendy użytkownika

Poniższe komendy są **wymaganym interfejsem przyszłego projektu**, a nie informacją, że aplikacja już istnieje lub została uruchomiona.

Pierwsze przygotowanie zależności w katalogu projektu:

```bash
uv sync --locked
```

Każde uruchomienie zwykłej aplikacji:

```bash
uv run --locked python -m polska_osint
```

Uruchomienie demonstracji bez pobierania bieżących danych:

```bash
uv run --locked python -m polska_osint --demo
```

Adres wyświetlany w terminalu:

```text
http://127.0.0.1:8765
```

Zatrzymanie: `Ctrl+C` w terminalu, w którym działa program.

README ma podać wymagania wstępne i instrukcję ich samodzielnego spełnienia. Nie dołączać skryptu instalującego narzędzia globalnie. Pierwsze pobranie zależności wymaga internetu; uruchomiona demonstracja i odczyt wcześniej zapisanych danych nie powinny go wymagać.

### 4.3. Wymagane zachowanie

| Sytuacja | Zachowanie |
|---|---|
| Pierwszy start | Utworzenie lokalnego katalogu danych i bazy; czytelny stan pusty; rozpoczęcie pracy dopuszczonych źródeł. |
| Kolejny start | Natychmiastowy odczyt zapisanych rekordów; aktualizacja źródeł bez blokowania interfejsu. |
| Zatrzymanie programu | Zatrzymanie harmonogramu, zamknięcie połączeń i bazy, zwolnienie blokady instancji. |
| Uśpienie komputera | Brak założenia, że w tym czasie trwa monitoring. Po wznowieniu wykrycie przerwy i pojedyncze odświeżenie zaległych źródeł. |
| Brak internetu | Widoczne zapisane dane, jawny stan błędu/nieaktualności; brak sztucznego czyszczenia mapy. |
| Ponowne uruchomienie drugiej instancji | Czytelny błąd i zakończenie drugiego procesu, bez uruchamiania drugiego kolektora. |
| Zajęty port | Informacja o problemie; nie zabijać obcego procesu i nie zmieniać ustawień sieci. |
| Tryb demo | Oddzielne dane, trwały baner „DANE DEMONSTRACYJNE”, brak żądań do realnych źródeł. |

Serwer ma nasłuchiwać wyłącznie na `127.0.0.1`. Nie obsługiwać w MVP parametru pozwalającego wystawić aplikację na `0.0.0.0`. Jeden proces, jeden worker. Bez automatycznego przeładowywania kodu w standardowej komendzie.

### 4.4. Dane i konfiguracja

Wszystkie zapisy aplikacji pozostają wewnątrz projektu:

```text
var/
  live/
    app.sqlite3
    logs/
  demo/
    app.sqlite3
    logs/
```

Katalog `var/`, pliki blokad i środowisko `.venv/` mają być wykluczone z repozytorium. Nie umieszczać danych aplikacji w globalnych katalogach użytkownika bez jego decyzji.

Domyślna konfiguracja powinna wystarczyć do uruchomienia. Opcjonalny lokalny `config.local.toml` może zmieniać port, aktywność adapterów i dopuszczalne interwały. Ma być ignorowany przez Git. Nie wymagać kluczy API ani pliku `.env` dla bazowego MVP.

Kopia zapasowa w MVP jest ręczna: zatrzymać aplikację i skopiować cały katalog `var/live/`. README musi wyraźnie odradzać kopiowanie samego pliku SQLite podczas aktywnej pracy. Nie tworzyć osobnej usługi backupu.

## 5. Model informacji i reguły interpretacji

### 5.1. Trzy rodzaje obiektów

| `kind` | Znaczenie | Przykład |
|---|---|---|
| `warning` | Ostrzeżenie lub zalecenie dotyczące zagrożenia. | Ostrzeżenie meteorologiczne obowiązujące na wskazanym obszarze. |
| `event` | Informacja, że określone zdarzenie nastąpiło lub trwa. | Oficjalny opis istotnego incydentu granicznego. |
| `context` | Materiał pomagający interpretować sytuację, niekoniecznie opis realnego zagrożenia. | Zapowiedziane ćwiczenie lub komunikat organizacyjny istotny dla mieszkańców. |

Oficjalne ostrzeżenie przed burzą nie jest dowodem, że burza już wystąpiła. Komunikat o działaniach ostrożnościowych nie jest dowodem naruszenia przestrzeni powietrznej. Ćwiczenie nie staje się realnym alarmem na podstawie użytych w jego treści słów.

### 5.2. Kategorie

W MVP wystarczy zamknięty katalog:

- `weather` — ostrzeżenia meteorologiczne;
- `public_safety` — ostrzeżenia dla mieszkańców i istotne sytuacje kryzysowe;
- `border` — istotne wydarzenia graniczne;
- `infrastructure` — poważne utrudnienia lub zdarzenia infrastrukturalne opisane przez wybrane źródła;
- `airspace` — wyłącznie oficjalnie opisane i zatwierdzone komunikaty dotyczące bezpieczeństwa powietrznego;
- `other_context` — kontekst po świadomej decyzji operatora.

Posiadanie kategorii nie oznacza posiadania kompletnego źródła danych dla tej kategorii. W szczególności warstwa `airspace` nie jest detektorem ani kompletnym rejestrem incydentów.

### 5.3. Statusy — oddzielne osie

Nie tworzyć pojedynczej skali mieszającej wiarygodność, ważność i aktualność.

**Podstawa informacji (`information_basis`):**

| Wartość | Etykieta | Reguła |
|---|---|---|
| `official_statement` | Oficjalny komunikat | Opis jest oparty na wskazanym komunikacie właściwej instytucji. |
| `independent_confirmation` | Niezależne potwierdzenia | Wyłącznie ręcznie, z udokumentowaną oceną niezależności co najmniej dwóch źródeł pierwotnych dla wskazanego faktu. |
| `unconfirmed` | Brak wystarczającego potwierdzenia | Materiał nie pozwala przyjąć silniejszej podstawy; nie publikować go automatycznie jako incydentu. |

Domyślną etykietą dla przyjętych ostrzeżeń jest „Oficjalne ostrzeżenie”, nie „Potwierdzone wystąpienie zjawiska”. Status niezależnych potwierdzeń nie jest automatycznie nadawany i nie jest wymagany do ukończenia scenariusza głównego.

**Spójność (`consistency`):** `no_known_conflict`, `disputed`, `denied`. Przy `disputed` lub `denied` wymagane są: wskazanie spornego twierdzenia, dokumenty oraz krótka notatka. Dementi dotyczące przyczyny nie usuwa automatycznie informacji o samym wydarzeniu.

**Przebieg wydarzenia (`event_phase`):** `planned`, `ongoing`, `ended`, `unknown`. Dotyczy wydarzeń i kontekstu; brak informacji oznacza `unknown`.

**Ważność ostrzeżenia (`warning_status`):** `upcoming`, `active`, `expired`, `cancelled`, `unknown`. Dotyczy ostrzeżeń. `expired` oznacza upływ zadeklarowanej ważności, nie potwierdzenie zakończenia zjawiska.

**Publikacja (`publication_state`):** `published`, `withdrawn`, `merged`. Kandydaci oczekujący na akceptację są przechowywani w kolejce kontroli, nie w publicznej liście. „Publikacja” oznacza tu wyłącznie pojawienie się w lokalnym interfejsie.

**Oczekiwanie na przegląd zmiany:** oddzielny znacznik `pending_review`, nie nowy stan faktyczny wydarzenia.

### 5.4. Istotność

Lista ma wyróżniać „Bezpieczeństwo i granice” oraz „Ostrzeżenia dla mieszkańców”. Liczne ostrzeżenia pogodowe nie mogą wypierać pojedynczego ważnego komunikatu granicznego.

Wystarczą dwie wewnętrzne wartości: `normal` i `important`. Istotność może ustawić operator; dla ostrzeżeń można zachować oficjalny stopień źródła. Nie wyprowadzać jednego „wyniku ryzyka” z różnych skal instytucji.

## 6. Źródła i kontrakty integracji

### 6.1. Zakres dowodów i aktualność adresów

Wcześniejszy raport wskazał odczyt przykładowych danych IMGW i RSO oraz strony RCB i SG. Nie oznacza to gwarancji ciągłej dostępności, kompletności, stabilnego schematu ani prawa do dowolnego ponownego wykorzystania. Każdy adapter wymaga opisanego kontraktu i testów próbek.

| ID źródła | Zakres MVP | Punkt startowy z raportu | Domyślny interwał |
|---|---|---|---:|
| `imgw_meteo` | Oficjalne ostrzeżenia meteorologiczne | `https://danepubliczne.imgw.pl/api/data/warningsmeteo` | 5 min |
| `rso` | Publiczne komunikaty, ostrzeżenia i aktualizacje | `https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/1?_format=json` | 5 min |
| `rcb` | Alerty RCB i ich aktualizacje, nie cały serwis prasowy | `https://www.gov.pl/web/rcb` — strona startowa, nie API | 10 min |
| `sg` | Wybrane istotne materiały centralnego serwisu SG | `https://www.strazgraniczna.pl/pl/aktualnosci` — strona HTML | 30 min |

Interwały są ustawieniami projektu, a nie deklaracją szybkości publikacji instytucji. Dłuższy wymagany przez dostawcę interwał ma pierwszeństwo.

### 6.2. IMGW — reguły adaptera

Adapter ma pobierać ostrzeżenia meteorologiczne, odwzorować identyfikator, typ, stopień, treść, okres obowiązywania, czas publikacji i dostępne identyfikatory obszarów. Nazwy rzeczywistych pól należy potwierdzić na próbce i zapisać w `docs/sources.md`.

Automatyczna publikacja jest dozwolona, gdy rozpoznano rodzaj ostrzeżenia, jednoznacznie zidentyfikowano dokument i poprawnie odczytano czas oraz obszar odniesienia. Brak geometrii do poprawnie odczytanego kodu administracyjnego nie wymaga wymyślenia punktu: ostrzeżenie może być widoczne na liście z oznaczeniem brakującej geometrii.

Nieznany kod, niejednoznaczny czas, nieobsługiwany rodzaj komunikatu albo brak wymaganych pól kierują konkretny rekord do kontroli. Pozostałe poprawne rekordy mogą być przetworzone, ale cała próba ma wtedy stan częściowy. Nie wolno na tej podstawie usuwać nieobecnych rekordów.

Nie pobierać ostrzeżeń hydrologicznych „przy okazji”. Ich odmienny schemat i geografia są poza MVP.

### 6.3. RSO — reguły adaptera

Korzystać z publicznego kanału JSON wskazanego w raporcie. Nie uzależniać MVP od osobnego dostępu CAP/OpenAPI i tokena.

W M0 ustalić rzeczywiste zasady filtrowania, zakresu i paginacji. **Nie zakładać, że końcowe `/1` w adresie oznacza numer strony.** Nie deklarować kompletności na podstawie jednej odpowiedzi, jeśli kontrakt tego nie uzasadnia.

Każdy komunikat sklasyfikować jako jednoznaczne ostrzeżenie, opisowe wydarzenie, kontekst lub materiał do kontroli. Sam fakt występowania w RSO nie pozwala na automatyczne opublikowanie go jako potwierdzonego incydentu.

Automatyczna publikacja dotyczy wyłącznie rozpoznanych, przetestowanych typów ostrzeżeń z poprawną ważnością i zrozumiałym obszarem. Ćwiczenia, testy syren, niejednoznaczne alarmy i swobodny opis trafiają do kontroli. Ćwiczenia mają etykietę kontekstu, nigdy realnego alarmu.

Jeżeli komunikat wskazuje IMGW jako źródło, zapisać pochodzenie. Taki przedruk nie jest niezależnym potwierdzeniem ostrzeżenia.

Puste współrzędne są prawidłowym stanem. Województwo przypisane do komunikatu nie staje się automatycznie miejscem wydarzenia; może oznaczać obszar publikacji lub powiadomienia.

### 6.4. RCB — reguły adaptera

Zidentyfikować właściwy wykaz alertów i strukturę dokumentów w M0. Nie wymyślać adresu RSS ani API. Pobierać tylko sekcję objętą kontraktem, nie cały serwis gov.pl.

Odczytywać tytuł, kanoniczny URL, publikację, treść istotną dla alertu i dostępne oznaczenia aktualizacji. Nowe materiały oraz istotne zmiany przechodzą przez kontrolę operatora. Reguły mogą przygotować typ, obszary i kandydaturę odwołania, ale nie zatwierdzają samodzielnie interpretacji opisowego komunikatu.

Oddzielać lokalizację opisywanego zdarzenia od polskiego obszaru dystrybucji alertu. Wydarzenie poza Polską może być prezentowane, gdy przyjęty komunikat wskazuje znaczenie dla Polski; brak granic zagranicznych w lokalnym podkładzie nie uzasadnia umieszczenia zdarzenia na terytorium Polski.

Nie dodawać raportu dobowego jako piątej integracji. Nie pobierać zdjęć ani materiałów multimedialnych.

### 6.5. Straż Graniczna — reguły adaptera

Pobierać materiały z centralnego serwisu aktualności. Nie uruchamiać crawlera wszystkich oddziałów.

Treści opisowe zawsze przechodzą przez kolejkę kontroli przed publikacją wydarzenia. Jednoznacznie promocyjne lub organizacyjne publikacje mogą otrzymać status pominiętych z zapisaną przyczyną. Operator powinien móc zobaczyć pominięte materiały; wątpliwy materiał należy przekazać do kontroli, nie odrzucać po jednym słowie kluczowym.

Priorytet mają istotne incydenty i ograniczenia ważne dla mieszkańców. Zbiorczej informacji o liczbie interwencji nie rozbijać na wymyślone zdarzenia i punkty. Nie wykorzystywać siedziby oddziału jako lokalizacji opisywanego incydentu.

Nie zapisywać nazwisk, szczegółów pozwalających identyfikować osoby ani informacji operacyjnych niepotrzebnych do celu aplikacji. Oczyszczony opis ma dotyczyć zdarzenia i przybliżonego obszaru.

### 6.6. Dokumentacja dostępu

Dla każdego źródła `docs/sources.md` musi zawierać: adres startowy i dokumentację, datę sprawdzenia, schemat, identyfikację dokumentów, interpretację czasu, zakres i paginację, zasady aktualizacji, wymagane oznaczenia źródła, stwierdzone ograniczenia oraz wynik próby dostępu.

Nie utożsamiać publicznego adresu z nieograniczoną zgodą na automatyczne pobieranie i publikację. Sprawdzić warunki źródła i zasady dostępu; sam plik robots.txt nie rozstrzyga praw do treści. Nie obchodzić CAPTCHA, logowania, blokad lub limitów.

Stan dostępu adaptera: `enabled`, `disabled_by_user`, `blocked_access`, `needs_verification`. Powód blokady jest widoczny w UI. Niejednoznaczny dostęp nie oznacza zakazu budowania reszty projektu, ale wyklucza udawanie działającej integracji.

## 7. Pobieranie, świeżość i odporność

### 7.1. Harmonogram

Wystarczy jeden prosty harmonogram asynchroniczny uruchamiany wraz z aplikacją. Nie potrzebuje osobnego procesu ani zewnętrznego brokera.

Reguły:

- jedna aktywna operacja pobierania na źródło; maksymalnie dwie jednocześnie dla całej aplikacji;
- po starcie odświeżyć źródła, których termin minął, bez czekania pełnego interwału;
- ręczne „Odśwież” korzysta z tego samego mechanizmu, nie tworzy drugiej pętli;
- po wznowieniu komputera wykonać jedno odświeżenie zaległego źródła, nie odtwarzać wszystkich opuszczonych wywołań;
- respektować `Retry-After`, warunkowe żądania i limity dostawcy, gdy są dostępne;
- na błędy stosować rosnące opóźnienie, ograniczone domyślnie do 60 minut; wymaganie dostawcy może je wydłużyć;
- stosować limit czasu i rozmiaru odpowiedzi, z wartościami zapisanymi w konfiguracji; dla pojedynczych JSON/HTML punktem startowym jest 20 sekund i 10 MB;
- operacje sieciowe nie mogą trzymać otwartej transakcji zapisu SQLite.

### 7.2. Zakres nadrabiania

Dla źródeł będących bieżącym zestawem ostrzeżeń pobrać aktualny dostępny zestaw. Dla źródeł publikacyjnych domyślnie przeglądać ostatnie 7 dni, w granicach potwierdzonego kontraktu i rozsądnych limitów. Dodatkowo sprawdzać wcześniej znane dokumenty dotyczące niewygasłych ostrzeżeń, nawet jeśli ich pierwsza publikacja jest starsza.

Jeżeli brak paginacji lub limit dostawcy uniemożliwia pokrycie całego okna, zapisać i pokazać faktyczny zakres. Nie twierdzić, że nadrobiono całą przerwę. Dłuższa przerwa w działaniu może oznaczać brak publikacji historycznych, których źródło już nie udostępnia.

Nie implementować ogólnokrajowego historycznego backfillu. Stare wydarzenia nie są monitorowane bezterminowo. UI ma podawać czas ostatniego sprawdzenia dokumentu, zamiast sugerować jego ciągłą weryfikację.

### 7.3. Stany techniczne

Rozdzielić:

- **wynik ostatniej próby:** `success`, `not_modified`, `partial`, `error`;
- **dostępność adaptera:** aktywny, wyłączony lub zablokowany;
- **świeżość:** wyliczana z ostatniego poprawnego sprawdzenia;
- **pokrycie:** potwierdzone dla zadanego zakresu albo niepełne/nieustalone.

Pusty, poprawny zestaw może oznaczać zero komunikatów. Nie jest awarią. HTML zwrócony zamiast oczekiwanego JSON, uszkodzony schemat i strona antybotowa nie są poprawnym pustym zestawem.

Domyślna granica technicznej nieaktualności wynosi `3 × interwał + 2 minuty`. To wskaźnik pracy kolektora, nie miara prawdziwości komunikatu. Błąd ostatniej próby pokazywać od razu, także zanim przekroczona zostanie ta granica.

`last_successful_check` może przesunąć się po poprawnym ponownym odczycie niezmienionego dokumentu. `content_updated_at` nie może się wtedy zmienić. HTTP 304 jest poprawnym sprawdzeniem tylko wtedy, gdy istnieje odpowiednia zapisana reprezentacja.

### 7.4. Błędy i brak rekordów

Nie zastępować dobrego zestawu błędną odpowiedzią. Poprawne nowe rekordy z częściowej odpowiedzi można zachować, ale częściowy wynik nie upoważnia do wnioskowania o usunięciu pozostałych.

Zniknięcie dokumentu ze źródła nie jest dementi. Usunięcie z bieżącej listy nie jest dowodem zakończenia wydarzenia. `404` dokumentu zapisać jako problem dostępności, zachowując historię i brak pewności.

Informacja o przerwie w pracy aplikacji powinna być widoczna w stanie systemu. Nie należy gwarantować monitoringu 24/7 w projekcie uruchamianym ręcznie.

## 8. Przepływ przetwarzania i kontrola publikacji

```text
Pobranie z dozwolonego źródła
        ↓
Walidacja odpowiedzi i zapis wyniku próby
        ↓
Identyfikacja dokumentu i wykrycie rzeczywistej zmiany
        ↓
Oczyszczenie treści, normalizacja i zachowanie podstawy źródłowej
        ↓
Rozpoznanie rodzaju, czasu, obszaru i pochodzenia
        ↓
Jednoznaczne ostrzeżenie? ── tak ──→ publikacja / aktualizacja
        │
        nie
        ↓
Kolejka kontroli → akceptacja / poprawa / odrzucenie / powiązanie
        ↓
Bieżący rekord + historia + mapa lub lista bez geometrii
```

### 8.1. Warunki automatycznej publikacji

Wszystkie warunki muszą być spełnione:

1. Źródło jest dopuszczone, a odpowiedź przeszła walidację kontraktu.
2. Rekord należy do przetestowanego typu ostrzeżenia, nie do ogólnego opisu wydarzenia.
3. Ma stabilną tożsamość, pochodzenie, zrozumiałą treść i prawidłowo zinterpretowaną ważność.
4. Obszar został jednoznacznie odczytany albo brak lokalizacji jest jawny; nie ma nierozstrzygniętej sprzeczności geograficznej.
5. Nie wykryto ćwiczenia, testu, negacji, niejednoznacznego odwołania ani innego przypadku wymagającego kontroli.
6. Podsumowanie i wszystkie istotne fakty wynikają z zachowanego dokumentu.

Nieznany typ lub schemat nie jest automatycznie dopasowywany do „najbardziej podobnego”. Dodać pozycję do kontroli z powodem, bez cichego pominięcia.

Brak geometrii przy poprawnie odczytanym kodzie lub obszarze nie blokuje użytecznej publikacji na liście. Niejednoznaczność tego, **który obszar wskazano**, blokuje automatyczne przypisanie lokalizacji.

### 8.2. Podsumowania bez LLM

Dla ostrzeżeń generować krótki opis szablonem z pól źródła: instytucja, rodzaj ostrzeżenia, oficjalny stopień, obszar i okres ważności. Nie dopisywać przyczyn, skutków ani prognoz nieobecnych w źródle.

Dla materiałów opisowych pokazać operatorowi tytuł, oczyszczoną treść i propozycje pól. Operator wpisuje lub poprawia zwięzłe podsumowanie, zwykle do trzech zdań. Wersja robocza może składać się z tytułu i wybranego fragmentu, ale nie jest publikowana bez akceptacji.

Notatka interpretacyjna operatora jest oddzielna od opisu faktów. Samo zaznaczenie „zatwierdź” nie staje się nowym niezależnym dowodem.

### 8.3. Deduplikacja i aktualizacje

**Tożsamość dokumentu:** stabilny identyfikator źródła; jeżeli go brak — kanoniczny URL potwierdzony przez adapter. Nie usuwać arbitralnie parametrów adresu, które mogą identyfikować dokument.

**Wersje dokumentu:** porównywać z ostatnią zapisaną wersją skrót znormalizowanej, istotnej treści i pól źródłowych. Nie uwzględniać paska nawigacji, czasu pobrania ani elementów reklamowych.

Ponowny odczyt tej samej treści nie tworzy nowego wydarzenia, wersji lub wpisu do kontroli. Powrót treści z wersji A do B i z powrotem do A jest nową zmianą, a nie powodem do jej zgubienia przez globalne ograniczenie unikalności skrótu.

**Tożsamość wydarzenia:** nowy dokument nie oznacza automatycznie nowego wydarzenia. Bezpieczne automatyczne aktualizacje są dopuszczone przy tej samej tożsamości dokumentu albo jawnej, przetestowanej relacji aktualizacji wskazanej przez źródło.

Podobieństwo czasu, miejsca i tytułu może tworzyć sugestię powiązania, ale nie wystarcza do automatycznego scalenia. Dwa pożary lub incydenty w jednym powiecie tego samego dnia mogą być odrębne.

RSO i IMGW mogą być powiązane automatycznie tylko po jednoznacznym identyfikatorze lub relacji źródłowej. Gdy tożsamość jest niepewna, pokazać kandydaturę połączenia. Samo podobieństwo tekstu nie tworzy niezależnego potwierdzenia.

### 8.4. Zmiana wcześniej zatwierdzonego tekstu

Istotna zmiana RCB lub SG tworzy nowy element kontroli związany z istniejącym rekordem. Poprzedni zatwierdzony opis pozostaje dostępny z czytelnym oznaczeniem:

> „Źródło zmieniło treść. Prezentowana interpretacja oczekuje ponownego sprawdzenia.”

Nie przedstawiać starego statusu jako świeżo zweryfikowanego. Potencjalne odwołanie lub sprostowanie ma priorytet w kolejce. Do czasu kontroli interfejs nie może sugerować pewności, że wcześniejszy stan nadal trwa albo że zagrożenie na pewno ustało.

Operator widzi różnicę istotnych pól i treści, dokumenty oraz przyczynę skierowania do kontroli. Akceptacja tworzy nową wersję wydarzenia.

Reguły nie nadpisują automatycznie pól świadomie poprawionych przez operatora. Jeżeli nowe dane źródłowe zmieniają podstawę takiej poprawki, skierować konflikt do kontroli i oznaczyć niepewność. Sam czas ponownego pobrania może zostać zaktualizowany niezależnie od interpretacji.

Jeżeli przed rozpatrzeniem zadania pojawi się kolejna wersja dokumentu, starsze zadanie otrzymuje stan `superseded`, a kolejka pokazuje aktualną propozycję. Historia wcześniejszych zmian pozostaje dostępna. Akceptacja sprawdza zarówno wersję wydarzenia, jak i aktualność wersji dokumentu; nie wolno zatwierdzić starego kandydata jako bieżącej treści po cichej zmianie źródła.

### 8.5. Minimalny panel operatora

Panel „Do sprawdzenia” obsługuje:

| Akcja | Wymagane zachowanie |
|---|---|
| Zatwierdź | Publikacja rekordu po walidacji, z pochodzeniem i historią decyzji. |
| Popraw i zatwierdź | Zmiana rodzaju, kategorii, czasu, opisu, obszaru i statusów; istotne fakty nadal wymagają źródła. |
| Odrzuć | Zapis powodu, bez publikacji. Odrzucony materiał pozostaje dostępny w filtrze historii kontroli. |
| Powiąż z istniejącym | Dokument zostaje dowodem lub aktualizacją istniejącego rekordu, zamiast tworzyć duplikat. |
| Oznacz sprzeczność / dementi | Wskazanie konkretnego twierdzenia, dokumentu i notatki. |
| Wycofaj błędną publikację | Wyłączenie z domyślnej mapy, zachowanie karty z informacją o korekcie i historii. |
| Rozdziel błędne połączenie | Wybór dokumentów do wydzielenia, utworzenie odrębnego rekordu i zapis przyczyny. |

Nie implementować ogólnego mechanizmu cofania całej bazy. Rozdzielenie polega na jawnej korekcie relacji dokumentów, z zachowaniem historii obu rekordów.

Zbiorczy artykuł może być użyty przy kilku rekordach, ale tylko gdy operator wskaże fragmenty potwierdzające odrębne wydarzenia. Same statystyki nie upoważniają do tworzenia pojedynczych zdarzeń.

Każda decyzja otrzymuje czas, typ aktora (`system` lub `operator`) i uzasadnienie tam, gdzie zmienia interpretację. Aktualizacje zatwierdzać z numerem wersji; przy konflikcie zwrócić informację o nowszym stanie zamiast nadpisać go w ciemno.

## 9. Czas i lokalizacja

### 9.1. Znaczniki czasu

Przechowywać rozdzielnie:

| Pole | Znaczenie |
|---|---|
| `occurred_time` | Czas zdarzenia: dokładny moment, przedział, sama data lub brak danych. |
| `source_published_at` | Czas publikacji podany przez źródło; może pozostać nieznany. |
| `source_updated_at` | Czas aktualizacji podany przez źródło; nie zastępować go czasem pobrania. |
| `first_seen_at` | Pierwszy odczyt materiału przez aplikację. |
| `last_checked_at` | Ostatnie prawidłowe sprawdzenie dokumentu. |
| `valid_from`, `valid_until` | Ważność ostrzeżenia; koniec może być nieznany lub „do odwołania”. |
| `record_updated_at` | Ostatnia istotna zmiana lokalnego rekordu. |

`occurred_time` ma zachować oryginalną informację, precyzję i ewentualne założenie o strefie. Znane momenty przechowywać w UTC, prezentować w `Europe/Warsaw`. Sama data pozostaje datą, nie sztucznym momentem o północy.

Interpretację godzin bez strefy ustala adapter na podstawie kontraktu i zapisuje jako założenie. Nie dopisywać UTC bez podstawy. Przypadki niejednoznaczności czasu przy zmianie czasu sezonowego kierować do kontroli.

Słowa „wczoraj” i „dziś” odnosić do właściwej publikacji, nie do bieżącego dnia pobrania. Gdy kontekst publikacji lub późniejszej edycji nie pozwala na jednoznaczne rozstrzygnięcie, pozostawić niepewność.

Domyślnie ostrzeżenie jest aktywne dla przedziału `[valid_from, valid_until)`. Adapter może przyjąć inną semantykę tylko wtedy, gdy wynika to z udokumentowanego kontraktu. Wartości specjalnych typu „do odwołania” nie przedstawiać jako rzeczywistej daty odległej o tysiące lat.

Stan `expired` wolno wyliczyć z upływu ważności. Stanu wydarzenia `ended` nie wolno wyliczać z braku nowych publikacji.

### 9.2. Trzy role lokalizacji

Każda lokalizacja ma rolę:

| Rola | Co oznacza |
|---|---|
| `event_location` | Miejsce opisywanego wydarzenia. |
| `warning_area` | Obszar, dla którego źródło formułuje ostrzeżenie. |
| `notification_area` | Obszar dystrybucji komunikatu lub powiadomienia. |

Jeden rekord może mieć kilka lokalizacji o różnych rolach. Legenda i panel szczegółów muszą wyjaśniać, którą rolę przedstawia dana geometria.

### 9.3. Dokładność

Minimalne pola lokalizacji: nazwa, rola, typ dokładności, kod administracyjny jeśli istnieje, odwołanie do geometrii jeśli istnieje, źródło ustalenia i ewentualna notatka o niepewności.

| Informacja źródłowa | Prezentacja w MVP |
|---|---|
| Jednoznaczny, bezpieczny punkt wskazany w źródle | Punkt z oznaczeniem pochodzenia. Nie używać tej ścieżki do danych operacyjnych. |
| Powiat lub województwo | Obszar administracyjny, nie punkt zdarzenia w jego środku. |
| Miejscowość bez jednoznacznego dopasowania | Nazwa i niepewność na liście; propozycja regionu do kontroli. |
| Obszar powiadomienia | Obszar oznaczony jako powiadomienie, nie jako miejsce incydentu. |
| Słabo określony odcinek granicy | Tylko obszar lub opis wsparty komunikatem; bez odtwarzania tras i pozycji służb. |
| Brak danych | Karta na liście, informacja „Brak ustalonej lokalizacji”, bez geometrii na mapie. |

Nie używać losowych współrzędnych, środka kraju ani siedziby instytucji jako zastępczej lokalizacji. Punkt wykorzystany technicznie do etykiety obszaru nie może być prezentowany jako miejsce zdarzenia.

MVP nie wymaga ogólnopolskiego geokodowania nazw ulic i adresów. Podstawowy poziom automatycznego dopasowania to administracyjne obszary PRG. Niejednoznaczne nazwy rozstrzyga operator na podstawie komunikatu. Brak słownika miejscowości nie blokuje publikacji bez punktu.

### 9.4. Geometrie referencyjne

Przygotować lokalny, uproszczony podkład Polski z granicami województw i powiatów, pochodzący z PRG. Zachować identyfikatory jako tekst, z zerami wiodącymi. Normalizację kodów i poziom jednostki potwierdzić w M0; nie dopasowywać ich wyłącznie na podstawie nieudokumentowanego skracania.

Geometrie powinny być przygotowane jednorazowo podczas implementacji i dostarczone z projektem wraz z metadanymi źródła, datą pobrania, wersją, informacją o przetworzeniu i atrybucją. Użytkownik nie ma wykonywać ręcznej konwersji danych GIS, aby uruchomić MVP.

Format runtime: GeoJSON w układzie oczekiwanym przez Leaflet, ze sprawdzoną kolejnością współrzędnych. Uproszczenie nie może niszczyć granic lub połączeń w sposób zmieniający interpretację obszaru. Narzędzia GIS, jeżeli potrzebne do przygotowania danych, są zależnościami deweloperskimi, nie obowiązkową częścią uruchamiania aplikacji.

Nie pobierać granic przy każdym starcie. Nie używać płatnych kafelków, zewnętrznego geokodera ani CDN do podstawowej mapy. Własny podkład granic i nazw jest wystarczający; szczegółowa mapa ulic nie jest wymaganiem.

Nie podmieniać PRG nieopisanym, przypadkowym zbiorem. Jeżeli danych nie da się pozyskać lub wykorzystać w przyjętym trybie, zgłosić konkretny brak. Syntetyczna geometria może istnieć wyłącznie jako wyraźnie oznaczony materiał testowy, nie jako mapa administracyjna.

## 10. Model danych i historia

### 10.1. Założenia

SQLite jest jedyną bazą danych. Włączyć kontrolę kluczy obcych, używać krótkich transakcji i lokalnego pliku bazy. Można zastosować WAL z poprawnym zamykaniem połączeń. Nie tworzyć własnego systemu zdarzeniowego, silnika grafowego ani warstwy danych na hipotetyczną skalę.

Bieżący stan wydarzenia jest zapisany bezpośrednio. Historia zawiera kolejne istotne wersje, nie tysiące identycznych wyników odpytywania. Geometrie referencyjne pozostają lokalnymi plikami i słownikiem, bez PostGIS.

### 10.2. Wymagane encje

| Encja / tabela | Najważniejsze dane |
|---|---|
| `sources` | Identyfikator, nazwa, adres, konfiguracja, stan dostępu, interwał, wynik i czas ostatnich prób. |
| `fetch_runs` | Źródło, początek i koniec, wynik, liczby pobranych/zmienionych/błędnych rekordów, faktyczny zakres i błąd bez wrażliwej treści. |
| `documents` | Źródło, niepusty klucz tożsamości, opcjonalny identyfikator dostawcy, kanoniczny URL, pierwsze i ostatnie sprawdzenie. |
| `document_versions` | Kolejny numer wersji, skrót istotnej treści, oczyszczona treść, istotne pola źródłowe, czasy źródła, wersja parsera. |
| `events` | Rodzaj, kategoria, tytuł, opis, statusy, istotność, czas, ważność, lokalizacje, publikacja, numer wersji i ewentualny rekord docelowy po połączeniu. |
| `event_evidence` | Relacja wydarzenia z konkretną wersją dokumentu, wspierane pola, fragment dowodowy, relacja potwierdzenia/aktualizacji/sprzeczności/przedruku i znane pochodzenie pierwotne. |
| `event_revisions` | Kolejny stan wydarzenia i jego powiązań źródłowych, czas, aktor, powód zmiany i opis różnicy. |
| `review_items` | Dokument i wersja, ewentualne wydarzenie, proponowane pola, powód kontroli, priorytet i stan obsługi. |
| `operator_actions` | Dziennik decyzji o publikacji, odrzuceniu, korekcie, połączeniu i rozdzieleniu, z czasem i odwołaniami do obiektów. |

Pola złożone, takie jak kilka lokalizacji i mapa powiązań pól ze źródłami, mogą być małymi, walidowanymi strukturami JSON. Nie rozbijać ich na kilkanaście tabel bez potrzeby.

Wymagane ograniczenia tożsamości:

- `documents`: unikalna para `(source_id, identity_key)`;
- `document_versions`: unikalna para `(document_id, version_number)`;
- `review_items`: brak dwóch aktywnych zadań dla tej samej wersji, tego samego celu i tego samego powodu;
- ponowna akceptacja już rozstrzygniętego zadania nie tworzy drugiej publikacji;
- połączenie rekordów nie pozwala następnemu pobraniu odtworzyć tego samego duplikatu jako nowego wydarzenia.

### 10.3. Pochodzenie faktów

Każdy opublikowany rekord musi wskazywać źródło opisu i istotnych pól: rodzaju, czasu, lokalizacji, ważności i zmian statusu. Wystarczy powiązanie ścieżki pola z konkretną wersją dokumentu i krótkim, zachowanym fragmentem. Nie budować pełnego grafu twierdzeń.

Dokument może wspierać kilka rekordów, a rekord może odwoływać się do wielu dokumentów. Liczba dokumentów i liczba znanych źródeł pierwotnych są odrębnymi informacjami. Jeżeli pochodzenie przedruku jest nieustalone, tak je oznaczyć; nie dopisywać niezależności.

Tytuł i opis mogą być zredagowane przez operatora, ale muszą zachowywać sens źródła. Notatki operatora są oznaczone jako notatki, nie jako oficjalny komunikat.

### 10.4. Minimalizacja zapisywanych treści

Przed utrwaleniem odrzucić skrypty, HTML interfejsu serwisu, multimedia, zbędne metadane i dane osobowe niepotrzebne do celu. Zapisywać tylko tekst i pola potrzebne do weryfikacji. Nie archiwizować automatycznie całych witryn, fotografii ani filmów.

Jeśli materiał wymaga ręcznej oceny wrażliwych szczegółów, przechować bezpieczny tytuł, URL i informację o potrzebie kontroli zamiast pełnej nieocenzurowanej treści. W razie wątpliwości operator otwiera oryginał bezpośrednio u wydawcy.

Ślady dowodowe odnoszą się do utrwalonej, oczyszczonej wersji; nie udawać, że jest to niezmieniony zrzut całej strony. Zachować informację o redakcji i przetworzeniu. Logi nie mogą zawierać pełnych odpowiedzi ani danych osobowych.

### 10.5. Migracje

Wystarczy katalog kolejnych migracji SQL i numer wersji schematu. Migracje mają być powtarzalnie kontrolowane, bez kasowania danych użytkownika. Jeżeli automatyczna migracja nie może zostać bezpiecznie zakończona, zatrzymać start z komunikatem; nie resetować bazy.

## 11. Architektura i struktura projektu

### 11.1. Stack

| Warstwa | Wybór |
|---|---|
| Język | Python; jedna sprawdzona wersja zapisana w `.python-version` i zgodna z `pyproject.toml`. |
| Zależności | `uv`, `pyproject.toml`, dostarczony i sprawdzony `uv.lock`. |
| Backend | FastAPI + Uvicorn, jeden proces i jeden worker. |
| Walidacja | Pydantic. |
| HTTP | HTTPX. |
| HTML | Beautiful Soup, parsery specyficzne dla źródła. |
| Harmonogram | Prosty asynchroniczny mechanizm wewnątrz aplikacji. |
| Baza | SQLite i mała warstwa repozytorium, bez serwera baz danych. |
| Frontend | Statyczny HTML, CSS i niewielkie moduły JavaScript. |
| Mapa | Leaflet; pliki biblioteki, style i zasoby dostępne lokalnie. |
| Testy | pytest, kontrolowane odpowiedzi HTTP i zamrożony zegar. |
| Kontrola jakości kodu | Ruff. |

Wersje bibliotek należy dobrać i zablokować podczas implementacji, nie przepisywać z wcześniejszego raportu ani zakładać, że „najnowsze” oznacza kompatybilne. Nie dodawać Node.js, bundlera, Reacta ani innego frameworka frontendowego, jeżeli statyczne moduły rozwiązują wymagania.

### 11.2. Sugerowany układ

```text
polska-osint/
├── README.md
├── PRD.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore
├── config.example.toml
├── src/polska_osint/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── config.py
│   ├── db.py
│   ├── migrations/
│   ├── models.py
│   ├── repositories.py
│   ├── scheduler.py
│   ├── sources/
│   │   ├── base.py
│   │   ├── imgw_meteo.py
│   │   ├── rso.py
│   │   ├── rcb.py
│   │   └── sg.py
│   ├── processing/
│   │   ├── normalize.py
│   │   ├── relevance.py
│   │   ├── deduplicate.py
│   │   ├── geography.py
│   │   └── publication.py
│   ├── services/
│   │   ├── ingestion.py
│   │   ├── events.py
│   │   └── review.py
│   ├── api/
│   └── static/
│       ├── index.html
│       ├── css/
│       ├── js/
│       ├── vendor/leaflet/
│       └── geo/
├── scripts/
│   └── prepare_geo.py
├── tests/
│   └── fixtures/
├── demo/
├── docs/
│   ├── sources.md
│   ├── data-model.md
│   └── implementation-status.md
├── THIRD_PARTY_NOTICES.md
└── var/                        # tworzone lokalnie, poza repozytorium
```

Układ nie jest powodem do tworzenia pustych abstrakcji. Niewielkie moduły mogą być połączone, jeśli odpowiedzialności pozostają czytelne. Nie implementować systemu pluginów. `prepare_geo.py` jest narzędziem odtworzenia paczki referencyjnej dla dewelopera, nie obowiązkowym krokiem startu użytkownika.

### 11.3. Kontrakt adaptera

Każdy adapter ma:

- pobrać tylko dopuszczone adresy w ustalonym zakresie;
- rozpoznać wynik pełny, częściowy, niezmieniony i błąd;
- zwrócić listę dokumentów z tożsamością, URL, znormalizowanymi polami i podstawą źródłową;
- zwrócić metadane pokrycia oraz informacje o niepoprawnych rekordach;
- nie publikować bezpośrednio w UI i nie wykonywać dowolnych zapisów poza serwisem ingestion.

Adapter nie decyduje sam o niezależnym potwierdzeniu i nie tworzy opisów faktów bez źródła. Zegarem i klientem HTTP należy móc sterować w testach. Nie tworzyć osobnej pętli harmonogramu w każdym adapterze.

### 11.4. Minimalne API aplikacji

Poniższe ścieżki są **projektowanym API lokalnym**, nie adresami instytucji.

| Metoda i ścieżka | Cel |
|---|---|
| `GET /api/health` | Stan aplikacji, tryb live/demo, czas serwera i informacja o przerwie w pracy. |
| `GET /api/sources` | Dostępność, ostatnie sprawdzenie, wynik, świeżość i pokrycie źródeł. |
| `POST /api/sources/{id}/refresh` | Zaplanowanie pojedynczego odświeżenia z blokadą równoległego pobierania. |
| `GET /api/events` | Filtrowany zestaw do mapy i listy. |
| `GET /api/events/{id}` | Szczegóły, lokalizacje i dowody. |
| `GET /api/events/{id}/history` | Chronologiczna historia zmian. |
| `GET /api/review` | Kolejka kontroli, w tym filtr materiałów odrzuconych/pominiętych. |
| `GET /api/review/{id}` | Dokument, proponowane pola, różnice i powód kontroli. |
| `POST /api/review/{id}/resolve` | Zatwierdzenie, poprawa, odrzucenie lub powiązanie; wymaga oczekiwanej wersji. |
| `POST /api/events/{id}/correct` | Korekta, zmiana spójności, wycofanie albo rozdzielenie; wymaga powodu i wersji. |

Dla `GET /api/events` przyjąć limit bezpieczeństwa, domyślnie 1000 rekordów. Odpowiedź zawiera liczbę wyników i flagę ograniczenia. Jeżeli przekroczono limit, UI ma poprosić o zawężenie filtrów i wyraźnie informować o niepełnym widoku. Nie pokazywać pierwszej strony jako całego obrazu sytuacji.

Mapa i lista korzystają z tego samego zwróconego zestawu. Lista może stronicować go lokalnie. Brak geometrii nie usuwa rekordu z listy.

Nie dodawać WebSocketów. Interfejs odświeża dane co 60 sekund i po własnej operacji operatora. Krótkie operacje zapisu nie mogą blokować pętli sieciowej; dostępu do SQLite nie współdzielić niekontrolowanie między wątkami.

## 12. Interfejs użytkownika

### 12.1. Główne widoki

Wystarczą trzy widoki: **Sytuacja**, **Do sprawdzenia** i **Źródła**. Historia jest częścią karty wydarzenia, a nie osobnym panelem analitycznym.

Widok „Sytuacja” na komputerze:

```text
┌────────────────────────────────────────────────────────────────┐
│ Polska — sytuacja i ostrzeżenia   Tryb   Aktualizacja   Źródła  │
├────────────────────────────────────────────────────────────────┤
│ Zakres / kategoria / podstawa informacji / obszar / historia    │
├───────────────────┬─────────────────────────┬──────────────────┤
│ Lista             │ Mapa Polski 2D          │ Szczegóły        │
│                   │                         │                  │
│ Bezpieczeństwo    │ Obszary i punkty        │ Opis i statusy   │
│ i granice         │ z jawną legendą ról     │ Czas i ważność   │
│                   │                         │ Źródła           │
│ Ostrzeżenia       │                         │ Historia zmian   │
│ dla mieszkańców   │                         │ Niepewność       │
└───────────────────┴─────────────────────────┴──────────────────┘
```

Panel szczegółów może być początkowo zwinięty. Priorytetem jest wygodny interfejs desktopowy. Nie budować osobnej aplikacji mobilnej.

### 12.2. Filtry i domyślny zakres

Domyślnie pokazywać wszystkie obecnie obowiązujące i zapowiedziane ostrzeżenia oraz wydarzenia, których istotna publikacja lub zmiana nastąpiła w ostatnich 7 dniach. Stare ostrzeżenie nadal ważne nie może zniknąć tylko z powodu starej daty publikacji.

Udostępnić filtrowanie rodzaju, kategorii, podstawy informacji, województwa i zakresu publikacji/aktualizacji: 24 godziny, 7 dni, 30 dni. Pole wyboru pokazuje również wygasłe/odwołane ostrzeżenia i wycofane publikacje jako historię.

Nazwać filtr czasu zgodnie z działaniem: „Publikacja lub istotna aktualizacja”. Nie sugerować, że jest to dokładny czas wystąpienia wydarzenia. Karta pokazuje obie informacje oddzielnie.

Kontekst i ćwiczenia nie trafiają do domyślnej warstwy zagrożeń. Mogą być widoczne po wybraniu odpowiedniego rodzaju.

### 12.3. Karta rekordu

Każda karta zawiera:

- tytuł, rodzaj, kategorię i zwięzły opis;
- podstawę informacji, spójność, przebieg albo ważność;
- obszary z rolą i dokładnością oraz wyraźny brak geometrii, jeżeli występuje;
- czas zdarzenia, publikacji, istotnej zmiany i ostatniego sprawdzenia;
- oryginalne źródła jako odnośniki, nazwę instytucji i odpowiednie fragmenty;
- informację o przedruku lub nieustalonej niezależności;
- historię zmian i oznaczenie oczekującej aktualizacji;
- notatkę operatora, oddzieloną od treści źródłowej.

Nie wyświetlać procentu wiarygodności. Nie ukrywać braku danych za pustym polem: używać etykiet „Nie podano czasu zdarzenia”, „Brak ustalonej lokalizacji”, „Przebieg nieznany”.

### 12.4. Mapa i czytelność

Punkty, obszary ostrzeżeń i obszary powiadomień muszą mieć odróżnialną legendę oraz opis tekstowy. Nie używać jednego koloru jednocześnie jako miary ważności, wiarygodności i kategorii.

Kliknięcie listy zaznacza geometrię, jeśli istnieje. Kliknięcie obszaru może pokazywać kilka powiązanych rekordów; nie nadpisywać ich jednym popupem. Przy braku geometrii otworzyć szczegóły, bez przesuwania mapy do losowego punktu.

Nie wymagać fotorealistycznego podkładu, zdjęć ani animacji. Zachować polskie etykiety, czytelną typografię, widoczny fokus klawiatury i komunikaty nieoparte wyłącznie na kolorze.

### 12.5. Jawne ograniczenia

Stały komunikat w aplikacji:

> **Brak informacji na mapie nie oznacza braku zagrożenia. Aplikacja pokazuje publikacje z wybranych źródeł i nie zastępuje oficjalnych komunikatów ani służb alarmowych.**

Tryb demo ma dodatkowy trwały baner. Niedostępność źródła, przekroczony limit rekordów i niepełne pokrycie mają być widoczne poza panelem technicznym — użytkownik nie powinien musieć ich szukać.

Demonstracja korzysta z ustalonego zegara scenariusza i pokazuje jego datę w banerze. Ten sam zegar służy backendowi i interfejsowi do wyliczania ważności, aby przykładowe aktywne ostrzeżenia nie wygasły wraz z upływem rzeczywistego czasu. Nie przedstawiać syntetycznych materiałów jako autentycznych publikacji instytucji.

## 13. Bezpieczeństwo lokalnej aplikacji

Brak publicznego wdrożenia nie zwalnia z podstawowych zabezpieczeń.

Wymagane minimum:

1. Nasłuchiwanie wyłącznie na loopback, walidacja nagłówka Host i brak otwartego CORS.
2. Żadnych operacji zmieniających dane przez GET. Dla żądań modyfikujących wymagać poprawnego pochodzenia i tokena przeciwko żądaniom z obcych stron, wygenerowanego przy starcie. Bez budowy systemu kont.
3. Pobieranie wyłącznie z ustalonej listy źródeł. Sprawdzać adres docelowy po przekierowaniu; nie traktować każdego linku z artykułu jako zlecenia pobrania. Nie pozwalać użytkownikowi w UI podawać dowolnego URL do pobrania przez serwer.
4. Wyświetlanie tekstu bez wykonywania HTML ze źródła. Nie wstawiać treści zewnętrznej do `innerHTML` ani popupów Leaflet bez bezpiecznej obsługi.
5. Odnośniki do źródeł tylko z dozwolonym protokołem; otwieranie nowej karty bez dostępu do okna aplikacji.
6. Zapytania SQLite z parametrami, dozwolony katalog pól sortowania, walidacja danych wejściowych i limit rozmiaru żądań.
7. Brak telemetrii, analityki zewnętrznej, sekretów w repozytorium i przesyłania treści do modeli AI.
8. Lista zależności i zasobów z licencjami w `THIRD_PARTY_NOTICES.md`; zachowanie wymaganych oznaczeń dostawców.

Nie kopiować polityki licencyjnej z cudzej aplikacji jako prawa do danych. Nie dodawać „bezpiecznego opóźnienia”, które miałoby usprawiedliwiać publikację danych operacyjnych. Takie dane są poza zakresem niezależnie od opóźnienia.

## 14. Testy i mierzalne kryteria jakości

### 14.1. Strategia

Testy jednostkowe i integracyjne mają działać bez internetu, z kontrolowanymi odpowiedziami HTTP, tymczasową bazą i wstrzykiwanym zegarem. Testy nie mogą pobierać bieżących komunikatów, czekać pięciu minut na harmonogram ani zależeć od aktualnej pogody.

Przygotować niewielki zestaw zredukowanych próbek rzeczywistych formatów, o ile można je zachować, oraz scenariusze syntetyczne pokrywające błędy i rzadkie zmiany. Każda próbka ma wskazywać, czy jest autentyczna po redakcji, czy syntetyczna. Nie publikować danych testowych w bazie live.

Dla każdego źródła osobno wykonać i opisać kontrolowaną próbę rzeczywistego dostępu podczas implementacji, jeżeli dostęp jest dopuszczony. To oddzielne sprawdzenie, nie część domyślnego uruchamiania testów. Zielone testy na fixture nie dowodzą działania źródła na żywo.

### 14.2. Krytyczne scenariusze

| ID | Scenariusz | Oczekiwany wynik |
|---|---|---|
| T01 | Kilkukrotne pobranie identycznego ostrzeżenia | Jeden dokument, jedna niezmieniona wersja treści, jeden rekord i brak powielonej kontroli. |
| T02 | Aktualizacja tego samego identyfikatora | Ten sam rekord, nowa wersja dokumentu i prawidłowa historia. |
| T03 | Treść A → B → A | Trzy kolejne wersje; ostatnia zmiana nie ginie przez ponowne użycie skrótu A. |
| T04 | Ostrzeżenie przed zjawiskiem | Rodzaj `warning`, nie twierdzenie, że zjawisko wystąpiło. |
| T05 | Ćwiczenie lub test syren | Brak automatycznej publikacji jako realnego incydentu; kontekst do kontroli. |
| T06 | Brak czasu zdarzenia, ale znana publikacja | Czas zdarzenia pozostaje nieznany. |
| T07 | „Wczoraj” w starej publikacji i późniejsze pobranie | Odniesienie do właściwej publikacji albo jawna niepewność, nie do dnia pobrania. |
| T08 | Sama data lub niejednoznaczna godzina sezonowej zmiany czasu | Zachowanie precyzji daty; niejednoznaczność kierowana do kontroli. |
| T09 | Miejscowość o kilku możliwych dopasowaniach | Brak arbitralnego punktu; propozycje lub brak lokalizacji. |
| T10 | Znany obszar bez geometrii albo nieznany kod | Rekord na liście z informacją o problemie; żadnego fikcyjnego punktu. |
| T11 | Alert dla polskiego województwa dotyczący zdarzenia poza Polską | Rozdzielone role lokalizacji; brak przypisania zagranicznego incydentu do polskiego obszaru powiadomienia. |
| T12 | Przedruk ostrzeżenia IMGW w RSO | Relacja pochodzenia; brak automatycznego wzrostu liczby niezależnych potwierdzeń. |
| T13 | Dwa podobne incydenty w tym samym powiecie | Brak automatycznego scalenia tylko na podstawie podobieństwa. |
| T14 | Zniknięcie komunikatu z feedu lub HTTP 404 | Brak automatycznego dementi albo zakończenia wydarzenia. |
| T15 | Upływ ważności ostrzeżenia | Status `expired`; brak wniosku o zakończeniu zjawiska lub innego wydarzenia. |
| T16 | HTTP 200 ze stroną antybotową lub błędnym schematem | Błąd adaptera, nie poprawny pusty zestaw. |
| T17 | Poprawny pusty zestaw i brak nowych publikacji | Zdrowy odczyt z zerem wyników; dotychczasowa historia pozostaje. |
| T18 | Odpowiedź częściowo uszkodzona lub niepełna paginacja | Stan częściowy i jawny zakres; brak usuwania nieobecnych rekordów. |
| T19 | Zmiana opublikowanego tekstu wymagająca kontroli | Nowe zadanie kontroli i oznaczenie poprzedniego opisu jako oczekującego na przegląd. |
| T20 | Dementi jednego szczegółu | Oznaczenie konkretnego spornego twierdzenia, bez automatycznego usuwania całego wydarzenia. |
| T21 | Powtórzona akceptacja lub zapis ze starej wersji | Brak duplikatu; konflikt wersji zamiast cichego nadpisania. |
| T22 | Błędne połączenie i późniejsze rozdzielenie | Właściwe przypisanie dokumentów, odrębne rekordy i zachowana historia decyzji. |
| T23 | Niebezpieczny HTML w źródle lub żądanie modyfikacji z obcej strony | Brak wykonania treści; odrzucenie nieuprawnionej modyfikacji. |
| T24 | Przekierowanie pobierania poza dopuszczony zakres | Przerwanie pobrania, bez dostępu do nieautoryzowanego adresu. |
| T25 | Druga instancja lub wiele kliknięć „Odśwież” | Brak dwóch kolektorów dla tego samego źródła i bazy. |
| T26 | Zatrzymanie, restart i symulowana przerwa | Dane zachowane, harmonogram wznowiony bez lawiny zaległych wywołań. |
| T27 | Demo i tryb live | Oddzielne bazy, oznaczenia syntetycznych danych i zero ruchu do źródeł w demo. |
| T28 | Brak internetu po wcześniejszym użyciu | Lokalna mapa, zasoby i zapisane karty działają; błędy źródeł są widoczne. |
| T29 | Stare, ale nadal aktywne ostrzeżenie | Obecne w widoku domyślnym mimo przekroczenia siedmiu dni od publikacji. |
| T30 | Migracja bazy, ponowny start i ręczna kopia przy zatrzymanej aplikacji | Zachowanie danych; brak automatycznego resetu i poprawny odczyt odtworzonej kopii. |

Nie wymaga się osobnego testu dla każdego szczegółu CSS. Wystarczy krótki przegląd UI: mapa/lista/szczegóły, filtry, kontrola, historia, brak lokalizacji, offline, demo i błąd źródła.

### 14.3. Zestaw jakości interpretacji

Przed oznaczeniem automatycznych reguł jako gotowych przygotować co najmniej 40 opisanych przypadków, z uwzględnieniem typowych publikacji i błędnych interpretacji. Ten sam przypadek może weryfikować kilka reguł, ale przypadki oceny jakości nie powinny być wyłącznie kopiami przykładów wykorzystanych do dopasowania reguł.

Mierzyć osobno:

- **poprawność automatycznej publikacji:** odsetek opublikowanych automatycznie rekordów, których rodzaj i interpretacja są prawidłowe;
- **pokrycie wybranych źródeł:** ile materiałów dostępnych w sprawdzonym zakresie zostało rzeczywiście przetworzonych;
- **obciążenie kontrolą:** ile materiałów trafia do operatora i z jakich powodów.

Docelowo dążyć do minimum 95% poprawnych automatycznych publikacji na wydzielonym zbiorze i zera krytycznych pomyłek opisanych w T04–T15. Podawać licznik i mianownik, nie sam procent. Przy małej liczbie automatycznych publikacji jasno zaznaczyć ograniczenie próby.

Jeżeli reguła nie spełnia wymagań, zawęzić automatyczny zakres albo skierować dany typ do kontroli. Nie obniżać progu bezpieczeństwa i nie dodawać LLM jako niezweryfikowanej poprawki.

Późniejszy przegląd 100–200 publikacji z pilota służy dalszej ocenie; nie jest warunkiem wygenerowania działającego projektu ani zobowiązaniem do monitorowania przez agenta po zakończeniu implementacji.

### 14.4. Cele sprawności

To cele projektowe do sprawdzenia, nie deklarowane wyniki pomiaru:

| Obszar | Cel |
|---|---|
| Uruchomienie | Odczyt zapisanych danych i dostępny UI bez czekania na zewnętrzne źródła. |
| Lokalna demonstracja | Użyteczny pierwszy widok w kilka sekund, bez połączenia z internetem. |
| API listy | Dla testowej bazy do 10 000 rekordów i standardowych filtrów cel poniżej 500 ms, bez czasu sieci zewnętrznej. |
| Zużycie zasobów | Brak stałego zajmowania rdzenia CPU; pobieranie tylko zgodnie z harmonogramem. |
| Zapis | Krótkie transakcje i brak duplikacji treści przy niezmienionych odpowiedziach. |
| Logi | Rotowane i ograniczone; domyślnie 14 dni logów oraz 30 dni szczegółowych wyników pobrań. |
| Historia merytoryczna | Bez automatycznego kasowania dokumentów i wydarzeń w v1; kontrola zajętości dysku w README. |

Nie optymalizować na zapas. Jeżeli pomiar ujawni problem, najpierw sprawdzić indeksy, liczbę renderowanych obiektów i niepotrzebne przetwarzanie. Raport pomiaru ma wskazywać rzeczywiste środowisko; brak pomiaru oznaczyć jako brak pomiaru.

## 15. Etapy implementacji dla Codex

Realizować pionowe, działające fragmenty. Po każdym etapie uruchomić właściwe testy i uzupełnić `docs/implementation-status.md`: co działa, co sprawdzono, co jest zablokowane. Nie utrzymywać pustych deklaracji „gotowe”.

### M0 — Kontrakty źródeł i lokalny szkielet

**Cel:** ustalić rzeczywiste podstawy integracji i uruchamiania, bez rozbudowanego researchu pobocznych źródeł.

**Zakres:** cztery adresy, dostęp i warunki, przykładowe schematy, zakres/paginacja, czas, tożsamość dokumentów; przygotowanie PRG i atrybucji; `pyproject.toml`, lockfile, struktura, CLI i lokalna konfiguracja.

**Rezultat:** sprawdzony kontrakt każdego możliwego adaptera, opis blokad pozostałych, aplikacja na loopback ze statycznym szkieletem i stanem pustym. Zasoby mapy dostępne lokalnie.

**Odbiór:** istnieją rzeczywiste próbki lub precyzyjny opis braku dostępu; nie ma wymyślonych API; start nie wymaga globalnych zmian i nie uruchamia usługi systemowej.

### M1 — IMGW od pobrania do mapy

**Zależność:** M0 dla IMGW i PRG.

**Zakres:** baza, dokumenty i wersje, adapter IMGW, ostrzeżenia, czas, obszary, mapa/lista, stan źródła, podstawowy harmonogram i demo.

**Rezultat:** jeden kompletny przepływ działający na próbce oraz na rzeczywistym źródle, jeżeli jest dostępne. Ponowne pobranie nie tworzy duplikatów, a awaria nie czyści mapy.

**Odbiór:** T01–T04, T06, T08, T10, T14–T18, T27–T29 w zakresie etapu. Użytkownik może ręcznie uruchomić demonstrację i zobaczyć poprawnie opisane ostrzeżenia.

### M2 — RSO i wspólny model

**Zależność:** M1 i kontrakt RSO.

**Zakres:** adapter RSO, rozpoznane typy ostrzeżeń, kontrola ćwiczeń, brak współrzędnych, zakres pobierania oraz pochodzenie przedruków IMGW.

**Rezultat:** drugi strumień we wspólnym modelu, bez automatycznego utożsamiania komunikatu z incydentem.

**Odbiór:** T05, T09–T12, T18; znane ograniczenia pokrycia są widoczne. Ćwiczenie nie trafia na mapę zagrożeń, a przedruk nie staje się drugim niezależnym dowodem.

### M3 — RCB, SG i panel kontroli

**Zależność:** M2 i odpowiednie kontrakty źródeł opisowych.

**Zakres:** oba adaptery HTML, filtrowanie istotności, kandydaci danych, kolejka, akceptacja/poprawa/odrzucenie, podstawa źródłowa, role geometrii i ręczne powiązanie z wydarzeniem.

**Rezultat:** właściciel projektu sam kontroluje publikację niejednoznacznych materiałów, bez edytowania bazy lub kodu.

**Odbiór:** można przejść od nowego artykułu do opublikowanej karty, poprawić lokalizację albo świadomie pozostawić jej brak. T07, T09, T11, T13, T19–T21 przechodzą; nie ma automatycznej publikacji opisowego incydentu.

### M4 — Korekty, historia i odporność

**Zależność:** M3.

**Zakres:** pełna historia, odwołania i sporne twierdzenia, wycofanie, rozdzielenie połączenia, wersjonowanie decyzji, blokada drugiej instancji, restart, przerwy, offline, zabezpieczenia lokalnego API i kopia danych.

**Rezultat:** aplikacja pozostaje czytelna po błędach i aktualizacjach, a operator może poprawić błędną interpretację bez utraty dowodów.

**Odbiór:** T14–T26 i T30 przechodzą. Nie ma utraty danych przy restarcie, ukrytego odświeżania po zatrzymaniu ani prezentowania nieaktualnej interpretacji jako świeżo sprawdzonej.

### M5 — Odbiór lokalnego MVP i przekazanie projektu

**Zależność:** M4.

**Zakres:** pełny zestaw testów, 40 opisanych przypadków, przegląd UI, kontrolowane sprawdzenie źródeł, kontrola lockfile i README na czystym środowisku projektowym, uporządkowanie dokumentacji i atrybucji.

**Rezultat:** kompletny projekt gotowy do samodzielnego uruchomienia, wraz z uczciwą listą ograniczeń.

**Odbiór:** spełniona definicja ukończenia z rozdziału 16. Nie wykonywać wdrożenia, nie zostawiać procesu aplikacji i nie tworzyć infrastruktury. Ewentualny zablokowany adapter oznacza jawnie niepełny zakres live, nie pomyślne ukończenie czterech integracji.

## 16. Definicja ukończenia

### 16.1. Projekt i uruchamianie

- [ ] Dostarczono kompletny katalog źródłowy, nie sam szkielet, plan lub makietę.
- [ ] Istnieją `pyproject.toml`, sprawdzony `uv.lock`, README i zasoby potrzebne do mapy.
- [ ] Działają określone komendy live i demo; instrukcja nie wymaga globalnej instalacji przez agenta.
- [ ] Standardowy start nasłuchuje tylko na `127.0.0.1` i uruchamia jeden kolektor na źródło.
- [ ] `Ctrl+C` kończy działanie; nie ma autostartu, usługi, tunelu, hostingu ani procesu pozostawionego po przekazaniu.
- [ ] Dane aplikacji pozostają w katalogu projektu i przetrwają restart.

### 16.2. Dane i funkcje

- [ ] Cztery adaptery mają kontrakty, testy i prawdziwe stany działania; blokady są wyraźnie wykazane.
- [ ] Automatycznie publikowane są tylko obsługiwane jednoznaczne ostrzeżenia.
- [ ] RCB, SG i niejednoznaczne rekordy przechodzą przez działającą kolejkę kontroli.
- [ ] Każdy opublikowany rekord ma źródło, prawidłowe czasy i jawną dokładność lokalizacji.
- [ ] Działają mapa, lista, filtry, szczegóły, historia, korekty i rozdzielenie błędnego połączenia.
- [ ] Przedruki nie są liczone jako niezależne potwierdzenia bez podstawy.
- [ ] Ćwiczenia, odwołania, brak lokalizacji i brak czasu nie prowadzą do pozornie precyzyjnych incydentów.
- [ ] Niepełne pokrycie, awarie i ograniczenie liczby rekordów są widoczne.
- [ ] Demo jest odizolowane i nie pobiera realnych danych; praca offline zachowuje lokalny odczyt.

### 16.3. Testy i dokumentacja

- [ ] Krytyczne scenariusze T01–T30 mają pokrycie testowe lub jawnie opisany kontrolowany test ręczny tam, gdzie dotyczy UI/systemu.
- [ ] Testy domyślne nie zależą od internetu ani bieżącej sytuacji w źródłach.
- [ ] Przygotowano i opisano zestaw jakości interpretacji; nie przedstawiono celów jako uzyskanych wyników.
- [ ] Udokumentowano źródła, zakres, czas, dostęp, licencje zasobów, ograniczenia i daty sprawdzeń.
- [ ] W `implementation-status.md` podano rzeczywiście wykonane testy, ich wynik i wszystkie pominięte sprawdzenia.
- [ ] README wyjaśnia uruchomienie, zatrzymanie, demo, kopię danych, przerwy w działaniu i typowe błędy.

**Warunek uczciwego odbioru:** brak dostępu do źródła nie może zostać ukryty za danymi demonstracyjnymi. Można przekazać wartościowy projekt z częściowym zakresem live, ale trzeba go tak nazwać. „Pełne MVP z czterema źródłami” wymaga rzeczywistego sprawdzenia tych czterech integracji, bez gwarantowania ich późniejszej ciągłej dostępności.

## 17. Minimalna zawartość README i przekazania

README ma być krótkie i praktyczne. Musi zawierać:

1. Co aplikacja pokazuje i czego nie obiecuje.
2. Wymagania wstępne oraz trzy komendy: przygotowanie zależności, live, demo.
3. Lokalny adres i zatrzymanie przez `Ctrl+C`.
4. Znaczenie kolejek kontroli, podstawy informacji, czasu i dokładności lokalizacji.
5. Informację, że zbieranie działa tylko podczas uruchomienia; skutki uśpienia i dłuższej przerwy.
6. Lokalizację danych, konfiguracji i logów oraz ręczną kopię przy zatrzymanej aplikacji.
7. Komendy testów i kontroli jakości.
8. Ograniczenia źródeł oraz odsyłacz do `docs/sources.md`.

Docelowe komendy deweloperskie, z zależnościami zadeklarowanymi w projekcie:

```bash
uv run --locked pytest
uv run --locked ruff check .
```

W przekazaniu agent ma napisać, co zaimplementował i sprawdził, wskazać realne blokady oraz podać komendę ręcznego uruchomienia. Nie ma twierdzić, że aplikacja została zainstalowana jako usługa, wdrożona lub będzie dalej działała w tle.

## 18. Reguły ograniczające rozrost implementacji

Przy niejasności wybierać mniejszy zakres, który zachowuje prawdziwość informacji. Nie zadawać ponownie pytań o zaakceptowany wybór stosu, źródeł, prywatny charakter lub lokalny sposób uruchamiania.

Jeżeli źródło nie udostępnia oczekiwanego pola, pozostawić brak lub skierować materiał do kontroli. Jeżeli adapter jest zablokowany, opisać problem i realizować pozostałe niezależne funkcje. Nie zastępować go innym dostawcą bez zmiany zakresu.

Dopuszczalna drobna zmiana techniczna musi mieć konkretne uzasadnienie i wpis w `implementation-status.md`. Nie może wprowadzać chmury, płatnego API, globalnego komponentu, kolejnego źródła lub obowiązkowego LLM.

Nie implementować jednocześnie wszystkich warstw „na przyszłość”. Po ukończeniu tego PRD dalsze rozszerzenia są osobnym zadaniem. Kryterium sukcesu stanowi użyteczne lokalne MVP z uczciwą informacją, a nie liczba integracji, efektów i abstrakcji.

## 19. Materiały źródłowe do kontraktów adapterów

Poniższe odnośniki przeniesiono z wcześniejszego raportu. Służą do ponownego sprawdzenia podczas M0; ich zamieszczenie nie oznacza ponownego sprawdzenia dostępności przy tworzeniu PRD.

| Oznaczenie | Materiał | Zastosowanie |
|---|---|---|
| S1 | [IMGW — ostrzeżenia meteorologiczne](https://danepubliczne.imgw.pl/api/data/warningsmeteo) | Punkt startowy integracji meteo. |
| S2 | [IMGW — informacje o API](https://danepubliczne.imgw.pl/apiinfo) | Kontrakt, oznaczenia i warunki wymagające sprawdzenia. |
| S3 | [RSO — informacje integracyjne](https://komunikaty.tvp.pl/Info/Integration) | Publiczne formaty, zakres dostępu i odróżnienie od innych interfejsów. |
| S4 | [RSO — przykładowy adres JSON](https://komunikaty.tvp.pl/komunikatyxml/wszystkie/wszystkie/1?_format=json) | Próbka kontraktu; nie zakładać semantyki końcówki adresu. |
| S5 | [Rządowe Centrum Bezpieczeństwa](https://www.gov.pl/web/rcb) | Ustalenie właściwej sekcji alertów i warunków publikacji. |
| S6 | [Straż Graniczna — aktualności](https://www.strazgraniczna.pl/pl/aktualnosci) | Punkt startowy centralnego adaptera HTML. |
| S7 | [Geoportal — Państwowy Rejestr Granic](https://www.geoportal.gov.pl/pl/dane/panstwowy-rejestr-granic-prg/) | Dane referencyjne, identyfikatory, geometria i pochodzenie. |
| S8 | [Leaflet — GeoJSON](https://leafletjs.com/examples/geojson/) | Obsługa mapy i geometria; zasoby biblioteki dostarczyć lokalnie. |
| S9 | [uv — dokumentacja](https://docs.astral.sh/uv/) | Projekt, środowisko, zależności i lockfile. |
| S10 | [SQLite — WAL](https://www.sqlite.org/wal.html) | Zachowanie lokalnej bazy i konsekwencje kopii podczas pracy. |

Podstawą zakresu pozostają: brief użytkownika „Wklejony tekst(20261011-140648).txt”, wcześniejszy raport „Polska platforma OSINT — raport badawczo-architektoniczny” oraz późniejsza akceptacja trzech końcowych rekomendacji i ręcznego uruchamiania lokalnego. Ten PRD dodaje wymagania implementacyjne, nie nowe twierdzenia o bieżących wydarzeniach.

---

## 20. Skrócone zlecenie implementacyjne

> Zbuduj prywatne, lokalne MVP „Polska — sytuacja i ostrzeżenia” zgodnie z tym PRD. Użyj Python + uv + FastAPI + SQLite + Leaflet. Zaimplementuj cztery wybrane źródła, automatyczną publikację jednoznacznych ostrzeżeń oraz kontrolę opisowych komunikatów, historię, pochodzenie i niepewność lokalizacji. Zachowaj stan źródeł i danych po przerwach. Dostarcz kompletny projekt, testy, lokalne zasoby mapy, izolowaną demonstrację i instrukcję ręcznego uruchomienia. Nie dodawaj LLM ani dalszych integracji. Nie instaluj globalnych komponentów, nie konfiguruj usług, nie wdrażaj, nie wystawiaj aplikacji w sieci i nie pozostawiaj jej uruchomionej. Użytkownik sam uruchomi projekt poleceniem `uv run --locked python -m polska_osint`.
