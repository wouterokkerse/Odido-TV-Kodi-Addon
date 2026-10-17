# Odido TV for Kodi — 0.2.1 Kodi TV integration

A standalone, unofficial Odido TV addon targeting **Kodi 21.2**.

Live TV, replay, channel search and local saved lists for Odido TV subscribers.
A subscriber has confirmed live playback, replay and current-programme labels
working in version **0.1.8**. Compatibility with other devices and subscription
packages may vary. This project is not affiliated with Odido.

The addon uses a stable device identity and configurable device name. Manage
registered devices through Odido's official service when your device limit is
reached. Updating the addon retains the existing device ID, session and lists.

Playback handling follows the public protocol and redirect behavior documented
in [wouterokkerse/dut-iptv](https://github.com/wouterokkerse/dut-iptv).
All **127 automated tests** pass using synthetic API/CDN responses and Kodi
doubles. The development environment could not run full Kodi/Widevine playback;
the subscriber's device testing supplies the live-service confirmation.

Download the installable addon:
[plugin.video.odidotv-0.2.1.zip](downloads/plugin.video.odidotv-0.2.1.zip).
The unpacked Python source is in [plugin.video.odidotv](plugin.video.odidotv),
with tests and reproducible packaging scripts alongside it. Version 0.2.0 adds
optional IPTV Manager integration; native Kodi TV operation needs device testing.

## Install / update

1. Install `plugin.video.odidotv-0.2.1.zip` through **Add-ons → Install from zip
   file**, over the existing addon. Keep its addon data.
2. **Fully quit Kodi and start it again.** The updated playback service must be
   restarted; reopening only the addon leaves the old service running.
3. Open **Odido TV (unofficial)**. Your saved login should remain available.
4. Test NPO 1, then a subscribed protected channel such as RTL 4. Stop playback
   and switch channels; also test a replay available in the official service.

For a fresh install, enable **Settings → System → Add-ons → Unknown sources**
first. Kodi installs InputStream Adaptive and InputStream Helper from its official
repository. Enable InputStream Adaptive under **VideoPlayer InputStream** if needed.
Protected playback may prompt InputStream Helper to install Widevine.

Sign in using your **TV customer number and TV PIN**, found in Mijn Odido or the
Odido app. The PIN is not your Mijn Odido password. Official guidance:
[Odido TV login details](https://www.odido.nl/service/producten/tv/gebruiken/inloggegevens-tv).
The addon does not save the PIN or customer number. It saves scoped cookies and
the CSRF session token in its Kodi profile. Sign-out clears that local session;
it does not unregister the device on Odido's servers.

**Device name** remains configurable, defaulting to Kodi Odido TV. The login
request sends it as `authenticateDevice.deviceName`. Changing the name does not
change the physical device ID. Current Odido acceptance of the label field is
still unverified.

## Kodi TV, IPTV Simple and IPTV Manager

Version 0.2.0 exports channels and EPG through
[IPTV Manager](https://github.com/add-ons/service.iptv.manager). IPTV Manager
writes the M3U playlist/XMLTV guide consumed by IPTV Simple. The addon exports
stable channel IDs, channel numbers, catalogue logos and **plugin playback
links**. Signed manifest URLs, Odido cookies, PINs, CSRF and licence data are not
exported. A missing catalogue logo uses the addon icon.

1. Install this update and fully restart Kodi. Open Odido TV and confirm you are
   signed in and can play a channel.
2. Open **Odido TV → Settings → Kodi TV / IPTV Manager**. Install a Kodi 21
   compatible **IPTV Manager** from Kodi's repository if it is not installed.
3. Enable **Enable Kodi TV integration** and save the settings. It is off by
   default, so installing this update alone does not reconfigure Kodi TV.
4. Use **Choose Kodi TV channels** to select the channels in your subscription.
   All catalogue channels are selected initially. A smaller selection speeds up
   the first guide import. Cancelling the picker preserves the selection;
   selecting none exports none. **Use all Kodi TV channels** resets it.
5. Choose **Configure IPTV Simple with IPTV Manager**. IPTV Manager asks before
   applying its IPTV Simple configuration. Existing playlist/guide settings can
   be replaced, so retain your current settings if you use another IPTV source.
6. Choose **Enable and refresh channels and guide now**. The first import can take several
   minutes. IPTV Manager manages future refreshes in its own settings.
7. Open Kodi's **TV → Channels / Guide**. If channels do not appear immediately,
   verify IPTV Simple is enabled and restart Kodi after the import completes.

On Kodi 21, IPTV Simple can have multiple instances. If the automatic setup does
not configure the active instance, open **IPTV Simple → Configure → Add/Manage
addon configuration**, select the intended instance and set its local playlist to
`special://profile/addon_data/service.iptv.manager/playlist.m3u8` and XMLTV guide to
`special://profile/addon_data/service.iptv.manager/epg.xml`. Enable catchup in that
instance for replay links. Keep IPTV Manager's guide timeshift at zero: exported
programme times include UTC offsets. Configuration labels vary with IPTV Simple
version. The addon does not directly write IPTV Simple instance files.

The EPG contains **seven calendar days including today, plus tomorrow** by
default. Choose 1, 3 or 7 replay-guide days in Odido settings. For programmes
already broadcast, replay-capable channels include an XMLTV catchup link back to
the existing replay playback route. Future programmes appear in the guide without
a playback link. Odido still decides replay availability, subscription rights,
parental access and concurrent stream limits when playback starts.

Channel selection applies to Kodi TV exports only. The catalogue is not an
entitlement list: selecting a channel does not subscribe to it. Unsupported or
retired catalogue entries may have no EPG or fail at playback. Native recording,
server-side timers and timeshift controls are not added by this integration.

Guide refreshes use groups of at most 20 channels and individual fallback for a
provider-rejected group. Today's guide is cached for 15 minutes, tomorrow for an
hour and past days for a day; old files outside the configured window are pruned.
A failed channel retains its previously cached schedule when available. Refresh
stops further provider requests on network failure, retains cached data and
records the safe error code. Expired/auth-refused sessions require signing in
through the addon; background refresh never opens credential prompts.

IPTV Manager's callback connection opens **before** loading the catalogue/guide,
meeting its initial connection timeout. Versioned JSON is sent with a complete
write and ASCII escapes for Unicode titles, matching the manager's chunk decoder.
The callback destination is always loopback. No playback relay ports or credentials
are embedded in the exported links. Native TV playback uses the same Widevine and
local media relay as the working addon, with a fresh playback URL per tune.

If importing fails, use **Export diagnostics** in Odido TV and inspect
`last_iptv_error`. `LOGIN_REQUIRED` means sign in inside Odido first;
`IPTV_INVALID_SELECTION` means reset/select channels again. Other provider errors
retain their safe stage code. No raw responses or exception messages are logged.

All 127 unit tests pass. A separate compatibility check ran these payloads through
IPTV Manager's actual M3U/XMLTV writers and verified matching channel IDs and replay
catchup links. Full socket-based callback delivery and Kodi PVR/Widevine playback
could not be run in this workspace; they require testing on your Kodi device.

## Diagnosing an empty Kodi TV import

Version 0.2.1's **Enable and refresh channels and guide now** explicitly saves
Odido's enabled state and channel/EPG discovery URIs before starting Manager.
The addon must be signed in and IPTV Manager must be enabled. This avoids
starting a scan with an unsaved enable toggle or missing discovery settings.
It does not change your IPTV Simple instance settings.

After refreshing, open **Odido settings → Kodi TV / IPTV Manager → Check Kodi TV
integration**. The status dialog shows the integration and dependency enabled
states, channel/guide export phase and count, and whether IPTV Manager's
playlist.m3u8 and epg.xml files exist. Export phases are persistent across Kodi
restarts and contain no credentials or playback URLs:

* NOT_CALLED: no callback has reached this addon since installing this update.
  Run the new enable-and-refresh action and check that Manager is enabled.
* STARTED: callback reached the addon; export has not completed yet.
* READY: payload generated but not yet confirmed sent to Manager.
* SENT with a positive count: payload was sent to Manager. It does not prove
  that Manager finished writing its files or that IPTV Simple selected them.
* SENT with zero entries: check channel selection and provider guide availability.
* DISABLED / ERROR: enable integration or report the safe error code shown.

If both Manager files exist but Kodi TV is empty, check the active IPTV Simple
instance (often **Migrated Add-on Config**) rather than its legacy global
settings. Kodi 21 IPTV Simple reads instance-specific paths. Set playlist and EPG
locations to **Local path**, using the two Manager paths in the setup section,
and ensure that instance is enabled. Do not enter local paths in the remote URL
fields. Reopen Kodi TV after restarting Kodi. These checks are diagnostic;
the precise cause on the reporting device has not yet been confirmed.

**Export diagnostics** also displays the last IPTV error directly in the dialog.
The generated JSON retains that error without account/provider response dumps.

## Live programme changes in 0.1.8

The Live TV menu previously sent all 266 catalogue channel IDs in one
current-programme request, while stream startup queried only the selected
channel. The menu now queries groups of at most 20 channels. A provider rejection
of a group triggers individual lookups using the same single-channel request
already working at stream startup.

A failed channel no longer discards successful programme labels for others.
If individual retries succeed, no warning is shown. Genuine residual failures
remain visible and retain their bounded API code in diagnostics. Network/schema
failures stop further retries; authentication failures are propagated. This is
not a verified definition of Odido's batch limit: the exact cause of the original
menu rejection remains unconfirmed without its provider error code.

Live stream startup, replay requests and the media relay retain their working
contracts. Fully restart Kodi after updating and reopen Live TV.

## Replay changes in 0.1.7

Replay requests now match the reference's 300-programme page size and Amsterdam
00:00:00 through 23:59:59 day boundaries, regardless of Kodi's system timezone.
The day picker and programme labels use Amsterdam time too. Daylight-saving
changes produce 23- or 25-hour requests. A small EU-rule fallback supports Kodi
builds without a timezone database; no extra dependency is required.

Date parsing no longer uses datetime.strptime's lazy _strptime import. Programme
normalization accepts null picture, poster, plot and time fields without raising
TypeError or passing a null plot into Kodi's typed metadata API. These are
corrected error paths; the precise origin of the user's TypeError has not been
verified because its original stack trace was unavailable.

Unexpected addon errors now show a safe source-location code, such as
TypeError_PLUGIN_L123, with an internal-error message instead of a subscription
message. This contains only the exception type, source basename and line number.
Replay errors and empty responses are recorded in last_guide_error in exported
diagnostics. No raw response, exception message, credentials or URLs are included.

Install over the existing addon and fully restart Kodi. Open **Replay / TV guide
→ NPO 1 → Today**, then try yesterday. Keep the saved addon data and login.

## Playback behavior retained from 0.1.6

Version 0.1.6 replaces the unverified QueryAllChannel discovery with the same
OTT catalogue used by the reference addon:
[public T-Mobile channel catalogue](https://dut-epg.github.io/tmobile/channels.json).
Its explicit `id`/`assetid` pairs supply the guide channel ID and playback media
ID. No media ID is inferred by adding one or taking the first provider variant.
For example, NPO 1 uses channel 141430714 / media 141430715; RTL 8 uses channel
141430473 / media 186566279. The bundled snapshot contains 266 entries, sorted
by channel number, rather than the previous 556-entry discovery list.

The catalogue refreshes once daily with a separate HTTPS request that sends no
Odido session headers or cookies. A validated cached copy, or the bundled copy
on first installation, remains usable when the feed is unavailable. The feed
may contain older names or retired channels; these pairs are the same source
used by the reference and have not been newly verified against Odido here.

The retained live request uses `CUTV` and the current playbill ID, matching the
reference. The previous 0.1.5 change addressed only that request, leaving the
channel/media discovery mismatch unresolved. The reported 146020013 numeric
error's precise meaning remains unknown.

Open **Live TV** again after upgrading so Kodi loads the new IDs. Re-add old
channel bookmarks if they still point to identifiers from the previous discovery
list. Your device identity and login are retained.

Guide notifications now show the bounded API error code as well as the generic
programme-information message. Export diagnostics also records `last_guide_error`.
Provider errors include fixed operation suffixes such as `_PLAYCHANNEL`, `_GUIDE`
and `_PROGRAMME`, without account data or raw provider response messages.

The fork documents a redirect chain from the `lb.tvx…` manifest URL to a final
media server and `/wh…` path. Its working fix retains that final redirected base
for `PLTV`/`TVOD` segment requests. Sending the load-balancer URL straight to Kodi
can leave segment requests using the wrong host/path.

This addon now includes its own relay inside the existing background service:

* Each playback gets an independent media context and random local route.
* The relay follows HTTPS redirects and discovers the final media prefix.
* DASH BaseURLs, initialization URLs and segment templates use that final base.
  Routing keeps template variables visible and preserves existing signed query
  bytes. Optional browser routing parameters are added only when present in the
  upstream manifest and absent from the original URL.
* The local server is threaded. Segment responses are forwarded in 64 KiB chunks,
  with byte ranges preserved, so media downloads do not serialize channel changes.
* Binary Widevine challenges/responses pass through a separate licence route.
  Odido CSRF/cookies/custom-data headers go to the appropriate upstream request;
  a localhost Host header is never forwarded to the licence server.
* DRM metadata/PSSH, periods, representations and timelines are retained.
  Malformed CENC/Dolby metadata is normalized as in the fork. A missing default
  KID can be copied from the public PlayReady header; media still requires a
  legitimate Widevine licence. No decryption keys are obtained by the addon.
* A manifest refresh can discover a new media server while outstanding requests
  from a previous context retain their original base.

The relay binds only to **127.0.0.1**, uses an operating-system-selected port and
requires a random secret route. It does not conflict with the fork's port 11189.
Upstream requests keep TLS verification enabled. Signed URLs and licence data
are kept in memory and are not dumped to disk.

## Features retained from 0.1.1

* Live TV with current programme labels when available.
* Seven-day guide/replay navigation; Odido decides replay access at playback time.
* Case-insensitive channel-name search.
* Local My list / Watch later bookmarks.
* Dutch and English interface.
* Playback heartbeat, attempted every 60 seconds during this addon's video.

Film/series catalogue browsing, recordings, purchases, cloud lists, profiles,
Trakt and library export are not implemented. Optional native TV integration is
provided through IPTV Manager; native recordings/timers are not implemented. Kodi 22 is outside
the declared target. Subscription, location, concurrent-stream, parental and device
restrictions still apply. The guide uses Amsterdam time and calendar days.

## If playback still fails

Choose **Export diagnostics** after trying a channel. The dialog shows the last
relay error code and the location of `diagnostics.json` under
`special://profile/addon_data/plugin.video.odidotv/`.

| Code | Meaning / next check |
| --- | --- |
| `RELAY_NOT_AVAILABLE` | Fully restart Kodi; check that the addon service is enabled |
| `MANIFEST_HTTP_…` | Upstream manifest request failed; report the numeric status |
| `SEGMENT_HTTP_…` | Upstream initialization/media request failed |
| `LICENSE_HTTP_…` | Upstream licence request was refused or failed |
| `INVALID_MANIFEST_XML` | Manifest was not a supported MPD response |
| `SEGMENT_READ_ERROR` / `LICENSE_READ_ERROR` | Upstream response was interrupted |
| `NETWORK_ERROR` | Provider API request could not complete |
| `API_…_PLAYCHANNEL` | Odido rejected the playback request; report the full code |
| `API_…_GUIDE` | Odido rejected the current-programme/guide lookup |
| `NO_CURRENT_PROGRAMME` | No current programme was returned for this channel |
| `CHANNEL_CATALOG_UNAVAILABLE` | No valid cached or bundled channel catalogue was available |
| `DEVICE_LIMIT` | Free a device slot through the official Odido service |

Report the channel, live/replay action, operating system, Kodi/InputStream Adaptive
versions and the error code. You can share `diagnostics.json`; it contains versions,
local session status and bounded playback/guide error codes. Do not share cookies.txt,
session.json, PINs, signed URLs or raw licence payloads. Kodi/InputStream's own
debug logs can contain signed URLs independently of this addon.

The reference fork notes working playback on a phone and a remaining native
Widevine `SIGILL` crash on one Linux laptop. If a protected channel crashes Kodi,
that is a distinct device/CDM compatibility question. A clear-channel test followed
by a protected-channel test helps separate CDN routing from licence/CDM issues.
This port does not establish that all Widevine platforms will work.

## Development

```sh
python -m unittest discover -s tests -v
python scripts/localize.py
python scripts/build.py
```

No pip dependencies are needed. Kodi provides its own API modules and the two
declared playback dependencies. Tests cover the v0.1.1 login/session behavior,
redirected media bases, DASH templates and ranges, DRM metadata, binary licence
forwarding, per-channel isolation and interrupted segment responses. HTTP handler
methods are exercised in memory because this workspace prohibits local sockets.

The build validates source syntax, XML, translation IDs and package structure,
then writes the installable ZIP and SHA-256 checksum to `dist/`.
See [SOURCES.md](SOURCES.md) for reference details. GPL-3.0-or-later; not affiliated
with or endorsed by Odido.
