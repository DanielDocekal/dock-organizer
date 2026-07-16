# dockgroups

CLI nástroj v Pythonu pro organizaci macOS Docku do tematických skupin (složek/stacků na pravé straně Docku). Náhrada placených utilit typu DockGroups/DockStacks.

## Struktura projektu

- `dockgroups.py` — hlavní CLI skript (jediný vstupní bod)
- `dockgroups` — spouštěcí shell wrapper; jediný způsob, jak nástroj spouštět (viz bod 8)
- `requirements.txt` — závislosti instalované výhradně do `.venv`
- `groups.yaml` — konfigurace skupin, JEDINÝ zdroj pravdy o tom, co kam patří
- `WISHLIST.md` — nápady mimo scope, jen poznámky k budoucímu zvážení, needělat bez výslovného zadání
- `backups/` — zálohy Dock plistu s timestampem (negitovat, je v .gitignore)
- `Stacks/<skupina>/` — generované složky s aliasy (podsložka projektu; NE `DockGroups`, NE `~/DockGroups`! viz bod 9); NIKDY needitovat ručně, vždy jen přes `apply`

## Klíčové principy — neporušovat

1. **Idempotence:** `apply` lze spustit kdykoliv a opakovaně; vždy jen srovná realitu s groups.yaml. Žádné vedlejší efekty při opakovaném běhu.
2. **Levá strana Docku je nedotknutelná.** Nástroj nikdy nepřidává, neodebírá ani nepřesouvá aplikace v levé (aplikační) části Docku. Pracuje výhradně s pravou stranou (persistent-others).
3. **Složky v Stacks/ se nikdy nemažou a nevytvářejí znovu**, pokud už existují — Dock si položky drží podle cesty v plistu a recreate složky odpojí ikonu v Docku. Mění se pouze obsah složek (aliasy).
4. **Aliasy, ne symlinky, a ne přes Finder automation.** Vytvářené přes NSURL bookmark data (`NSURLBookmarkCreationSuitableForBookmarkFile`, hodnota `1<<10`) voláním `osascript -l JavaScript` (JXA + ObjC bridge — `ObjC.import('Foundation')`) — NE `tell application "Finder"`. Finder automation vyžaduje jednorázové macOS Automation povolení (systémový dialog, na který nejde skriptem odpovědět) a pro tvorbu/čtení aliasů není potřeba. Rozřešení cíle aliasu (`URLByResolvingBookmarkData...`) MUSÍ použít options `NSURLBookmarkResolutionWithoutUI (1<<8) | NSURLBookmarkResolutionWithoutMounting (1<<9)` — bez nich při smazaném/nedostupném cíli proces segfaultuje (Foundation se pokusí zobrazit "Locate file" UI, které v headless kontextu nemá kam). Ikona složky: `NSWorkspace.setIcon(forFile:options:)` po vykreslení emoji do `NSImage` (`NSFont` + `drawAtPoint:withAttributes:`) — taky bez potřeby povolení. Symlinky v Docku nezobrazují správně ikony aplikací, proto ne symlinky.
5. **Záloha před každou změnou Docku.** Bez výjimky.
6. **Ollama je striktně volitelná.** Cokoliv kolem AI klasifikace musí mít graceful fallback; nástroj musí být plně funkční bez běžící Ollamy.
7. **Minimální závislosti:** Python 3 stdlib + PyYAML. Nic dalšího nepřidávat bez výslovného souhlasu. Externí binárky: `dockutil` (přes Homebrew), `osascript`, `sips`/`iconutil` pro ikony.
8. **Izolace přes `.venv`:** projekt používá virtuální prostředí přímo ve složce projektu (`.venv/`). Závislosti (PyYAML) se instalují VÝHRADNĚ do něj — nikdy globálně, nikdy `--user`, nikdy přes brew. Uživatel nástroj vždy spouští přes wrapper `./dockgroups <příkaz>`, nikdy přímo `python3 dockgroups.py`. Wrapper při chybějícím `.venv` ho založí, nainstaluje `requirements.txt` a teprve pak předá argumenty skriptu.
9. **Case-insensitive APFS past: generovaná složka se jmenuje `Stacks/`, ne `DockGroups/`, a je VŽDY podsložka projektu, NIKDY `~/DockGroups`.** macOS APFS je defaultně case-insensitive (ale case-preserving) — dva názvy lišící se jen velikostí písmen jsou fyzicky STEJNÝ soubor/složka (ověřeno přes inode). Padlo to na tom dvakrát: (a) `~/DockGroups` a `~/dockgroups` (kořen projektu) jsou stejná cesta — přímé použití `~/DockGroups` by mísilo generovaná data s git repem a přidalo do Docku celý projektový adresář; (b) i podsložka pojmenovaná `DockGroups` v kořeni projektu koliduje s `dockgroups` (spouštěcí wrapper skript v té samé složce) — `mkdir` na ni spadl na `FileExistsError`, protože „DockGroups" *je* ten wrapper skript. Proto `Stacks/` (`SCRIPT_DIR / "Stacks"`) — jméno, které nekoliduje s ničím v projektu. Nikdy nepoužívej `Path.home() / "DockGroups"` ani jakýkoli název lišící se od existujícího souboru v projektu jen velikostí písmen.
10. **`Icon\r` soubor uvnitř skupinové složky NIKDY nemazat.** Není to vedlejší produkt — `NSWorkspace.setIcon` na složce uloží samotná obrazová data ikony do resource forku právě tohoto souboru (na složce samotné žádný `com.apple.ResourceFork` není, jen bit `hasCustomIcon`). Smazání `Icon\r` by ikonu složky rozbilo. Musí zůstat, jen neviditelný (viz `hide_icon_carrier_file`).
11. **Dock cachuje obsah stacku nezávisle na tom, jestli je `Icon\r` správně skrytý.** I když je na disku všechno v pořádku (invisible bit nastavený), běžící proces Docku si může držet starý obsah složky v paměti (např. přes spánek/probuzení Macu) a ukazovat needitovaný stacku obsah včetně viditelné dlaždice „Icon?". `apply` restartuje Dock automaticky, KDYŽ SÁM něco změní (viz `hide_icon_carrier_file` návratová hodnota); pokud se stará položka objeví bez toho, že by `apply` běžel, je to nesouvisející desync Dockovy vlastní cache — řeší se prostým `killall Dock`, není to bug v datech.

## Příkazy nástroje

Vše se volá přes wrapper `./dockgroups <příkaz>` (viz bod 8), nikdy přímo `python3 dockgroups.py`.

- `./dockgroups suggest` — AI návrh třídění (bootstrap i údržba)
- `./dockgroups apply` — přestaví složky a Dock podle groups.yaml
- `./dockgroups status` — přehled skupin + nezařazené aplikace
- `./dockgroups restore` — obnova poslední zálohy Docku

## Prostředí

- macOS, Apple Silicon
- Ollama na `localhost:11434`, výchozí model `gemma4:12b-mlx`
- Volání Ollamy vždy s `"think": false` (thinking mód je na tomto stroji zoufale pomalý — řádově minuty místo sekund) a `"options": {"num_ctx": 8192}` (Ollama defaultně běží jen na 4096 bez ohledu na max context modelu; 8192 si Mac Mini bez problému dovolí)
- dockutil může a nemusí být nainstalovaný — detekovat, nabídnout `brew install dockutil`

## Konvence

- Kód i komentáře anglicky, výstupy pro uživatele (CLI hlášky) česky
- Žádné tiché selhání: chybějící aplikace z konfigurace = warning s názvem, ne pád ani ignorace
- `killall Dock` pouze pokud se reálně něco změnilo
- Po změnách kódu vždy ověřit, že `apply` po druhém spuštění nehlásí žádné změny (test idempotence)

## Verzování

- Projekt má lokální git repozitář — je to jediný mechanismus pro historii/zálohy `groups.yaml` a kódu.
- ŽÁDNÉ ruční kopie souborů (`*.bak`, `*.v1`, `*-old` apod.) jako náhrada verzování — místo toho `git commit` podle potřeby (např. před riskantní úpravou, po úspěšném `suggest`).
- Commituje se lokálně dle potřeby; bez vzdáleného repozitáře, žádný push (není kam).
