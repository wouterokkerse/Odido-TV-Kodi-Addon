# Provider and playback references

Checked on 2026-10-17 through connected GitHub tools. No user credentials were
included in tools, source, tests or archives during this playback update.

## Playback fix requested by the user

Primary reference: [wouterokkerse/dut-iptv](https://github.com/wouterokkerse/dut-iptv).
Inspected its AGENTS.md work summary and these source files:

* [service.dutiptv.proxy/service.py](https://github.com/wouterokkerse/dut-iptv/blob/master/service.dutiptv.proxy/service.py):
  dynamic redirected media base, browser-style MPD routing parameters, streamed
  media responses, threaded HTTP server, licence forwarding without localhost
  Host, DRM structure preservation and missing-default-KID metadata correction.
* [service proxy constants](https://github.com/wouterokkerse/dut-iptv/blob/master/service.dutiptv.proxy/resources/lib/constants.py):
  Odido Origin/Referer and browser-style request headers.
* [T-Mobile/Odido api.py](https://github.com/wouterokkerse/dut-iptv/blob/master/plugin.video.tmobile/resources/lib/api.py):
  Authenticate, heartbeat, QueryPlaybill and PlayChannel contracts; the live
  branch queries the current playbill and sends CUTV plus its ID to PlayChannel;
  PlayChannel's playURL and authorizeResult.triggers.
* [T-Mobile/Odido util.py](https://github.com/wouterokkerse/dut-iptv/blob/master/plugin.video.tmobile/resources/lib/util.py):
  manifest, segment and licence header separation; licence custom data.

The new standalone relay implements these behaviors without the fork's raw URL,
account-response, request-header or licence-data diagnostic dumps. It uses
stdlib urllib and a private ephemeral loopback port instead of requests and the
shared Dut-IPTV proxy. It preserves all DASH periods and representations.

The fork's AGENTS.md reports an lb.tvx -> rrs02y -> mag01/wh... redirect chain,
403 segment responses before the routing fix, and a phone working while one
Linux laptop still crashes in its Widevine CDM. Those are the reference author's
observations, not newly reproduced results in this environment. Follow its
instruction to fully restart Kodi after updating the service.

## Earlier provider references retained

* [Official Odido TV login guidance](https://www.odido.nl/service/producten/tv/gebruiken/inloggegevens-tv):
  TV customer number/PIN and where to find them.
* [dut-iptv historical T-Mobile API](https://github.com/dut-iptv/dut-iptv/blob/master/plugin.video.tmobile/resources/lib/api.py):
  original VSP client protocol.
* [iptv-org guide implementation for another VSP provider](https://github.com/iptv-org/epg/blob/master/sites/playtv.unifi.com.my/playtv.unifi.com.my.config.js):
  QueryAllChannel / channelDetails discovery hypothesis. This was the original speculative discovery method; replaced in 0.1.6
  by the reference plugin's explicit OTT mapping.

## Restored baseline and limitations

Version 0.1.4 uses the exact archived 0.1.1 source as its starting point. The
related-Magenta GetDeviceList/ReplaceDevice experiment and registration-response
shape diagnostics from 0.1.2/0.1.3 are removed. Local sessions are retained by
keeping the addon ID and profile format. The user reports login now works after
manually freeing device slots.

Automated tests use synthetic API/CDN responses. The workspace's outbound proxy
is unavailable and loopback sockets are prohibited, so full HTTP socket/Kodi/
Widevine playback has not been exercised here. The module-level media routing,
HTTP handler behavior and protocol/header boundaries are tested in memory.

## 0.1.5 follow-up

The user's next screenshot reported API_146020013 before media relay startup.
Reinspection of the reference api.py live-channel branch showed CUTV with a
current playbillID, whereas 0.1.4 sent BTV without a playbill. Version 0.1.5
corrects this specific request difference and adds safe API-stage suffixes.
The reference's extra QueryPlaybill call supplies display metadata only; this
addon already has current-programme metadata and does not need that extra call.
No numeric-code definition was found or assumed. Provider channel/media discovery
still requires real-device validation. The updated suite has 73 synthetic tests.

## 0.1.6 channel and media source correction

Re-read plugin.video.tmobile/resources/lib/base/l5/api.py::api_get_channels and
base/l1/constants.py in wouterokkerse/dut-iptv. Together these load
https://dut-epg.github.io/tmobile/channels.json; api_play_url uses each entry's
key/id as channelID and assetid as mediaID. QueryAllChannel was an unverified
cross-provider assumption in this addon, not the reference's discovery method.
Version 0.1.5 had left that difference unresolved.

Fetched the same catalogue through its backing public GitHub file:
https://github.com/dut-epg/dut-epg.github.io/blob/master/tmobile/channels.json
A bundled snapshot retains only id, assetid, name and channelno for 266 entries;
no icon/media URLs or account information are bundled. The addon refreshes from
the reference HTTPS URL at most daily and validates the mapping before use.
Attribution: dut-epg / Dut-IPTV public channel catalogue.

NPO 1's pair is 141430714 / 141430715, while RTL 8's pair is
141430473 / 186566279 (not channelID + 1). Regression tests assert both and
exercise the full simulated NPO 1 catalogue -> current programme -> PlayChannel
path without QueryAllChannel. The guide and stream functions share the same
channel source. Actual Odido response/error meaning and current validity of the
public catalogue's entries remain unverified in this environment.

## 0.1.7 replay follow-up

The user confirmed live streaming in 0.1.6, then reported TypeError when opening
the replay guide. No original traceback was available. Re-read the reference
base/l5/api.py functions _tmobile_query_playbill_list and
api_get_epg_by_date_channel: count 300, single channel, Amsterdam midnight through
23:59:59 converted to UTC epoch milliseconds. This update matches that request
while retaining pagination if an entire page is returned. Live current-programme
lookup remains count 1 and the working stream/relay contracts are retained.

The original addon instead used count 100 and the host's local timezone.
Potential local TypeError paths in nullable programme fields and lazy date parsing
are addressed, without claiming a verified root cause. New safe source-location
codes will identify any remaining exception without dumping request/account data.
Timezone fallback implements EU rules since 1996 for recent TV-guide dates.
94 automated synthetic tests pass; replay provider/device validation is pending.

## 0.1.8 live-menu programme lookup

The user confirmed replay works after 0.1.7, but the Live TV menu still reports
unavailable current-programme information. Its prior request contained all 266
channel IDs; stream startup uses a successful single-channel request. The new
menu helper uses groups of 20, with single-channel fallback on provider API
rejection. Twenty is a conservative implementation choice, not a documented
Odido limit. The fallback reuses the same QueryPlaybillListStcProps contract as
the reference's api_get_info/live branch and this addon's working stream startup.
Partial successes are retained. No API error definitions or provider limits are
assumed. 102 synthetic tests pass. The subscriber subsequently confirmed that the live
menu works with 0.1.8; no independent service validation was performed here.

## 0.2.0 IPTV Manager integration

Read add-ons/service.iptv.manager at master commit
382c90d40d84988b883083ca117d35e4ac34e8f7:

* resources/lib/modules/addon.py: discovery settings iptv.enabled,
  iptv.channels_uri and iptv.epg_uri; plugin URI invocation with a loopback TCP
  port; connect within 10 seconds, then read JSON until connection close.
* tests/home/addons/plugin.video.example/plugin.py and resources/settings.xml:
  JSON-STREAMS / JSON-EPG version 1 payload fields and ISO programme timestamps.
* resources/lib/modules/iptvsimple.py: channel ID/number/logo mapping, playlist
  catchup=vod and per-programme XMLTV catchup-id links on Kodi 19+.
* resources/lib/functions.py: refresh and setup-iptv-simple script actions.

Implementation uses original standalone stdlib code and an optional dependency;
no IPTV Manager implementation is bundled. Setup uses Manager's supported script
entry point instead of directly modifying PVR settings. Kodi 21 multi-instance
configuration may require selecting the instance manually, documented in README.

Extended the same dut-epg catalogue snapshot with its public icon/replay fields.
No channel/media IDs changed. Exported stream and catchup URLs contain public
content IDs and route back to the existing login/Widevine/relay playback flow.

Validation: 122 synthetic unit tests. Additionally executed the upstream
IptvSimple class's actual write_playlist/write_epg methods in an isolated
scratch harness, using installed dateutil and a minimal Kodi-utils double.
The resulting M3U/XMLTV parsed successfully with matching odido.* channel IDs,
Unicode labels and a plugin URL in XMLTV catchup-id. Upstream source was used
only in the development scratch directory, not bundled or published. This is a
writer-level contract check, not a full Manager socket or Kodi PVR playback test.

## 0.2.1 import diagnostics and refresh preflight

The user reports Manager appears to sync with Odido, but IPTV Simple's migrated
configuration is empty/incomplete; exact active-instance paths were not provided.
Inspected Kodi Omega's AddonSettings.cpp: legacy settings without type are valid
hidden strings, so missing type was not treated as a verified defect. Inspected
AddonBuiltins.cpp, filesystem/PluginDirectory.cpp and generic/ScriptRunner.cpp:
RunPlugin uses [base URL, -1, options, resume], matching this addon's routing.

Inspected kodi-pvr/pvr.iptvsimple Omega resources/settings.xml (legacy settings
hidden for migration), resources/instance-settings.xml and
src/iptvsimple/utilities/SettingsMigration.cpp. The migration is skipped when
kodi_addon_instance_name is already populated; ongoing playback reads instance
settings. This supports checking the migrated instance's local playlist/XMLTV
paths, but does not establish the paths configured on the user's device.

The new refresh preflight persists iptv.enabled and callback URIs before starting
Manager; the diagnostic screen separates callback receipt, generation/send,
Manager file creation and dependency enabled states. No PVR settings are rewritten.
127 tests pass. Full Kodi PVR instance/socket validation still requires the device.

## 0.2.2 native IPTV Simple configuration

The subscriber confirms both Manager callbacks now show SENT, while IPTV Simple
still does not use the generated files by default. The setup now configures a
native instance directly rather than asking Manager's older setup script to
write legacy global settings and copy them over instance XML files.

Verified against Kodi Omega:
* xbmc/addons/addoninfo/AddonInfo.cpp::GetKnownInstanceIds scans
  instance-settings-N.xml under the PVR addon profile and uses positive IDs.
* xbmc/addons/Addon.cpp defines the corresponding per-instance settings path.
* xbmc/addons/IAddon.h names kodi_addon_instance_name and
  kodi_addon_instance_enabled; zero is reserved for global settings.
* kodi-pvr/pvr.iptvsimple Omega resources/instance-settings.xml and
  src/iptvsimple/InstanceSettings.cpp define local path type 0, m3uPath/epgPath,
  catchup fields and UTC timeshift. SettingsMigration.cpp confirms old global
  values are migration-only once an instance has a name.

The original standalone pvr.py module creates/reuses only a dedicated or existing
Manager instance, preserves other providers, writes atomic XML and backs up a
repaired instance once. It reserves the implicit ID 1 and prevents hiding an
unrelated legacy provider without instance files. Manager's existing restart
logic or a user Kodi restart loads the configuration; no direct stop/restart is
issued while configuring the instance. No Kodi/PVR implementation is bundled.

139 synthetic tests pass. New tests use real temporary XML files and assert
byte-for-byte preservation of unrelated native/global settings, no duplicates,
existing Manager repair, backup retention, default-flag removal, ID handling and
that the plugin saves native paths before refreshing. The native Kodi addon has
not been run here; actual activation remains a device validation step.
