#!/usr/bin/env python3
"""dockgroups — organizace macOS Docku do tematických skupin."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

BATCH_SIZE = 10
OLLAMA_TIMEOUT = 120
MAX_RETRIES = 2
OLLAMA_NUM_CTX = 8192  # Ollama defaultně běží jen na 4096, i když model umí víc

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "groups.yaml"
BACKUPS_DIR = SCRIPT_DIR / "backups"
DOCKGROUPS_HOME = SCRIPT_DIR / "Stacks"
# Podsložka projektu, NE "DockGroups" a NE ~/DockGroups přímo — na case-insensitive
# APFS by "DockGroups" kolidovalo s "dockgroups" (wrapper skript ve stejné složce)
# a ~/DockGroups by kolidovalo s ~/dockgroups (kořen projektu). Viz CLAUDE.md bod 9.

APP_SEARCH_DIRS = [
    Path("/Applications"),
    Path.home() / "Applications",
    Path("/Applications/Utilities"),
]
# Nezařazené se hledají jen v hlavních dvou (dle zadání), Utilities se
# používají jen při dohledávání konkrétní nakonfigurované aplikace.
UNCLASSIFIED_SEARCH_DIRS = [
    Path("/Applications"),
    Path.home() / "Applications",
]


def load_config() -> dict:
    """Načte groups.yaml. Chybějící soubor = prázdná konfigurace."""
    if not CONFIG_PATH.exists():
        return {"settings": {}, "groups": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("settings", {})
    data.setdefault("groups", {})
    return data


def clean_app_name(name: str) -> str:
    """Odstraní neviditelné formátovací Unicode znaky (např. U+200E) z názvu.

    Některé instalátory je vkládají na začátek jména .app balíčku; bez
    očištění by název v groups.yaml nikdy přesně nesedl.
    """
    return "".join(c for c in name if unicodedata.category(c) != "Cf")


def find_app_bundles(dirs: list[Path]) -> dict[str, Path]:
    """Vrátí mapu {název_bez_.app: cesta} pro .app balíčky v daných složkách.

    Při shodě názvu vyhrává první výskyt podle pořadí `dirs`. Skryté
    balíčky (název začínající tečkou) a neviditelné formátovací znaky
    v názvu se ignorují/odstraňují.
    """
    found: dict[str, Path] = {}
    for base in dirs:
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir())
        except PermissionError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.suffix == ".app" and entry.is_dir():
                name = clean_app_name(entry.stem)
                found.setdefault(name, entry)
    return found


def get_bundle_id(app_path: Path) -> str | None:
    """Přečte CFBundleIdentifier z Info.plist dané aplikace."""
    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.exists():
        return None
    try:
        with open(info_plist, "rb") as f:
            data = plistlib.load(f)
        return data.get("CFBundleIdentifier")
    except Exception:
        return None


def run_jxa(script: str, args: list[str]) -> str | None:
    """Spustí JavaScript for Automation (ObjC bridge) skript, vrátí jeho stdout.

    Používá se místo `tell application "Finder"` — Finder automation vyžaduje
    jednorázové macOS Automation povolení a je zbytečná; NSURL/NSWorkspace
    volané přes ObjC bridge žádné povolení nepotřebují.
    """
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(script)
            script_path = f.name
        try:
            result = subprocess.run(
                ["osascript", script_path, *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
        finally:
            os.unlink(script_path)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


_MAKE_ALIAS_JXA = """
ObjC.import('Foundation');

function run(argv) {
    var targetPath = argv[0];
    var aliasPath = argv[1];
    var SUITABLE_FOR_BOOKMARK_FILE = 1 << 10; // NSURLBookmarkCreationSuitableForBookmarkFile

    var targetURL = $.NSURL.fileURLWithPath(targetPath);
    var aliasURL = $.NSURL.fileURLWithPath(aliasPath);

    var bmError = Ref();
    var bookmarkData = targetURL.bookmarkDataWithOptionsIncludingResourceValuesForKeysRelativeToURLError(
        SUITABLE_FOR_BOOKMARK_FILE, $(), $(), bmError
    );
    if (!bookmarkData) { return "ERROR"; }

    var writeError = Ref();
    var ok = $.NSURL.writeBookmarkDataToURLOptionsError(
        bookmarkData, aliasURL, SUITABLE_FOR_BOOKMARK_FILE, writeError
    );
    return ok ? "OK" : "ERROR";
}
"""


def create_alias(app_path: Path, group_dir: Path, app_name: str) -> bool:
    """Vytvoří skutečný Finder alias (NSURL bookmark data), ne symlink."""
    alias_path = group_dir / f"{app_name}.app"
    output = run_jxa(_MAKE_ALIAS_JXA, [str(app_path), str(alias_path)])
    return output == "OK"


_RESOLVE_ALIAS_JXA = """
ObjC.import('Foundation');

function run(argv) {
    var aliasPath = argv[0];
    var aliasURL = $.NSURL.fileURLWithPath(aliasPath);
    var WITHOUT_UI = 1 << 8;        // NSURLBookmarkResolutionWithoutUI
    var WITHOUT_MOUNTING = 1 << 9;  // NSURLBookmarkResolutionWithoutMounting

    var readError = Ref();
    var bookmarkData = $.NSURL.bookmarkDataWithContentsOfURLError(aliasURL, readError);
    if (!bookmarkData) { return "ERROR"; }

    var resolveError = Ref();
    var resolvedURL = $.NSURL.URLByResolvingBookmarkDataOptionsRelativeToURLBookmarkDataIsStaleError(
        bookmarkData, WITHOUT_UI | WITHOUT_MOUNTING, $(), $(), resolveError
    );
    try {
        var p = resolvedURL.path.js;
        if (typeof p !== "string" || p.length === 0) { return "ERROR"; }
        return "OK:" + p;
    } catch (e) {
        return "ERROR";
    }
}
"""


def resolve_alias_target(alias_path: Path) -> Path | None:
    """Zjistí cílovou cestu Finder aliasu přes NSURL bookmark data. None = nelze rozřešit
    (typicky smazaný/přesunutý cíl)."""
    output = run_jxa(_RESOLVE_ALIAS_JXA, [str(alias_path)])
    if output is None or not output.startswith("OK:"):
        return None
    return Path(output[len("OK:") :])


_SET_ICON_JXA = """
ObjC.import('AppKit');

function run(argv) {
    var emoji = argv[0];
    var targetPath = argv[1];
    var size = 512;

    var image = $.NSImage.alloc.initWithSize($.NSMakeSize(size, size));
    image.lockFocus;

    var font = $.NSFont.systemFontOfSize(size * 0.78);
    var attrs = $.NSMutableDictionary.alloc.init;
    attrs.setObjectForKey(font, "NSFont");

    var nsStr = $(emoji);
    var strSize = nsStr.sizeWithAttributes(attrs);
    var x = (size - strSize.width) / 2;
    var y = (size - strSize.height) / 2;
    nsStr.drawAtPointWithAttributes($.NSMakePoint(x, y), attrs);

    image.unlockFocus;

    var ws = $.NSWorkspace.sharedWorkspace;
    var ok = ws.setIconForFileOptions(image, targetPath, 0);
    return ok ? "OK" : "FAIL";
}
"""


def hide_icon_carrier_file(folder: Path) -> bool:
    """Skryje pomocný soubor `Icon\\r`, který `NSWorkspace.setIcon` vytvoří pro
    uložení vlastní ikony složky. Dostane BSD `hidden` flag automaticky, ale
    Dock stack grid view ho ignoruje a bez skrytí ho zobrazí jako viditelnou
    položku ve stacku — potřeba je klasický Finder `invisible` bit (0x4000)
    v `com.apple.FinderInfo`, který Finder normálně nastaví sám, ale
    NSWorkspace.setIcon ne.

    Vrací True, pokud bit skutečně chyběl a musel se nastavit — Dock si obsah
    stacku cachuje, takže tahle změna se v Docku neprojeví bez killall Dock.
    """
    icon_file = folder / "Icon\r"
    if not icon_file.exists():
        return False

    current = subprocess.run(
        ["xattr", "-px", "com.apple.FinderInfo", str(icon_file)],
        capture_output=True, text=True, timeout=10,
    )
    if current.returncode == 0:
        existing_hex = current.stdout.replace(" ", "").replace("\n", "")
        if len(existing_hex) >= 18 and existing_hex[16:18].lower() == "40":
            return False  # bit už je nastavený, není co dělat

    finder_info = bytearray(32)
    finder_info[8] = 0x40  # horní byte Finder flags -> bit 0x4000 = kIsInvisible
    subprocess.run(
        ["xattr", "-wx", "com.apple.FinderInfo", finder_info.hex(), str(icon_file)],
        capture_output=True,
        timeout=10,
    )
    return True


def set_folder_icon(folder: Path, emoji: str) -> tuple[bool, bool]:
    """Vyrenderuje emoji do NSImage a nastaví ho jako vlastní ikonu složky.

    Vrací (ok, changed) — changed značí, že bylo potřeba i restartovat Dock.
    """
    output = run_jxa(_SET_ICON_JXA, [emoji, str(folder)])
    ok = output == "OK"
    changed = False
    if ok:
        changed = hide_icon_carrier_file(folder)
    return ok, changed


def is_apple_system_app(path: Path) -> bool:
    bundle_id = get_bundle_id(path)
    return bool(bundle_id and bundle_id.startswith("com.apple."))


def collect_unclassified(groups: dict) -> dict[str, Path]:
    """Aplikace z /Applications a ~/Applications, které nejsou v žádné skupině
    a nejsou systémové (com.apple.*)."""
    all_apps = find_app_bundles(UNCLASSIFIED_SEARCH_DIRS)
    classified_names = set()
    for group in groups.values():
        classified_names.update((group or {}).get("apps", []) or [])
    return {
        name: path
        for name, path in sorted(all_apps.items())
        if name not in classified_names and not is_apple_system_app(path)
    }


def print_unclassified(groups: dict) -> None:
    unclassified = collect_unclassified(groups)
    print("== Nezařazené ==")
    if unclassified:
        for name in unclassified:
            print(f"  - {name}")
    else:
        print("  (žádné)")


def build_app_context(name: str, path: Path) -> dict:
    """Kontext o aplikaci pro Ollamu: název nestačí, potřeba bundle id / kategorie."""
    ctx = {"name": name}
    info_plist = path / "Contents" / "Info.plist"
    try:
        with open(info_plist, "rb") as f:
            data = plistlib.load(f)
        if data.get("CFBundleIdentifier"):
            ctx["bundle_id"] = data["CFBundleIdentifier"]
        if data.get("LSApplicationCategoryType"):
            ctx["category"] = data["LSApplicationCategoryType"]
        if data.get("CFBundleDisplayName"):
            ctx["display_name"] = data["CFBundleDisplayName"]
    except Exception:
        pass
    return ctx


def ollama_list_models(url: str) -> list[str] | None:
    """Vrátí seznam nainstalovaných modelů, nebo None když Ollama neběží."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return None


def ollama_generate(url: str, model: str, prompt: str) -> str | None:
    """Zavolá Ollama /api/generate s vynuceným JSON výstupem. None při chybě/timeoutu."""
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            data = json.loads(resp.read())
        return data.get("response")
    except Exception:
        return None


def parse_json_response(raw: str | None) -> dict | None:
    """Vytáhne JSON objekt z odpovědi modelu.

    Ollama `format: json` vynucuje čistý JSON jen na gguf backendu; MLX modely
    (např. gemma4:12b-mlx) občas odpověď obalí do ```json ... ``` bloku.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


def propose_groups(url: str, model: str, app_names: list[str]) -> list[dict] | None:
    """Bootstrap: požádá model o 4-6 tematických skupin pokrývajících dané appky."""
    prompt = (
        "You are organizing macOS Dock applications into thematic groups (folders).\n"
        "Below is a list of installed application names.\n"
        "Propose between 4 and 6 broad, meaningful thematic groups that together "
        "could sensibly contain ALL of these apps (every app should fit at least one).\n"
        "Rules for good groups:\n"
        "- Each group must represent ONE clear, coherent category. Never combine unrelated "
        "domains into a single group name just to hit the 4-6 count — e.g. do not merge "
        "\"Games\" with \"Communication\", or \"Media\" with \"Communication\". If those are "
        "both needed, make them separate groups.\n"
        "- It's fine for a group to end up small (even just 2-3 apps) if that's genuinely the "
        "only correct home for them — group sizes do not need to be balanced.\n"
        "- If several apps are clearly game clients/launchers or cloud-gaming apps, give them "
        "their own dedicated group rather than folding them into something else.\n"
        "Respond with strict JSON only, no extra text, using exactly this schema:\n"
        '{"groups": [{"name": "<short group name>", "icon": "<single emoji or empty string>"}]}\n\n'
        "Applications:\n" + "\n".join(f"- {n}" for n in app_names)
    )
    raw = ollama_generate(url, model, prompt)
    data = parse_json_response(raw)
    if data is None:
        return None
    try:
        groups = data["groups"]
        if not isinstance(groups, list) or not (4 <= len(groups) <= 6):
            return None
        seen_names = set()
        result = []
        for g in groups:
            name = str(g["name"]).strip()
            if not name or name in seen_names:
                return None
            seen_names.add(name)
            icon = str(g.get("icon", "") or "").strip()
            result.append({"name": name, "icon": icon})
        return result
    except Exception:
        return None


def classify_batch(
    url: str,
    model: str,
    contexts: list[dict],
    allowed_groups: list[str],
    allow_new: bool,
) -> dict | None:
    """Vrátí {app_name: {"group":..., "new_group": bool}} nebo None při nevalidní odpovědi."""
    requested_names = {c["name"] for c in contexts}
    if allow_new:
        rule = (
            'You may propose a new group ONLY if none of the allowed groups fit well; '
            'in that case set "new_group": true and pick a short sensible new group name.'
        )
    else:
        rule = "You MUST assign every app to one of the allowed groups listed above — never invent a new one."
    prompt = (
        "You are classifying macOS applications into existing thematic Dock groups.\n"
        f"Allowed groups: {', '.join(allowed_groups)}\n"
        f"{rule}\n"
        "Use the provided metadata (bundle id, macOS category, display name) to judge each app's purpose.\n"
        "Classify by the app's PRIMARY, core purpose — never by an incidental secondary feature "
        "(e.g. a game platform having a chat feature does not make it a communication app).\n"
        "Common patterns to apply:\n"
        "- Game clients, launchers, and cloud-gaming apps belong in a games/entertainment group, "
        "never in communication or productivity groups.\n"
        "- Music/video/photo apps (streaming players, image viewers, photo editors) belong in a "
        "media/graphics group, not communication, even if they have social or sharing features.\n"
        "- File managers, FTP/SFTP/SSH clients, remote-desktop tools, and terminal emulators are "
        "development/technical tools — prefer a development group over a general system-utilities "
        "group when both exist.\n"
        "- A communication group is only for apps whose primary purpose is messaging, calling, or "
        "email between people — not entertainment or media apps.\n"
        "Respond with strict JSON only, no extra text, using exactly this schema:\n"
        '{"assignments": [{"app": "<name exactly as given>", "group": "<group name>", "new_group": <true|false>}]}\n'
        'Include exactly one assignment for every application below, using its exact "name" as "app".\n\n'
        "Applications:\n" + json.dumps(contexts, ensure_ascii=False, indent=2)
    )
    raw = ollama_generate(url, model, prompt)
    data = parse_json_response(raw)
    if data is None:
        return None
    try:
        assignments = data["assignments"]
        if not isinstance(assignments, list):
            return None
        result = {}
        for item in assignments:
            app = str(item["app"])
            if app not in requested_names or app in result:
                return None
            group = str(item.get("group", "")).strip()
            new_group = bool(item.get("new_group", False))
            if not group:
                return None
            if new_group:
                if not allow_new:
                    return None
            elif group not in allowed_groups:
                return None
            result[app] = {"group": group, "new_group": new_group}
        if set(result) != requested_names:
            return None
        return result
    except Exception:
        return None


def classify_batch_with_retry(
    url: str,
    model: str,
    contexts: list[dict],
    allowed_groups: list[str],
    allow_new: bool,
) -> dict | None:
    for _ in range(MAX_RETRIES + 1):
        result = classify_batch(url, model, contexts, allowed_groups, allow_new)
        if result is not None:
            return result
    return None


def chunked(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def cmd_status(args: argparse.Namespace) -> None:
    config = load_config()
    groups = config.get("groups", {})

    if not groups:
        print("Žádné skupiny nejsou nakonfigurované v groups.yaml.")
    else:
        for name in sorted(groups):
            group = groups[name] or {}
            icon = group.get("icon", "")
            apps = group.get("apps", []) or []
            header = f"{icon} {name}".strip() if icon else name
            print(f"== {header} ==")

            if not apps:
                print("  (prázdná skupina)")

            group_dir = DOCKGROUPS_HOME / name
            for app_name in apps:
                app_path = find_app_bundles(APP_SEARCH_DIRS).get(app_name)
                if app_path is None:
                    print(f"  ⚠ {app_name} — aplikace nenalezena na disku")
                    continue

                if group_dir.is_dir():
                    alias_path = group_dir / f"{app_name}.app"
                    if alias_path.exists():
                        target = resolve_alias_target(alias_path)
                        if target is None:
                            print(f"  ✗ {app_name} — alias existuje, ale nelze rozřešit cíl")
                        else:
                            print(f"  ✓ {app_name}")
                    else:
                        print(f"  · {app_name} — zatím bez aliasu (spusť apply)")
                else:
                    print(f"  · {app_name} — složka skupiny zatím neexistuje (spusť apply)")
            print()

    print_unclassified(groups)


def ensure_dockutil() -> str | None:
    """Ověří dostupnost dockutil, případně nabídne instalaci přes Homebrew."""
    path = shutil.which("dockutil")
    if path:
        return path

    print("⚠ dockutil není nainstalovaný (nutný pro umístění složek do Docku).")
    if shutil.which("brew") is None:
        print("Homebrew taky není nainstalovaný. Nainstaluj ho ručně (https://brew.sh) a spusť apply znovu.")
        return None

    answer = input("Nainstalovat dockutil přes Homebrew teď? [y/N]: ").strip().lower()
    if answer != "y":
        print("Bez dockutil nelze složky umístit do Docku. Končím.")
        return None

    result = subprocess.run(["brew", "install", "dockutil"])
    if result.returncode != 0:
        print("⚠ Instalace dockutil selhala.")
        return None

    path = shutil.which("dockutil")
    if path is None:
        print("⚠ dockutil se nepodařilo najít ani po instalaci.")
    return path


def backup_dock_plist() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUPS_DIR / f"dock-{timestamp}.plist"
    subprocess.run(["defaults", "export", "com.apple.dock", str(backup_path)], check=True)
    return backup_path


def dockutil_list_others() -> list[dict]:
    """Vrátí položky pravé strany Docku (persistentOthers) jako [{"label", "path"}]."""
    result = subprocess.run(["dockutil", "--list"], capture_output=True, text=True, timeout=15)
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label, url, section = parts[0], parts[1], parts[2]
        if section != "persistentOthers":
            continue
        path = urllib.parse.unquote(url.replace("file://", "")).rstrip("/")
        entries.append({"label": label, "path": path})
    return entries


def dock_has_path(entries: list[dict], target: Path) -> bool:
    target_str = str(target).rstrip("/")
    return any(e["path"] == target_str for e in entries)


def dockutil_add_group(group_dir: Path) -> bool:
    result = subprocess.run(
        [
            "dockutil", "--add", str(group_dir),
            "--view", "grid", "--display", "folder", "--sort", "name",
            "--section", "others", "--no-restart",
        ],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def dockutil_remove_path(group_dir: Path) -> bool:
    result = subprocess.run(
        ["dockutil", "--remove", str(group_dir), "--no-restart"],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def cmd_apply(args: argparse.Namespace) -> None:
    config = load_config()
    groups = config.get("groups") or {}

    dockutil_path = ensure_dockutil()
    if dockutil_path is None:
        sys.exit(1)

    backup_path = backup_dock_plist()
    print(f"Záloha Docku: {backup_path.relative_to(SCRIPT_DIR)}")

    changed = False
    summary: list[str] = []

    DOCKGROUPS_HOME.mkdir(parents=True, exist_ok=True)

    configured_names = set(groups.keys())
    existing_group_dirs = [d for d in DOCKGROUPS_HOME.iterdir() if d.is_dir()]
    orphaned = [d for d in existing_group_dirs if d.name not in configured_names]

    dock_entries = dockutil_list_others()

    for orphan in orphaned:
        answer = input(
            f"Skupina '{orphan.name}' byla odebrána z groups.yaml. Smazat složku i položku v Docku? [y/N]: "
        ).strip().lower()
        if answer != "y":
            print(f"  Ponecháno beze změny: {orphan.name}")
            continue
        if dock_has_path(dock_entries, orphan):
            dockutil_remove_path(orphan)
        shutil.rmtree(orphan)
        changed = True
        summary.append(f"Smazána skupina '{orphan.name}' (odebrána z groups.yaml)")

    apps_index = find_app_bundles(APP_SEARCH_DIRS)

    for name in sorted(groups):
        group = groups[name] or {}
        icon = group.get("icon", "")
        apps = group.get("apps", []) or []
        group_dir = DOCKGROUPS_HOME / name

        if not group_dir.exists():
            group_dir.mkdir(parents=True)
            changed = True
            summary.append(f"Vytvořena složka skupiny '{name}'")

        if not apps:
            print(f"Skupina '{name}' je prázdná — žádné aplikace k zařazení.")

        existing_aliases = {p.stem: p for p in group_dir.glob("*.app")}
        wanted_names = set()

        for app_name in apps:
            app_path = apps_index.get(app_name)
            if app_path is None:
                print(f"⚠ {app_name} (skupina '{name}') — aplikace nenalezena, přeskakuji")
                continue
            wanted_names.add(app_name)
            if app_name in existing_aliases:
                continue
            if create_alias(app_path, group_dir, app_name):
                changed = True
                summary.append(f"+ {name}/{app_name}")
            else:
                print(f"⚠ Nepodařilo se vytvořit alias pro {app_name} ve skupině '{name}'")

        for existing_name, alias_path in existing_aliases.items():
            if existing_name not in wanted_names:
                alias_path.unlink()
                changed = True
                summary.append(f"- {name}/{existing_name}")

        if icon:
            icon_ok, icon_changed = set_folder_icon(group_dir, icon)
            if not icon_ok:
                print(f"⚠ Nepodařilo se nastavit ikonu skupiny '{name}'")
            elif icon_changed:
                changed = True
                summary.append(f"Opravena viditelnost pomocného souboru ikony ve skupině '{name}'")

        if not dock_has_path(dock_entries, group_dir):
            if dockutil_add_group(group_dir):
                changed = True
                summary.append(f"Přidáno do Docku: {name}")
            else:
                print(f"⚠ Nepodařilo se přidat skupinu '{name}' do Docku")

    if changed:
        subprocess.run(["killall", "Dock"])

    if summary:
        print("Shrnutí změn:")
        for line in summary:
            print(f"  {line}")
    else:
        print("Beze změn.")


def cmd_suggest(args: argparse.Namespace) -> None:
    config = load_config()
    groups = config.get("groups") or {}
    settings = config.get("settings") or {}
    ollama_url = settings.get("ollama_url", "http://localhost:11434")
    ollama_model = settings.get("ollama_model", "gemma4:12b-mlx")
    settings.setdefault("ollama_url", ollama_url)
    settings.setdefault("ollama_model", ollama_model)

    models = ollama_list_models(ollama_url)
    if models is None:
        print(f"⚠ Ollama na {ollama_url} není dostupná. AI návrh přeskočen.")
        print_unclassified(groups)
        sys.exit(0)
    if ollama_model not in models:
        available = ", ".join(models) if models else "—"
        print(f"⚠ Model '{ollama_model}' není v Ollamě nainstalovaný (dostupné: {available}). AI návrh přeskočen.")
        print_unclassified(groups)
        sys.exit(0)

    bootstrap = not groups
    working_groups = {name: dict(g or {}) for name, g in groups.items()}
    for g in working_groups.values():
        g.setdefault("apps", [])

    if bootstrap:
        apps_to_classify = collect_unclassified({})
        if not apps_to_classify:
            print("Nenalezeny žádné aplikace k roztřídění.")
            return
        print(f"Navrhuji rozdělení {len(apps_to_classify)} aplikací do skupin, ptám se Ollamy ({ollama_model})...")
        proposed = propose_groups(ollama_url, ollama_model, list(apps_to_classify.keys()))
        if proposed is None:
            print("⚠ Ollama nevrátila platný návrh skupin. AI návrh přeskočen.")
            print_unclassified(groups)
            sys.exit(0)
        print("Navržené skupiny:")
        for g in proposed:
            label = f"{g['icon']} {g['name']}".strip() if g["icon"] else g["name"]
            print(f"  {label}")
            entry = {}
            if g["icon"]:
                entry["icon"] = g["icon"]
            entry["apps"] = []
            working_groups[g["name"]] = entry
        allowed_group_names = [g["name"] for g in proposed]
        allow_new = False
    else:
        apps_to_classify = collect_unclassified(groups)
        if not apps_to_classify:
            print("Žádné nezařazené aplikace k roztřídění.")
            return
        allowed_group_names = list(working_groups.keys())
        allow_new = True
        print(f"{len(apps_to_classify)} nezařazených aplikací, ptám se Ollamy ({ollama_model})...")

    app_items = list(apps_to_classify.items())
    accepted_count = 0
    quit_requested = False

    try:
        for batch in chunked(app_items, BATCH_SIZE):
            contexts = [build_app_context(name, path) for name, path in batch]
            result = classify_batch_with_retry(ollama_url, ollama_model, contexts, allowed_group_names, allow_new)
            if result is None:
                names = ", ".join(n for n, _ in batch)
                print(f"⚠ Dávka přeskočena (Ollama nevrátila platnou odpověď ani po {MAX_RETRIES} opakováních): {names}")
                continue

            for name, _path in batch:
                suggestion = result.get(name)
                if suggestion is None:
                    print(f"⚠ {name} — bez návrhu, přeskakuji")
                    continue
                group_name = suggestion["group"]
                is_new = suggestion["new_group"]
                label = f"{group_name}{' (NOVÁ skupina)' if is_new else ''}"

                while True:
                    choice = input(f"{name} → {label}  [y/n/e/q]: ").strip().lower()
                    if choice in ("y", "n", "e", "q"):
                        break
                    print("Zadej y, n, e nebo q.")

                if choice == "q":
                    quit_requested = True
                    break
                if choice == "n":
                    continue
                if choice == "e":
                    manual = input("Název skupiny: ").strip()
                    if not manual:
                        continue
                    target_group = manual
                else:
                    target_group = group_name

                working_groups.setdefault(target_group, {"apps": []})
                working_groups[target_group].setdefault("apps", [])
                if name not in working_groups[target_group]["apps"]:
                    working_groups[target_group]["apps"].append(name)
                    accepted_count += 1
                if target_group not in allowed_group_names:
                    allowed_group_names.append(target_group)

            if quit_requested:
                break
    except KeyboardInterrupt:
        print("\nPřerušeno uživatelem, ukládám dosavadní výběr...")

    config["groups"] = working_groups
    config["settings"] = settings
    save_config(config)
    print(f"Uloženo do {CONFIG_PATH.name}: přijato {accepted_count} přiřazení.")


def cmd_restore(args: argparse.Namespace) -> None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUPS_DIR.glob("dock-*.plist"))

    if args.list:
        if not backups:
            print("Žádné zálohy nenalezeny.")
        else:
            for b in backups:
                print(b.name)
        return

    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = BACKUPS_DIR / target.name
    else:
        if not backups:
            print("Žádné zálohy k obnovení.")
            sys.exit(1)
        target = backups[-1]

    if not target.exists():
        print(f"⚠ Záloha nenalezena: {target}")
        sys.exit(1)

    subprocess.run(["defaults", "import", "com.apple.dock", str(target)], check=True)
    subprocess.run(["killall", "Dock"])
    print(f"Obnoveno ze zálohy: {target.name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dockgroups",
        description="Organizace macOS Docku do tematických skupin.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Přehled skupin a nezařazených aplikací").set_defaults(func=cmd_status)
    subparsers.add_parser("apply", help="Přestaví složky a Dock podle groups.yaml").set_defaults(func=cmd_apply)
    subparsers.add_parser("suggest", help="AI návrh třídění přes Ollamu").set_defaults(func=cmd_suggest)

    restore_parser = subparsers.add_parser("restore", help="Obnova zálohy Dock plistu")
    restore_parser.add_argument("file", nargs="?", help="Konkrétní soubor zálohy k obnovení")
    restore_parser.add_argument("--list", action="store_true", help="Vypíše dostupné zálohy")
    restore_parser.set_defaults(func=cmd_restore)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
