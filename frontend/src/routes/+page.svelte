<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { jobBusy, jobPhase, machineState } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import { DesignStore, isDesignSignal } from '$lib/design.svelte';
	import { EditController } from '$lib/edits.svelte';
	import { saveFile } from '$lib/saving';
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
	let catalogueOpen = $state(false);
	let generatorsOpen = $state(false);
	let clipartOpen = $state(false);
	const sheets = new SheetStore(() => localStorage.getItem('openkerf.token') ?? '');
	let calibrateOpen = $state(false);
	const camera = new CameraStore(() => localStorage.getItem('openkerf.token') ?? '');
	const catalogue = new PresetariatStore(() => localStorage.getItem('openkerf.token') ?? '');
	const tiling = new TilingStore(token);
	/** An action that replaces the current work, awaiting a yes. */
	type Vervanging =
		| { kind: 'file'; file: File }
		| { kind: 'project'; file: File }
		| { kind: 'fresh' };
	let pending = $state<Vervanging | null>(null);
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
		await maybeAskFirst({ kind: 'file', file });
	}

	/**
	 * Every action that replaces the current work asks the same question.
	 *
	 * Opening a file already did that; opening a project file went straight over it
	 * without a word — including the sheets, because those come along from the file.
	 * That is the worst form: throwing work away silently.
	 *
	 * What counts as "work" differs per action. A file comes onto *this* sheet, so only
	 * this sheet counts there. A project and starting over replace *all* the sheets, so
	 * then yesterday's box counts too, even when the sheet you see now is empty.
	 */
	async function maybeAskFirst(action: Vervanging) {
		const touchesEverySheet = action.kind !== 'file';
		const thereIsWork = !design.isEmpty || (touchesEverySheet && sheets.sheets.length > 1);
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

	async function runIt(action: Vervanging) {
		if (action.kind === 'file') {
			await replaceWith(action.file);
		} else if (action.kind === 'project') {
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

	async function replaceWith(file: File) {
		if (!design.isEmpty) {
			if (!(await edits.clear()).ok) return;
		}
		if (await control.load(file)) {
			design.select(null);
			await design.load();
		}
	}

	/** Placing adds: the engine loads on top of what is already there. */
	async function placeImage(file: File) {
		if (!canEdit) return;
		if (await control.load(file)) await design.load();
	}

	async function saveThenOpen() {
		const action = pending;
		pending = null;
		if (!action) return;
		// Downloading counts as saving: the API marks the design clean. What would go
		// away decides what you keep: for a file that is this sheet, for a project and
		// for starting over *all* the sheets go — and then an SVG of the active sheet is
		// not a rescue but half of one.
		//
		// Wait until the file really is there, and do not hope for 800 ms: the next
		// thing that happens empties the bed. If the save fails, the emptying does not
		// go ahead and the dialog is still up.
		const opgeslagen =
			action.kind === 'file'
				? await saveFile('/api/design/export.svg', 'design.svg')
				: await saveFile('/api/project/export.openkerf', 'project.openkerf');
		if (!opgeslagen) {
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
	let phase = $derived(jobPhase(device, status.activeJob, design.isEmpty));
	let workUnderWay = $derived(jobBusy(phase));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		camera.load();
		sheets.load();
		library.load();
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
				const ids = wanted.split(',').filter(Boolean);
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
		state: () => { snap: boolean; layerNumbers: boolean };
	} | null>(null);

	let cornersOpen = $state(false);
	let offsetOpen = $state(false);

	/** Which menu is open, and where. */
	let menu = $state<{ list: MenuList; x: number; y: number } | null>(null);
	/** Where the bed was clicked — "paste here" promises that place. */
	let menuPoint = $state<{ x: number; y: number } | null>(null);

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

	/** The state in which an action is or is not possible. */
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
			empty: design.isEmpty
		};
	});

	function openObjectMenu(event: MouseEvent) {
		menuPoint = null;
		menu = { list: objectMenu(actionContext, handlers), x: event.clientX, y: event.clientY };
	}

	function openCanvasMenu(event: MouseEvent, point: { x: number; y: number }) {
		menuPoint = point;
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
	canStop={(control.capabilities?.actions.stop ?? false) && !control.needsToken}
	stopArmed={workUnderWay}
	canEdit={canEdit && design.preview === null}
	{narrow}
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
		onOpenCatalogue={() => (catalogueOpen = true)}
		onOpenGenerators={() => (generatorsOpen = true)}
		onOpenClipart={() => (clipartOpen = true)}
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
					onRotate={rotate}
					onAssign={assign}
					onLayerChange={() => design.load()}
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
					revision={design.revision}
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

<!-- Opening, opening a project and starting over all three throw work away: ask
     first, with the same words and the same way out. -->
<Dialog
	title={pending?.kind === 'fresh'
		? t('replace.title.new')
		: design.dirty
			? t('replace.title.unsaved')
			: pending?.kind === 'project'
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
		{:else if pending?.kind === 'file'}
			{t('replace.workOnSheet', { n: design.elements.length })}
		{:else}
			{t('replace.workInProject')}
		{/if}
		{#if pending?.kind === 'file'}
			{t('replace.opensSheet')}
		{:else if pending?.kind === 'project'}
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

<Offset
	bind:open={offsetOpen}
	count={design.selectedIds.length}
	busy={edits.busy}
	onToepassen={async (distance) => {
		offsetOpen = false;
		if ((await edits.offset(design.selectedIds, distance)).ok) await design.load();
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
		{canEdit}
		onApplied={() => design.load()}
		token={token()}
		onMakeGrid={(id) => {
			// From the material to the grid: that is where the question arises.
			libraryOpen = false;
			gridMaterial = id;
			gridOpen = true;
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
	<TestGridResult {library} {canEdit} focusGrid={freshGrid} />
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
