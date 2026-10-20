# Kontrakt oficjalnych PDF IMGW

Aktywny adapter odczytuje wyłącznie [bieżący katalog ostrzeżeń meteorologicznych](https://danepubliczne.imgw.pl/data/current/ost_meteo/) oraz znane pliki aktualnych ostrzeżeń. Nie ma parsera JSON `warningsmeteo`, hydro ani pobierania archiwum podczas pracy aplikacji.

Indeks musi mieć rozpoznany nagłówek. Wybór: najnowszy zbiorczy PDF na prefiks wydawniczy i znane aktywne dokumenty, maksymalnie 20 plików. Transport zachowuje limity, robots, warunkowe odczyty i kontrolę przekierowań. Nieznany lub nieczytelny plik daje jawny częściowy/błędny odczyt, bez zgadywania tekstu.

Parser `pypdf` odczytuje drukowane pola: zjawisko/stopień, obszar z numerami ostrzeżeń, ważność, prawdopodobieństwo, przebieg/przyczyna i wydanie. Podpisy, kontakty, mapy i stopki są usuwane przed zapisem. Opis komunikatu jest tekstem tych pól, nie nowym skrótem lub oceną operatora. Bieżąca wersja parsera: `imgw-pdf/2`.

Tożsamość ostrzeżenia: `imgw-pdf:{rok}:{kod_powiat}:{numer}`. Rok, kod i numer mają podstawę w zweryfikowanej tabeli. Tożsamość nie wynika z tytułu ani transportowej nazwy zbiorczego PDF. Powtórzenie ostrzeżenia w nowym zbiorze aktualizuje URL odczytu bez merytorycznej nowej wersji. Zmiana treści i ODWOŁANIE zapisują kolejną wersję i aktualizują bieżący widok bez zatwierdzania. Starszy spóźniony PDF pozostaje w historii, nie cofa bieżącego tekstu. Sprzeczne powtórzenia pól/tożsamości mają niewiarygodny kontrakt i nie są prezentowane jako poprawne dane.

Jawne polskie godziny są normalizowane Europe/Warsaw → UTC. Niejednoznaczny DST i nieprawidłowe przedziały pozostają nieznane, z diagnostyką. Nie są zastępowane datą pobrania. Stopnie 1–3 i przetestowane typy Burze, Silny wiatr, Upał, Intensywne opady deszczu mają oznaczenie ostrzeżenia. Nierozpoznane typy/stopnie nie otrzymują wygenerowanej ważności/oceny; tekst źródła i ograniczenia są zachowane. Expired nie oznacza potwierdzenia końca zjawiska; ODWOŁANIE jest stanem podanym przez wydawcę.

Powiaty są dopasowane do lokalnych kodów i granic PRG. Brak lub niejednoznaczność geometrii nie powoduje tworzenia punktu incydentu. Dokumenty mają `source_pdf_url`, a wyświetlany `original_url` jest ograniczony do sprawdzonego formatu oficjalnego bieżącego PDF lub miesięcznego ZIP archiwum. Każda historyczna wersja zachowuje swój odnośnik.

Historyczne sprawdzenie opisane w tym miejscu korzystało z danych live. Kopie odpowiedzi, pomiary, zrzuty i szczegółowe zestawienia usunięto z bieżącej wersji 18.10.2026; zobacz [zasady przechowywania wyników](evidence/README.md).
