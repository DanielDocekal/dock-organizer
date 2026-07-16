# Zadání: dockgroups — organizace macOS Docku do skupin

Postav CLI nástroj v Pythonu podle pravidel v CLAUDE.md. Projekt žije v `~/dockgroups/`.

**Pozor na case-insensitive APFS:** generované složky žijí v `Stacks/` jako podsložka projektu (`~/dockgroups/Stacks/<skupina>/`), NIKDY v `~/DockGroups/` ani v podsložce pojmenované `DockGroups`. Na macOS je `~/DockGroups` a `~/dockgroups` (projekt) fyzicky STEJNÁ cesta (case-insensitive, ale case-preserving filesystem) a i podsložka `DockGroups` by kolidovala s wrapper skriptem `dockgroups` v kořeni projektu. Viz CLAUDE.md bod 9.

## Cíl

Dock na Macu neumí seskupovat aplikace. Nástroj to řeší přes nativní mechanismus: složky s aliasy aplikací na pravé straně Docku (stacky). Uživatel spravuje jediný soubor `groups.yaml`, nástroj z něj idempotentně generuje složky a nasazuje je do Docku. Volitelná lokální AI (Ollama) pomáhá s tříděním.

## Konfigurace: groups.yaml

```yaml
settings:
  ollama_model: gemma4:12b-mlx
  ollama_url: http://localhost:11434

groups:
  AI:
    icon: 🤖
    apps:
      - Claude
      - ChatGPT
  Dev:
    icon: 💻
    apps:
      - Termius
      - TablePlus
```

- Názvy aplikací bez přípony `.app`
- `icon` (emoji) volitelný — když je, vyrenderuj emoji a nastav složce vlastní ikonu (`NSWorkspace.setIcon(forFile:options:)` přes `osascript -l JavaScript`, viz CLAUDE.md bod 4), aby se v Docku vizuálně odlišily jednotlivé skupiny; bez něj zůstane výchozí modrá složka

## Příkazy

### `apply`
1. Záloha aktuálního Dock plistu do `backups/dock-<timestamp>.plist`
2. Pro každou skupinu zajisti existenci `Stacks/<skupina>/` (podsložka projektu; existující složky NIKDY nemazat/nerecreatovat — viz CLAUDE.md bod 3)
3. Srovnej obsah složky s konfigurací: chybějící aliasy vytvoř (NSURL bookmark data přes `osascript -l JavaScript`, ne Finder automation — viz CLAUDE.md bod 4), aliasy na aplikace odebrané z konfigurace smaž
4. Aplikace hledej v `/Applications`, `~/Applications`, `/Applications/Utilities`; nenalezená aplikace = warning, pokračuj
5. Přes dockutil zajisti, že každá skupina je na pravé straně Docku s `--view grid --display folder --sort name`; skupiny odstraněné z groups.yaml odeber z Docku i z disku (jediná výjimka z pravidla nemazání — ale jen po interaktivním potvrzení)
6. `killall Dock` jen pokud proběhla reálná změna; na konci vypiš shrnutí co se změnilo (nebo "beze změn")
7. Levé strany Docku se nedotýkej za žádných okolností

### `status`
- Vypiš skupiny a jejich obsah (odliš aliasy, jejichž cíl už neexistuje)
- Sekce **Nezařazené**: aplikace z /Applications a ~/Applications, které nejsou v žádné skupině. Ignoruj /System a aplikace, jejichž bundle ID začíná `com.apple.`

### `suggest`
Klasifikace přes Ollamu (URL a model ze settings). Dva režimy:

- **Bootstrap** (groups.yaml chybí nebo nemá žádné skupiny): model navrhne 4–6 smysluplných skupin a rozřadí do nich všechny nalezené aplikace
- **Údržba** (skupiny existují): model zařazuje pouze nezařazené aplikace do stávajících skupin; smí navrhnout novou skupinu jen s explicitním označením, že je nová

Ke každé aplikaci pošli kontext z `Info.plist`: název, `CFBundleIdentifier`, `LSApplicationCategoryType`, případně `CFBundleDisplayName`. Samotný název nestačí.

Technika:
- Dávky po max 10 aplikacích na request
- Každý request na Ollamu s `"think": false` (thinking mód je na tomto stroji řádově pomalejší — jednotky minut místo sekund) a `"options": {"num_ctx": 8192}` (Ollama defaultně běží na 4096 bez ohledu na max context modelu)
- Vyžaduj striktní JSON výstup (žádný okolní text); validuj proti povoleným názvům skupin; nevalidní odpověď → retry dávky, max 2×, pak dávku přeskoč s hlášením
- Odpověď modelu může přijít obalená v markdown code fence (` ```json ... ``` `) i přes `format: json` — při parsování to počítej a fence odřízni
- Návrhy zobrazuj interaktivně po jedné aplikaci: `y` = přijmout, `n` = přeskočit, `e` = zadat skupinu ručně, `q` = konec
- Přijaté návrhy zapiš do groups.yaml (zachovej formátování a komentáře, pokud to PyYAML rozumně dovolí; jinak čistý přepis)
- Ollama nedostupná / model chybí → srozumitelná hláška + fallback na výpis nezařazených, exit code 0

### `restore`
- Obnov poslední zálohu z `backups/` (defaults import + killall Dock)
- S argumentem `--list` vypiš dostupné zálohy, s `restore <soubor>` obnov konkrétní

## Kvalita

- Jeden soubor `dockgroups.py`, argparse, čitelné členění do funkcí
- Ošetři: dockutil chybí (nabídni brew install), Homebrew chybí (řekni to a skonči), aplikace s mezerami/diakritikou v názvu, prázdná skupina
- Na závěr napiš stručný README.md (instalace, použití, příklady)

## Izolace závislostí — `.venv`

Projekt používá `.venv` přímo ve složce projektu, závislosti (PyYAML) jdou výhradně do něj — nikdy globálně, `--user` ani přes brew.

- `requirements.txt` — obsahuje `PyYAML`
- `dockgroups` — spouštěcí shell wrapper ve složce projektu; při chybějícím `.venv` ho vytvoří (`python3 -m venv .venv`), nainstaluje do něj `requirements.txt` a předá všechny argumenty do `dockgroups.py` (spuštěného interpretem z `.venv`)
- Uživatel vždy volá jen `./dockgroups <příkaz>` (např. `./dockgroups status`), nikdy `python3 dockgroups.py` přímo
- `.gitignore` obsahuje `.venv/`, `backups/`, `__pycache__/`

## Postup — důležité

1. Nejdřív napiš kostru + `status` a ukaž mi výstup (ať vidím, co jsi našel na disku)
2. Pak `suggest` v bootstrap režimu — vygenerujeme spolu první groups.yaml, který si upravím
3. Teprve po mém odsouhlasení groups.yaml spusť první `apply`
4. Nakonec test idempotence: druhý `apply` musí hlásit "beze změn"
