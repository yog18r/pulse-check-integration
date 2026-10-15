/**
 * The card's English text: the source every other language follows.
 *
 * A value is either a string or, when the wording depends on a number,
 * an object of CLDR plural forms (`one`, `few`, `many`, `other`) chosen
 * with `Intl.PluralRules`. English needs `one` and `other`; Polish and
 * Czech need more, Chinese only `other`. `{name}`-style placeholders are
 * filled in by the translator.
 *
 * The other languages are typed against this object, so a missing key is
 * a compile error, and `test/i18n/catalogs.test.ts` checks plural forms
 * and placeholders at runtime.
 */
export const en = {
  // -- the card ---------------------------------------------------------------
  'app.connecting': 'Connecting to Pulse Check',
  'app.connecting_detail': 'One moment.',
  'app.missing': 'Pulse Check integration not found',
  'app.missing_detail':
    'This card needs the Pulse Check integration. Install it, add it under Settings → Devices & services, then reload this page.',
  'app.error': 'Could not reach Pulse Check',
  'app.error_detail': 'The subscription failed.',
  'app.tabs_label': 'Device health views',
  'app.maintenance': 'Maintenance mode until {time}. Notifications are held back.',
  'app.snoozed': { one: '{count} snoozed', other: '{count} snoozed' },
  'app.show': 'show',
  'app.hide': 'hide',

  'tab.batteries': 'Batteries',
  'tab.connectivity': 'Connectivity',
  'tab.actions': 'Actions',

  'headline.ok': 'All devices OK',
  'headline.attention': {
    one: '{count} device needs attention',
    other: '{count} devices need attention',
  },
  'breakdown.low': { one: '{count} low battery', other: '{count} low batteries' },
  'breakdown.offline': { one: '{count} offline', other: '{count} offline' },
  'breakdown.quiet': { one: '{count} quiet', other: '{count} quiet' },

  'empty.no_batteries': 'No battery-powered devices',
  'empty.no_batteries_detail': 'Nothing here runs on batteries.',
  'empty.batteries_ok': 'No battery problems',
  'empty.batteries_ok_detail': 'Every battery is above the warning threshold.',
  'empty.online': 'All devices online',
  'empty.online_detail': 'No devices are offline or unusually quiet.',
  'empty.actions': 'Nothing to do',

  // -- one device row ---------------------------------------------------------
  'row.open': '{name}, open in Home Assistant',
  'row.offline': 'Offline',
  'row.quiet': 'Quiet',
  'row.online': 'Online',
  'row.charging': 'charging',
  'row.charging_title': 'Charging',
  'row.snoozed_until': 'until {date}',
  'row.unusual_title': "Compared with this device's own history",
  'row.heard': 'heard {time}',
  'row.last_heard': 'last heard {time}',
  'row.limit': 'limit {hours}',
  'row.left': '{days} left',
  'row.charge_in': 'charge in {days}',
  'row.year_plus': 'more than a year left',
  'row.estimate_high': '{basis} (high confidence)',
  'row.estimate_medium': '{basis} (medium confidence)',
  'row.estimate_low': '{basis} (low confidence)',
  'row.estimate_fallback': 'Estimated by the Pulse Check integration',
  'row.done': 'Done',
  'row.done_label': 'Mark {name} done',
  'row.done_title': 'Record that this battery was replaced or charged',

  'battery.low': 'Low',
  'battery.ok': 'OK',
  'battery.level': 'Battery level',

  'snooze.title': 'Snooze: hide this device for a while',
  'snooze.label': 'Snooze {name}',
  'snooze.until_title': 'Snoozed until {date}. Click to unsnooze.',
  'snooze.unsnooze_label': 'Unsnooze {name}',
  'snooze.days': { one: '{count} day', other: '{count} days' },

  'rows.show_more': { one: 'Show {count} more', other: 'Show {count} more' },
  'rows.show_less': 'Show less',

  'integration.title': 'Integration: {platform}',
  'integration.phone': 'Phone',
  'integration.unknown': 'Unknown',

  'spark.title': {
    one: '{count}-day trend: {first}% → {last}%',
    other: '{count}-day trend: {first}% → {last}%',
  },
  'spark.title_day': 'Last day trend: {first}% → {last}%',

  // -- time and durations -----------------------------------------------------
  // "5m ago" itself comes from Intl.RelativeTimeFormat in the user's language.
  'time.never': 'never',
  'time.just_now': 'just now',
  'unit.minutes': '{n}m',
  'unit.hours': '{n}h',
  'unit.days': '{n}d',
  'unit.weeks': '{n}w',
  'unit.months': '{n}mo',
  'days_left.under_day': 'under a day',
  'days_left.year_plus': '1y+',

  // -- the Actions tab --------------------------------------------------------
  'actions.to_buy': 'To buy:',
  'actions.unknown_type': 'unknown',
  'actions.hint':
    'Set the battery type and count in the card editor (Per-device settings) to make the list exact.',
  'actions.replace': 'Replace',
  'actions.charge': 'Charge',
  'action.replace_one': 'Replace {type} in {name}',
  'action.replace_many': 'Replace {count} × {type} in {name}',
  'action.replace_unknown': 'Replace the battery in {name}',
  'action.charge': 'Charge {name}',

  // -- groups -----------------------------------------------------------------
  'group.no_area': 'No area',
  'type.lock': 'Locks',
  'type.cover': 'Covers and blinds',
  'type.vacuum': 'Vacuums',
  'type.phone': 'Phones and trackers',
  'type.media': 'Media players',
  'type.remote': 'Remotes',
  'type.climate': 'Climate',
  'type.motion': 'Motion sensors',
  'type.contact': 'Contact sensors',
  'type.light': 'Lights',
  'type.switch': 'Switches',
  'type.other': 'Other',

  // -- words the integration sends in English (see serverText.ts) --------------
  'basis.trend': 'trend over current cycle',
  'basis.flat': { one: 'flat for {count} day', other: 'flat for {count} days' },
  'basis.slow': { one: 'slow drain over {count} day', other: 'slow drain over {count} days' },
  'basis.cycles': {
    one: 'from {count} previous cycle of ~{days} days',
    other: 'from {count} previous cycles of ~{days} days',
  },
  'basis.charge': 'until charge needed',
  'unusual.faster': 'draining {factor}× faster than usual',
  'unusual.drop': 'level dropped suddenly',

  // -- the editor -------------------------------------------------------------
  'editor.title': 'Title',
  'editor.no_title': 'No title',
  'editor.tabs': 'Tabs',
  'editor.default_tab': 'Default tab',
  'editor.group_by': 'Group by',
  'group.none': 'No grouping',
  'group.area': 'Area',
  'group.integration': 'Integration',
  'group.device_type': 'Device type',
  'editor.sort': 'Sort order',
  'sort.level': 'Lowest level first',
  'sort.name': 'Name',
  'sort.replace_soon': 'Soonest to run out first',
  'editor.rows': 'Rows per tab',
  'editor.all_rows': 'Show all rows',
  'editor.sparklines': 'Trend sparklines',
  'editor.over': 'over',
  'editor.days': 'days',
  'editor.sparkline_days': 'Sparkline days',
  'editor.problems_only': 'Batteries tab: problems only',
  'editor.areas': 'Areas shown on this card',
  'editor.areas_hint':
    'Untick an area to leave its devices out of this card. The integration still monitors them.',
  'editor.integrations': 'Integrations shown on this card',
  'editor.device_types': 'Device types shown on this card',
  'editor.note':
    'What is monitored at all, thresholds, quiet rules, exclusions and notifications are set in the integration: Settings → Devices & services → Pulse Check → Configure. The lists above only change what this card shows.',
  'keep.stray_title': 'From YAML; not found in this instance',

  'settings.legend': 'Per-device settings',
  'settings.hint':
    "These are stored by the Pulse Check integration the moment you change them, so every card and notification uses them. The dialog's Save button only applies to the card's layout options above. Battery type and count feed the Actions tab; tick rechargeable for devices you charge rather than replace; trend days sets this device's sparkline window (phones: 1 day).",
  'settings.missing': 'The Pulse Check integration is not set up, so there is nothing to edit.',
  'settings.error': 'Could not reach the Pulse Check integration.',
  'settings.edited': 'Devices with settings',
  'settings.search': 'Search devices to edit…',
  'settings.for': 'Settings for {name}',
  'settings.name': 'Display name',
  'settings.name_placeholder': 'Display name (optional)',
  'settings.area': 'Area',
  'settings.area_title':
    'Area shown on the card. Pre-filled from the device registry; pick another to override.',
  'settings.no_area': 'No area',
  'settings.battery_type': 'Battery type',
  'settings.battery_type_placeholder': 'Battery type…',
  'settings.other': 'Other…',
  'settings.other_type': 'Other battery type',
  'settings.other_example': 'e.g. 2CR5',
  'settings.count': 'Battery count',
  'settings.rechargeable': 'Rechargeable',
  'settings.quiet': 'Quiet hours',
  'settings.hours': 'hours',
  'settings.trend': 'Trend days',
  'settings.card_default': 'card default',
  'settings.notify': 'Notify',
  'settings.policy': 'Notification policy',
  'settings.policy_default': 'Default for its severity',
  'policy.instant': 'Instantly, with reminders',
  'policy.daily': 'In the daily digest',
  'policy.weekly': 'In the weekly digest',
  'policy.none': 'Never',
  'settings.saved': 'Saved to Pulse Check',
  'settings.not_saved': 'Not saved: {reason}',

  'battery_group.cylindrical': 'Cylindrical',
  'battery_group.coin': 'Coin cells',
  'battery_group.photo': 'Lithium photo',
  'battery_group.li_ion': 'Lithium-ion cells',
  'battery_group.packs': 'Packs',
  'battery_type.builtin': 'Built-in rechargeable',
  'battery_type.li_ion_pack': 'Li-ion pack',
  'battery_type.nimh_pack': 'NiMH pack',

  'picker.device': 'Device',
  'picker.search': 'Search devices…',
  'picker.none': 'No devices match',
  'picker.more': 'Keep typing to narrow it down',

  // -- YAML errors, shown on the card and in the editor -------------------------
  'config.mapping': 'Card config must be a YAML mapping (key: value pairs).',
  'config.one_of': '"{key}" must be one of: {allowed}.',
  'config.list': '"{key}" must be a list of names or ids.',
  'config.boolean': '"{key}" must be true or false.',
  'config.title': '"title" must be text.',
  'config.show_tabs': '"show_tabs" must be a non-empty list containing only: {allowed}.',
  'config.default_tab_missing': '"default_tab" ({tab}) is not in "show_tabs".',
  'config.max_rows': '"max_rows" must be a whole number of at least 1, or "all".',
  'config.sparkline_days': '"sparkline_days" must be a whole number of days from 1 to {max}.',

  // -- the dashboard's card picker --------------------------------------------
  'card.name': 'Pulse Check Card',
  'card.description': 'Battery levels, offline and gone-quiet devices across every integration.',
} as const satisfies Record<string, string | PluralForms>;

/** One message's plural forms. `other` is always required. */
export type PluralForms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };
