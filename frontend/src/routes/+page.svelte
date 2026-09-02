<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { jobBusy, jobPhase, machineState, mayLeaveWorkArea, transportAllowed } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import {
		DEFAULT_BRIDGES,
		DesignStore,
		bridgeSummary,
		elementName,
		isDesignSignal,
		type DesignElement
	} from '$lib/design.svelte';
	import { EditController } from '$lib/edits.svelte';
	import { saveFile } from '$lib/saving';
	import type { Tool } from '$components/ToolRail.svelte';
	import { LibraryStore } from '$lib/library.svelte';
	import { StatusConnection } from '$lib/status.svelte';
	import Canvas from '$components/Canvas.svelte';
	import DesignPanel from '$components/DesignPanel.svelte';
	import CutPath from '$components/CutPath.svelte';
	import JobPanel from '$components/JobPanel.svelte';
	import StatusBar from '$components/StatusBar.svelte';
	import ToolRail from '$components/ToolRail.svelte';
	import Dialog from '$components/Dialog.svelte';
	import MaterialLibrary from '$components/MaterialLibrary.svelte';
	import Generators from '$components/Generators.svelte';
	import CameraCalibration from '$components/CameraCalibration.svelte';
	import Clipart from '$components/Clipart.svelte';
import Series from '$components/Series.svelte';
	import SheetTabs from '$components/SheetTabs.svelte';
	import SheetMaterial from '$components/SheetMaterial.svelte';
	import PhoneView from '$components/PhoneView.svelte';
	import JobStart from '$components/JobStart.svelte';
	import { SheetStore } from '$lib/sheets.svelte';
	import { CameraStore } from '$lib/camera.svelte';
	import { TilingStore } from '$lib/tiling.svelte';
import { SeriesStore } from '$lib/series.svelte';
	import TestGrid from '$components/TestGrid.svelte';
	import TestGridResult from '$components/TestGridResult.svelte';
	import TextDialog from '$components/TextDialog.svelte';
	import TopBar from '$components/TopBar.svelte';
	import ActionBar from '$components/ActionBar.svelte';
	import Menu from '$components/Menu.svelte';
	import CornersDialog from '$components/CornersDialog.svelte';
	import StencilDialog from '$components/StencilDialog.svelte';
	import Offset from '$components/Offset.svelte';
	import {
		KEYS,
		comboOf,
		canvasMenu,
		keyLabel,
		nodeMenu,
		objectMenu,
		historyActions,
		arrangeActions,
		alignActions,
		type Action,
		type Context as ActionContext,
		type Handlers,
		type NodeContext,
		type NodeHandlers,
		type Menu as MenuList
	} from '$lib/actions';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import AlarmCard from '$components/AlarmCard.svelte';
	import NotificationCard from '$components/NotificationCard.svelte';
	import { Notifications, Watchdog } from '$lib/notifications.svelte';

	const status = new StatusConnection();
	const control = new Controller();
	// Decision B3: reporting yes, intervening no. The watchdog reads the status and
	// decides when there is something to say; it sends nothing to the machine.
	const notifications = new Notifications();
	const watchdog = new Watchdog(notifications);
	/** Is the settings card open? Reachable beside the panel tabs. */
	let notificationsOpen = $state(false);
	/** The prompt card: only on screen just after a job has started. */
	let promptOpen = $state(false);
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
	// Cropping: the next drag frame crops the selected image.
	let cropping = $state(false);

	// Three devices, three apps (DESIGN-SYSTEM v2). Not a shrunken desktop but a
	// shape of its own: below 768px this is a monitor with an emergency stop.
	let width = $state(1440);
	let onPhone = $derived(width < 768);
	let tablet = $derived(width >= 768 && width < 1200);
	// Below this width the file buttons no longer fit *beside* the machine controls in
	// the top bar; they move to the rail menu then. Since the sheet's material is in
	// the bar (decision B1) that bound is no longer at 950 but at the whole tablet
	// width: measured, the bar otherwise ran 99px over the edge at 1024, and then the
	// start button is off screen. What you burn into weighs more than a file button one
	// tap away in the rail menu.
	let narrow = $derived(tablet);
	// Below 880px the project button in the bar costs the material's name (measured:
	// 63px → 40px at 850, → 7px at 768). There the project lives in the rail menu;
	// above it, it is in the bar. See the media query in TopBar.svelte.
	let projectInRail = $derived(width < 880);
	// `krap` used to be here: below 1500px the project pair disappeared from the bar
	// and lived only in the rail menu. That was exactly where the user did not find it.
	// The pair is now one "Project" button with a menu, which fits in the bar at every
	// width — so there is no tight state any more.
	/**
	 * On the smallest tablet the panel starts closed (gap B2).
	 *
	 * The panel scales with the window, so it is never wider than the canvas — but
	 * below 850px the bed keeps less than 400px, and then the first thing you see is a
	 * sliver of work area beside a full form. The grip beside it is one tap, and on a
	 * tablet start/pause/stop are in the top bar anyway. Only on opening: after that the
	 * user decides.
	 */
	let panelOpen = $state(true);
	// The pointer position lives in the canvas but belongs in the status bar: that is
	// where you look for it.
	let pointerMm = $state<{ x: number; y: number } | null>(null);
	/** Height of the action bar plus the sheet bar; the alarm card hangs below it. */
	let topEdgeHeight = $state(0);
	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.style.setProperty('--topedge-height', `${topEdgeHeight}px`);
		return () => document.documentElement.style.removeProperty('--topedge-height');
	});
	/** The material the test grid dialog opens with, when you jump there from the
	    library. */
	let gridMaterial = $state<number | null>(null);

	// The wow moment. Only on the edge from not-running to running, and gone again
	// afterwards — otherwise it is decoration rather than a message.
	let wow = $state(false);
	let wasRunning = false;
	function celebrate() {
		wow = true;
		setTimeout(() => (wow = false), 900);
		// The only moment the permission question means anything: something is burning
		// now, so there will be something to report. On loading the app the same
		// question would come without an occasion — and that refusal is final.
		if (notifications.shouldAsk) promptOpen = true;
		watchdog.started();
	}
	control.onStarted = celebrate;
	$effect(() => {
		const now = Boolean(status.activeJob?.running);
		// It should celebrate even when somebody else started it (phone, console).
		if (now && !wasRunning) celebrate();
		wasRunning = now;
	});
	// What is switched on for the chosen image. Comes from the API, because the recipe
	// lives on the node in the engine — not in the browser.
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
	// Which layer a setting should land on, when the library was opened from one.
	let libraryLayer = $state<string | null>(null);
	let generatorsOpen = $state(false);
	let clipartOpen = $state(false);
	let seriesOpen = $state(false);
	const sheets = new SheetStore(() => localStorage.getItem('openkerf.token') ?? '');
	let calibrateOpen = $state(false);
	const camera = new CameraStore(() => localStorage.getItem('openkerf.token') ?? '');
	const tiling = new TilingStore(token);
	// The list a series burns from. Beside the other stores, because three surfaces
	// read it — this window, the context panel and the run block in the Job panel —
	// and one of them gets it from the status payload rather than from its own load.
	const series = new SeriesStore(token);
	/** An action that replaces the current work, awaiting a yes. */
	type Replacement = { kind: 'project'; file: File } | { kind: 'fresh' };
	let pending = $state<Replacement | null>(null);
	/** Timestamp of the recovery file that would survive this action. */
	let recoverable = $state<string | null>(null);
	/** Which question is up now; a late answer to an older one does not count. */
	let questionCounter = 0;
	// Work from a previous session. Never restore it silently: anybody who wants to
	// start with an empty canvas must be able to.
	let recovery = $state<{ exists: boolean; when: string | null } | null>(null);
	let textOpen = $state(false);
	let textAt = $state<{ x: number; y: number } | null>(null);
	let editingText = $state<string | null>(null);
	let estimate = $state<number | null>(null);
	let gridOpen = $state(false);
	let freshGrid = $state<number | null>(null);
	// A stamp rather than a flag: coming back a second time has to scroll again, and a
	// boolean that is already true says nothing happened.
	let readBoard = $state<number | null>(null);
	/** Changing the current sheet's material (decision B1). */
	let materialOpen = $state(false);
	let sheetMaterial = $derived(
		library.materials.find((m) => m.id === sheets.active?.material_id)?.name ?? null
	);

	// Undo throws the engine's ids away (restored nodes come back without an id and get
	// different ones on renumbering). A kept selection could point at a *different*
	// element afterwards, so we let it go.
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
	 * Opening replaces, it does not add.
	 *
	 * The engine loads a file on top of what is already there. That is sometimes handy
	 * but it is not what "opening" means, so we empty it first — and we ask first when
	 * work would disappear because of it.
	 *
	 * The question hung off `dirty`, and that is one step too strict. A freshly
	 * imported drawing sits at `dirty === false` (`/api/job/load` calls
	 * `document.clean()` — rightly, it is identical to the file), and at that moment
	 * there is no autosave either. Measured: import a drawing, import another, and the
	 * first is gone — without a question, without a message, without anything to fall
	 * back on. What is on the bed is work, whether it was typed or opened; so we ask as
	 * soon as there is something there.
	 */
	async function openFile(file: File) {
		if (!canEdit) return;
		await importInto(file);
	}

	/**
	 * Importing adds to the sheet.
	 *
	 * It used to empty the bed first, and then ask whether that was allowed. That is
	 * what *opening* means, not what importing means: a sheet is a plate, and a plate
	 * holds more than one part — the second import threw away the first. There is
	 * nothing to ask any more, because nothing goes away.
	 *
	 * What did come in is selected, so it can be dragged into place straight away. On
	 * a sheet that already has work the new shapes land at the coordinates the file
	 * gives them, and that is often right on top of something; without a selection you
	 * would first be looking for what just arrived.
	 */
	async function importInto(file: File) {
		const added = await control.load(file);
		if (added === null) return;
		await design.load();
		// The API refuses a file without shapes, so an empty import does not get here;
		// the guard is there so a future route that does allow it says nothing rather
		// than "0 shapes imported".
		if (!added.length) return;
		design.selectMany(added);
		layoutNotice = t('notice.import.added', { n: added.length });
	}

	/**
	 * Both actions that replace the current work ask the same question.
	 *
	 * Opening a project file went straight over it without a word — including the
	 * sheets, because those come along from the file. That is the worst form: throwing
	 * work away silently. Importing is no longer among these: it adds, so there is
	 * nothing to lose.
	 *
	 * Both of them replace *all* the sheets, so yesterday's box counts too, even when
	 * the sheet you see now is empty.
	 */
	async function maybeAskFirst(action: Replacement) {
		const thereIsWork = !design.isEmpty || sheets.sheets.length > 1;
		if (!thereIsWork) {
			await runIt(action);
			return;
		}
		recoverable = null;
		pending = action;
		// What can still be recovered *after* this action changes what you choose — so
		// it is in the question. Only for a changed design: a design identical to a file
		// on disk has the recovery file cleaned up (`autosave.forget_if_saved`), so then
		// the promise would not hold.
		if (!design.dirty) return;
		// A counter and not a comparison with `action`: `$state` hands back a proxy, so
		// `pending === action` is always false and the answer never arrived. Measured:
		// the autosave existed, the design was dirty, and the line
		// bleef gone.
		const number = ++questionCounter;
		const response = await fetch('/api/design/autosave');
		if (!response.ok) return;
		const staat = await response.json();
		if (questionCounter === number && pending !== null && staat.exists) recoverable = staat.when;
	}

	/** Starting over. See `/api/project/new`: the library stays. */
	async function newProject() {
		if (!canEdit) return;
		await maybeAskFirst({ kind: 'fresh' });
	}

	async function runIt(action: Replacement) {
		if (action.kind === 'project') {
			await laadProject(action.file);
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

	/** Write routes carry the token; one place instead of at every call. */
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
		await maybeAskFirst({ kind: 'project', file });
	}

	/** A project also carries the library context, so it has a route of its own. */
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

	/** Placing adds too, and here that was always the case. */
	async function placeImage(file: File) {
		if (!canEdit) return;
		if ((await control.load(file)) !== null) await design.load();
	}

	async function saveThenOpen() {
		const action = pending;
		pending = null;
		if (!action) return;
		// Downloading counts as saving: the API marks the design clean. Both actions
		// that get here replace *all* the sheets, so what is kept is the whole project
		// and not an SVG of the active sheet — that would be half a rescue.
		//
		// Wait until the file really is there, and do not hope for 800 ms: the next
		// thing that happens empties the bed. If the save fails, the emptying does not
		// go ahead and the dialog is still up.
		const saved = await saveFile('/api/project/export.openkerf', 'project.openkerf');
		if (!saved) {
			pending = action;
			return;
		}
		await design.load();
		await runIt(action);
	}

	async function draw(shape: Record<string, unknown>) {
		if (!canEdit) return;
		const result = await edits.draw(shape);
		if (result.ok) {
			await design.load();
			// Back to selecting: one shape per click is more predictable than
			// accidentally leaving a row of shapes behind.
			//
			// Except for a point, where a row of them is the whole idea: points are
			// placed for perforating or for drill marks, and one alone is rarely the
			// job. Measured on three clicks with the general rule in force: one point
			// on the bed and the tool back on Select, so the second and third click
			// selected instead of placing. Escape or the Select button ends it, and the
			// rail shows which mode you are in, which is where a mode belongs.
			if (shape.type !== 'point') tool = 'select';
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

	/** What the last corner operation had to report; the panel shows it. */
	let cornerNotice = $state<string | null>(null);
	/** What the last tidy-up action did (split, layer, clean up). */
	let layoutNotice = $state<string | null>(null);

	async function corners(style: 'round' | 'chamfer', sizeMm: number) {
		if (!canEdit || !hasSelection) return;
		cornerNotice = null;
		const outcome = await edits.corners(design.selectedIds, style, sizeMm);
		if (!outcome) return;
		if (outcome.paths.length) {
			// Chamfered shapes have become paths and have a new id; the old selection
			// points at something that no longer exists.
			design.select(null);
		}
		await design.load();
		if (outcome.skipped) {
			cornerNotice = t('notice.corners.skipped', { n: outcome.skipped });
		}
	}

	async function splitSelection() {
		if (!canEdit || !hasSelection) return;
		layoutNotice = null;
		const outcome = await edits.split(design.selectedIds);
		if (!outcome) return;
		// The pieces are new elements; the old selection points at a path that has
		// been replaced by a group.
		design.select(null);
		await design.load();
		if (outcome.count) {
			design.selectMany(outcome.ids);
			layoutNotice = t('notice.split.done', { n: outcome.count });
		} else {
			layoutNotice = t('notice.split.nothing');
		}
	}

	/**
	 * Making an area out of the selection, or taking it away.
	 *
	 * Without a fill a shape only grids its outline — measured: 8 % of the area
	 * black instead of over 90 %. Hence this is a button of its own and not a side
	 * effect of "into the grid layer".
	 */
	async function setFill(filled: boolean) {
		if (!canEdit || !hasSelection) return;
		layoutNotice = null;
		const outcome = await edits.fill(design.selectedIds, filled);
		if (!outcome) return;
		await design.load();
		const count = filled ? outcome.filled : outcome.cleared;
		layoutNotice =
			t(filled ? 'notice.fill.filled' : 'notice.fill.cleared', { n: count }) +
			(outcome.skipped ? ` ${t('notice.fill.skipped', { n: outcome.skipped })}` : '');
	}

	/**
	 * Bridges (tabs) on the selection: small gaps left in the cut.
	 *
	 * Without them a part drops into the machine the moment the contour closes, and a
	 * dropped part shifts. The engine cuts the gaps itself once the two attributes are on
	 * the shape, so this only sets them — and says how many shapes got them, because a
	 * selection can hold a line, and a line carries none.
	 */
	async function setBridges(fields: { count?: number; length_mm?: number }) {
		if (!canEdit || !hasSelection) return;
		bridgeNotice = null;
		const outcome = await edits.setBridges(design.selectedIds, fields);
		if (!outcome) {
			// The refusal goes beside the field that caused it — a length that cannot work
			// is answered where the length is typed. It is taken *out* of the general
			// notice at the same time: the sentence has a better home here, and the same
			// fact twice on one screen is one fact too many.
			bridgeNotice = edits.error;
			edits.error = null;
			// Nothing changed on the shapes, so the panel's summary is the same object and its
			// fields would keep the refused numbers — a read-back of a state that is not
			// there. This tells the panel to fetch them from the shapes again.
			bridgeRevision += 1;
			return;
		}
		await design.load();
		bridgeNotice = t(
			outcome.skipped ? 'notice.bridges.doneSkipped' : 'notice.bridges.done',
			{
				n: outcome.bridged,
				count: outcome.count,
				length: i18n.number(outcome.length_mm),
				skipped: outcome.skipped
			}
		);
	}

	async function clearBridges() {
		if (!canEdit || !hasSelection) return;
		bridgeNotice = null;
		const outcome = await edits.clearBridges(design.selectedIds);
		if (!outcome) {
			bridgeNotice = edits.error;
			edits.error = null;
			bridgeRevision += 1;
			return;
		}
		await design.load();
		bridgeNotice = t('notice.bridges.cleared', { n: outcome.cleared });
	}

	/**
	 * Lock or unlock what is selected.
	 *
	 * The notice says what a lock means, because the shape looks the same afterwards
	 * apart from its handles: without a word, the first thing a user does is try to
	 * drag it and read a refusal instead.
	 */
	/** Ask the API what lies on top of what; the answer opens the question. */
	async function lookForDuplicates() {
		if (!canEdit) return;
		layoutNotice = null;
		const picked = design.selectedIds;
		const query = picked.length ? `?ids=${picked.map(encodeURIComponent).join(',')}` : '';
		const response = await fetch(`/api/design/duplicates${query}`);
		if (!response.ok) return;
		const found = await response.json();
		// Also when there is nothing: the answer belongs where the question was asked.
		// A note in the side panel would be invisible with nothing selected, which is
		// exactly the case you get from the bed's own menu.
		duplicates = found;
	}

	async function removeDuplicates() {
		const found = duplicates;
		duplicates = null;
		if (!found) return;
		const picked = design.selectedIds;
		const outcome = await post('/api/design/duplicates/remove', {
			ids: picked.length ? picked : undefined
		});
		if (!outcome.ok) return;
		const body = await outcome.json().catch(() => null);
		await design.load();
		// Select what stayed: it puts the count in a panel that is only there with a
		// selection, and it shows *where* the stacks were — the drawing itself gives no
		// sign that anything happened.
		const stacks: string[][] = found.groups ?? [];
		const gone = new Set<string>(body?.removed_ids ?? []);
		const keepers = stacks.flat().filter((id) => !gone.has(id));
		if (keepers.length) design.selectMany(keepers);
		layoutNotice = t('notice.duplicates.removed', { n: body?.removed ?? found.extra });
	}

	async function lockSelection(locked: boolean) {
		if (!canEdit || !hasSelection) return;
		layoutNotice = null;
		const ids = design.selectedIds;
		if (!(await edits.setLocked(ids, locked)).ok) return;
		await design.load();
		layoutNotice = t(locked ? 'notice.lock.locked' : 'notice.lock.unlocked', {
			n: ids.length
		});
	}

	async function toALayer(kind: 'cut' | 'engrave' | 'raster') {
		if (!canEdit || !hasSelection) return;
		layoutNotice = null;
		const outcome = await edits.singleLayer(design.selectedIds, kind);
		if (!outcome) return;
		await design.load();
		const layer = design.operations.find((o) => o.id === outcome.operation_id);
		const name =
			layer?.label ??
			t(
				({
					cut: 'panel.kind.cut',
					engrave: 'panel.kind.engrave',
					raster: 'panel.kind.raster'
				} as const)[kind]
			);
		const howMany = outcome.assigned || design.selectedIds.length;
		layoutNotice = t('notice.layer.assigned', {
			n: howMany,
			layer: t(outcome.created ? 'notice.layer.newLayer' : 'notice.layer.existing', { name: name }),
			removed: outcome.removed ? t('notice.layer.removedFrom', { n: outcome.removed }) : ''
		});
	}

	async function tidyUp() {
		if (!canEdit) return;
		layoutNotice = null;
		const outcome = await edits.prune();
		if (!outcome) return;
		await design.load();
		layoutNotice = outcome.removed
			? t('notice.prune.done', { n: outcome.removed })
			: t('notice.prune.none');
	}

	async function arrange(action: string) {
		// 'rescue' works on the whole design; the rest on the selection.
		if (!canEdit || (!hasSelection && action !== 'rescue')) return;
		const ids = design.selectedIds;
		if (action === 'offset') {
			// The question lives in a dialog of its own (`Offset.svelte`); there used to
			// be a `window.prompt` here, and that fell outside the theme *and* validated
			// nothing.
			offsetOpen = true;
			return;
		}
		if (action === 'rescue') {
			// Putting everything on the bed, including what you cannot point at because
			// it is off screen.
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
			// A boolean operation produces a new path; the old selection no longer exists.
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
	// The tab is in the URL, so that the back button and a bookmark work. Local state
	// is the source of truth, the URL follows. The other way round does not work:
	// replaceState does not make $page.url reactive, which left the panel on the old
	// tab while the URL did follow along.
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
	let phonePosition = $derived(
		device?.position.mm
			? `${device.position.mm[0].toFixed(1)}, ${device.position.mm[1].toFixed(1)} mm`
			: '—'
	);
	// Do not call it `state`: `$state` would then be read as a store reference.
	let machine = $derived(machineState(device, status.connected));
	/**
	 * The job's phase, from the same function the Job panel uses.
	 *
	 * Before this the top bar read the machine state (`machine === 'busy'`) and the
	 * panel read `job.running`. For a job that has been spooled but not yet picked up
	 * those two disagree, and then one button disables what the other offers — measured
	 * with a machine that does not answer: the bar disabled starting, the panel left it
	 * on. One function, one answer.
	 */
	let phase = $derived(jobPhase(device, status.activeJob, design.burnsNothing));
	let workUnderWay = $derived(jobBusy(phase));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		camera.load();
		sheets.load();
		library.load();
		// The list a series burns from. Fetched here and not only by its own window,
		// because two surfaces outside it read it the moment somebody right-clicks: the
		// Insert-column rows in the menu and the read-back line under a text in the
		// panel. Without this the menu would say "no list is attached" while one is,
		// which is the one thing a greyed row may never do.
		series.load();
		leesKlembord();
		if (window.innerWidth < 850) panelOpen = false;
		const wantedTab = $page.url.searchParams.get('tab');
		if (wantedTab === 'design' || wantedTab === 'layers') tab = wantedTab;
		design.load().then(async () => {
			// Only offer it when there is nothing there: restoring on top of existing
			// work gives a mishmash, and the API refuses that too.
			if (design.isEmpty) {
				const response = await fetch('/api/design/autosave');
				if (response.ok) {
					const state = await response.json();
					if (state.exists) recovery = state;
				}
			}
			const wanted = $page.url.searchParams.get('select');
			if (wanted) {
				// Only what is still there. A bookmark or a reload can name a shape that
				// has since been deleted, and a selection of a shape that does not exist
				// is worse than none: the action bar counts one, the panel shows nothing,
				// and the right-click menu comes up empty.
				const here = new Set(design.elements.map((element) => element.id));
				const ids = wanted.split(',').filter((id) => here.has(id));
				design.select(ids[0] ?? null);
				ids.slice(1).forEach((id) => design.toggle(id));
			}
		});
		// Only hook up after mount: replaceState before the router is ready breaks the
		// render. So the URL follows the action, not an effect.
		design.onSelect = () => {
			syncUrl();
			loadImageState();
		};
		// The available actions depend on the active device, so fetch them again as soon
		// as the user switches machine in MeerK40t.
		const poll = setInterval(() => control.refreshCapabilities(), 10_000);
		// The permission can change behind our back: anybody resetting it in the
		// browser's site settings does not expect to have to reload afterwards.
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

	// The engine signals that the element tree has changed; only then fetch again. The
	// store swallows bursts itself, so one signal per change is fine.
	$effect(() => {
		const latest = status.events[0];
		if (latest && isDesignSignal(latest.code)) design.load();
	});

	// Alarm signals from the engine (`pipe;usb_status`) and the two-second snapshot:
	// two separate sources, so two separate effects.
	$effect(() => {
		const latest = status.events[0];
		if (latest) watchdog.signal(latest);
	});
	$effect(() => {
		watchdog.status(status.device, status.connected);
	});
	// The same socket carries the state of a running tile series; the top bar, the
	// canvas and the phone all read this one source.
	$effect(() => {
		tiling.adopt(status.snapshot?.tiling ?? null);
	});
	// And the series, from the same socket and for the same reason: the run block in
	// the Job panel, the context panel's read-back line and this page all have to say
	// the same thing about which row is next. The rows themselves never ride here —
	// `series.load()` in `onMount` brings those once.
	$effect(() => {
		series.adopt(status.snapshot?.series ?? null);
	});
	/**
	 * Fetching the division, and again as soon as something about it changes.
	 *
	 * The division is computed on the server and never stored, so it has to be
	 * requested here — and that happened nowhere. Consequence: `tiling.layout` stayed
	 * empty, and then the canvas draws no seams, no marks and no dimmed tiles, and the
	 * panel does not know how far the board has to shift. Everything was right, only
	 * nothing ever came in.
	 *
	 * It hangs off the number of elements, the active sheet and the state of the
	 * series: those are exactly the three things that can move the division.
	 */
	$effect(() => {
		void design.elements.length;
		void sheets.active?.id;
		void tiling.run?.current;
		// Only fetch when tiling can actually apply: a board bigger than the bed, or a
		// series that is already running. Without that brake a request goes out on every
		// change in the design that almost always 409s.
		const sheet = sheets.active;
		const bed = device?.bed;
		const tooBig =
			Boolean(sheet && bed) &&
			(sheet!.width_mm > (bed!.width_mm ?? 0) || sheet!.height_mm > (bed!.height_mm ?? 0));
		if (tooBig || tiling.run) tiling.load();
	});

	// ─── Klembord, menu's en sneltoetsen ──────────────────────────────────────
	//
	// Everything below hangs off one list: `$lib/actions.ts`. The action bar above
	// the canvas, the context menu and the keyboard read the same names, the same
	// shortcuts and the same reasons-why-not out of it. That is the whole point: before
	// this every action lived in exactly one place, and so there was no second place
	// where it could be called the same thing.

	/** How many shapes are on the clipboard; the menu has to know whether paste is
	    possible. */
	let clipboard = $state(0);
	async function leesKlembord() {
		const response = await fetch('/api/design/clipboard');
		if (response.ok) clipboard = (await response.json()).count ?? 0;
	}

	async function klembordActie(wat: 'copy' | 'cut', ids: string[]) {
		if (!ids.length || !canEdit) return;
		const response = await post(`/api/design/clipboard/${wat}`, { ids });
		if (!response.ok) return;
		clipboard = (await response.json()).count ?? 0;
		if (wat === 'cut') {
			design.select(null);
			await design.load();
		}
	}

	async function plakken(point?: { x: number; y: number }) {
		if (!canEdit || !clipboard) return;
		const response = await post('/api/design/clipboard/paste', {
			x_mm: point?.x ?? null,
			y_mm: point?.y ?? null
		});
		if (!response.ok) return;
		const outcome = await response.json().catch(() => null);
		await design.load();
		if (outcome?.ids?.length) design.selectMany(outcome.ids);
	}

	/** The handle through which the canvas's zoom states can be operated from here. */
	let canvasControl = $state<{
		zoom: (what: 'all' | 'selection' | 'bed' | 'hundred') => void;
		step: (factor: number) => void;
		snap: () => void;
		layerNumbers: () => void;
		node: (verb: 'add' | 'remove' | 'curve' | 'corner') => void;
		penBack: () => void;
		state: () => {
			snap: boolean;
			layerNumbers: boolean;
			penDrawing: boolean;
			nodeIndex: number;
			nodeCount: number;
			nodeClosed: boolean;
			nodeKind: 'line' | 'quad' | 'cubic' | 'arc' | null;
		};
	} | null>(null);

	/** What the last bridge action has to report — beside the field, not at the top. */
	let bridgeNotice = $state<string | null>(null);
	/** Bumped on a refusal, so the panel's two fields go back to what the shapes carry. */
	let bridgeRevision = $state(0);
	// The note belongs to the shapes it was about. Without this the refusal from a rectangle
	// stayed on screen under a line that had just been selected — measured, and it read as if
	// the line had been refused for the wrong reason.
	$effect(() => {
		design.selectedIds;
		untrack(() => (bridgeNotice = null));
	});

	let cornersOpen = $state(false);
	let stencilOpen = $state(false);
	let stencilReport = $state<Awaited<ReturnType<typeof edits.stencil>> | null>(null);
	let stencilError = $state<string | null>(null);
	/**
	 * The cut-path window (gap S1).
	 *
	 * State here and not in the panel: it is opened from two places — the pre-flight
	 * and the canvas menu — and a window that two surfaces can open has to be owned
	 * by the page above both of them.
	 */
	let cutPathOpen = $state(false);
	let offsetOpen = $state(false);

	/** Which menu is open, and where. */
	let menu = $state<{ list: MenuList; x: number; y: number } | null>(null);
	/** Where the bed was clicked — "paste here" promises that place. */
	let menuPoint = $state<{ x: number; y: number } | null>(null);
	/**
	 * The shapes under the right-click that opened the menu, topmost first.
	 *
	 * The canvas knows this — it asks the browser what is under the pointer — and
	 * hands it over, because the menu is built here. Emptied when the menu closes, so
	 * a later menu cannot show yesterday's pile.
	 */
	let underPointer = $state<string[]>([]);
	/** Where you are in a pile of shapes after an Alt+click; the action bar says it. */
	let deeper = $state<{ index: number; total: number } | null>(null);
	/**
	 * What a look for duplicates found, while the question is on screen.
	 *
	 * Looking and removing are two steps on purpose: removing changes nothing you can
	 * see — the drawing looks the same, because what goes was lying underneath — so the
	 * number in the question is the only evidence the user gets.
	 */
	let duplicates = $state<{
		looked_at: number;
		skipped: number;
		stacks: number;
		extra: number;
		groups?: string[][];
	} | null>(null);

	/**
	 * Put a column of the list into the selected text.
	 *
	 * Appended and never replacing: a tag normally reads "No. {serial}", so what is
	 * already there is the half somebody typed. It goes out through the ordinary text
	 * route, which is what re-renders the path and what refuses a bracket that does not
	 * close — one road in, so this menu cannot make a text the text field would refuse.
	 */
	async function insertColumn(column: string) {
		const id = design.selectedId;
		// No name to insert. The row is greyed in that state and carries no shortcut, so
		// this is the belt to that brace rather than a case anybody can reach.
		if (!id || !column.trim()) return;
		const was = design.elements.find((element) => element.id === id)?.text?.text ?? '';
		if ((await edits.updateText(id, { text: `${was}{${column}}` })).ok) {
			await design.load();
			// The list has to be asked again, because what a placeholder renders is
			// computed for the row the bed shows and this text has a placeholder it did
			// not have a moment ago. Without it the panel's read-back line would quote
			// the run instead of the name.
			await series.load();
		}
	}

	/**
	 * "Burn only once" on the selection, or on every plate of the series again.
	 *
	 * One request per shape, because that is what the route takes: the mark is about a
	 * jig frame or the pockets the pieces sit in, and those are a handful of shapes.
	 */
	async function setBurnOnce(once: boolean) {
		const ids = design.selectedIds;
		if (!ids.length) return;
		for (const id of ids)
			await post(`/api/design/elements/${encodeURIComponent(id)}/once`, { once });
		await design.load();
	}

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
		split: splitSelection,
		fill: (on) => setFill(on),
		corners: () => (cornersOpen = true),
		stencil: () => {
			// The window measures on opening, so the last answer of a previous shape does
			// not stand over a new one.
			stencilReport = null;
			stencilError = null;
			stencilOpen = true;
		},
		// `DEFAULT_BRIDGES` and not the two numbers again: the panel's switch offers the same
		// default, and the menu label names it ("Add bridges (4 × 2 mm)"). Written twice they
		// drift, and then the row promises one thing and does another.
		bridges: (on) =>
			on
				? setBridges({
						count: DEFAULT_BRIDGES.count,
						length_mm: DEFAULT_BRIDGES.lengthMm
					})
				: clearBridges(),
		onlyLayer: (kind) => toALayer(kind),
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
		insertColumn: (column) => insertColumn(column),
		burnOnce: (once) => setBurnOnce(once),
		series: () => (seriesOpen = true),
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
		rescue: () => arrange('rescue'),
		cutPath: () => (cutPathOpen = true),
		selectOne: (id) => design.select(id),
		setLocked: (locked) => lockSelection(locked),
		duplicates: () => lookForDuplicates()
	};

	/**
	 * One shape as a line of text: what it is, and how big.
	 *
	 * For the list of what lies under the pointer. The name alone is not enough
	 * there — two rectangles on top of each other both read "Rectangle" — and the
	 * measure is what you can see on the bed, so it is the quickest way to tell which
	 * of the two you mean.
	 */
	function shapeLine(element: DesignElement, index: number): string {
		const perMm = design.design?.units_per_mm ?? 1;
		const box = element.bounds;
		if (!box) return `${index}. ${elementName(element)}`;
		return t('canvas.under.item', {
			index,
			name: elementName(element),
			// No forced decimal: "60 × 60 mm" fits on one line of the menu where
			// "60.0 × 60.0 mm" wraps, and a tenth only shows when there is one.
			width: i18n.number((box[2] - box[0]) / perMm),
			height: i18n.number((box[3] - box[1]) / perMm)
		});
	}

	/** The state in which an action is or is not possible. */
	/** The bridges on the selection; the menu row, the shortcut and the panel all read it. */
	let bridgeState = $derived(bridgeSummary(design.elements.filter((e) => design.isSelected(e.id))));

	let actionContext = $derived.by<ActionContext>(() => {
		const chosen = design.elements.filter((e) => design.isSelected(e.id));
		const image = chosen.length === 1 && Boolean(chosen[0]?.image);
		const state = canvasControl?.state();
		return {
			count: chosen.length,
			inGroup: chosen.some((e) => Boolean(e.group_id)),
			lockedCount: chosen.filter((e) => e.locked).length,
			isImage: image,
			isText: chosen.length === 1 && chosen[0]?.text !== null,
			isCropped: image && Boolean(imageState?.cropped),
			filled: chosen.length > 0 && chosen.every((e) => Boolean(e.fill)),
			bridges: { carries: bridgeState.carries, has: bridgeState.has },
			clipboard: clipboard,
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
			empty: design.isEmpty,
			// By name, in the order they lie: the top one first. With the measure behind
			// it, because a pile is usually two shapes of the same kind — a list that
			// says "Rectangle" twice is no choice at all.
			under: underPointer
				.map((id) => design.elements.find((e) => e.id === id))
				.filter((e): e is NonNullable<typeof e> => Boolean(e))
				.map((e, index) => ({
					id: e.id,
					label: shapeLine(e, index + 1),
					selected: design.isSelected(e.id)
				})),
			// The columns of the list a series burns from, so the menu can offer to put one
			// into a text. Empty when nothing is attached, and the row then says so.
			columns: series.state?.attached ? series.state.columns : [],
			// `mkonce` rides every snapshot (`design.py`), but the shared element type in
			// `$lib/design.svelte` does not name it yet and that file belongs to another
			// surface this round. One narrow read, so the row knows which of its two
			// wordings to show; the cast goes when the type grows.
			once:
				chosen.length > 0 &&
				chosen.every((e) => Boolean((e as { once?: boolean }).once))
		};
	});

	/**
	 * The menu row for this key combination, if there is one and it is refused.
	 *
	 * The rows carry the reason a verb cannot be done now, and the keyboard has to obey the
	 * same reason as the menu — otherwise the key posts a request the row already knows will
	 * be refused, and the answer is a 409 in the console instead of a sentence.
	 */
	function refusedRow(combo: string): Action | undefined {
		const label = keyLabel(combo);
		if (!label) return undefined;
		// Both surfaces, because both carry rows with a reason. Alt+P opened the cut path
		// on an empty bed while the canvas-menu row beside it was disabled with "Nothing
		// is on the bed" — measured; the same held for zoom-all and zoom-selection. The
		// point of `off` is that one table governs the menu, the action bar and the
		// keyboard, and searching one menu made that untrue for the other.
		return [
			...objectMenu(actionContext, handlers),
			...canvasMenu(actionContext, handlers, menuPoint)
		]
			.flatMap((group) => group.items)
			.find(
				(item): item is Action =>
					typeof item !== 'string' &&
					!('items' in item) &&
					item.key === label &&
					Boolean(item.off)
			);
	}

	function openObjectMenu(event: MouseEvent, under: string[] = []) {
		menuPoint = null;
		underPointer = under;
		menu = { list: objectMenu(actionContext, handlers), x: event.clientX, y: event.clientY };
	}

	/**
	 * The node the canvas has in hand — for the menu on it and for its shortcuts.
	 *
	 * The state lives in the canvas (that is where the points are drawn and dragged) and
	 * the table of verbs lives in `actions.ts`; this is the one place the two meet, so the
	 * menu row and the key can never mean different things.
	 */
	function nodeContext(): NodeContext {
		const state = canvasControl?.state();
		return {
			index: state?.nodeIndex ?? -1,
			count: state?.nodeCount ?? 0,
			closed: state?.nodeClosed ?? false,
			kind: state?.nodeKind ?? null,
			busy: edits.busy,
			may: canEdit
		};
	}

	const nodeHandlers: NodeHandlers = {
		addNode: () => canvasControl?.node('add'),
		removeNode: () => canvasControl?.node('remove'),
		setKind: (kind) => canvasControl?.node(kind === 'line' ? 'corner' : 'curve')
	};

	function openNodeMenu(event: MouseEvent) {
		menuPoint = null;
		underPointer = [];
		menu = { list: nodeMenu(nodeContext(), nodeHandlers), x: event.clientX, y: event.clientY };
	}

	function openCanvasMenu(event: MouseEvent, point: { x: number; y: number }) {
		menuPoint = point;
		underPointer = [];
		menu = {
			list: canvasMenu(actionContext, handlers, point),
			x: event.clientX,
			y: event.clientY
		};
	}

	/**
	 * Eén tabel, één afhandelaar.
	 *
	 * Before this the shortcuts lived in two places — here and in `Canvas` — and the
	 * keys every desktop app has were missing: ⌘Z did nothing, ⌘C and ⌘V did not exist,
	 * nor did ⌘G. What can and cannot be intercepted in a browser is explained at
	 * `KEYS`.
	 */
	function sneltoets(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
		if (menu) return; // the menu handles its own keys
		const combo = comboOf(event);
		const canvas = canvasControl?.state();

		// While the pen is drawing, Escape and Backspace are its: they stop the line and
		// take back the last point. Deleting the shape that happens to be selected is never
		// what was meant, and it is what used to happen.
		if (canvas?.penDrawing && (combo === 'escape' || combo === KEYS.delete)) return;

		// Same for the node tool with a node in hand. Run it through the menu rows, so the
		// key and the row cannot disagree about whether it is allowed: a row that says
		// "a line needs two nodes" must not be reachable by keyboard either.
		if (tool === 'nodes' && (canvas?.nodeIndex ?? -1) >= 0) {
			const rows = nodeMenu(nodeContext(), nodeHandlers)
				.flatMap((group) => group.items)
				.filter((item): item is Action => typeof item !== 'string' && !('items' in item));
			const row = rows.find((r) => r.key && r.key === keyLabel(combo));
			if (row) {
				event.preventDefault();
				if (!row.off) row.run();
				return;
			}
		}

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
			// ⌘L reads the current state, so the same key locks and unlocks.
			[KEYS.lock]: () => handlers.setLocked(actionContext.lockedCount !== actionContext.count),
			[KEYS.delete]: handlers.remove,
			[KEYS.selectAll]: handlers.selectAll,
			[KEYS.group]: () => handlers.arrange('group'),
			[KEYS.ungroup]: () => handlers.arrange('ungroup'),
			[KEYS.ungroupAlt]: () => handlers.arrange('ungroup'),
			[KEYS.bridges]: () => handlers.bridges(!bridgeState.has),
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
			[KEYS.cutPath]: handlers.cutPath,
			[KEYS.zoomIn]: () => canvasControl?.step(1.25),
			[KEYS.zoomOut]: () => canvasControl?.step(1 / 1.25)
		};
		const action = run[combo];
		if (action) {
			event.preventDefault();
			// A row that says why something cannot be done now must not be reachable by
			// keyboard either — the same rule the node tool follows above. Measured before
			// this with a line selected: ⌘⇧B posted /api/design/bridges anyway, came back 409
			// with a console error, while the menu row beside it was greyed out and said "A
			// line, text or an image carries no bridges". Only a row that is *explicitly* off
			// stops the key, so no shortcut that worked before stops working — and it is
			// both menus that are searched (see `refusedRow`), because the reasons live on
			// the canvas menu too.
			if (refusedRow(combo)) return;
			action();
			return;
		}

		// The arrows move 0.1 mm; with shift 1 mm (an accessibility requirement).
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

<svelte:window bind:innerWidth={width} onkeydown={sneltoets} />

{#if onPhone}
	<!-- The phone is an app of its own: monitor and emergency stop. See DESIGN-SYSTEM v2,
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
		position={phonePosition}
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
	canStop={transportAllowed('stop', { able: control.capabilities?.actions, phase, blocked: control.needsToken })}
	stopArmed={workUnderWay}
	mayLeave={mayLeaveWorkArea(phase)}
	canEdit={canEdit && design.preview === null}
	{narrow}
	canPause={transportAllowed('pause', { able: control.capabilities?.actions, phase, blocked: control.needsToken })}
	canResume={transportAllowed('resume', { able: control.capabilities?.actions, phase, blocked: control.needsToken })}
	paused={phase === 'paused'}
	onPause={() => control.pause()}
	onResume={() => control.resume()}
	onStart={requestStart}
	onStop={() => control.stop()}
	onOpenFile={openFile}
	onOpenProject={openProject}
	onNewProject={newProject}
	onSaved={() => design.load()}
	material={sheetMaterial}
	thicknessMm={sheets.active?.thickness_mm ?? null}
	onOpenMaterial={() => (materialOpen = true)}
	canFrame={(design.elements?.length ?? 0) > 0 &&
		(control.capabilities?.motion?.move ?? false) &&
		!control.needsToken}
	onFrame={() => {
		// No dialog: this is a check movement, not an irreversible step. Through the
		// controller, so that a complaining machine gets on screen.
		control.frame();
	}}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail
		compact={tablet}
		files={narrow}
		{projectInRail}
		bind:tool
		{canEdit}
		onOpenGrid={() => (gridOpen = true)}
		onOpenLibrary={() => (libraryOpen = true)}
		onOpenGenerators={() => (generatorsOpen = true)}
		onOpenClipart={() => (clipartOpen = true)}
		onOpenSeries={() => (seriesOpen = true)}
		onPlaceImage={placeImage}
		onOpenFile={openFile}
		onOpenProject={openProject}
		onNewProject={newProject}
		onSaved={() => design.load()}
	/>
	<!-- Sheets above the canvas: every sheet is a document of its own, so this is also
	     the place where you see which piece of material you are working on. -->
	<div class="stage">
		<!-- Everything between the top bar and the canvas measures itself.
		     The alarm card hangs below the top bar and, since the previous round, covered
		     the action bar and the sheet bar — precisely the two things you need while a
		     message is up. Measured with a USB failure: the card lay across the alignment
		     buttons and across the sheet bar's plus, and Playwright could not click
		     through it. The same approach as `--palette-height` below the canvas: measure,
		     do not calculate. -->
		<div class="bovenrand" bind:clientHeight={topEdgeHeight}>
		<!-- Align, group, mirror and the history: verbs on the selection, so against the
		     bed and not in the properties panel. See DESIGN-SYSTEM v4, "Where does an
		     action belong". -->
		<ActionBar
			history={historyActions(actionContext, handlers)}
			align={alignActions(actionContext, handlers)}
			arrange={arrangeActions(actionContext, handlers)}
			count={actionContext.count}
			note={deeper ? t('canvas.deeper', { index: deeper.index, total: deeper.total }) : null}
			onMore={(event: MouseEvent) => {
				const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
				menuPoint = null;
				menu = {
					list: objectMenu(actionContext, handlers),
					x: box.left,
					y: box.bottom + 4
				};
			}}
		/>
		<SheetTabs
			{sheets}
			{library}
			{canEdit}
			elements={design.elements?.length ?? 0}
			onEditMaterial={() => (materialOpen = true)}
			onSwitched={async () => {
				design.select(null);
				await design.load();
			}}
		/>
		</div>
		<Canvas
			onPointerMm={(point) => (pointerMm = point)}
			onContextObject={openObjectMenu}
			onDeeper={(info) => (deeper = info)}
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
			onContextNode={(e) => openNodeMenu(e)}
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
		{#if wow}
			<!-- Once, on starting: that is when it actually happens. -->
			<JobStart label={status.activeJob?.label ?? null} />
		{/if}
	</div>

	{#if tablet}
	<!-- On a tablet, 280 of 1024 pixels is a quarter of your work surface. The panel
	     may go while you are drawing; the machine buttons are in the top bar, so you
	     never lose the laser. -->
	<button
		class="panelgrip"
		aria-expanded={panelOpen}
		onclick={() => (panelOpen = !panelOpen)}
	>
		<!-- The grip is the pill, not the column. The button stays 44px wide because a
		     thumb needs that, but it is transparent: collapsed, a blank 44px strip
		     otherwise stayed along the edge (gap B6), and that reads as a render fault
		     rather than as something to push at. -->
		<span class="pill" aria-hidden="true">{panelOpen ? '›' : '‹'}</span>
		<span class="vw">{panelOpen ? t('panel.collapse') : t('panel.expand')}</span>
	</button>
{/if}
<aside class="panel" class:gone={tablet && !panelOpen} aria-label={t('panel.aria')}>
		<!-- The bell is in the same row but outside the tablist: according to ARIA a
		     tablist may only contain tabs, and axe otherwise counted the bell as a
		     missing child (aria-required-children). -->
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
			<!-- The fixed place for notifications. Beside the tabs and not floating above
			     the canvas: this panel is about *this* machine, and that is exactly what a
			     notification is about. The bell carries its own state — off or blocked is
			     something you have to be able to see without clicking. -->
			<button
				class="bell"
				class:quiet={!notifications.active}
				aria-haspopup="dialog"
				title={notifications.active ? t('tabs.notifications.on') : t('tabs.notifications.off')}
				aria-label={notifications.active ? t('tabs.notifications.onAria') : t('tabs.notifications.offAria')}
				onclick={() => (notificationsOpen = true)}
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
					{series}
					onRotate={rotate}
					onAssign={assign}
					onChooseMaterial={(id) => {
						// From the layer to the library, which is the direction the question
						// comes from: this shape has to be cut, so what is it made of? The
						// layer travels along, so the window opens with Apply already
						// pointed at it and one tap does the rest.
						libraryLayer = id;
						libraryOpen = true;
					}}
					onLayerChange={() => design.load()}
					onUnlock={() => lockSelection(false)}
					box={design.liveBox}
					onSetPosition={setPosition}
					onSetSize={setSize}
					onArrange={arrange}
					cornerNote={cornerNotice}
					onPrune={tidyUp}
					tidyNote={layoutNotice}
					image={imageState as never}
					onImageSet={(name, enabled, values) =>
						setImage({ adjustment: name, enabled, values })}
					onImageClear={() => setImage({ clear: true })}
					onBridges={setBridges}
					onBridgesOff={clearBridges}
					bridgeNote={bridgeNotice}
					bridgeRevision={bridgeRevision}
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
					{series}
					events={status.events}
					{control}
					activeJob={status.activeJob}
					nothingBurns={design.burnsNothing}
					revision={design.revision}
					selectedIds={design.selectedIds}
					bind:preflight
					onJog={async (dx, dy) => {
						await edits.jog(dx, dy);
					}}
					onHome={async (force?: boolean) => {
						// `force` comes from the rotary question in the panel: the API refuses
						// homing while the rotary is on, and this is the confirmed way through.
						await edits.home(false, force);
					}}
					onUnlock={async () => {
						await edits.unlock();
					}}
					profile={library.activeMachine}
					onFrame={() => control.frame()}
					onCutPath={() => (cutPathOpen = true)}
					colorFor={(id) => design.colorFor(id)}
		onFocus={async (mm) => {
						await post('/api/machine/focus', { distance_mm: mm });
					}}
				/>
			{/if}
		</div>
	</aside>
</div>

<!-- Camera controls beside the canvas, not in the right-hand panel: you are looking at
     the bed while you switch it on. -->
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
		<!-- A long message does not belong in a pill-shaped bar: it becomes a blob then.
		     Its own frame, a readable line width, and dismissible. -->
		<div class="camerror" role="alert">
			<p class="wrap">{camera.error}</p>
			<button aria-label={t('common.dismiss')} onclick={() => (camera.error = null)}>×</button>
		</div>
	{/if}
{/if}

<StatusBar
	pointerMm={pointerMm}
	{device}
	machineState={machine}
	job={status.activeJob}
	connected={status.connected}
	{control}
	{edits}
	actions={!tablet}
/>
{/if}

<!-- Libraries and tools as dialogs of their own: in 280px you cannot search and
     compare. See DESIGN-SYSTEM.md. -->
<TextDialog
	bind:open={textOpen}
	initial={editingText ? (design.elements.find((e) => e.id === editingText)?.text ?? null) : null}
	onConfirm={async (options) => {
		if (editingText) {
			// Text is a path, but the engine keeps the source and re-renders.
			if ((await edits.updateText(editingText, options)).ok) await design.load();
			editingText = null;
		} else if (textAt) {
			draw({ type: 'text', x_mm: textAt.x, y_mm: textAt.y, ...options });
		}
		textAt = null;
	}}
/>

<!-- Work from a previous session: offer it, do not push it. -->
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
			class="btn gone"
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

<!-- Opening a project and starting over both throw work away: ask first, with the
     same words and the same way out. Importing is not among them — that adds. -->
<Dialog
	title={pending?.kind === 'fresh'
		? t('replace.title.new')
		: design.dirty
			? t('replace.title.unsaved')
			: t('replace.title.project')}
	open={pending !== null}
	width="510px"
>
	<!-- Two occasions, two sentences. "Changed since it was last saved" above a
	     drawing you have just opened is untrue, and a question that claims something
	     you can contradict yourself is one you learn to click away. -->
	<p class="ask">
		{#if design.dirty}
			{t('replace.changed')}
		{:else}
			{t('replace.workInProject')}
		{/if}
		{#if pending?.kind === 'project'}
			{t('replace.opensProject', { n: sheets.sheets.length })}
		{:else if sheets.sheets.length === 1}
			{t('replace.emptiesBed')}
		{:else}
			{t('replace.emptiesSheets', { n: sheets.sheets.length })}
		{/if}
	</p>
	{#if recoverable}
		<!-- What can be recovered regardless belongs in the question; it changes what
		     you choose. Only *this* sheet, because that is as far as the recovery file
		     reaches — and we name that boundary. -->
		<p class="ask nuance">{t('replace.recoverable', { when: recoverable })}</p>
	{/if}
	<div class="ask-actions">
		<button class="btn" onclick={() => (pending = null)}>{t('common.cancel')}</button>
		<button
			class="btn"
			onclick={() => {
				const action = pending;
				pending = null;
				if (action) runIt(action);
			}}
		>{t('replace.dontSave')}</button>
		<!-- Cancel / Do not save / Save: the triptych every operating system uses for
		     this question. "Open without saving" was there first, and then the three
		     buttons do not fit on one line — measured at 1024: the primary one dropped
		     to a line of its own. The verbs are already in the title and the sentence
		     above. -->
		<button class="btn primary" onclick={saveThenOpen}
			>{pending?.kind === 'fresh' ? t('replace.saveAndStart') : t('replace.saveAndOpen')}</button
		>
	</div>
</Dialog>

<!-- What lies on top of what: the count, why it matters, and one button that does
     it. A confirm and not a straight action, because the drawing looks identical
     afterwards — the only proof is the sentence in the notice. -->
<Dialog title={t('duplicates.title')} open={duplicates !== null} width="470px">
	{#if duplicates}
		<p class="ask">
			{duplicates.stacks === 0
				? t('duplicates.none')
				: duplicates.stacks > 1
					? t('duplicates.foundSpread', { n: duplicates.extra, stacks: duplicates.stacks })
					: t('duplicates.found', { n: duplicates.extra })}
		</p>
		{#if duplicates.stacks}
			<p class="ask nuance">{t('duplicates.why')}</p>
		{/if}
		{#if duplicates.skipped}
			<p class="ask nuance">{t('duplicates.skipped', { n: duplicates.skipped })}</p>
		{/if}
		<div class="ask-actions">
			{#if duplicates.stacks}
				<button class="btn" onclick={() => (duplicates = null)}>{t('common.cancel')}</button>
				<button class="btn primary" onclick={removeDuplicates}
					>{t('duplicates.remove', { n: duplicates.extra })}</button
				>
			{:else}
				<button class="btn primary" onclick={() => (duplicates = null)}>{t('common.close')}</button>
			{/if}
		</div>
	{/if}
</Dialog>

<!-- The prompt card floats and does not block: a job has just started, and that
     must not disappear behind a modal window. -->
{#if !onPhone && promptOpen && notifications.shouldAsk}
	<div class="vraagkaart">
		<NotificationCard {notifications} variant="prompt" onDone={() => (promptOpen = false)} />
	</div>
{/if}

<Dialog title={t('notifications.title')} bind:open={notificationsOpen} width="460px">
	<NotificationCard {notifications} />
</Dialog>

{#if menu}
	<Menu menu={menu.list} x={menu.x} y={menu.y} onClose={() => (menu = null)} />
{/if}

<!-- The cut path: a workspace, so a window of its own (the placement rule). The bed
     comes from the machine and the sheet from the project, so the path lies on the
     same two rectangles as the canvas draws. -->
<CutPath
	bind:open={cutPathOpen}
	revision={design.revision}
	bed={device?.bed ?? null}
	sheet={sheets.active}
	colorFor={(id) => design.colorFor(id)}
/>

<CornersDialog
	bind:open={cornersOpen}
	count={design.selectedIds.length}
	busy={edits.busy}
	notice={cornerNotice}
	onToepassen={async (stijl, size) => {
		await corners(stijl, size);
		if (!cornerNotice) cornersOpen = false;
	}}
/>

<StencilDialog
	bind:open={stencilOpen}
	count={design.selectedIds.length}
	busy={edits.busy}
	report={stencilReport}
	error={stencilError}
	onLook={async (bridgeMm, perIsland) => {
		const answer = await edits.stencil(design.selectedIds, bridgeMm, perIsland, true);
		stencilReport = answer;
		// The refusal *is* the answer here — "these are single strokes" is what the reader
		// needs — so it is shown where the count would have been, and not swallowed.
		stencilError = answer ? null : edits.error;
	}}
	onApply={async (bridgeMm, perIsland) => {
		const answer = await edits.stencil(design.selectedIds, bridgeMm, perIsland);
		if (!answer) {
			stencilError = edits.error;
			return;
		}
		stencilOpen = false;
		await design.load();
	}}
/>

<Offset
	bind:open={offsetOpen}
	count={design.selectedIds.length}
	busy={edits.busy}
	onToepassen={async (distance) => {
		offsetOpen = false;
		if ((await edits.offset(design.selectedIds, distance)).ok) await design.load();
	}}
/>

<CameraCalibration bind:open={calibrateOpen} {camera} />

<Clipart bind:open={clipartOpen} {canEdit} onInserted={() => design.load()} />

<!-- One design burned once per row of a list. Every verb in here either reads or
     moves the pointer; the burning is the Job panel's button, at the machine. -->
<Series
	bind:open={seriesOpen}
	{series}
	{sheets}
	{library}
	{canEdit}
	onEditMaterial={() => {
		// One modal at a time: the material dialog is a decision you make once, and two
		// stacked windows leave the reader guessing which Escape closes what.
		seriesOpen = false;
		materialOpen = true;
	}}
	onChanged={() => design.load()}
	onDeleteShape={async (id) => {
		// `.ok` and not the result itself: an EditResult is an object and therefore
		// always truthy, so `if (await …)` would reload the design after a refusal too.
		if ((await edits.remove([id])).ok) await design.load();
	}}
/>

<Generators
	bind:open={generatorsOpen}
	hasSelection={design.selectedIds.length > 0}
	selectedIds={design.selectedIds}
	busy={edits.busy}
	hasZAxis={design.layerCapabilities.z_step}
	listAttached={series.attached}
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
		// A sheet that appears silently is a surprise; say so.
		const used = result?.sheets ?? 1;
		return {
			notice:
				used > 1
					? t('notice.sheets.spread', { n: used })
					: null
		};
	}}
/>

<!-- The sheet's material: a small dialog, two choices. It cannot be in the top bar —
     that scrolls horizontally and clips every dropdown — and on a tablet a dialog can
     be operated with a finger as well. -->
<Dialog title={t('sheetMaterial.title')} bind:open={materialOpen} width="440px">
	{#if sheets.active}
		<SheetMaterial
			{sheets}
			{library}
			sheet={sheets.active}
			onDone={() => (materialOpen = false)}
		/>
	{/if}
</Dialog>

<!-- Wider than the 640px that used to be here. Since the library has two panels —
     materials on the left, settings on the right — 640 is just too narrow: the setting
     itself kept 380px and then thickness, values, source and the button squeeze onto one
     line. -->
<Dialog title={t('library.title')} bind:open={libraryOpen} width="1120px">
	<MaterialLibrary
		{library}
		operations={design.operations}
		sheetMaterialId={sheets.active?.material_id ?? null}
		sheetMaterialName={sheetMaterial}
		targetLayer={libraryLayer}
		{canEdit}
		onApplied={() => design.load()}
		token={token()}
		onMakeGrid={(id) => {
			// From the material to the grid: that is where the question arises.
			libraryOpen = false;
			gridMaterial = id;
			gridOpen = true;
		}}
		onReadBoard={() => {
			// The same window, but the reader is coming back with a plank in their hand
			// rather than going out to burn one — so it opens at the half that reads a
			// board back, and the drawing form above it is not what they are looking at.
			libraryOpen = false;
			gridOpen = true;
			readBoard = Date.now();
		}}
	/>
</Dialog>

<Dialog title={t('testgrid.title')} bind:open={gridOpen} width="860px">
	<TestGrid
		{library}
		{canEdit}
		materialId={gridMaterial ?? sheets.active?.material_id ?? null}
		thicknessMm={sheets.active?.thickness_mm ?? null}
		onGenerated={(id) => {
			// A freshly burned grid: step 3 should be on it straight away instead of
			// hanging on "choose a grid…".
			freshGrid = id;
			design.load();
		}}
	/>
	<TestGridResult {library} {canEdit} focusGrid={freshGrid} scrollTo={readBoard} />
</Dialog>

<style>
	/* The two bars above the canvas as one block, so that it can measure itself. */
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
		/* The starting moment lays itself over the bed; that needs an anchor. */
		position: relative;
	}
	.camstrip {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-4));
		/* --palette-height comes from the colour strip under the canvas (B2), which
		   measures itself. Without that term the camera pill lay across the first colour
		   swatches. Zero as long as there is no strip. */
		bottom: calc(var(--statusbar-height) + var(--space-3) + var(--palette-height, 0px));
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
	/* On a tablet there is no room at the bottom *beside* the zoom bar: at 768 the
	   camera pill lay half across it. It goes above it then. */
	@media (max-width: 1199px) {
		.camstrip {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 56px + var(--palette-height, 0px));
		}
		.camerror {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 108px + var(--palette-height, 0px));
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
		bottom: calc(var(--statusbar-height) + var(--space-3) + 40px + var(--palette-height, 0px));
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
	/* The message contains a command on a line of its own; that must not be glued
	   together as one long slab of text. */
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

	/* Bottom right, but *beside* the panel and not over it: that is exactly where the
	   spooler card with the progress of the job that has just started sits, and covering
	   that with the question "shall I tell you when it is done" is the wrong of the
	   wrong. The same widths as `.panel` below — two rules that belong together, so they
	   state beside each other. */
	.vraagkaart {
		position: fixed;
		right: calc(280px + var(--space-4));
		bottom: calc(var(--statusbar-height) + var(--space-4));
		z-index: 70;
		width: min(360px, calc(100vw - 300px - 2 * var(--space-4)));
	}
	@media (max-width: 1199px), (pointer: coarse) {
		.vraagkaart {
			/* Follows the panel width below; two rules that belong together. */
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
	/* On tablet and phone the text is one step larger (15px instead of 13), but the
	   panel stayed 280px — which fits a fifth less on a line than on the desktop and
	   breaks layer names in the middle of a word. 280 × 15/13 ≈ 323: the same number of
	   characters per line as on the desktop.

	   A fixed 324px went wrong on the smallest tablet (gap B2): at 768 the canvas kept
	   316px and the panel was therefore *wider* than the work. Now the panel scales with
	   the window, with 324 as a ceiling so that the text line at 1024 and above stays
	   unchanged. Measured at 768: panel 292, canvas 348 — the canvas wins, as it
	   should. */
	@media (max-width: 1199px), (pointer: coarse) {
		.panel {
			width: clamp(280px, 38vw, 324px);
		}
	}
	.panel.gone { display: none; }
	/* The grip sits against the edge of the canvas, where your thumb already is. The
	   touch target is the whole column (44px, thumb size), but what you see is a pill in
	   the middle: a full 44px column in the panel colour was a blank strip beside the
	   canvas, and that says nothing. */
	.panelgrip {
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
	.panelgrip .pill {
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
	.panelgrip:hover .pill { background: var(--surface-2); color: var(--text-1); }
	.panelgrip:focus-visible { outline: none; }
	.panelgrip:focus-visible .pill { outline: 2px solid var(--accent); outline-offset: 2px; }
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
	/* Off is a state, not a fault: the struck-through bell already says so. No red,
	   because nothing is broken. */
	.bell.quiet {
		color: var(--text-2);
	}
	:global(.ask) { margin: 0 0 var(--space-4); }
	/* The nuance sits below the main sentence and must not drown it out. */
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
	/* "Discard" removes the automatically saved design for good and sat 8px from
	   "Later". This dialog appears unasked on opening — precisely when you are not
	   looking yet — and with a glove on you do not hit the middle of a target. 24px
	   between them, on touch screens only; the mouse layout on the desktop stays as it
	   was. See DESIGN-SYSTEM, "Touch as a first-class input". */
	@media (max-width: 1199px), (pointer: coarse) {
		:global(.ask-actions .btn.gone) { margin-right: var(--space-4); }
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

	/* On tablet/phone the app is primarily monitor + photo input: the panel folds below
	   the canvas, the rail disappears. */
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
