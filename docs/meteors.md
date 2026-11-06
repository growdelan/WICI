# Noc meteorów nad Polską

Wybierz **Sytuacja → Warstwy → Nocne niebo → Odtwórz noc meteorów w 3D**. Odtwarzacz otwiera lokalny zapis 265 trajektorii z 4 na 5 listopada 2026 r. Zarejestrowany odcinek wyróżnionego meteoru zaczął się w okolicach Nysy o **21:57:30 UTC (22:57:30 czasu polskiego)**. Trwał **4,08 s** i sięgał od **82,67 do 60,59 km** wysokości. W katalogu GMN ma identyfikator `20261104215730_pYgTq`.

- **Cała noc** pokazuje trajektorie nad Polską i ich kolejność w czasie. W tempie **W rytmie zjawisk** odtwarzacz przyspiesza przerwy i zwalnia na czas przelotu. Szare linie pokazują wszystkie ślady z katalogu wybranej nocy. Po zjawisku jego ślad pozostaje podświetlony do trzech minut na osi czasu, żeby łatwiej go dostrzec podczas przyspieszania. Kliknięcie śladu albo wybór wpisu na liście otwiera pojedynczy przelot.
- **Trajektoria** pozwala obejrzeć przebieg z boku. Zatrzymaj czas, przesuń suwak wstecz lub odtwórz przelot w zwolnieniu.
- **Z ziemi** ustawia kamerę w miejscu obserwatora. Wybierz miejscowość lub **Wskaż na mapie** i kliknij punkt. **Najbliższy początek** wybiera meteor, którego zarejestrowany ślad rozpoczął się najbliżej Twojego miejsca. Podana odległość jest liczona po powierzchni do punktu pod początkiem trajektorii. Rzeczywista widoczność zależała również od chmur, otoczenia i jasności nieba.

## Wybór innej nocy

Data oznacza początek przedziału od lokalnego południa do południa następnego dnia w strefie Europe/Warsaw. Północ i zmiana czasu mieszczą się w jednej sesji. W zwykłym trybie wybierz datę zakończonej nocy i naciśnij **Wczytaj**. Aplikacja pobiera katalog GMN na żądanie, bez konta i klucza. Dołączona noc jest dostępna także w demonstracji i po wyłączeniu pobierania przez `[sources.meteors]` w konfiguracji.

Lista obejmuje trajektorie, których zarejestrowany początek leży w granicach Polski. Pusta lista oznacza, że w pobranych danych brakuje takich obserwacji. Pokrycie sieci kamer, zachmurzenie i termin publikacji wpływają na liczbę wpisów. Niedostępność archiwum jest sygnalizowana osobno. Dołączony zapis przygotowano z wydania katalogu GMN wygenerowanego 6 listopada 2026 r. o 12:49 UTC. [Listopadowa tabela źródłowa GMN](https://globalmeteornetwork.org/data/traj_summary_data/monthly/traj_summary_monthly_202611.txt).

## Jak czytać odtworzenie

GMN podaje czas początku w UTC, czas trwania oraz współrzędne obu końców odcinka. Wysokości odnoszą się do elipsoidy WGS84. Prędkość dotyczy początku odcinka względem Ziemi, a jasność absolutna jest przeliczona na odległość 100 km. WICI odtwarza tor pomiędzy tymi punktami i rysuje smugę, aby można było śledzić ruch. Punkt końcowy wyznacza koniec zarejestrowanej trajektorii w atmosferze. Potwierdzenie upadku meteorytu na ziemię wymaga osobnych dowodów. [Opis pól GMN](https://globalmeteornetwork.org/data/media/GMN_orbit_data_columns.pdf) · [Pochodzenie danych i licencja](../THIRD_PARTY_NOTICES.md#global-meteor-network--noc-meteorów).
