"""Build Kodi translation catalogs from this project's English/Dutch strings."""
import json
from pathlib import Path

STRINGS = {
30052: ('The addon encountered an internal error. Please report the full code below.', 'Er is een interne fout in de add-on opgetreden. Meld de volledige code hieronder.'),
30001: ('Live TV', 'Live tv'),
30002: ('Replay / TV guide', 'Terugkijken / tv-gids'),
30005: ('Search channels', 'Zenders zoeken'),
30006: ('My list (this device)', 'Mijn lijst (dit apparaat)'),
30007: ('Watch later (this device)', 'Kijk later (dit apparaat)'),
30008: ('Sign in', 'Inloggen'),
30009: ('Sign out', 'Uitloggen'),
30010: ('Settings', 'Instellingen'),
30011: ('Export diagnostics', 'Diagnostiek opslaan'),
30012: ('No items found.', 'Geen items gevonden.'),
30015: ('Odido TV customer number', 'Klantnummer Odido TV'),
30016: ('Odido TV PIN', 'Pincode Odido TV'),
30017: ('Signed in.', 'Ingelogd.'),
30018: ('Sign in with your TV customer number and TV PIN from Mijn Odido.', 'Log in met je TV-klantnummer en TV-pincode uit Mijn Odido.'),
30020: ('Odido TV could not complete this request. Check your connection and subscription. This experimental build still needs subscriber testing.', 'Odido TV kon dit verzoek niet uitvoeren. Controleer je verbinding en abonnement. Deze experimentele versie moet nog met een abonnement worden getest.'),
30021: ('Add to My list', 'Toevoegen aan Mijn lijst'),
30022: ('Add to Watch later', 'Toevoegen aan Kijk later'),
30023: ('Remove from this list', 'Verwijderen uit deze lijst'),
30024: ('List updated.', 'Lijst bijgewerkt.'),
30025: ('Today', 'Vandaag'),
30026: ('Widevine or InputStream Adaptive is unavailable on this device.', 'Widevine of InputStream Adaptive is niet beschikbaar op dit apparaat.'),
30027: ('Your session expired or access was refused. Sign in again and check your TV subscription.', 'Je sessie is verlopen of toegang is geweigerd. Log opnieuw in en controleer je TV-abonnement.'),
30028: ('Session removed from this device.', 'Sessie verwijderd van dit apparaat.'),
30030: ('Diagnostics saved (no credentials or playback URLs):', 'Diagnostiek opgeslagen (zonder inloggegevens of afspeel-URL’s):'),
30032: ('Not yet broadcast', 'Nog niet uitgezonden'),
30035: ('Current programme information is unavailable.', 'Informatie over het huidige programma is niet beschikbaar.'),
30040: ('About this addon', 'Over deze addon'),
30045: ('Experimental — Kodi 21.2; PIN is not saved', 'Experimenteel — Kodi 21.2; pincode wordt niet opgeslagen'),
30046: ('Use your TV customer number and PIN, not your Mijn Odido password', 'Gebruik je TV-klantnummer en pincode, niet je Mijn Odido-wachtwoord'),
30047: ('Device name', 'Apparaatnaam'),
30048: ('Device name is sent at the next sign-in', 'Apparaatnaam wordt bij de volgende login meegestuurd'),
30049: ('Odido refused registration because of its device limit. Manage your registered devices in the official Odido service, then retry. Naming this device does not free a slot; this addon keeps the same device ID.', 'Odido heeft registratie geweigerd vanwege de apparaatlimiet. Beheer je geregistreerde apparaten via de officiële Odido-dienst en probeer opnieuw. Een apparaatnaam maakt geen plek vrij; deze addon behoudt hetzelfde apparaat-ID.'),
30050: ('Restart Kodi completely to start the updated playback service, then try the channel again.', 'Sluit Kodi volledig af en start opnieuw om de bijgewerkte afspeeldienst te starten. Probeer de zender daarna opnieuw.'),
30051: ('Last playback error', 'Laatste afspeelfout'),
}

root = Path(__file__).resolve().parents[1] / 'plugin.video.odidotv/resources/language'
for index, language in enumerate(('en_gb', 'nl_nl')):
    target = root / ('resource.language.' + language) / 'strings.po'
    target.parent.mkdir(parents=True, exist_ok=True)
    blocks = ['msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n']
    for number, texts in STRINGS.items():
        blocks.append('msgctxt "#%s"\nmsgid %s\nmsgstr %s\n' % (
            number, json.dumps(texts[0], ensure_ascii=False),
            json.dumps(texts[index] if index else '', ensure_ascii=False)))
    target.write_text('\n'.join(blocks), encoding='utf-8')
