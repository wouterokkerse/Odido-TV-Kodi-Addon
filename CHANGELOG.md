# Changelog

## 0.2.6

* Request silent Kodi TV guide imports on startup when stale and hourly while
  Kodi runs, without opening the Odido add-on or starting playback.
* Reuse IPTV Manager's background service, preserve its interval and other
  source settings, and respect active imports and disabled integration.
* Renew saved login sessions before background guide requests.
* Retry failed exports after 15 minutes and add an automatic-refresh toggle.

## 0.2.5

* Remember the TV customer number and PIN locally after successful sign-in.
* Renew expired sessions once using saved credentials and the existing device ID.
* Sign-out removes saved credentials; network failures preserve them for retry.
* Keep credentials out of diagnostics and document local unencrypted storage.

## 0.2.4

* Address the actual native TV OSD start button, rather than only stream startup.
* Add an optional local Estuary copy whose control 600 seeks to 0% during native
  TV playback and retains Previous for movies and other playback.
* Prepare the skin from the device's installed Estuary using Kodi VFS; preserve
  stock files, all assets and original licences. Support cancellation, cleanup,
  repeat setup and refusal to overwrite unrelated destinations/skins.
* Add enable/restore actions in Playback settings. Skin selection uses Kodi's
  standard API and confirmation/rollback behavior; installing the addon alone
  does not change the active skin.
* No replay requests, stream restarts, DRM changes or retention-window edits.
* 163 tests pass, plus a patch check against actual Kodi 21 Estuary XML. Native
  skin activation and seeking require device testing.

## 0.2.3

* Add Watch live and Play from beginning of live buffer channel context actions.
* Add a default live-start setting, applying to addon and native Kodi TV tuning.
* Set InputStream Adaptive play_timeshift_buffer explicitly while keeping the
  same provider live request, Widevine licence and media relay.
* In-progress programme links now open that live stream's buffer rather than
  requesting a replay. Timed native guide links switch to replay after completion.
* Export timed future links so they become usable without another guide import;
  reject playback before broadcast and completed replay on non-replay channels.
* Preserve DASH timeline/buffer depth and explain that buffer start is limited
  to provider history, not guaranteed to be the programme's beginning.
* 151 tests pass; actual live seeking still needs device validation.

## 0.2.2

* User confirmed both exports are SENT; IPTV Simple still lacks its native paths.
* Configure an enabled Kodi 21 IPTV Simple instance with local Manager playlist
  and guide paths from both the setup and enable/refresh actions.
* Reuse existing Manager instances or create Odido TV (IPTV Manager), preserve
  other providers/global settings, back up repaired Manager files and avoid
  duplicates on repeated setup. Do not overwrite active remote sources merely
  because unused local fields happen to contain Manager paths.
* Stop invoking Manager's legacy setup/copy-all-instance-files routine. Enable
  IPTV Simple if disabled; Manager retains control of refresh/reload scheduling.
* Show the saved instance filename in a scrollable integration status viewer.
* 139 tests pass, including real XML files, preservation, defaults, backups,
  repeated setup, native paths and enabling a disabled PVR addon.
* Native Kodi instance activation still requires testing on the user's device.

## 0.2.1

* Add Check Kodi TV integration: enabled states, persistent channel/guide callback
  phases and counts, and Manager playlist/XMLTV file presence.
* Replace the direct Manager refresh button with Enable and refresh: validate
  login/Manager enabled state, persist Odido discovery settings, then run Manager.
* Display last IPTV export error in the diagnostics dialog.
* Explain Kodi 21's per-instance/Migrated Config local-path configuration. This
  update does not rewrite PVR instances or claim the reported cause is verified.
* 127 tests pass, including discovery-save ordering, callback status persistence,
  failed callback safety and output-file status reporting.

## 0.2.0

* Add optional IPTV Manager v1 channel/EPG exports for native Kodi TV through
  IPTV Simple. Integration is off by default and uses the existing Odido session.
* Export stable channel IDs, numbers, catalogue logos and plugin playback URLs.
* Add channel selection and setup/refresh controls in a Kodi TV settings category.
* Add seven-day EPG history (including today) and tomorrow; settings allow 1/3/7
  days. Replay-capable, already-broadcast programmes get native guide catchup links.
* Cache schedules per channel/day; use bounded batches and individual API fallback,
  preserve cached schedules on errors, prune old guide files and honor cancellation.
* Open callbacks before API work, use sendall and ASCII-escaped JSON for Manager's
  chunk decoder; never export session, signed MPD or licence credentials.
* Add safe IPTV error diagnostics and keep background exports non-interactive.
* Retain working live/replay/DRM relay contracts. No recording/timer support added.
* 122 tests pass plus a contract check against IPTV Manager's actual M3U/XMLTV
  writers. Native Kodi PVR integration still needs subscriber device testing.

## 0.1.8

* User confirmed replay now works; current-programme lookup in the Live TV menu
  still reports unavailable information.
* Replace the 266-channel menu query with groups of at most 20 IDs and fall back
  to single-channel lookups for provider-rejected groups.
* Preserve successful programme labels when another channel fails; show no
  warning when individual retries fully recover a rejected group.
* Stop retrying on network/schema failures and propagate authentication errors.
* Keep working single-channel stream startup, replay and relay contracts.
* 102 tests pass, including grouping, fallback, partial results, authentication,
  network failures and menu labels/warnings. A subscriber confirmed the update works.

## 0.1.7

* User confirmed live playback works in 0.1.6; replay browsing reports TypeError.
* Match reference replay query size (300) and Amsterdam day boundaries, including
  DST transitions, independently of Kodi's system timezone.
* Use Amsterdam dates in replay navigation and programme labels.
* Avoid lazy _strptime imports and normalize nullable programme metadata.
* Show safe source locations for unexpected exceptions; keep provider errors
  distinct from internal addon errors and record replay failures in diagnostics.
* 94 synthetic tests pass, including replay navigation, full-day requests, null
  fields, date parsing, both timezone paths and safe internal-error reporting.
* Precise original TypeError location and updated replay playback are unverified.

## 0.1.6

* Replace speculative QueryAllChannel/first-media selection with the reference
  plugin's explicit OTT id/assetid mapping from dut-epg.github.io/tmobile/channels.json.
* Use those same channel IDs for guide/current-programme lookups and playback.
* Refresh the public catalogue daily without Odido session credentials; fall back
  to a validated cache or bundled 266-entry snapshot when unavailable.
* Sort by channel number; reopen Live TV to discard Kodi's previous listing.
* Show the API code on guide failure and include it in exported diagnostics.
* 81 automated tests pass, including the actual reference NPO 1 and RTL 8 ID pairs
  and an end-to-end simulated catalogue/guide/PlayChannel request.
* Provider playback still needs validation on the user's device.

## 0.1.5

* Match the reference fork's live request: query the current playbill and send
  `businessType: CUTV` with `playbillID` to PlayChannel instead of BTV without it.
* Stop with NO_CURRENT_PROGRAMME when no programme is returned.
* Add fixed API-operation suffixes to provider errors for easier diagnosis.
* Retain 0.1.1 login/device identity and 0.1.4 relay behavior.
* 73 synthetic tests pass. Actual Odido/Kodi playback remains unverified; the
  meaning of the reported numeric code 146020013 is not established.

## 0.1.4

* Restore the 0.1.1 login/device-name baseline; remove device-replacement and
  registration-shape diagnostic additions from 0.1.2/0.1.3.
* Port the playback behavior documented in wouterokkerse/dut-iptv: final redirected
  media bases, retained /wh... prefixes, optional browser routing parameters,
  threaded media forwarding and binary licence proxying.
* Preserve DASH periods/tracks/PSSH and normalize public CENC/Dolby metadata.
* Give each playback an independent local media context on an ephemeral loopback
  port, with scoped cookies and isolated licence headers.
* Report bounded playback error codes without raw URL/account/licence dumps.
* Keep the addon ID/profile format. Fully restart Kodi after installation.
* 70 automated tests pass with simulated responses. Device playback remains to
  be validated; this workspace cannot bind loopback sockets or reach Odido.

## 0.1.1

* Add a Device name setting, defaulting to Kodi Odido TV, and send it as
  `authenticateDevice.deviceName` at login. Provider acceptance needs verification.
* Retain the existing device identity when upgrading or changing the label.
* Explain the device-limit response in Dutch and English instead of only
  displaying the generic request failure.
* Add name, migration, failed-registration and error-dialog regression tests.

## 0.1.0

* Initial experimental Odido TV client for Kodi 21.2.
