# dockgroups

[🇨🇿 Čeština](README.md) | 🇬🇧 English

A macOS CLI tool that organizes your Dock into themed groups (folders/stacks on the right side of the Dock) — a free alternative to paid utilities like DockGroups/DockStacks. Configuration lives in a single YAML file; an optional local AI (Ollama) can help classify your apps.

## How it works

macOS's Dock has no built-in way to group apps. `dockgroups` works around that with a native mechanism: it creates a folder per group inside the project, fills it with Finder aliases to your apps, and pins it to the right side of the Dock. The left (application) side of the Dock is never touched.

## Requirements

- macOS (tested on Apple Silicon)
- Python 3
- [Homebrew](https://brew.sh) — needed for `dockutil`
- [dockutil](https://github.com/keimpx/dockutil) — the tool offers to install it via Homebrew automatically if missing
- [Ollama](https://ollama.com) — optional, only needed for AI-assisted classification (`suggest`); the tool is fully functional without it

## Installation

```bash
git clone https://github.com/DanielDocekal/dock-organizer.git
cd dock-organizer
cp groups.example.yaml groups.yaml   # edit to define your own groups
```

Nothing else to install — `./dockgroups` is a launcher script that creates its own `.venv` and installs dependencies (just PyYAML) on first run.

## Usage

Everything goes through the `./dockgroups <command>` wrapper.

```bash
./dockgroups status    # overview of groups + unclassified apps
./dockgroups suggest   # AI-assisted classification via Ollama (bootstrap or maintenance)
./dockgroups apply     # rebuilds the folders and Dock from groups.yaml
./dockgroups restore   # restores the latest Dock backup (--list to see available backups)
```

`apply` is idempotent — run it again any time; it only reconciles reality with your config and never breaks anything. The current Dock plist is backed up automatically before every change.

## Configuration: groups.yaml

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

- App names without the `.app` suffix.
- `icon` (an emoji) is optional — when set, it becomes the folder's custom icon so groups are visually distinguishable in the Dock.
- `groups.yaml` is the single source of truth for what belongs where — edit it by hand, or let `suggest` help.

## AI classification (suggest)

`suggest` uses a local Ollama instance to classify your apps:

- **Bootstrap** — if `groups.yaml` doesn't exist yet or has no groups, the model proposes 4–6 thematic groups and sorts every detected app into them.
- **Maintenance** — if groups already exist, the model only classifies newly-appeared/unclassified apps into them.

Suggestions are reviewed interactively, one app at a time (accept / skip / enter a group manually / quit). Without a running Ollama instance, `suggest` reports clearly that it's skipping the AI step and just lists unclassified apps — the rest of the tool works unchanged.

## License

[MIT](LICENSE)

## Author

Daniel Dočekal — [GitHub](https://github.com/DanielDocekal) · [365tipu.cz](https://365tipu.cz)
