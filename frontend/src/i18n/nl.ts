/** Dutch. Machine translated; corrections welcome. */
import type { Catalog } from './index';

export const nl: Catalog = {
  // -- the card ---------------------------------------------------------------
  'app.connecting': 'Verbinden met Pulse Check',
  'app.connecting_detail': 'Een ogenblik.',
  'app.missing': 'Pulse Check-integratie niet gevonden',
  'app.missing_detail':
    'Deze kaart heeft de Pulse Check-integratie nodig. Installeer die, voeg hem toe via Instellingen → Apparaten & diensten en laad deze pagina opnieuw.',
  'app.error': 'Pulse Check niet bereikbaar',
  'app.error_detail': 'Het abonnement is mislukt.',
  'app.tabs_label': 'Weergaven van apparaatstatus',
  'app.maintenance': 'Onderhoudsmodus tot {time}. Meldingen worden tegengehouden.',
  'app.snoozed': { one: '{count} gepauzeerd', other: '{count} gepauzeerd' },
  'app.show': 'tonen',
  'app.hide': 'verbergen',
  'app.updated': 'Pulse Check is bijgewerkt naar {version}. Vernieuw om de nieuwe kaart te laden.',
  'app.refresh': 'Vernieuwen',
  'app.stale':
    'Pulse Check is voor het laatst {time} bijgewerkt; de gegevens hieronder zijn mogelijk verouderd.',
  'undo.replaced': '{name} gemarkeerd als vervangen.',
  'undo.charged': '{name} gemarkeerd als opgeladen.',
  'undo.undo': 'Ongedaan maken',
  'failed.snooze': '{name} kon niet worden gepauzeerd.',
  'failed.unsnooze': 'Pauze van {name} kon niet worden beëindigd.',
  'failed.replaced': '{name} kon niet als vervangen worden gemarkeerd.',
  'failed.charged': '{name} kon niet als opgeladen worden gemarkeerd.',
  'failed.undo': 'Markering van {name} kon niet ongedaan worden gemaakt.',

  'tab.batteries': 'Batterijen',
  'tab.connectivity': 'Verbinding',
  'tab.actions': 'Acties',

  'headline.ok': 'Alle apparaten OK',
  'headline.attention': {
    one: '{count} apparaat vraagt aandacht',
    other: '{count} apparaten vragen aandacht',
  },
  'breakdown.low': { one: '{count} batterij laag', other: '{count} batterijen laag' },
  'breakdown.offline': { one: '{count} offline', other: '{count} offline' },
  'breakdown.quiet': { one: '{count} stil', other: '{count} stil' },
  'breakdown.not_provided': { one: '{count} niet geleverd', other: '{count} niet geleverd' },

  'empty.no_batteries': 'Geen apparaten op batterijen',
  'empty.no_batteries_detail': 'Niets hier werkt op batterijen.',
  'empty.batteries_ok': 'Geen batterijproblemen',
  'empty.batteries_ok_detail': 'Elke batterij zit boven de waarschuwingsdrempel.',
  'empty.online': 'Alle apparaten online',
  'empty.online_detail': 'Geen apparaten zijn offline of ongewoon lang stil.',
  'empty.actions': 'Niets te doen',

  // -- one device row ---------------------------------------------------------
  'row.open': '{name}, openen in Home Assistant',
  'row.offline': 'Offline',
  'row.unavailable': 'Niet beschikbaar',
  'row.not_provided': 'Niet geleverd',
  'row.not_provided_by': 'niet meer geleverd door {integration}',
  'row.quiet': 'Stil',
  'row.online': 'Online',
  'row.charging': 'laadt op',
  'row.charging_title': 'Opladen',
  'row.snoozed_until': 'tot {date}',
  'row.unusual_title': 'Vergeleken met de eigen geschiedenis van dit apparaat',
  'row.heard': 'gemeld {time}',
  'row.last_heard': 'laatst gemeld {time}',
  'row.limit': 'grens {hours}',
  'row.left': 'nog {days}',
  'row.charge_in': 'opladen over {days}',
  'row.usual_low': 'meestal laagste {level}%',
  'row.year_plus': 'nog meer dan een jaar',
  'row.estimate_high': '{basis} (hoge betrouwbaarheid)',
  'row.estimate_medium': '{basis} (gemiddelde betrouwbaarheid)',
  'row.estimate_low': '{basis} (lage betrouwbaarheid)',
  'row.estimate_fallback': 'Geschat door de Pulse Check-integratie',
  'row.done': 'Klaar',
  'row.done_label': '{name} als klaar markeren',
  'row.done_title': 'Vastleggen dat deze batterij is vervangen of opgeladen',

  'battery.low': 'Laag',
  'battery.ok': 'OK',
  'battery.level': 'Batterijniveau',

  'snooze.title': 'Pauzeren: dit apparaat een tijdje verbergen',
  'snooze.label': '{name} pauzeren',
  'snooze.until_title': 'Gepauzeerd tot {date}. Klik om de pauze te beëindigen.',
  'snooze.unsnooze_label': 'Pauze van {name} beëindigen',
  'snooze.days': { one: '{count} dag', other: '{count} dagen' },

  'rows.show_more': { one: 'Nog {count} tonen', other: 'Nog {count} tonen' },
  'rows.show_less': 'Minder tonen',

  'integration.title': 'Integratie: {platform}',
  'integration.phone': 'Telefoon',
  'integration.unknown': 'Onbekend',

  'spark.title': {
    one: 'Trend over {count} dag: {first}% → {last}%',
    other: 'Trend over {count} dagen: {first}% → {last}%',
  },
  'spark.title_day': 'Trend van de laatste dag: {first}% → {last}%',

  // -- time and durations -----------------------------------------------------
  'time.never': 'nooit',
  'time.just_now': 'zojuist',
  'unit.minutes': '{n} min',
  'unit.hours': '{n} u',
  'unit.days': '{n} d',
  'unit.weeks': '{n} wk',
  'unit.months': '{n} mnd',
  'days_left.year_plus': '1 jr+',

  // -- the Actions tab --------------------------------------------------------
  'actions.to_buy': 'Te kopen:',
  'actions.unknown_type': 'onbekend',
  'actions.hint':
    'Stel het batterijtype en aantal in de kaarteditor in (Instellingen per apparaat) om de lijst exact te maken.',
  'actions.replace': 'Vervangen',
  'actions.charge': 'Opladen',
  'action.replace_one': '{type} in {name} vervangen',
  'action.replace_many': '{count} × {type} in {name} vervangen',
  'action.replace_unknown': 'De batterij in {name} vervangen',
  'action.charge': '{name} opladen',

  // -- groups -----------------------------------------------------------------
  'group.no_area': 'Geen ruimte',
  'type.lock': 'Sloten',
  'type.cover': 'Zonwering en rolluiken',
  'type.vacuum': 'Stofzuigers',
  'type.phone': 'Telefoons en trackers',
  'type.media': 'Mediaspelers',
  'type.remote': 'Afstandsbedieningen',
  'type.climate': 'Klimaat',
  'type.motion': 'Bewegingssensoren',
  'type.contact': 'Contactsensoren',
  'type.light': 'Lampen',
  'type.switch': 'Schakelaars',
  'type.other': 'Overig',

  // -- words the integration sends in English (see serverText.ts) --------------
  'basis.trend': 'trend over huidige cyclus',
  'basis.flat': { one: '{count} dag onveranderd', other: '{count} dagen onveranderd' },
  'basis.slow': {
    one: 'langzaam leeglopen over {count} dag',
    other: 'langzaam leeglopen over {count} dagen',
  },
  'basis.cycles': {
    one: 'uit {count} eerdere cyclus van ~{days} dagen',
    other: 'uit {count} eerdere cycli van ~{days} dagen',
  },
  'basis.charge': 'tot opladen nodig is',
  'unusual.faster': 'loopt {factor}× sneller leeg dan normaal',
  'unusual.drop': 'niveau plotseling gedaald',

  // -- the editor -------------------------------------------------------------
  'editor.title': 'Titel',
  'editor.no_title': 'Geen titel',
  'editor.tabs': 'Tabbladen',
  'editor.default_tab': 'Standaardtabblad',
  'editor.group_by': 'Groeperen op',
  'group.none': 'Niet groeperen',
  'group.area': 'Ruimte',
  'group.integration': 'Integratie',
  'group.device_type': 'Apparaattype',
  'editor.sort': 'Sorteervolgorde',
  'sort.level': 'Laagste niveau eerst',
  'sort.name': 'Naam',
  'sort.replace_soon': 'Eerst te vervangen bovenaan',
  'editor.rows': 'Rijen per tabblad',
  'editor.all_rows': 'Alle rijen tonen',
  'editor.sparklines': 'Trend-sparklines',
  'editor.over': 'over',
  'editor.days': 'dagen',
  'editor.sparkline_days': 'Sparkline-dagen',
  'editor.problems_only': 'Tabblad Batterijen: alleen problemen',
  'editor.areas': 'Ruimtes op deze kaart',
  'editor.areas_hint':
    'Vink een ruimte uit om de apparaten ervan van deze kaart weg te laten. De integratie blijft ze bewaken.',
  'editor.integrations': 'Integraties op deze kaart',
  'editor.device_types': 'Apparaattypen op deze kaart',
  'editor.note':
    'Wat er überhaupt wordt bewaakt, drempels, stilregels, uitsluitingen en meldingen stel je in bij de integratie: Instellingen → Apparaten & diensten → Pulse Check → Configureren. De lijsten hierboven veranderen alleen wat deze kaart toont.',
  'keep.stray_title': 'Uit YAML; niet gevonden in deze instantie',

  'editor.device_settings': 'Instellingen per apparaat',
  'editor.device_settings_hint':
    'Naam, ruimte, batterijgegevens, stil-drempel en meldingsbeleid van een apparaat staan nu in de instellingen van de Pulse Check-integratie (Configureren → Instellingen per apparaat), omdat ze voor elke kaart en voor meldingen gelden, niet alleen voor deze.',
  'editor.device_settings_link': 'Pulse Check-instellingen openen',

  'battery_type.builtin': 'Ingebouwde accu',
  'battery_type.li_ion_pack': 'Li-ion-accupack',
  'battery_type.nimh_pack': 'NiMH-accupack',

  // -- YAML errors, shown on the card and in the editor -------------------------
  'config.mapping': 'De kaartconfiguratie moet een YAML-mapping zijn (sleutel: waarde-paren).',
  'config.one_of': '"{key}" moet een van deze zijn: {allowed}.',
  'config.list': '"{key}" moet een lijst van namen of ID\'s zijn.',
  'config.boolean': '"{key}" moet true of false zijn.',
  'config.title': '"title" moet tekst zijn.',
  'config.show_tabs': '"show_tabs" moet een niet-lege lijst zijn met alleen: {allowed}.',
  'config.default_tab_missing': '"default_tab" ({tab}) staat niet in "show_tabs".',
  'config.max_rows': '"max_rows" moet een geheel getal van minstens 1 zijn, of "all".',
  'config.sparkline_days': '"sparkline_days" moet een geheel aantal dagen van 1 tot {max} zijn.',

  // -- the dashboard's card picker --------------------------------------------
  'card.name': 'Pulse Check-kaart',
  'card.description':
    'Batterijniveaus en offline of stil geworden apparaten over alle integraties heen.',
};
