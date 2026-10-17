# Changelog

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
