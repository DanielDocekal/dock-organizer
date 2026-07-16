# dockgroups

🇨🇿 Čeština | [🇬🇧 English](README.en.md)

CLI nástroj pro macOS, který organizuje Dock do tematických skupin (složek/stacků na pravé straně Docku) — náhrada placených utilit typu DockGroups/DockStacks. Konfigurace je jeden YAML soubor, volitelná lokální AI (Ollama) pomáhá s tříděním aplikací.

## Jak to funguje

Dock na macOS neumí aplikace seskupovat. `dockgroups` to řeší nativním mechanismem: vytvoří v projektu složku pro každou skupinu, naplní ji Finder aliasy aplikací a připne ji na pravou stranu Docku. Levé (aplikační) strany Docku se nástroj nikdy nedotkne.

## Požadavky

- macOS (testováno na Apple Silicon)
- Python 3
- [Homebrew](https://brew.sh) — kvůli `dockutil`
- [dockutil](https://github.com/keimpx/dockutil) — nástroj sám nabídne instalaci přes Homebrew, pokud chybí
- [Ollama](https://ollama.com) — volitelné, jen pro AI návrh třídění (`suggest`); bez ní je nástroj plně funkční

## Instalace

```bash
git clone https://github.com/DanielDocekal/dock-organizer.git
cd dock-organizer
cp groups.example.yaml groups.yaml   # uprav si vlastní skupiny
```

Nic dalšího instalovat nemusíš — `./dockgroups` je spouštěcí skript, který si při prvním běhu sám založí `.venv` a nainstaluje závislosti (jen PyYAML).

## Použití

Vše se volá přes wrapper `./dockgroups <příkaz>`.

```bash
./dockgroups status    # přehled skupin + nezařazené aplikace
./dockgroups suggest   # AI návrh třídění přes Ollamu (bootstrap i údržba)
./dockgroups apply     # přestaví složky a Dock podle groups.yaml
./dockgroups restore   # obnova poslední zálohy Docku (--list pro výpis záloh)
```

`apply` je idempotentní — spusť ho kdykoliv znovu, jen srovná realitu s konfigurací a nic nerozbije. Před každou změnou Docku se automaticky zálohuje aktuální Dock plist.

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

- Názvy aplikací bez přípony `.app`.
- `icon` (emoji) je volitelný — pokud je vyplněný, nastaví se jako vlastní ikona složky, aby šly skupiny v Docku vizuálně rozeznat.
- `groups.yaml` je jediný zdroj pravdy o tom, co kam patří — uprav ho ručně, nebo si nech poradit přes `suggest`.

## AI třídění (suggest)

`suggest` používá lokální Ollamu k roztřídění aplikací:

- **Bootstrap** — pokud `groups.yaml` ještě neexistuje nebo nemá skupiny, model navrhne 4–6 tematických skupin a rozřadí do nich všechny nalezené aplikace.
- **Údržba** — pokud skupiny už existují, model zařazuje jen nově přibylé/nezařazené aplikace do nich.

Návrhy se schvalují interaktivně po jedné aplikaci (přijmout / přeskočit / zadat skupinu ručně / konec). Bez běžící Ollamy `suggest` srozumitelně nahlásí, že AI návrh přeskakuje, a jen vypíše nezařazené aplikace — zbytek nástroje funguje beze změny.

## Licence

[MIT](LICENSE)

## Autor

Daniel Dočekal — [GitHub](https://github.com/DanielDocekal) · [365tipu.cz](https://365tipu.cz)
