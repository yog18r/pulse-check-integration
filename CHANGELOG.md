# Changelog

What changed in each release of Pulse Check. The section for a version is
also its release notes on GitHub, which is what HACS shows when it offers
the update.

## 0.2.10 - 2026-11-08

### Fixed
- **Per-device battery sensors no longer hide problems.** With that option
  on, Pulse Check's own sensors on a device counted as the device
  reporting, so it never went quiet, and a device with a single battery
  entity could drop out of monitoring altogether. Pulse Check's own
  entities are now ignored when judging a device.
- **No more duplicate notifications** when a recompute started while a
  slow notification was still being sent.
- **Notifications that fail are retried**, every 15 minutes up to four
  times, instead of being counted as sent; so are the grouped messages of
  the per-integration limit and the maintenance summary. A notify target
  that does not exist or keeps failing appears under Settings, Repairs,
  and the repair clears once a message gets through or the target is
  taken out of the options.
- **Saving the options no longer pauses notifications for five minutes**,
  and a snooze or Done made just before saving is no longer lost.
- **A restart timeout shorter than the quiet period after start** no
  longer silently does nothing.
- **A battery reporting 100 % once is not a new battery.** A rise in level
  now has to hold for an hour before it counts as a replacement or charge,
  and Undo can take back one that was detected automatically.
- **The shopping-list example in the README works**: the attention sensor
  now has the `shopping` attribute it relied on.
- Devices that Home Assistant 2026.10 registers as child devices are
  treated as devices instead of loose entities, and a YAML entity removed
  from the configuration (an automation deleted from `automations.yaml`,
  say) reads as *not provided* rather than as a critical "unavailable".
- Removing Pulse Check deletes its saved data and repair issues.
- The card says when a snooze, Done or Undo fails, shows Undo only once
  the mark is recorded, and warns when its data is more than 15 minutes
  old. Its editor can now pick services and entities with no device.

### Changed
- Battery history is read from the recorder once per refresh instead of
  twice, and sparklines only fetch the batteries they don't have yet.

## 0.2.9 - 2026-11-08

### Added
- **Devices that don't come back after a restart are reported.** Until
  now a device had to work once after a restart before it could count as
  offline, so one that died while Home Assistant was off was never
  reported. Thirty minutes after the start, one still not seen working
  counts as offline, "offline since the restart". Change the wait under
  Configure, Notifications, "Offline if not back after a restart"; 0
  waits for ever, as before.

### Fixed
- **A restart no longer forgets devices that were already offline.** One
  still down after the restart was treated as fixed: a false "resolved"
  event (a message, with the blueprint's resolved option), and no more
  reminders or digest entries. It now stays offline until it comes back.
- **The startup timings in Configure keep their values.** "Quiet period
  after start" and "Confirm offline or quiet after" showed their defaults
  when the dialog was opened again, so saving it put them back.

## 0.2.8 - 2026-11-08

### Added
- **Services and entities with no device can be unavailable.** Pulse
  Check used to watch only hardware for being offline. Services such as
  Sun, AdGuard Home or Backup, and entities with no device such as
  template sensors, automations and helpers, now count as unavailable when
  they stop working: shown on the Connectivity tab and notified as
  "unavailable" under the critical policy. They are never quiet. Turn it
  off under Configure, Filters, "Watch services and entities with no
  device", or leave out a noisy one with the usual filters.

### Changed
- The README leads with installing from the Home Assistant Marketplace,
  which replaced HACS in Home Assistant 2026.11.

## 0.2.7 - 2026-11-08

### Added
- **Refresh prompt after updates.** A browser tab keeps running the card it
  loaded until the page is refreshed. When the installed version is newer
  than the card on screen, the card now says so and offers a Refresh button.
  This first shows after the update that follows this one.
- **Undo for Done.** After pressing Done on the Actions tab, "Marked … as
  replaced" stays on screen for ten seconds with an Undo button, so a
  mistaken tap no longer resets the device's battery cycle.
- **`pulse_check.undo_mark` action.** Takes back the most recent replacement
  or charge recorded by hand, with the cycle it closed. One detected
  automatically from a jump in level is left alone.
- **Keyboard support in the snooze menu.** It focuses the first option when
  it opens; the arrow keys, Home and End move between options, and Escape
  closes it.

### Changed
- **Sparklines arrive in one request.** The card used to fetch each
  battery's history separately; it now asks once for all of them, and the
  integration reads the recorder once per window length instead of once per
  battery.

### Under the hood
- Dependabot opens weekly update pull requests for the card's packages, the
  Python tools and the GitHub Actions.
- Development tools updated; an unused coverage tool removed; a test that
  failed now and then on CI fixed.

## 0.2.6 - 2026-10-30

### Fixed
- **"Configuration error" on a dashboard opened while Home Assistant
  starts.** The card's file was only served at the end of Pulse Check's
  setup, so a page loaded during startup could not load the card at all. It
  is now served from the integration's first setup step.

## 0.2.5 - 2026-10-28

### Upgrading
- The first restart after updating still runs the card your browser already
  had. Refresh the dashboard once; later restarts recover by themselves.

### Fixed
- **"Pulse Check integration not found" after a restart.** The card now
  tries again until Pulse Check answers and subscribes again after the
  connection comes back, so it fills in by itself instead of needing a page
  refresh. While Home Assistant is still starting it says it is connecting.

## 0.2.4 - 2026-10-28

### Added
- **"Not provided" instead of offline for leftover entities.** When an
  integration stops providing an entity, typically after an update, Home
  Assistant keeps it as an unavailable placeholder. A device made only of
  those used to read as offline and send critical notifications. While its
  integration is running it now reads as *not provided*: a warning on the
  Connectivity tab saying which integration no longer provides it, notified
  under the warning policy (the weekly digest by default). Delete it from
  the device page to clear it.

### Under the hood
- Releases are built with the newest Node 24, which includes the fix for
  CVE-2026-111497 (Node2Shell). Nothing that ships was affected.

## 0.2.3 - 2026-10-23

### Fixed
- **A failed firmware check no longer reads as offline.** A device with no
  primary entities, such as Home Assistant's SkyConnect, was judged by its
  firmware update entity, which goes unavailable whenever a firmware check
  fails. Settings and update checkers no longer decide whether a device is
  offline.

## 0.2.2 - 2026-10-22

### Added
- **A limit on offline and quiet messages per integration.** An outage
  outside Home Assistant, such as a network controller updating, used to
  send one message per device. Each integration now sends at most three an
  hour by default; the rest follow an hour later as one message listing
  those still unresolved. Each integration has its own allowance, and
  battery messages are never held back. Set it under Configure,
  Notifications; 0 turns it off.

### Fixed
- **The snooze menu is no longer cut off** at the bottom of the card. It
  opens upwards when there is no room below.

## 0.2.1 - 2026-10-16

### Upgrading
- The switch replaces `binary_sensor.pulse_check_maintenance_mode`, which
  is removed. Point any dashboard or automation that used it at the switch.

### Changed
- **Maintenance mode is a switch.** `switch.pulse_check_maintenance_mode` on
  the Pulse Check device page turns it on for the default length from the
  options, and off ends it at once. The `pulse_check.maintenance_mode`
  action still takes any number of hours.

## 0.2.0 - 2026-10-16

### Added
- **Maintenance mode.** Holds every notification back for a few hours, for
  planned work such as migrating a Zigbee coordinator. Problems are still
  tracked; when it ends, one message lists those that appeared meanwhile
  and are still there.
- **Buttons on phone notifications.** Instant notifications sent to the
  companion app offer Mark replaced (or Mark charged), Remind me later and
  Snooze 1 day.
- **Nine more languages**: German, French, Spanish, Dutch, Italian,
  Brazilian Portuguese, Polish, Simplified Chinese and Czech, for the
  settings dialogs, the notifications and the card. They are machine
  translations; corrections are welcome.

## 0.1.1 - 2026-10-16

### Fixed
- The screenshots and links in the README now show in HACS.

## 0.1.0 - 2026-10-16

The first release of the integration and its dashboard card in one install.

- **Detection** of low batteries, offline devices and devices that have gone
  quiet, across every integration, grouped by device.
- **Entities**: counts of devices needing attention, low and critical
  batteries, offline and quiet devices, the next battery to run out, and a
  problem binary sensor.
- **Notifications** once per change of state, never per update: instant
  with reminders, or collected into daily or weekly digests, chosen per
  device. A digest missed while Home Assistant was off is sent once after
  the next start.
- **Days left** for each battery from its own history, replacement
  tracking, and a note when a battery drains faster than it used to.
- **The dashboard card**, served by the integration and added to the card
  picker automatically, with Batteries, Connectivity and Actions tabs,
  snoozing, and per-device settings.
- Batteries with no device or registry entry, such as YAML template
  sensors, are watched too.
