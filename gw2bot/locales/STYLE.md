# Translating GW2Bot

`de.json`, `fr.json` and `es.json` map the bot's English text to its translation. An empty translation means the text isn't translated yet; the bot shows the English. `scripts/i18n_extract.py` adds new text and removes old text, and `tests/test_i18n.py` checks the catalogs.

## Game terms

Players should see the names their game client uses. Before translating text that names something from the game, look it up:

1. **`glossary.json`**: official names from the GW2 API (`?lang=de` etc.) and the language wikis' interlanguage links. Rebuild it with `scripts/i18n_glossary.py`; add terms to `glossary_sources.json`.
2. **The API** for anything with an id: items, skills, traits, achievements, currencies, maps, professions.
3. **The language wikis** (wiki-de, wiki-fr, wiki-es.guildwars2.com) for everything else. Their interlanguage links are sometimes wrong, so check that the page is really about the same thing. Corrections go in `glossary_overrides.json`, with where they were checked.

Terms worth knowing:

| English | Deutsch | Français | Español |
|---|---|---|---|
| Guild | Gilde | Guilde | **Clan** |
| Profession | **Klasse** | Profession | Profesión |
| Achievement | Erfolg | Succès | Logro |
| Trading Post | Handelsposten | Comptoir | Bazar |
| Gem | Edelstein | Gemme | Gema |
| Wallet | Geldbörse | Portefeuille | Cartera |
| Raid | Schlachtzug | Raid | Incursión |
| Strike Mission | Angriffsmission | Mission d'attaque | Misión de ataque |
| PvP | PvP | JcJ | PvP |
| WvW | WvW | McM | McM |
| Chat link | Chatcode | Code en jeu | Código de chat |
| Build template | Build-Vorlage | Modèle d'archétype | Plantilla de ajustes |

Expansion names (Heart of Thorns, Path of Fire, End of Dragons, Secrets of the Obscure) are not translated. The Icebrood Saga is (Die Eisbrut-Saga, L'Épopée du givre, Sangre y Hielo).

Discord's own terms follow Discord's client: channel is Kanal / salon / canal, role is Rolle / rôle / rol, server is Server / serveur / servidor.

## Examples in descriptions

An example must be something the command accepts in that language.

- Items, skills, traits and achievements are searched by their localized name, so use the official name, e.g. *Beispiel: Meteorschauer*.
- Event names (`/reminder`) are accepted in English and in the user's language, so use the localized names (Schatten-Behemoth).
- `/wiki` searches the wiki in the user's language, so use the localized page name (Löwenstein, L'Arche du Lion, Arco del León).

## Tone and form of address

Match how the game speaks to the player (sampled from the API's achievement and currency texts):

- **Deutsch:** the game uses the plural "Ihr" ("Treibt ein Huhn zum Äußersten"). Address the user as Ihr/Euch/Euer, capitalized. Descriptions read like the game's UI: "Zeigt Eure Geldbörse an".
- **Français:** instructions are infinitives ("Tuer  centaures"); the user is "vous". Descriptions: "Affiche votre portefeuille".
- **Español:** the game uses "tú" ("Mata a  centauros"). Descriptions: "Muestra tu cartera".

## Mechanics

- Keep `{placeholders}` exactly as they are; their order may change.
- Command and option names (`api_key`, `user_to_prompt`, `channel`...) are not translated. When a description mentions one, keep it as is.
- Command descriptions, option descriptions and choices are at most 100 characters.

## Grammar the code handles

- **Casing within sentences.** Where English lowercases a game word inside a sentence ("A level 80 exotic greatsword", "A level 80 weaver"), the code lowercases it for French and Spanish and keeps it capitalized for German (nouns). The sentence's first letter is capitalized afterwards, so a translation may start with a placeholder: `{type} der Stufe {level} ({rarity})`.
- **Leaving out a placeholder.** A translation may drop a placeholder its grammar doesn't need, e.g. `{number}. Geburtstag` for `{number}{suffix} Birthday` (the English ordinal suffix). It may not add one the English text doesn't have.
- **Names that stay English.** API key permission scopes, Discord audit log reasons, WvW team names (the game doesn't translate them), the `/cats` and `/nodes` guides, and update notes (the forum is English only).
- **Names from the bundled game data.** Fractals, instabilities, event timers (world bosses, maps, meta event phases) and `/kp` encounters are in the catalogs, keyed by their English names, which the code still matches on. Use the game's names: for fractals the "Daily Tier 4" achievements (`/v2/achievements?lang=de`), for raid encounters and strikes the "Raid Bounty" achievements, for maps `/v2/maps`, and for the rest the wikis. Reminders are saved with the English event name; `/reminder event` also accepts the name in the user's language.
