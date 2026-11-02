# Changelog

## 0.9.5

### English

The day charts now read like clockwork, from midnight to midnight — and meters, planning and the Home Assistant connection shrug off restarts.

- **Day charts** (Today / Yesterday / Tomorrow)
  - The time axis runs from midnight to midnight on every graph, so the last hour of the day (11 pm – midnight) is finally visible instead of being cut off.
  - Each graph is drawn the way its data deserves: production and consumption as steps filling each whole hour, the grid as bars with a line through them, and the battery level as points placed at the exact moment they describe (the point at 11 pm is the level at midnight).
  - Tooltips show the real time of each point — "9:22 pm" for a reading taken at 9:22, not just the round hour — along with its time slot ("9 pm – 10 pm").
  - The ongoing hour now has two points: the forecast at the end of the hour and the live reading in the middle, so the battery or production curve no longer jumps to midnight or stops early.
  - All points are sorted and the whole day is covered from 0 h to 24 h: no more missing hour in the middle of a curve, and the measured curve ends exactly on the latest reading instead of one point before it.

- **Meters and data quality**
  - When Home Assistant restarts, a meter can briefly report a wrong (higher) index; this phantom reading is now cancelled like a dropout, so it no longer creates a huge spike or a several-hour gap in your real curves.
  - A counter jump that is physically impossible — more energy in one step than your installation could ever deliver — is ignored, no matter how long the wrong value lasts; when the real index comes back, it is counted as a normal difference.
  - Automatic corrections ("discard this reading") are re-checked against the raw measurement as long as it exists: if the value turns out plausible after all, the correction lifts by itself and the charts fill in again within about 15 minutes. Manual corrections are never touched.

- **Planning**
  - "Starts after" now also works for tasks scheduled on a specific day, not just today's: tomorrow's dryer set to run after the washer is now really placed after it, instead of sometimes before.
  - If you pick another start time for an appliance whose planned slot has already passed but never started, the appliance now really moves to the new time in the recalculated plan — previously the old slot stayed frozen and the new calculation changed nothing.

- **Home Assistant connection**
  - If WattSlot reconnects while Home Assistant is still starting up, it re-reads the states of all your entities a little later (about one minute, then five minutes after connecting), so "sensor not found" problems in the application status clear by themselves once Home Assistant is fully up.
  - "Check again" now really re-reads the states even when the connection already shows as active — before, it did nothing in that state and only restarting the app fixed the problem.

- **Project**
  - Daily download statistics of the app are now collected automatically every day (a small script queries the GitHub API and a scheduled workflow stores the result), so the team can see how many installations use each version.

### Français

Les courbes du jour se lisent désormais comme une horloge, de minuit à minuit — et compteurs, planning et connexion à Home Assistant encaissent les redémarrages sans accroc.

- **Courbes du jour** (Aujourd'hui / Hier / Demain)
  - L'axe du temps va désormais de minuit à minuit sur chaque graphe : la dernière heure de la journée (23 h – minuit) est enfin visible au lieu d'être coupée.
  - Chaque graphe est tracé selon la nature de ses données : production et consommation en paliers remplissant chaque heure entière, réseau en barres traversées par une ligne, niveau de batterie en points placés à l'instant exact qu'ils décrivent (le point de 23 h est le niveau à minuit).
  - Les info-bulles indiquent l'heure réelle de chaque point — « 21 h 22 » pour un relevé pris à 21 h 22, pas seulement l'heure ronde — avec sa tranche (« 21 h – 22 h »).
  - La tranche en cours comporte désormais deux points : la prévision à la fin de l'heure et le relevé en direct au milieu ; la courbe de batterie ou de production ne saute donc plus jusqu'à minuit et ne s'arrête plus en avance.
  - Tous les points sont triés et toute la journée est couverte de 0 h à 24 h : plus d'heure manquante au milieu d'une courbe, et la courbe mesurée s'arrête exactement sur le dernier relevé au lieu de s'arrêter un point avant.

- **Compteurs et qualité des données**
  - Au redémarrage de Home Assistant, un compteur peut rapporter brièvement un index erroné (plus haut) ; ce relevé fantôme est désormais annulé comme une coupure : plus de pic géant ni de trou de plusieurs heures dans vos courbes réelles.
  - Un saut de compteur physiquement impossible — plus d'énergie en un seul pas que votre installation ne pourrait jamais en délivrer — est ignoré, quelle que soit la durée de la mauvaise valeur ; quand l'index réel revient, il est compté comme un écart normal.
  - Les corrections automatiques (« écarter cette mesure ») sont revérifiées contre la mesure brute tant qu'elle existe : si la valeur s'avère finalement plausible, la correction se lève toute seule et les courbes se remplissent à nouveau en environ 15 minutes. Les corrections manuelles ne sont jamais touchées.

- **Planning**
  - « Démarre après » fonctionne aussi pour les tâches prévues à un jour précis, pas seulement pour aujourd'hui : le sèche-linge de demain réglé « après le lave-linge » est désormais réellement placé après, et non parfois avant.
  - Si vous choisissez une autre heure de départ pour un appareil dont le créneau prévu est déjà passé mais ne s'est pas lancé, l'appareil est réellement déplacé à la nouvelle heure dans le plan recalculé — auparavant l'ancien créneau restait figé et le nouveau calcul ne changeait rien.

- **Connexion à Home Assistant**
  - Si WattSlot se reconnecte pendant que Home Assistant démarre encore, il relit un peu plus tard les états de toutes vos entités (environ une minute, puis cinq minutes après la connexion) : les problèmes « capteur introuvable » affichés dans l'état de l'application disparaissent donc d'eux-mêmes une fois Home Assistant complètement démarré.
  - « Vérifier à nouveau » relit réellement les états même quand la connexion est déjà active — auparavant, il ne faisait rien dans cet état et seul un redémarrage de l'application réglait le problème.

- **Projet**
  - Des statistiques de téléchargement quotidiennes de l'application sont désormais collectées automatiquement chaque jour (un petit script interroge l'API GitHub et un workflow planifié enregistre le résultat), pour voir combien d'installations utilisent chaque version.

## 0.9.4

WattSlot speaks more precisely, and the graph of your home becomes an explorer.

- **Assistant**: it now answers questions about cost, the next appliance to start, your tariff and your requests. The time it took to answer is shown.
- **Tariff**: time-of-use price bands can start and end at the exact minute (off-peak from 10:30 pm, for instance); prices are weighed by the minute, a band's end always follows its start in the day, and the minute is shown right next to the hour.
- **Graph of your home**: a whole new graph to explore your home — a global view of everything at once, double-click to enter an element and **Back** to come out, full screen, and a search to find an element. Many readability fixes: no more overlapping objects, views centered on first display, a lower zoom floor, a clearer properties panel.
- **Day timeline**: the other possible starts of an appliance appear right on the day's timeline; a planned appliance can be cancelled from the timeline or from **Next action**; an appliance already running no longer opens a choice sheet.
- **My home**: a device's sensor can be replaced from its sheet; the sensor list fits in the sheet and the unit is shown next to it.
- **Data quality**: a corrected impossible reading now fills the gap in the charts, the corrected value replaces the wrong one, and the message about a discarded reading follows the range you are viewing.
- **Today**: the trend is now a pill you can read at a glance, shown at the top of the Battery and Sun cards.
- **Charts**: legend settings moved under a **Customize** icon in the title bar; **Compute** and **Refresh real data** became icons in the title bar, with the age of the last calculation staying stable.
- **Fixes**: the measured production is 0 kWh after sunset; the connection to Home Assistant is repaired after its restart; **Other starts** is readable in all themes.

## 0.9.3

WattSlot now adapts to your home: no talk of the sun without panels, nor of a battery without one.

- Without solar panels, the weather, production, surplus and self-consumption disappear from every screen; without a battery, everything about the battery too. Use **Read Home Assistant again** in **My home › Devices** if you add them later.
- No appliance to place yet (none in the Energy dashboard): Today and the first steps invite you to add one.
- Provisional plan: while WattSlot is still importing your Home Assistant history, the plan says so; its figures become accurate at the first calculation after the import.
- First steps: the status shows "Getting started" instead of a red "calculation blocked"; it refreshes when you change screen and after a calculation. Templates are named after your contract (single price, off-peak hours, Tempo, dynamic price).
- Detection: a power setting (an inverter's limit, for instance) is no longer taken for a measured power; the grid and an unnamed battery get a name in your Home Assistant language; a missing sensor is reported once.

## 0.9.2

Fixes found while installing the beta on a fresh Home Assistant.

- First steps: when something required is missing before the first plan (a solar forecast, for instance), the last step says what and opens the right setting, instead of "All set" and a calculation that silently did nothing. A calculation that fails is now reported.
- Standalone (Docker): the Home Assistant address given in `HA_URL` is filled in on the connection page.

## 0.9.1

Public beta for testers: clearer screens, data you can trust, and an easy way to give feedback.

- Beta: a "Beta" badge, a **Give feedback** button at the bottom of Settings (a ready-made form on GitHub), and a **Support WattSlot** card (GitHub Sponsors, Ko-fi).
- New **Charts** section: the figures and charts of the plan, moved out of Planning. The week is a table with one row per day.
- **My home** in four tabs (Essentials, Devices, Data, Advanced), one setting per sheet, and a complete sheet for each device.
- **Data quality**: WattSlot checks your meters, corrects impossible readings (a sensor dropout counted as a reset) and lets you choose another correction or undo it. One wrong reading no longer hides the others in the charts. The original data is never changed.
- **Other possible starts**: up to three other starts proposed by the plan, with their effect on the cost; choose one, or go back to the calculation's choice.
- Planning: **My requests** under the plan; Compute and Refresh next to the tabs; plan indicators for the whole day.
- **Assistant**: chat with Home Assistant's assistant (or Open WebUI) from the app, with the conversation kept; the internal address of the MCP server is remembered and can be changed.
- Your contract: subscription and subscribed power; the currency of your prices, shown everywhere.
- Week: where the horizon stops is explained, and missing days are shown.
- Fixes: a clear message when the expected consumption is impossible; the forecast production axis of the week starts at 0; no more tiny negative values or duplicated hours; no more occasional "Unable to read the plan".
- New README and user guide in English and French, with new screenshots.

## 0.9.0

Public beta, under the new name WattSlot.

- New name, icon and logo: WattSlot is a new app in Home Assistant (`wattslot`), installed from a public repository without any token.
- Homes without solar panels: off-peak, day colour or dynamic tariffs work on their own, without solar forecast.
- New version notice in Settings and Application status.
- Planning of appliances: taller tracks without legend, planned above and measured below, energy written in each block.
- History import writes about 5 times less to disk.
- Solver retries once differently when it wrongly reports a plan as impossible; the "battery full" bonus only breaks ties.
- Fixes: first-step "Notification" check, today's real data right after the update, start times of today's real cycles, hour axis of daily charts, stale warning of an appliance already placed in today's plan.
- The old v1 dashboard is removed.
- User documentation in English and French, links to support the project.

## 0.8.0

Home Assistant app quality: updates, backups and options.

- Updates from the app store: the app is published on its own branch, only once its image is online, so Home Assistant offers "Update" for each new version.
- Hot backups: before Home Assistant copies the app's folder, the app freezes a consistent copy of its database and graph; only that copy is backed up, and it is put back in place after a restore. Raw readings are left out (kept 3 days, rebuilt from Home Assistant's history).
- Options, in English and French: log level, how long raw readings (1 to 30 days) and quarter-hour data (31 to 3660 days) are kept.
- Clean stop: 30 seconds to write pending data before stopping; watched by the image's health check, so Home Assistant's watchdog restarts the app if it stops answering.
- Icon, logo and updated documentation.

## 0.7.0

First version planned for everyday use (development phases 0 to 6 bis).

- Reads your home from Home Assistant's Energy dashboard: solar production, grid, battery and appliances; history imported from Home Assistant's statistics.
- Daily plan and seven-day horizon: when to start each appliance, when to charge and discharge the battery, around solar forecast and electricity prices (single, off-peak, day colour or dynamic).
- Your home, your rules: appliance behaviours, time constraints, recurrences, battery settings, objective (cost, self-consumption, grid, CO₂), ready-made templates, backup and sharing.
- New interface: Today, Planning (agenda and detailed charts), My home in plain sentences, Assistant, Settings; guided first steps; five themes with automatic light and dark; six languages (German, Dutch, Spanish and Italian to be reviewed).
- Requests from the app or Home Assistant's Assist, reminders, configurable notifications.
- MCP server for Home Assistant's Assist (`/mcp`).
- Application status: problems explained in plain words, anonymised report.

## 0.0.1

- First development build: application state and connection to Home Assistant.
