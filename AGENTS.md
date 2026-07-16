# AGENTS.md

Instrukce pro nové Codex/chat session pracující v tomto workspace. Doplňuje `CLAUDE.md` (projektová pravidla) o obecné, znovupoužitelné zásady pro práci s gitem a GitHubem u projektů, které mají nebo budou mít veřejné repo.

## Git a GitHub — obecná pravidla pro tenhle typ projektu

### Než se repo poprvé zveřejní

1. **Zkontroluj, jestli v historii (ne jen v aktuálních souborech) není nic osobního/citlivého** — API klíče, tokeny, hesla, ale i "jen" osobní data jako vlastní seznam nainstalovaných aplikací, soukromé cesty, e-maily třetích stran. Stačí jeden `grep` napříč historií, ne jen `git status`.
2. **Osobní/lokální konfigurační soubory patří do `.gitignore` od začátku**, ne až dodatečně — pro tenhle projekt to byl `groups.yaml` (osobní seznam appek), nahrazený `groups.example.yaml` jako šablonou pro ostatní.
3. Pokud už osobní data v historii jsou (typicky proto, že `.gitignore` přišel pozdě), **nejde je jen smazat v novém commitu** — historie by je pořád obsahovala. Řešení: nová "orphan" větev (`git checkout --orphan`) bez jakékoli historie, do ní nahrát aktuální (už vyčištěný) stav souborů, jeden commit, a tuhle větev pushnout jako `main` na GitHub. Lokální vývojovou historii se všemi starými commity si ulož stranou jako čistě lokální archivní větev (`git branch main-archive main`) — nikdy ji nepushuj.
4. Po téhle jednorázové operaci srovnej lokální `main`, ať navazuje na to, co je na GitHubu (`git reset --hard <orphan-větev>` + `git branch --set-upstream-to=origin/main main`) — jinak se lokální a vzdálená historie natrvalo rozejdou a `git push` přestane fungovat napřímo.

### Po zveřejnění — běžný provoz

5. Jakmile je repo venku a citlivé soubory jsou v `.gitignore`, **žádné další skrývání historie není potřeba** — commituj normálně, i s menšími/rozpracovanými kroky. Skrývání historie je jednorázová věc na začátek, ne standardní pracovní styl.
6. **Verzuj přes git tagy + GitHub Releases**, ne přes ruční kopie souborů ani speciální větve pro každé vydání:
   - Lokálně se hromadí commity na `main` podle potřeby.
   - Když je hotová smysluplná dávka změn na zveřejnění: `git tag -a vX.Y.Z -m "..."`, `git push origin vX.Y.Z`, pak `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."`.
   - Číslování drž jednoduché semver (MAJOR.MINOR.PATCH) — nemusí být striktně dogmatické, hlavně ať je to čitelné a rostoucí.
7. **Výběr názvu veřejného repa:** než ho založíš, zkontroluj, že nekoliduje se jménem existujícího komerčního produktu nebo jiného projektu (i když je název pro tebe interně logický). U tohohle projektu to byl `dockgroups` → kolize s `dockgroups.com` a `DockStacks`, řešeno jako `dock-organizer`.

### Kontakt/autor a licence

8. Pokud repo dostává `LICENSE`, drž se stylu, který [DanielDocekal](https://github.com/DanielDocekal) používá napříč vlastními repy: MIT, `Copyright (c) <rok> Daniel Dočekal`.
9. README (pokud je to smysluplné vzhledem k publiku projektu) piš dvojjazyčně — `README.md` česky, `README.en.md` anglicky, s prokliky mezi sebou nahoře v obou souborech. Obě verze zakonči krátkou sekcí `## Autor` / `## Author` s odkazem na GitHub profil a blog.

### Co NEDĚLAT bez výslovného souhlasu

- Force push do sdílené/veřejné větve.
- Přepis historie větve, kterou už někdo jiný mohl stáhnout (fork, clone).
- Mazání větví (i lokálních archivních) bez potvrzení — `main-archive` styl větví nech ležet, dokud uživatel výslovně neřekne, že je může smazat.
