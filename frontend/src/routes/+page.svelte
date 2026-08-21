<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { jobBusy, jobPhase, machineState } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import { DesignStore, isDesignSignal } from '$lib/design.svelte';
	import { EditController } from '$lib/edits.svelte';
	import { bewaarBestand } from '$lib/saving';
	import type { Tool } from '$components/ToolRail.svelte';
	import { LibraryStore } from '$lib/library.svelte';
	import { StatusConnection } from '$lib/status.svelte';
	import Canvas from '$components/Canvas.svelte';
	import DesignPanel from '$components/DesignPanel.svelte';
	import JobPanel from '$components/JobPanel.svelte';
	import StatusBar from '$components/StatusBar.svelte';
	import ToolRail from '$components/ToolRail.svelte';
	import Dialog from '$components/Dialog.svelte';
	import MaterialLibrary from '$components/MaterialLibrary.svelte';
	import Presetariat from '$components/Presetariat.svelte';
	import Generators from '$components/Generators.svelte';
	import CameraCalibration from '$components/CameraCalibration.svelte';
	import Clipart from '$components/Clipart.svelte';
	import SheetTabs from '$components/SheetTabs.svelte';
	import SheetMaterial from '$components/SheetMaterial.svelte';
	import PhoneView from '$components/PhoneView.svelte';
	import JobStart from '$components/JobStart.svelte';
	import { SheetStore } from '$lib/sheets.svelte';
	import { CameraStore } from '$lib/camera.svelte';
	import { PresetariatStore } from '$lib/presetariat.svelte';
	import { TilingStore } from '$lib/tiling.svelte';
	import TestGrid from '$components/TestGrid.svelte';
	import TestGridResult from '$components/TestGridResult.svelte';
	import TextDialog from '$components/TextDialog.svelte';
	import TopBar from '$components/TopBar.svelte';
	import ActionBar from '$components/ActionBar.svelte';
	import Menu from '$components/Menu.svelte';
	import CornersDialog from '$components/CornersDialog.svelte';
	import Offset from '$components/Offset.svelte';
	import {
		KEYS,
		comboOf,
		canvasMenu,
		objectMenu,
		historyActions,
		arrangeActions,
		alignActions,
		type Context as ActionContext,
		type Handlers,
		type Menu as MenuList
	} from '$lib/actions';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import AlarmCard from '$components/AlarmCard.svelte';
	import NotificationCard from '$components/NotificationCard.svelte';
	import { Notifications, Watchdog } from '$lib/notifications.svelte';

	const status = new StatusConnection();
	const control = new Controller();
	// Besluit B3: melden ja, zelf ingrijpen nee. De bewaker leest de status en
	// besluit wanneer er iets te zeggen valt; hij stuurt niets naar de machine.
	const notifications = new Notifications();
	const watchdog = new Watchdog(notifications);
	/** Staat de instelkaart open? Bereikbaar naast de paneeltabs. */
	let meldingenOpen = $state(false);
	/** De aanleidingkaart: alleen in beeld vlak nadat er een job begon. */
	let vraagOpen = $state(false);
	const design = new DesignStore();
	const token = () =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
	const library = new LibraryStore(token);
	const edits = new EditController(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '')
	);

	let canEdit = $derived(!control.needsToken);
	let hasSelection = $derived(design.selectedIds.length > 0);
	let tool = $state<Tool>('select');
	// Bijsnijden: het volgende sleepkader knipt de geselecteerde afbeelding bij.
	let cropping = $state(false);

	// Drie apparaten, drie apps (DESIGN-SYSTEM v2). Geen gekrompen desktop maar
	// een eigen gedaante: onder 768px is dit een monitor met een noodrem.
	let breedte = $state(1440);
	let telefoon = $derived(breedte < 768);
	let tablet = $derived(breedte >= 768 && breedte < 1200);
	// Onder deze breedte passen de bestandsknoppen niet meer náást de
	// machinebediening in de bovenbalk; ze verhuizen dan naar het railmenu.
	// Sinds het materiaal van het vel in de balk staat (besluit B1) ligt die
	// grens niet meer op 950 maar op de hele tabletbreedte: gemeten liep de
	// balk op 1024 anders 99px over de rand, en dan staat de startknop buiten
	// beeld. Waarín je brandt weegt zwaarder dan een bestandsknop die één tik
	// verderop in het railmenu staat.
	let smal = $derived(tablet);
	// Onder 880px kost de projectknop in de balk de naam van het materiaal
	// (gemeten: 63px → 40px op 850, → 7px op 768). Daar woont het project in het
	// railmenu; daarboven staat het in de balk. Zie de mediaquery in TopBar.svelte.
	let projectInRail = $derived(breedte < 880);
	// `krap` stond hier: onder 1500px verdween het projectpaar uit de balk en
	// stond het alleen nog in het railmenu. Dat was precies waar de gebruiker het
	// niet vond. Het paar is nu één knop "Project" met een menu, die op elke
	// breedte in de balk past — dus is er geen krappe stand meer.
	/**
	 * Op de kleinste tablet begint het paneel dicht (gat B2).
	 *
	 * Het paneel schaalt mee met het venster, dus het is nooit meer breder dan
	 * het canvas — maar onder 850px houdt het bed nog geen 400px over, en dan is
	 * het eerste wat je ziet een sliver werkgebied naast een vol formulier. De
	 * greep ernaast is één tik, en starten/pauzeren/stoppen staan op tablet toch
	 * in de bovenbalk. Alleen bij het openen: daarna beslist de gebruiker.
	 */
	let paneelOpen = $state(true);
	// De muispositie leeft in het canvas maar hoort in de statusbalk: dat is
	// waar je hem zoekt.
	let muisMm = $state<{ x: number; y: number } | null>(null);
	/** Hoogte van de actiebalk plus de vellenbalk; de alarmkaart hangt eronder. */
	let bovenrandHoogte = $state(0);
	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.style.setProperty('--topedge-height', `${bovenrandHoogte}px`);
		return () => document.documentElement.style.removeProperty('--topedge-height');
	});
	/** Materiaal waarmee het testrastervenster opent, als je er vanuit de
	    bibliotheek naartoe springt. */
	let gridMateriaal = $state<number | null>(null);

	// Het wauw-moment. Alleen op de flank van niet-draaiend naar draaiend, en
	// daarna weer weg — anders is het decoratie in plaats van een bericht.
	let wauw = $state(false);
	let liep = false;
	function vier() {
		wauw = true;
		setTimeout(() => (wauw = false), 900);
		// Het enige moment waarop de toestemmingsvraag ergens op slaat: er brandt
		// nu iets, dus er valt straks iets te melden. Bij het laden van de app zou
		// dezelfde ask zonder aanleiding komen — en die weigering is definitief.
		if (notifications.shouldAsk) vraagOpen = true;
		watchdog.started();
	}
	control.onStarted = vier;
	$effect(() => {
		const nu = Boolean(status.activeJob?.running);
		// Ook als iemand anders startte (telefoon, console) hoort het te vieren.
		if (nu && !liep) vier();
		liep = nu;
	});
	// Wat er op de gekozen afbeelding aanstaat. Komt van de API, want het recept
	// leeft op de node in de engine — niet in de browser.
	let imageState = $state<Record<string, unknown> | null>(null);

	async function loadImageState() {
		const id = design.selectedId;
		const element = design.elements.find((e) => e.id === id);
		if (!id || !element?.image) {
			imageState = null;
			return;
		}
		const response = await fetch(`/api/design/elements/${encodeURIComponent(id)}/image`);
		imageState = response.ok ? await response.json() : null;
	}

	async function setImage(body: Record<string, unknown>) {
		const id = design.selectedId;
		if (!id) return;
		await post(`/api/design/elements/${encodeURIComponent(id)}/image`, body);
		await design.load();
		await loadImageState();
	}
	let libraryOpen = $state(false);
	let catalogueOpen = $state(false);
	let generatorsOpen = $state(false);
	let clipartOpen = $state(false);
	const sheets = new SheetStore(() => localStorage.getItem('openkerf.token') ?? '');
	let calibrateOpen = $state(false);
	const camera = new CameraStore(() => localStorage.getItem('openkerf.token') ?? '');
	const catalogue = new PresetariatStore(() => localStorage.getItem('openkerf.token') ?? '');
	const tiling = new TilingStore(token);
	/** Een handeling die het huidige werk vervangt, in afwachting van een ja. */
	type Vervanging =
		| { soort: 'bestand'; file: File }
		| { soort: 'project'; file: File }
		| { soort: 'nieuw' };
	let pending = $state<Vervanging | null>(null);
	/** Tijdstip van het herstelbestand dat deze handeling zou overleven. */
	let herstelbaar = $state<string | null>(null);
	/** Welke ask er nu staat; een laat antwoord op een oudere telt niet mee. */
	let vraagTeller = 0;
	// Werk van een vorige sessie. Nooit stilzwijgend terugladen: wie met een
	// leeg canvas wil beginnen, moet dat kunnen.
	let recovery = $state<{ exists: boolean; when: string | null } | null>(null);
	let textOpen = $state(false);
	let textAt = $state<{ x: number; y: number } | null>(null);
	let editingText = $state<string | null>(null);
	let estimate = $state<number | null>(null);
	let gridOpen = $state(false);
	let versRaster = $state<number | null>(null);
	/** Het materiaal van het huidige vel wijzigen (besluit B1). */
	let materiaalOpen = $state(false);
	let velMateriaal = $derived(
		library.materials.find((m) => m.id === sheets.active?.material_id)?.name ?? null
	);

	// Undo gooit de id's van de engine weg (herstelde nodes komen terug zonder
	// id en krijgen bij hernummeren andere). Een bewaarde selectie zou daarna
	// een ánder element kunnen aanwijzen, dus die laten we los.
	async function history(action: 'undo' | 'redo') {
		const result = action === 'undo' ? await edits.undo() : await edits.redo();
		if (result.idsInvalidated) design.select(null);
		await design.load();
	}

	async function setPosition(x: number, y: number) {
		const box = design.selectedSize;
		if (!box || !hasSelection || !canEdit) return;
		await edits.move(design.selectedIds, x - box.x, y - box.y);
		await design.load();
	}

	async function setSize(width: number, height: number) {
		const box = design.selectedSize;
		if (!box || !hasSelection || !canEdit) return;
		await edits.resize(design.selectedIds, box.x, box.y, width, height);
		await design.load();
	}

	async function nudge(dx: number, dy: number) {
		if (!hasSelection || !canEdit) return;
		await edits.move(design.selectedIds, dx, dy);
		await design.load();
	}

	/**
	 * Openen vervangt, het voegt niet toe.
	 *
	 * De engine laadt een bestand bovenop wat er al staat. Dat is soms handig
	 * maar het is niet wat "openen" betekent, dus maken we eerst leeg — en
	 * shouldAsk we het eerst als daarmee werk zou verdwijnen.
	 *
	 * De ask hing aan `dirty`, en dat is één stap te streng. Een net
	 * geïmporteerde tekening staat op `dirty === false` (`/api/job/load` roept
	 * `document.clean()` aan — terecht, hij is gelijk aan het bestand), en er is
	 * op dat moment ook geen autosave. Gemeten: importeer een tekening, importeer
	 * er nog een, en de eerste is weg — zonder ask, zonder melding, zonder iets
	 * om op terug te vallen. Wat op het bed ligt is werk, of het nu getypt of
	 * geopend is; shouldAsk doen we dus zodra er iets ligt.
	 */
	async function openFile(file: File) {
		if (!canEdit) return;
		await misschienEerstVragen({ soort: 'bestand', file });
	}

	/**
	 * Elke handeling die het huidige werk vervangt, stelt dezelfde ask.
	 *
	 * Openen van een bestand deed dat al; een projectbestand openen ging er
	 * zonder één woord overheen — inclusief de vellen, want die komen uit het
	 * bestand mee. Dat is de ergste vorm: stil werk weggooien.
	 *
	 * Wat "werk" is verschilt per handeling. Een bestand komt op dít vel, dus
	 * daar telt alleen dit vel. Een project en opnieuw beginnen vervangen álle
	 * vellen, dus dan telt de doos van gisteren ook mee, ook als het vel dat je
	 * nu ziet leeg is.
	 */
	async function misschienEerstVragen(actie: Vervanging) {
		const raaktAlleVellen = actie.soort !== 'bestand';
		const erLigtWerk = !design.isEmpty || (raaktAlleVellen && sheets.sheets.length > 1);
		if (!erLigtWerk) {
			await voerUit(actie);
			return;
		}
		herstelbaar = null;
		pending = actie;
		// Wat er ná deze handeling nog terug te halen is, verandert wat je
		// kiest — dus staat het in de ask. Alleen bij een gewijzigd ontwerp:
		// een ontwerp dat gelijk is aan een bestand op schijf laat het
		// herstelbestand juist opruimen (`autosave.forget_if_saved`), dus dan
		// zou de belofte niet kloppen.
		if (!design.dirty) return;
		// Een teller en geen vergelijking met `actie`: `$state` levert een proxy
		// terug, dus `pending === actie` is altijd onwaar en het antwoord kwam
		// nooit aan. Gemeten: autosave bestond, ontwerp was vuil, en de regel
		// bleef weg.
		const nummer = ++vraagTeller;
		const response = await fetch('/api/design/autosave');
		if (!response.ok) return;
		const staat = await response.json();
		if (vraagTeller === nummer && pending !== null && staat.exists) herstelbaar = staat.when;
	}

	/** Opnieuw beginnen. Zie `/api/project/new`: de bibliotheek blijft staan. */
	async function newProject() {
		if (!canEdit) return;
		await misschienEerstVragen({ soort: 'nieuw' });
	}

	async function voerUit(actie: Vervanging) {
		if (actie.soort === 'bestand') {
			await replaceWith(actie.file);
		} else if (actie.soort === 'project') {
			await laadProject(actie.file);
		} else {
			const response = await fetch('/api/project/new', {
				method: 'POST',
				headers: authHeaders()
			});
			if (!response.ok) return;
			design.select(null);
			await Promise.all([design.load(), sheets.load()]);
		}
	}

	function authHeaders(): Record<string, string> {
		const token = localStorage.getItem('openkerf.token') ?? '';
		return token ? { Authorization: `Bearer ${token}` } : {};
	}

	/** Schrijfroutes dragen het token; één plek in plaats van bij elke aanroep. */
	async function post(path: string, body: unknown) {
		const token = localStorage.getItem('openkerf.token') ?? '';
		return fetch(path, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			},
			body: JSON.stringify(body)
		});
	}

	async function openProject(file: File) {
		if (!canEdit) return;
		await misschienEerstVragen({ soort: 'project', file });
	}

	/** Een project draagt ook de bibliotheek-context, dus eigen route. */
	async function laadProject(file: File) {
		const form = new FormData();
		form.append('file', file);
		const token = localStorage.getItem('openkerf.token') ?? '';
		const response = await fetch('/api/project/open', {
			method: 'POST',
			headers: token ? { Authorization: `Bearer ${token}` } : {},
			body: form
		});
		if (response.ok) {
			design.select(null);
			await Promise.all([design.load(), library.load(), sheets.load()]);
		}
	}

	async function replaceWith(file: File) {
		if (!design.isEmpty) {
			if (!(await edits.clear()).ok) return;
		}
		if (await control.load(file)) {
			design.select(null);
			await design.load();
		}
	}

	/** Plaatsen voegt toe: de engine laadt bovenop wat er al staat. */
	async function placeImage(file: File) {
		if (!canEdit) return;
		if (await control.load(file)) await design.load();
	}

	async function saveThenOpen() {
		const actie = pending;
		pending = null;
		if (!actie) return;
		// Downloaden telt als saving: de API markeert het ontwerp schoon.
		// Wat er weg zou gaan bepaalt wat je bewaart: bij een bestand is dat
		// dit vel, bij een project en bij opnieuw beginnen gaan álle vellen
		// weg — dan is een SVG van het actieve vel geen redding maar een
		// halve.
		//
		// Wachten tot het bestand er werkelijk is, en niet 800 ms hopen: het
		// volgende dat gebeurt, gooit het bed leeg. Mislukt het saving, dan
		// gaat het leegmaken niet door en staat het venster er nog.
		const opgeslagen =
			actie.soort === 'bestand'
				? await bewaarBestand('/api/design/export.svg', 'ontwerp.svg')
				: await bewaarBestand('/api/project/export.openkerf', 'project.openkerf');
		if (!opgeslagen) {
			pending = actie;
			return;
		}
		await design.load();
		await voerUit(actie);
	}

	async function draw(shape: Record<string, unknown>) {
		if (!canEdit) return;
		const result = await edits.draw(shape);
		if (result.ok) {
			await design.load();
			// Terug naar selecteren: één vorm per klik is voorspelbaarder dan
			// per ongeluk een rij vormen achterlaten.
			tool = 'select';
		}
	}

	async function removeSelection() {
		if (!hasSelection || !canEdit) return;
		if (await edits.remove(design.selectedIds)) {
			design.select(null);
			await design.load();
		}
	}

	async function duplicateSelection() {
		if (!hasSelection || !canEdit) return;
		if (await edits.duplicate(design.selectedIds)) await design.load();
	}

	/** Wat de last hoekbewerking te melden had; het paneel toont het. */
	let hoekMelding = $state<string | null>(null);
	/** Wat de last indeel-handeling deed (splitsen, laag, opruimen). */
	let indeelMelding = $state<string | null>(null);

	async function hoeken(style: 'round' | 'chamfer', sizeMm: number) {
		if (!canEdit || !hasSelection) return;
		hoekMelding = null;
		const uitkomst = await edits.corners(design.selectedIds, style, sizeMm);
		if (!uitkomst) return;
		if (uitkomst.paths.length) {
			// Chamfered shapes have become paths and have a new id; the old selection
			// points at something that no longer exists.
			design.select(null);
		}
		await design.load();
		if (uitkomst.skipped) {
			hoekMelding = t('notice.corners.skipped', { n: uitkomst.skipped });
		}
	}

	async function splitsen() {
		if (!canEdit || !hasSelection) return;
		indeelMelding = null;
		const uitkomst = await edits.split(design.selectedIds);
		if (!uitkomst) return;
		// The pieces are new elements; the old selection points at a path that has
		// been replaced by a group.
		design.select(null);
		await design.load();
		if (uitkomst.count) {
			design.selectMany(uitkomst.ids);
			indeelMelding = t('notice.split.done', { n: uitkomst.count });
		} else {
			indeelMelding = t('notice.split.nothing');
		}
	}

	/**
	 * Making an area out of the selection, or taking it away.
	 *
	 * Without a fill a shape only rasters its outline — measured: 8 % of the area
	 * black instead of over 90 %. Hence this is a button of its own and not a side
	 * effect of "into the raster layer".
	 */
	async function vullen(filled: boolean) {
		if (!canEdit || !hasSelection) return;
		indeelMelding = null;
		const uitkomst = await edits.fill(design.selectedIds, filled);
		if (!uitkomst) return;
		await design.load();
		const aantal = filled ? uitkomst.filled : uitkomst.cleared;
		indeelMelding =
			t(filled ? 'notice.fill.filled' : 'notice.fill.cleared', { n: aantal }) +
			(uitkomst.skipped ? ` ${t('notice.fill.skipped', { n: uitkomst.skipped })}` : '');
	}

	async function naarEenLaag(kind: 'cut' | 'engrave' | 'raster') {
		if (!canEdit || !hasSelection) return;
		indeelMelding = null;
		const uitkomst = await edits.singleLayer(design.selectedIds, kind);
		if (!uitkomst) return;
		await design.load();
		const laag = design.operations.find((o) => o.id === uitkomst.operation_id);
		const naam =
			laag?.label ??
			t(
				({
					cut: 'panel.kind.cut',
					engrave: 'panel.kind.engrave',
					raster: 'panel.kind.raster'
				} as const)[kind]
			);
		const hoeveel = uitkomst.assigned || design.selectedIds.length;
		indeelMelding = t('notice.layer.assigned', {
			n: hoeveel,
			layer: t(uitkomst.created ? 'notice.layer.newLayer' : 'notice.layer.existing', { name: naam }),
			removed: uitkomst.removed ? t('notice.layer.removedFrom', { n: uitkomst.removed }) : ''
		});
	}

	async function opruimen() {
		if (!canEdit) return;
		indeelMelding = null;
		const uitkomst = await edits.prune();
		if (!uitkomst) return;
		await design.load();
		indeelMelding = uitkomst.removed
			? t('notice.prune.done', { n: uitkomst.removed })
			: t('notice.prune.none');
	}

	async function arrange(action: string) {
		// 'rescue' works on the whole design; the rest on the selection.
		if (!canEdit || (!hasSelection && action !== 'rescue')) return;
		const ids = design.selectedIds;
		if (action === 'offset') {
			// De ask staat in een eigen venster (`Offset.svelte`); hier stond een
			// `window.prompt`, en die viel buiten het thema én valideerde niets.
			offsetOpen = true;
			return;
		}
		if (action === 'rescue') {
			// Alles op het bed leggen, ook wat je niet kunt aanwijzen omdat het
			// buiten beeld ligt.
			await post('/api/design/nest', {
				ids: design.elements.filter((e) => !e.hidden).map((e) => e.id),
				margin_mm: 5
			});
			await design.load();
			return;
		}
		if (action === 'nest') {
			await post('/api/design/nest', { ids, margin_mm: 3 });
			await design.load();
			return;
		}
		if (action === 'simplify' || action === 'hatch' || action === 'wobble') {
			const result =
				action === 'simplify' ? await edits.simplify(ids) : await edits.effect(ids, action);
			if (result.ok) await design.load();
			return;
		}
		const result =
			action === 'group'
				? await edits.group(ids)
				: action === 'ungroup'
					? await edits.ungroup(ids)
					: action === 'mirror-h'
						? await edits.mirror(ids, 'horizontal')
						: action === 'mirror-v'
							? await edits.mirror(ids, 'vertical')
							: ['union', 'difference', 'intersection', 'xor'].includes(action)
								? await edits.boolean(ids, action)
								: await edits.align(ids, action);
		if (result.ok) {
			// Booleaans levert een nieuw pad op; de oude selectie bestaat niet meer.
			if (action === 'ungroup' || ['union', 'difference', 'intersection', 'xor'].includes(action))
				design.select(null);
			await design.load();
		}
	}

	async function rotate(angleDeg: number) {
		if (!hasSelection || !canEdit) return;
		await edits.rotate(design.selectedIds, angleDeg);
		await design.load();
	}

	async function assign(operationId: string, assigned: boolean) {
		if (!hasSelection || !canEdit) return;
		const result = assigned
			? await edits.assign(design.selectedIds, operationId)
			: await edits.unassign(design.selectedIds, operationId);
		if (result.ok) await design.load();
	}
	// De tab staat in de URL, zodat de terugknop en een bladwijzer werken.
	// Lokale state is de bron van waarheid, de URL volgt. Andersom werkt niet:
	// replaceState maakt $page.url niet reactief, waardoor het paneel op de
	// oude tab bleef staan terwijl de URL wél meeliep.
	let tab = $state<'design' | 'layers' | 'job'>('job');

	function selectTab(next: 'design' | 'layers' | 'job') {
		tab = next;
		syncUrl();
	}

	function syncUrl() {
		const url = new URL(window.location.href);
		url.searchParams.set('tab', tab);
		if (design.selectedIds.length) url.searchParams.set('select', design.selectedIds.join(','));
		else url.searchParams.delete('select');
		replaceState(url, {});
	}

	let preflight = $state(false);

	let device = $derived(status.device);
	let telefoonPositie = $derived(
		device?.position.mm
			? `${device.position.mm[0].toFixed(1)}, ${device.position.mm[1].toFixed(1)} mm`
			: '—'
	);
	// Niet `state` noemen: `$state` zou dan als store-referentie gelezen worden.
	let machine = $derived(machineState(device, status.connected));
	/**
	 * De fase van de job, uit dezelfde functie die het Job-paneel gebruikt.
	 *
	 * De bovenbalk las hiervóór de machinetoestand (`machine === 'busy'`) en het
	 * paneel `job.running`. Bij een job die gespoold is maar nog niet opgepakt zijn
	 * die twee het oneens, en dan set de ene knop uit wat de andere aanbiedt —
	 * gemeten met een niet-antwoordende machine: de balk zette starten uit, het
	 * paneel liet het aan staan. Eén functie, één antwoord.
	 */
	let phase = $derived(jobPhase(device, status.activeJob, design.isEmpty));
	let workUnderWay = $derived(jobBusy(phase));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		camera.load();
		sheets.load();
		library.load();
		leesKlembord();
		if (window.innerWidth < 850) paneelOpen = false;
		const wantedTab = $page.url.searchParams.get('tab');
		if (wantedTab === 'design' || wantedTab === 'layers') tab = wantedTab;
		design.load().then(async () => {
			// Alleen aanbieden als er niets staat: over bestaand werk heen
			// terugzetten geeft een mengelmoes, en dat weigert de API ook.
			if (design.isEmpty) {
				const response = await fetch('/api/design/autosave');
				if (response.ok) {
					const state = await response.json();
					if (state.exists) recovery = state;
				}
			}
			const wanted = $page.url.searchParams.get('select');
			if (wanted) {
				const ids = wanted.split(',').filter(Boolean);
				design.select(ids[0] ?? null);
				ids.slice(1).forEach((id) => design.toggle(id));
			}
		});
		// Pas ná mount koppelen: replaceState vóórdat de router klaar is breekt
		// de render. De URL volgt daarom de actie, niet een effect.
		design.onSelect = () => {
			syncUrl();
			loadImageState();
		};
		// De beschikbare acties hangen af van het actieve device, dus opnieuw
		// ophalen zodra de gebruiker in MeerK40t van machine wisselt.
		const poll = setInterval(() => control.refreshCapabilities(), 10_000);
		// De permission kan buiten ons om wijzigen: wie hem in de site-instellingen
		// van de browser terugzet, verwacht niet dat hij daarna moet verversen.
		const reread = () => notifications.read();
		window.addEventListener('focus', reread);
		document.addEventListener('visibilitychange', reread);
		return () => {
			clearInterval(poll);
			window.removeEventListener('focus', reread);
			document.removeEventListener('visibilitychange', reread);
			status.close();
		};
	});

	// De engine seint dat de elementenboom wijzigde; dan pas opnieuw ophalen.
	// De store slikt bursts zelf, dus een signaal per wijziging is prima.
	$effect(() => {
		const latest = status.events[0];
		if (latest && isDesignSignal(latest.code)) design.load();
	});

	// Alarmsignalen uit de engine (`pipe;usb_status`) en de tweesecondensnapshot:
	// twee losse bronnen, dus twee losse effecten.
	$effect(() => {
		const latest = status.events[0];
		if (latest) watchdog.signal(latest);
	});
	$effect(() => {
		watchdog.status(status.device, status.connected);
	});
	// Dezelfde socket draagt de stand van een lopende tegelreeks; de bovenbalk,
	// het canvas en de telefoon lezen straks allemaal deze ene bron.
	$effect(() => {
		tiling.adopt(status.snapshot?.tiling ?? null);
	});
	/**
	 * De opdeling ophalen, en opnieuw zodra iets eraan verandert.
	 *
	 * De opdeling wordt op de server berekend en nooit opgeslagen, dus hij moet
	 * hier opgevraagd worden — en dat gebeurde nergens. Gevolg: `tiling.layout`
	 * bleef leeg, en dan tekent het canvas geen naden, geen merken en geen
	 * gedimde tegels, en weet het paneel niet hoe ver de plaat moet opschuiven.
	 * Alles klopte, er kwam alleen nooit iets in.
	 *
	 * Hij hangt aan het aantal elementen, het actieve vel en de stand van de
	 * reeks: dat zijn precies de drie dingen die de opdeling kunnen verzetten.
	 */
	$effect(() => {
		void design.elements.length;
		void sheets.active?.id;
		void tiling.run?.current;
		// Alleen ophalen als tegels ook kunnen spelen: een plaat die groter is dan
		// het bed, of een reeks die al loopt. Zonder die rem gaat er bij elke
		// wijziging in het ontwerp een verzoek uit dat vrijwel altijd 409't.
		const vel = sheets.active;
		const bed = device?.bed;
		const teGroot =
			Boolean(vel && bed) &&
			(vel!.width_mm > (bed!.width_mm ?? 0) || vel!.height_mm > (bed!.height_mm ?? 0));
		if (teGroot || tiling.run) tiling.load();
	});

	// ─── Klembord, menu's en sneltoetsen ──────────────────────────────────────
	//
	// Alles hieronder hangt aan één lijst: `$lib/acties.ts`. De actiebalk boven
	// het canvas, het rechterklikmenu en het toetsenbord lezen daar dezelfde
	// namen, dezelfde sneltoetsen en dezelfde redenen-waarom-niet uit. Dat is
	// het hele point: hiervóór stond elke handeling op precies één plek, en dus
	// was er geen tweede plek waar hij hetzelfde kon heten.

	/** Hoeveel vormen op het klembord staan; het menu moet weten of plakken kan. */
	let klembord = $state(0);
	async function leesKlembord() {
		const response = await fetch('/api/design/clipboard');
		if (response.ok) klembord = (await response.json()).count ?? 0;
	}

	async function klembordActie(wat: 'copy' | 'cut', ids: string[]) {
		if (!ids.length || !canEdit) return;
		const response = await post(`/api/design/clipboard/${wat}`, { ids });
		if (!response.ok) return;
		klembord = (await response.json()).count ?? 0;
		if (wat === 'cut') {
			design.select(null);
			await design.load();
		}
	}

	async function plakken(point?: { x: number; y: number }) {
		if (!canEdit || !klembord) return;
		const response = await post('/api/design/clipboard/paste', {
			x_mm: point?.x ?? null,
			y_mm: point?.y ?? null
		});
		if (!response.ok) return;
		const uitkomst = await response.json().catch(() => null);
		await design.load();
		if (uitkomst?.ids?.length) design.selectMany(uitkomst.ids);
	}

	/** Het handvat waarmee de zoomstanden van het canvas hier te bedienen zijn. */
	let canvasControl = $state<{
		zoom: (what: 'all' | 'selection' | 'bed' | 'hundred') => void;
		step: (factor: number) => void;
		snap: () => void;
		layerNumbers: () => void;
		state: () => { snap: boolean; layerNumbers: boolean };
	} | null>(null);

	let hoekenOpen = $state(false);
	let offsetOpen = $state(false);

	/** Welk menu er open staat, en waar. */
	let menu = $state<{ lijst: MenuList; x: number; y: number } | null>(null);
	/** Waar er op het bed geklikt werd — "plakken hier" belooft die plek. */
	let menuPunt = $state<{ x: number; y: number } | null>(null);

	let handlers: Handlers = {
		cut: () => klembordActie('cut', design.selectedIds),
		copy: () => klembordActie('copy', design.selectedIds),
		paste: (at) => plakken(at),
		duplicate: duplicateSelection,
		remove: removeSelection,
		selectAll: () =>
			design.selectMany(design.elements.filter((el) => !el.hidden).map((el) => el.id)),
		clearSelection: () => design.select(null),
		arrange: (mode) => arrange(mode),
		rotate: (degrees) => rotate(degrees),
		split: splitsen,
		fill: (on) => vullen(on),
		corners: () => (hoekenOpen = true),
		onlyLayer: (kind) => naarEenLaag(kind),
		assignLayer: (id, inside) => assign(id, inside),
		toSheet: async (id) => {
			if (await sheets.move(design.selectedIds, id)) {
				design.select(null);
				await design.load();
			}
		},
		editText: () => {
			editingText = design.selectedId;
			textOpen = true;
		},
		crop: () => (cropping = true),
		uncrop: async () => {
			const id = design.selectedId;
			if (!id) return;
			await fetch(`/api/design/elements/${encodeURIComponent(id)}/crop`, {
				method: 'DELETE',
				headers: authHeaders()
			});
			await design.load();
			await loadImageState();
		},
		vectorise: async () => {
			const id = design.selectedId;
			if (!id) return;
			await post(`/api/design/elements/${encodeURIComponent(id)}/vectorise`, {
				method: 'vectrace'
			});
			await design.load();
		},
		undo: () => history('undo'),
		redo: () => history('redo'),
		zoom: (what) => canvasControl?.zoom(what),
		snap: () => canvasControl?.snap(),
		layerNumbers: () => canvasControl?.layerNumbers(),
		rescue: () => arrange('rescue')
	};

	/** De toestand waarin een handeling wel of niet kan. */
	let actionContext = $derived.by<ActionContext>(() => {
		const chosen = design.elements.filter((e) => design.isSelected(e.id));
		const image = chosen.length === 1 && Boolean(chosen[0]?.image);
		const state = canvasControl?.state();
		return {
			count: chosen.length,
			inGroup: chosen.some((e) => Boolean(e.group_id)),
			isImage: image,
			isText: chosen.length === 1 && chosen[0]?.text !== null,
			isCropped: image && Boolean(imageState?.cropped),
			filled: chosen.length > 0 && chosen.every((e) => Boolean(e.fill)),
			clipboard: klembord,
			busy: edits.busy,
			may: canEdit,
			layers: design.operations
				.filter((op) => !op.grid)
				.map((op) => ({
					id: op.id,
					label: op.label,
					inside: design.selectedIds.every((id) => op.element_ids.includes(id))
				})),
			sheets: sheets.sheets
				.filter((sheet) => !sheet.active)
				.map((sheet) => ({ id: sheet.id, name: sheet.name })),
			splittable: {
				shapes: chosen.filter((e) => (e.subpaths ?? 1) > 1).length,
				pieces: chosen.reduce((n, e) => n + ((e.subpaths ?? 1) > 1 ? (e.subpaths ?? 1) : 0), 0)
			},
			snap: state?.snap ?? true,
			layerNumbers: state?.layerNumbers ?? true,
			empty: design.isEmpty
		};
	});

	function openObjectMenu(event: MouseEvent) {
		menuPunt = null;
		menu = { lijst: objectMenu(actionContext, handlers), x: event.clientX, y: event.clientY };
	}

	function openCanvasMenu(event: MouseEvent, point: { x: number; y: number }) {
		menuPunt = point;
		menu = {
			lijst: canvasMenu(actionContext, handlers, point),
			x: event.clientX,
			y: event.clientY
		};
	}

	/**
	 * Eén tabel, één afhandelaar.
	 *
	 * Hiervóór stonden de sneltoetsen op twee plekken — hier en in `Canvas` — en
	 * ontbraken de toetsen die iedere desktop-app heeft: ⌘Z deed niets, ⌘C en ⌘V
	 * bestonden niet, ⌘G niet. Wat wel of niet af te vangen is in een browser
	 * staat toegelicht bij `KEYS`.
	 */
	function sneltoets(event: KeyboardEvent) {
		const doel = event.target as HTMLElement | null;
		if (doel?.closest('input, textarea, select, [contenteditable="true"]')) return;
		if (menu) return; // the menu handles its own keys
		const combo = comboOf(event);

		if (combo === 'escape') {
			design.select(null);
			return;
		}

		const run: Record<string, () => void> = {
			[KEYS.undo]: handlers.undo,
			[KEYS.redo]: handlers.redo,
			[KEYS.cut]: handlers.cut,
			[KEYS.copy]: handlers.copy,
			[KEYS.paste]: () => handlers.paste(),
			[KEYS.duplicate]: handlers.duplicate,
			[KEYS.delete]: handlers.remove,
			[KEYS.selectAll]: handlers.selectAll,
			[KEYS.group]: () => handlers.arrange('group'),
			[KEYS.ungroup]: () => handlers.arrange('ungroup'),
			[KEYS.ungroupAlt]: () => handlers.arrange('ungroup'),
			[KEYS.mirrorH]: () => handlers.arrange('mirror-h'),
			[KEYS.mirrorV]: () => handlers.arrange('mirror-v'),
			[KEYS.rotateLeft]: () => handlers.rotate(-90),
			[KEYS.rotateRight]: () => handlers.rotate(90),
			[KEYS.zoomHundred]: () => handlers.zoom('hundred'),
			[KEYS.zoomSelection]: () => handlers.zoom('selection'),
			[KEYS.zoomAll]: () => handlers.zoom('all'),
			[KEYS.zoomBed]: () => handlers.zoom('bed'),
			[KEYS.zoomAllOld]: () => handlers.zoom('all'),
			[KEYS.zoomSelectionOld]: () => handlers.zoom('selection'),
			[KEYS.zoomSelectionLightburn]: () => handlers.zoom('selection'),
			[KEYS.zoomIn]: () => canvasControl?.step(1.25),
			[KEYS.zoomOut]: () => canvasControl?.step(1 / 1.25)
		};
		const action = run[combo];
		if (action) {
			event.preventDefault();
			action();
			return;
		}

		// Pijltjes verplaatsen 0,1 mm; met shift 1 mm (toegankelijkheidseis).
		const step = event.shiftKey ? 1 : 0.1;
		const moves: Record<string, [number, number]> = {
			ArrowLeft: [-step, 0],
			ArrowRight: [step, 0],
			ArrowUp: [0, -step],
			ArrowDown: [0, step]
		};
		const move = moves[event.key];
		if (move && hasSelection && canEdit) {
			event.preventDefault();
			nudge(move[0], move[1]);
		}
	}

	function requestStart() {
		selectTab('job');
		preflight = true;
	}

	function toggleTheme() {
		const root = document.documentElement;
		root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
	}
</script>

<svelte:window bind:innerWidth={breedte} onkeydown={sneltoets} />

{#if telefoon}
	<!-- De telefoon is een eigen app: monitor en noodrem. Zie DESIGN-SYSTEM v2,
	     "Drie apparaten, drie apps". -->
	<PhoneView
		{device}
		state={machine}
		job={status.activeJob}
		{control}
		{camera}
		{notifications}
		{watchdog}
		connected={status.connected}
		position={telefoonPositie}
		{design}
		sheet={sheets.active
			? {
					name: sheets.active.name,
					width_mm: sheets.active.width_mm,
					height_mm: sheets.active.height_mm
				}
			: null}
	/>
{:else}
<AlarmCard watchdog={watchdog} />
<TopBar
	{device}
	state={machine}
	canStart={(control.capabilities?.actions.start ?? false) &&
		!control.needsToken &&
		!workUnderWay}
	canStop={(control.capabilities?.actions.stop ?? false) && !control.needsToken}
	stopArmed={workUnderWay}
	canEdit={canEdit && design.preview === null}
	{smal}
	canPause={(control.capabilities?.actions.pause ?? false) && !control.needsToken}
	canResume={(control.capabilities?.actions.resume ?? false) && !control.needsToken}
	paused={phase === 'paused'}
	onPause={() => control.pause()}
	onResume={() => control.resume()}
	onStart={requestStart}
	onStop={() => control.stop()}
	onOpenFile={openFile}
	onOpenProject={openProject}
	onNewProject={newProject}
	onSaved={() => design.load()}
	material={velMateriaal}
	thicknessMm={sheets.active?.thickness_mm ?? null}
	onOpenMaterial={() => (materiaalOpen = true)}
	canFrame={(design.elements?.length ?? 0) > 0 &&
		(control.capabilities?.motion?.move ?? false) &&
		!control.needsToken}
	onFrame={() => {
		// Geen dialoog: dit is een controlebeweging, geen onomkeerbare stap.
		// Via de controller, zodat een klagende machine in beeld komt.
		control.frame();
	}}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail
		compact={tablet}
		bestanden={smal}
		{projectInRail}
		bind:tool
		{canEdit}
		onOpenGrid={() => (gridOpen = true)}
		onOpenLibrary={() => (libraryOpen = true)}
		onOpenCatalogue={() => (catalogueOpen = true)}
		onOpenGenerators={() => (generatorsOpen = true)}
		onOpenClipart={() => (clipartOpen = true)}
		onPlaceImage={placeImage}
		onOpenFile={openFile}
		onOpenProject={openProject}
		onNewProject={newProject}
		onSaved={() => design.load()}
	/>
	<!-- Vellen boven het canvas: elk vel is een eigen document, dus dit is
	     ook de plek waar je ziet welk stuk materiaal je nu bewerkt. -->
	<div class="stage">
		<!-- Alles tussen de bovenbalk en het canvas meet zichzelf op.
		     De alarmkaart hangt onder de bovenbalk en dekte since de vorige ronde de
		     actiebalk en de vellenbalk af — precies de twee dingen die je nodig hebt
		     terwijl er een melding staat. Gemeten met een USB-failure: de kaart lag over
		     de uitlijnknoppen en over de plus van de vellenbalk, en Playwright kon er
		     niet doorheen klikken. Dezelfde aanpak als `--palet-hoogte` onder het
		     canvas: opmeten, niet uitrekenen. -->
		<div class="bovenrand" bind:clientHeight={bovenrandHoogte}>
		<!-- Uitlijnen, groeperen, spiegelen en de geschiedenis: werkwoorden op de
		     selectie, dus tegen het bed aan en niet in het eigenschappenpaneel.
		     Zie DESIGN-SYSTEM v4, "Waar hoort een handeling". -->
		<ActionBar
			history={historyActions(actionContext, handlers)}
			align={alignActions(actionContext, handlers)}
			arrange={arrangeActions(actionContext, handlers)}
			count={actionContext.count}
			onMore={(event: MouseEvent) => {
				const doos = (event.currentTarget as HTMLElement).getBoundingClientRect();
				menuPunt = null;
				menu = {
					lijst: objectMenu(actionContext, handlers),
					x: doos.left,
					y: doos.bottom + 4
				};
			}}
		/>
		<SheetTabs
			{sheets}
			{library}
			{canEdit}
			elementen={design.elements?.length ?? 0}
			onEditMaterial={() => (materiaalOpen = true)}
			onSwitched={async () => {
				design.select(null);
				await design.load();
			}}
		/>
		</div>
		<Canvas
			onPointerMm={(point) => (muisMm = point)}
			onContextObject={openObjectMenu}
			onContextCanvas={openCanvasMenu}
			bind:control={canvasControl}
			{device}
			{design}
			{edits}
			{canEdit}
			{tool}
			onEdited={() => design.load()}
			onDrawn={draw}
			onTextAt={(at) => {
				textAt = at;
				textOpen = true;
			}}
			cameraSrc={camera.src}
			cameraOpacity={camera.opacity}
			{tiling}
			sheet={sheets.active
				? {
						name: sheets.active.name,
						width: sheets.active.width_mm,
						height: sheets.active.height_mm
					}
				: null}
			sheetId={sheets.active?.id ?? null}
			onPath={async (points, closed) => {
				if (!canEdit) return;
				await post('/api/design/path', { points, closed });
				await design.load();
			}}
			bind:cropping
			onCrop={async (rect) => {
				const id = design.selectedId;
				if (!id) return;
				await post(`/api/design/elements/${encodeURIComponent(id)}/crop`, {
					x_mm: rect.x,
					y_mm: rect.y,
					width_mm: rect.width,
					height_mm: rect.height
				});
				await design.load();
				await loadImageState();
			}}
		/>
		{#if wauw}
			<!-- Eén keer, bij het starten: daar gebeurt het ook echt. -->
			<JobStart label={status.activeJob?.label ?? null} />
		{/if}
	</div>

	{#if tablet}
	<!-- Op een tablet is 280 van 1024 pixels een kwart van je werkblad. Het
	     paneel mag weg als je aan het tekenen bent; de machineknoppen staan
	     in de bovenbalk, dus je raakt de laser nooit kwijt. -->
	<button
		class="paneelgreep"
		aria-expanded={paneelOpen}
		onclick={() => (paneelOpen = !paneelOpen)}
	>
		<!-- De greep is de pil, niet de kolom. De knop blijft 44px breed omdat een
		     duim dat nodig heeft, maar hij is doorzichtig: ingeklapt bleef er
		     anders een blanco strook van 44px langs de rand staan (gat B6), en
		     dat leest als een renderfout in plaats van als iets om aan te duwen. -->
		<span class="pil" aria-hidden="true">{paneelOpen ? '›' : '‹'}</span>
		<span class="vw">{paneelOpen ? t('panel.collapse') : t('panel.expand')}</span>
	</button>
{/if}
<aside class="panel" class:weg={tablet && !paneelOpen} aria-label={t('panel.aria')}>
		<!-- Het belletje staat wél in dezelfde rij maar buiten de tablist: een
		     tablist mag volgens ARIA alleen tabs bevatten, en axe rekende het
		     belletje anders als ontbrekend kind aan (aria-required-children). -->
		<div class="tabsrij">
		<div class="tabs" role="tablist">
			<button
				class="tab"
				role="tab"
				aria-selected={tab === 'design'}
				onclick={() => selectTab('design')}
			>
				{t('tabs.edit')}
				{#if tab === 'design'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
			<button
				class="tab"
				role="tab"
				aria-selected={tab === 'layers'}
				onclick={() => selectTab('layers')}
			>
				{t('tabs.layers')}
				{#if tab === 'layers'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
			<button class="tab" role="tab" aria-selected={tab === 'job'} onclick={() => selectTab('job')}>
				{t('tabs.job')}
				{#if tab === 'job'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
		</div>
			<!-- De vaste plek voor notifications. Naast de tabs en niet zwevend boven het
			     canvas: dit paneel gaat over déze machine, en dat is precies waar een
			     melding over gaat. Het belletje draagt zijn eigen toestand — uit of
			     geblokkeerd is iets wat je moet kunnen zien zonder te klikken. -->
			<button
				class="bell"
				class:quiet={!notifications.active}
				aria-haspopup="dialog"
				title={notifications.active ? t('tabs.notifications.on') : t('tabs.notifications.off')}
				aria-label={notifications.active ? t('tabs.notifications.onAria') : t('tabs.notifications.offAria')}
				onclick={() => (meldingenOpen = true)}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"
					stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
					<path d="M13.7 21a2 2 0 0 1-3.4 0" />
					{#if !notifications.active}
						<line x1="3" y1="3" x2="21" y2="21" />
					{/if}
				</svg>
			</button>
		</div>
		<div class="panel-scroll">
			{#if tab === 'design' || tab === 'layers'}
				<DesignPanel
					show={tab === 'layers' ? 'layers' : 'selection'}
					bed={device?.bed?.width_mm && device?.bed?.height_mm
						? { width: device.bed.width_mm, height: device.bed.height_mm }
						: null}
					{design}
					{edits}
					{canEdit}
					onRotate={rotate}
					onAssign={assign}
					onLayerChange={() => design.load()}
					box={design.liveBox}
					onSetPosition={setPosition}
					onSetSize={setSize}
					onArrange={arrange}
					cornerNote={hoekMelding}
					onPrune={opruimen}
					tidyNote={indeelMelding}
					image={imageState as never}
					onImageSet={(name, enabled, values) =>
						setImage({ adjustment: name, enabled, values })}
					onImageClear={() => setImage({ clear: true })}
					onImageDpi={async (dpi) => {
						const id = design.selectedId;
						if (!id) return;
						await post(`/api/design/elements/${encodeURIComponent(id)}/image`, { dpi });
						await design.load();
					}}
				/>
			{:else}
				<JobPanel
					{device}
					{tiling}
					events={status.events}
					{control}
					activeJob={status.activeJob}
					revisie={design.revision}
					bind:preflight
					onJog={async (dx, dy) => {
						await edits.jog(dx, dy);
					}}
					onHome={async () => {
						await edits.home();
					}}
					onUnlock={async () => {
						await edits.unlock();
					}}
					profile={library.activeMachine}
					onFrame={() => control.frame()}
					colorFor={(id) => design.colorFor(id)}
		onFocus={async (mm) => {
						await post('/api/machine/focus', { distance_mm: mm });
					}}
				/>
			{/if}
		</div>
	</aside>
</div>

<!-- Camerabediening bij het canvas, niet in het rechterpaneel: je kijkt naar
     het bed terwijl je hem aanzet. -->
{#if camera.state.available}
	<div class="camstrip">
		<button
			class="cam"
			aria-pressed={camera.shown && camera.state.running}
			disabled={camera.busy || !canEdit}
			title={canEdit ? t('camera.title') : t('reason.needsToken')}
			onclick={() => (camera.state.running && camera.shown ? camera.stop() : camera.start())}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h4l2-2h6l2 2h4v11H3z"/><circle cx="12" cy="13" r="3.5"/></svg>
			{t('camera.button')}
		</button>
		{#if camera.shown && camera.state.running}
			<input
				type="range"
				min="0.1"
				max="1"
				step="0.05"
				aria-label={t('camera.opacity')}
				bind:value={camera.opacity}
			/>
			<button class="cam" onclick={() => (calibrateOpen = true)}>
				{camera.state.calibrated ? t('camera.recalibrate') : t('camera.calibrate')}
			</button>
		{/if}
	</div>
	{#if camera.error}
		<!-- Een lange melding hoort niet in een pilvormige balk: die wordt dan een
		     blob. Eigen kader, leesbare regelbreedte, en zelf weg te klikken. -->
		<div class="camerror" role="alert">
			<p class="wrap">{camera.error}</p>
			<button aria-label={t('common.dismiss')} onclick={() => (camera.error = null)}>×</button>
		</div>
	{/if}
{/if}

<StatusBar
	pointerMm={muisMm}
	{device}
	machineState={machine}
	job={status.activeJob}
	connected={status.connected}
	{control}
	acties={!tablet}
/>
{/if}

<!-- Bibliotheken en gereedschappen als eigen venster: in 280px kun je niet
     zoeken en vergelijken. Zie DESIGN-SYSTEM.md. -->
<TextDialog
	bind:open={textOpen}
	initial={editingText ? (design.elements.find((e) => e.id === editingText)?.text ?? null) : null}
	onConfirm={async (options) => {
		if (editingText) {
			// Tekst is een pad, maar de engine bewaart de bron en rendert opnieuw.
			if ((await edits.updateText(editingText, options)).ok) await design.load();
			editingText = null;
		} else if (textAt) {
			draw({ type: 'text', x_mm: textAt.x, y_mm: textAt.y, ...options });
		}
		textAt = null;
	}}
/>

<!-- Werk van een vorige sessie: aanbieden, niet opdringen. -->
<Dialog
	title={t('recovery.title')}
	open={recovery?.exists === true}
	width="420px"
>
	<p class="ask">
		{t('recovery.body', { when: i18n.dateTime(recovery?.when) })}
	</p>
	<div class="ask-actions">
		<button
			class="btn weg"
			onclick={async () => {
				await fetch('/api/design/autosave', { method: 'DELETE', headers: authHeaders() });
				recovery = null;
			}}
		>{t('recovery.discard')}</button>
		<button class="btn" onclick={() => (recovery = null)}>{t('recovery.later')}</button>
		<button
			class="btn primary"
			onclick={async () => {
				recovery = null;
				await post('/api/design/autosave/restore', {});
				await design.load();
			}}
		>{t('recovery.restore')}</button>
	</div>
</Dialog>

<!-- Opening, opening a project and starting over all three throw work away: ask
     first, with the same words and the same way out. -->
<Dialog
	title={pending?.soort === 'nieuw'
		? t('replace.title.new')
		: design.dirty
			? t('replace.title.unsaved')
			: pending?.soort === 'project'
				? t('replace.title.project')
				: t('replace.title.sheet')}
	open={pending !== null}
	width="510px"
>
	<!-- Two occasions, two sentences. "Changed since it was last saved" above a
	     drawing you have just opened is untrue, and a question that claims something
	     you can contradict yourself is one you learn to click away. -->
	<p class="ask">
		{#if design.dirty}
			{t('replace.changed')}
		{:else if pending?.soort === 'bestand'}
			{t('replace.workOnSheet', { n: design.elements.length })}
		{:else}
			{t('replace.workInProject')}
		{/if}
		{#if pending?.soort === 'bestand'}
			{t('replace.opensSheet')}
		{:else if pending?.soort === 'project'}
			{t('replace.opensProject', { n: sheets.sheets.length })}
		{:else if sheets.sheets.length === 1}
			{t('replace.emptiesBed')}
		{:else}
			{t('replace.emptiesSheets', { n: sheets.sheets.length })}
		{/if}
	</p>
	{#if herstelbaar}
		<!-- What can be recovered regardless belongs in the question; it changes what
		     you choose. Only *this* sheet, because that is as far as the recovery file
		     reaches — and we name that boundary. -->
		<p class="ask nuance">{t('replace.recoverable', { when: herstelbaar })}</p>
	{/if}
	<div class="ask-actions">
		<button class="btn" onclick={() => (pending = null)}>{t('common.cancel')}</button>
		<button
			class="btn"
			onclick={() => {
				const actie = pending;
				pending = null;
				if (actie) voerUit(actie);
			}}
		>{t('replace.dontSave')}</button>
		<!-- Cancel / Do not save / Save: the triptych every operating system uses for
		     this question. "Open without saving" was there first, and then the three
		     buttons do not fit on one line — measured at 1024: the primary one dropped
		     to a line of its own. The verbs are already in the title and the sentence
		     above. -->
		<button class="btn primary" onclick={saveThenOpen}
			>{pending?.soort === 'nieuw' ? t('replace.saveAndStart') : t('replace.saveAndOpen')}</button
		>
	</div>
</Dialog>

<!-- The prompt card floats and does not block: a job has just started, and that
     must not disappear behind a modal window. -->
{#if !telefoon && vraagOpen && notifications.shouldAsk}
	<div class="vraagkaart">
		<NotificationCard {notifications} variant="prompt" onDone={() => (vraagOpen = false)} />
	</div>
{/if}

<Dialog title={t('notifications.title')} bind:open={meldingenOpen} width="460px">
	<NotificationCard {notifications} />
</Dialog>

{#if menu}
	<Menu menu={menu.lijst} x={menu.x} y={menu.y} onClose={() => (menu = null)} />
{/if}

<CornersDialog
	bind:open={hoekenOpen}
	aantal={design.selectedIds.length}
	bezig={edits.busy}
	melding={hoekMelding}
	onToepassen={async (stijl, maat) => {
		await hoeken(stijl, maat);
		if (!hoekMelding) hoekenOpen = false;
	}}
/>

<Offset
	bind:open={offsetOpen}
	aantal={design.selectedIds.length}
	bezig={edits.busy}
	onToepassen={async (afstand) => {
		offsetOpen = false;
		if ((await edits.offset(design.selectedIds, afstand)).ok) await design.load();
	}}
/>

<Presetariat bind:open={catalogueOpen} {catalogue} {library} {canEdit} />

<CameraCalibration bind:open={calibrateOpen} {camera} />

<Clipart bind:open={clipartOpen} {canEdit} onInserted={() => design.load()} />

<Generators
	bind:open={generatorsOpen}
	hasSelection={design.selectedIds.length > 0}
	busy={edits.busy}
	onGenerate={async (what, body) => {
		const response = await post(`/api/design/generate/${what}`, {
			...body,
			ids: design.selectedIds
		});
		if (!response.ok) {
			const detail = await response.json().catch(() => null);
			return { error: detail?.detail ?? t('notice.failed') };
		}
		const result = await response.json().catch(() => null);
		await Promise.all([design.load(), sheets.load()]);
		// Een vel dat er stilzwijgend bijkomt is een verrassing; zeg het.
		const used = result?.sheets ?? 1;
		return {
			notice:
				used > 1
					? t('notice.sheets.spread', { n: used })
					: null
		};
	}}
/>

<!-- Materiaal van het vel: klein venster, twee keuzes. In de bovenbalk kan het
     niet — die scrollt horizontaal en knipt elk uitklapmenu af — en op een
     tablet is een venster bovendien met een vinger te bedienen. -->
<Dialog title={t('sheetMaterial.title')} bind:open={materiaalOpen} width="440px">
	{#if sheets.active}
		<SheetMaterial
			{sheets}
			{library}
			sheet={sheets.active}
			onDone={() => (materiaalOpen = false)}
		/>
	{/if}
</Dialog>

<!-- Breder dan de 640px die hier stond. Sinds de bibliotheek twee panelen heeft
     — materialen links, instellingen rechts — is 640 precies te smal: de
     instelling zelf hield 380px over en dan wringen dikte, waarden, bron en de
     knop op één regel. -->
<Dialog title={t('library.title')} bind:open={libraryOpen} width="1120px">
	<MaterialLibrary
		{library}
		operations={design.operations}
		sheetMaterialId={sheets.active?.material_id ?? null}
		sheetMaterialName={velMateriaal}
		{canEdit}
		onApplied={() => design.load()}
		token={token()}
		onMakeGrid={(id) => {
			// Vanuit het materiaal naar het raster: dat is waar de ask ontstaat.
			libraryOpen = false;
			gridMateriaal = id;
			gridOpen = true;
		}}
	/>
</Dialog>

<Dialog title={t('testgrid.title')} bind:open={gridOpen} width="860px">
	<TestGrid
		{library}
		{canEdit}
		materialId={gridMateriaal ?? sheets.active?.material_id ?? null}
		thicknessMm={sheets.active?.thickness_mm ?? null}
		onGenerated={(id) => {
			// Vers gebrand raster: stap 3 hoort er meteen op te staan in plaats van
			// op "kies een raster…" te blijven hangen.
			versRaster = id;
			design.load();
		}}
	/>
	<TestGridResult {library} {canEdit} focusGrid={versRaster} />
</Dialog>

<style>
	/* De twee balken boven het canvas als één blok, zodat het zichzelf kan
	   opmeten. */
	.bovenrand {
		flex: none;
		display: flex;
		flex-direction: column;
	}
	.stage {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		/* Het startmoment legt zich over het bed; dat vraagt een anker. */
		position: relative;
	}
	.camstrip {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-4));
		/* --palet-hoogte komt van de kleurenstrook onder het canvas (B2), die
		   zichzelf opmeet. Zonder die term lag de camerapil over de eerste
		   kleurvakjes heen. Nul zolang er geen strook is. */
		bottom: calc(var(--statusbar-height) + var(--space-3) + var(--palet-hoogte, 0px));
		z-index: 5;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 4px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: color-mix(in srgb, var(--surface-1) 92%, transparent);
		backdrop-filter: blur(6px);
		box-shadow: var(--shadow-float);
	}
	/* Op tablet is er onderin geen ruimte náást de zoombalk: de camerapil lag er
	   op 768 half overheen. Hij gaat er dan boven staan. */
	@media (max-width: 1199px) {
		.camstrip {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 56px + var(--palet-hoogte, 0px));
		}
		.camerror {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 108px + var(--palet-hoogte, 0px));
		}
	}
	.cam {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: 999px;
		color: var(--text-2);
	}
	.cam:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.cam:disabled { opacity: 0.45; cursor: not-allowed; }
	.cam[aria-pressed='true'] { color: var(--accent); }
	.camstrip input[type='range'] { width: 90px; }
	.camerror {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-4));
		bottom: calc(var(--statusbar-height) + var(--space-3) + 40px + var(--palet-hoogte, 0px));
		z-index: 5;
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		max-width: 42ch;
		padding: var(--space-3);
		border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--shadow-float);
	}
	.camerror p {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-1);
	}
	/* De melding bevat een commando op een eigen regel; dat mag niet als één
	   lange lap tekst aan elkaar geplakt worden. */
	.camerror .wrap { white-space: pre-wrap; }
	.camerror button {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		font-size: 15px;
		line-height: 1;
	}
	.camerror button:hover { background: var(--surface-2); color: var(--text-1); }

	/* Rechtsonder, maar náást het paneel en niet erover: precies daar staat de
	   spoolerkaart met de voortgang van de job die net begon, en die afdekken met
	   de ask "zal ik het melden als hij klaar is" is het verkeerde van het
	   verkeerde. Dezelfde breedtes als `.panel` hieronder — twee regels die
	   samen horen, dus ze staan naast elkaar. */
	.vraagkaart {
		position: fixed;
		right: calc(280px + var(--space-4));
		bottom: calc(var(--statusbar-height) + var(--space-4));
		z-index: 70;
		width: min(360px, calc(100vw - 300px - 2 * var(--space-4)));
	}
	@media (max-width: 1199px), (pointer: coarse) {
		.vraagkaart {
			/* Volgt de paneelbreedte hieronder; twee regels die samen horen. */
			right: calc(clamp(280px, 38vw, 324px) + var(--space-4));
			width: min(360px, calc(100vw - clamp(300px, 38vw + 20px, 344px) - 2 * var(--space-4)));
		}
	}

	.main {
		flex: 1;
		display: flex;
		min-height: 0;
	}
	.panel {
		width: 280px;
		flex: none;
		background: var(--surface-1);
		border-left: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	/* Op tablet en telefoon staat de tekst een stap groter (15px in plaats van
	   13), maar het paneel bleef 280px — daarmee past er een vijfde minder op
	   een regel dan op de desktop en breken laagnamen middenin een woord.
	   280 × 15/13 ≈ 323: hetzelfde aantal tekens per regel als op de desktop.

	   Vaste 324px liep op de kleinste tablet mis (gat B2): op 768 hield het
	   canvas 316px over en was het paneel dus bréder dan het werk. Nu schaalt
	   het paneel mee met het venster, met 324 als plafond zodat de tekstregel
	   op 1024 en hoger onveranderd blijft. Gemeten op 768: paneel 292, canvas
	   348 — het canvas wint, zoals het hoort. */
	@media (max-width: 1199px), (pointer: coarse) {
		.panel {
			width: clamp(280px, 38vw, 324px);
		}
	}
	.panel.weg { display: none; }
	/* De greep zit tegen de rand van het canvas, waar je duim al is. Het
	   raakdoel is de hele kolom (44px, duimmaat), maar wat je ziet is een pil in
	   het midden: een volle kolom van 44px in paneelkleur was een blanco strook
	   naast het canvas, en die zegt niets. */
	.paneelgreep {
		align-self: stretch;
		flex: none;
		width: 44px;
		display: grid;
		place-items: center;
		border: none;
		background: transparent;
		color: var(--text-2);
		font-size: var(--text-md);
	}
	.paneelgreep .pil {
		display: grid;
		place-items: center;
		width: 24px;
		height: 56px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface-1);
		box-shadow: var(--lift-1);
		line-height: 1;
		transition: background var(--transition), color var(--transition);
	}
	.paneelgreep:hover .pil { background: var(--surface-2); color: var(--text-1); }
	.paneelgreep:focus-visible { outline: none; }
	.paneelgreep:focus-visible .pil { outline: 2px solid var(--accent); outline-offset: 2px; }
	.vw {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}
	.tabsrij {
		display: flex;
		flex: none;
		border-bottom: 1px solid var(--line);
	}
	.tabs {
		display: flex;
		flex: 1;
	}
	.tab {
		flex: 1;
		padding: 8px 0 8px;
		font-weight: 500;
		color: var(--text-2);
		position: relative;
	}
	.tab[aria-selected='true'] {
		color: var(--text-1);
	}
	.tab svg {
		position: absolute;
		left: var(--space-4);
		bottom: -1px;
		width: calc(100% - var(--space-8));
		height: 2px;
	}
	.bell {
		flex: none;
		width: 36px;
		display: grid;
		place-items: center;
		color: var(--text-2);
	}
	.bell svg {
		width: 17px;
		height: 17px;
	}
	.bell:hover {
		color: var(--text-1);
		background: var(--surface-2);
	}
	/* Uit is een toestand, geen failure: het doorgestreepte belletje zegt het al.
	   Geen rood, want er is niets stuk. */
	.bell.quiet {
		color: var(--text-2);
	}
	:global(.ask) { margin: 0 0 var(--space-4); }
	/* De nuance staat onder de hoofdzin en mag hem niet overstemmen. */
	:global(.ask.nuance) {
		font-size: var(--text-sm);
		color: var(--text-2);
	}
	:global(.ask-actions) {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
		flex-wrap: wrap;
	}
	:global(.ask-actions .btn) {
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	:global(.ask-actions .btn:hover) { background: var(--surface-2); }
	/* "Weggooien" verwijdert het automatisch bewaarde ontwerp definitief en stond
	   op 8px van "Later". Dit venster verschijnt ongevraagd bij het openen —
	   precies wanneer je nog niet kijkt — en met een handschoen aan raak je het
	   midden van een doel niet. 24px ertussen, alleen op aanraakschermen; de
	   muisindeling op de desktop blijft zoals hij was. Zie DESIGN-SYSTEM,
	   "Touch als eersteklas input". */
	@media (max-width: 1199px), (pointer: coarse) {
		:global(.ask-actions .btn.weg) { margin-right: var(--space-4); }
	}
	:global(.ask-actions .btn.primary) {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.panel-scroll {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-4);
	}

	/* Op tablet/telefoon is de app primair monitor + foto-invoer: het paneel
	   klapt onder het canvas, de rail verdwijnt. */
	@media (max-width: 720px) {
		.main {
			flex-direction: column;
		}
		.panel {
			width: 100%;
			border-left: none;
			border-top: 1px solid var(--line);
			max-height: 45vh;
		}
	}
</style>
