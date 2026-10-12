<script lang="ts">
	import {
		phaseBody,
		phaseTitle,
		formatDuration,
		jobBusy,
		jobPhase,
		isStalled,
		pastEstimate,
		progressFromEstimate,
		remainingSeconds,
		transportAllowed,
		machineName,
		progressIsLive,
		PAUSE_KEY,
		STOP_KEY,
		type Device,
		type Job
	} from '$lib/api';
	import { screen } from '$lib/screen.svelte';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import type { Controller, Position } from '$lib/control.svelte';
	import type { SeriesStore } from '$lib/series.svelte';
	import { connection } from '$lib/connection.svelte';
	import { inkOn, layerNumber, type Design } from '$lib/design.svelte';
	import JobPreview from './JobPreview.svelte';
	import Dialog from './Dialog.svelte';
	import { rotary } from '$lib/rotary.svelte';
	import type { RotaryState } from '$lib/rotary';
	import Segmented from './Segmented.svelte';
	import Notice from './Notice.svelte';
	import Why from './Why.svelte';
	import Icon from './Icon.svelte';
	import EmptyState from './EmptyState.svelte';
	import Menu from './Menu.svelte';
	import type { Menu as MenuList } from '$lib/actions';

	let {
		control,
		device,
		series,
		job,
		nothingBurns = false,
		designLoaded = true,
		sheetName = '',
		revision = 0,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock,
		onLock,
		onFocus,
		onCutPath,
		colorFor,
		profile = null,
		selectedIds = []
	}: {
		control: Controller;
		device: Device | null;
		/**
		 * The series, for the two things the pre-flight has to say about one.
		 *
		 * A run going means this button burns one plate and counts nothing — the API
		 * refuses it (`Series.vet_plain_job`), and a refusal you only meet after
		 * pressing is a poor way to learn that. And the clock above it is about one
		 * plate while the afternoon is fifty, which is the line below the estimate.
		 */
		series: SeriesStore;
		job: Job | null;
		/** Nothing on the bed that will burn. Comes from the page, from the same
		 *  `burnsNothing` the top bar reads. */
		nothingBurns?: boolean;
		/**
		 * Has the first `/api/design` answered? (`design.loaded` on the page.)
		 *
		 * `nothingBurns` cannot tell "no layer burns" from "not read yet", and both
		 * arrive here as `true`. The buttons may stay off on either — a job that
		 * cannot be described must not be startable — but the card says nothing at
		 * all until the design has been read, rather than stating that the bed is
		 * empty over a document still on its way.
		 */
		designLoaded?: boolean;
		/**
		 * The name of the sheet on the bed, as the name to put on the machine.
		 *
		 * `profile` in this file is the *machine* profile, not the sheet, so this comes
		 * in as a prop along the same road as `nothingBurns`: the page reads it off the
		 * sheet store and hands it down through `JobPanel`.
		 */
		sheetName?: string;
		/** Increases on every change in the design; the estimate follows it. */
		revision?: number;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		/** `force` presses through the rotary guard — see the dialog below. */
		onHome?: (force?: boolean) => void;
		onUnlock?: () => void;
		/** Hold the motors again. The engine layer has had this as long as `unlock`;
		 *  the app offered only half the pair. */
		onLock?: () => void;
		onFocus?: (distanceMm: number) => void;
		/** Opening the cut-path window (gap S1). The frame itself lives in the top bar;
		 *  this is the moment you want to know in what order it burns — and unlike the
		 *  frame it costs no movement of the machine. */
		onCutPath?: () => void;
		/** The same layer colour the canvas and the layer list show. */
		colorFor?: (operationId: string | null) => string;
		/** What this machine profile says it can do; decides what appears. */
		profile?: { has_z: number; has_autofocus: number } | null;
		/** What is selected on the canvas. Print and cut takes its two marks from
		 *  there: pointing them out is a thing you do on the drawing, so it would be
		 *  wrong to invent a second way of picking shapes inside this panel. */
		selectedIds?: string[];
	} = $props();

	// Gap J9: one source for "where does this action live". See screen.svelte.ts.
	let barCarries = $derived(screen.controlsInBar);
	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	// Standing still, not only "paused according to the status field": on Lihuiyu
	// pausing sets `running` to false and reports nothing further. Without this it read
	// "Pause" (disabled) on a job that needed resuming.
	let paused = $derived(isStalled(job));
	let queued = $derived(device?.spooler.queue_length ?? 0);
	// A running job is the reason starting is not allowed; that has to be in the
	// tooltip, because a grey button without a reason is a riddle.
	let taken = $derived(running || paused);
	let cut = $derived(control.printcut);
	// The marks that are actually usable: the API drops a mark whose shape was deleted
	// to `drawn: null`, and offering "drive to mark 2" for a shape that is gone would be
	// a button that can only fail.
	let cutMarks = $derived((cut?.marks ?? []).filter((mark) => mark.drawn !== null));
	let tokenDraft = $state('');
	let step = $state(10);
	type Warning = { code: string; text: string; weight?: number };
	type Layer = {
		id: string | null;
		label: string;
		speed_mm_s: number | null;
		power_percent: number | null;
		passes: number;
		elements: number;
		source: string | null;
		/** The material this setting was made for — known as soon as it comes from a
		 *  preset (decision B1). */
		material_name?: string | null;
		thickness_mm?: number | null;
		warnings?: Warning[];
		/** Does this engine actually execute the layer? See `rasterOff`. */
		burns?: boolean;
		/** Is "burn along" on for this layer? A layer with it off is in this table
		 *  and marked, rather than left out of it (P11). */
		output?: boolean;
	};
	type Bounds = {
		bed: { width_mm: number; height_mm: number } | null;
		sheet: { width_mm: number; height_mm: number } | null;
		work: { x_mm: number; y_mm: number; width_mm: number; height_mm: number } | null;
		outside_bed: number;
		outside_sheet: number;
		outside_bed_ids: string[];
		outside_sheet_ids: string[];
	};
	type SheetInfo = {
		name: string;
		width_mm: number;
		height_mm: number;
		material_name: string | null;
		thickness_mm: number | null;
	};
	/**
	 * The clock, and with a series the whole afternoon.
	 *
	 * `burns_left` and `seconds_total` come from `/api/job/estimate` and are not worked
	 * out here: the route knows which burns are still due (the ones whose rows are not
	 * all in `done`, the same partition the run verbs act on) and it measures the plate
	 * with the mutator the burn itself uses, so the places the list has no rows left for
	 * and a jig frame already cut are out of the sum. Multiplying here instead would be
	 * a second place counting plates, and the moment the two disagree the number on the
	 * screen is nobody's. Without a series `burns_left` is 1 and `seconds_total` equals
	 * `seconds`, so there is no branch to keep in step.
	 */
	let estimate = $state<{
		seconds: number;
		parts: number;
		burns_left?: number;
		seconds_total?: number;
	} | null>(null);
	/**
	 * What gets burned, separate from how long it takes.
	 *
	 * A source of its own, because for the clock `/api/job/estimate` builds the whole
	 * cut plan and on a heavy design that takes minutes. The warning that a layer
	 * carries a setting for a *different* material is exactly what you have to see
	 * before starting; it should not be queued behind a time estimate.
	 */
	let overview = $state<{
		sheet?: SheetInfo | null;
		layers?: Layer[];
		bounds?: Bounds | null;
		engine?: { raster: boolean } | null;
		/** Machine-wide, and it changes what burns — so the pre-flight says it out loud
		 *  rather than leaving it on a settings page nobody opens twice. */
		rotary?: RotaryState | null;
	} | null>(null);
	let layers = $derived(overview?.layers ?? []);
	/**
	 * The rows of the layer table: what the server lists, plus what it leaves out.
	 *
	 * `/api/job/layers` only reports layers that burn, which is right for the clock
	 * and wrong for the reader. Measured with three layers, the third switched off and
	 * holding two shapes: the table had two rows, and the drawing under it said "2
	 * shapes sit in no layer that burns" — so the pre-flight named neither the layer
	 * nor the switch, while the Layers tab two clicks away showed that same layer
	 * dashed and tagged "does not burn". The layer belongs in the table, marked with
	 * the tag it already carries there (P11).
	 *
	 * From the design snapshot this panel fetches anyway, in the design's own order,
	 * and only for a layer that actually holds something: an empty switched-off layer
	 * is not a shape that will not burn.
	 */
	let pfLayers = $derived.by<Layer[]>(() => {
		const operations = design?.operations ?? [];
		if (!operations.length) return layers;
		const left = new Map(layers.filter((l) => l.id).map((l) => [l.id as string, l]));
		const rows: Layer[] = [];
		for (const op of operations) {
			const known = op.id ? left.get(op.id) : undefined;
			if (known) {
				rows.push(known);
				left.delete(op.id);
				continue;
			}
			if (op.output || !op.element_ids.length) continue;
			rows.push({
				id: op.id,
				label: op.label,
				speed_mm_s: op.speed,
				power_percent: op.power === null ? null : Math.round(op.power) / 10,
				passes: op.passes ?? 1,
				elements: op.element_ids.length,
				source: null,
				burns: false,
				output: false
			});
		}
		// A row the design does not know by id keeps its place at the end rather than
		// falling out of the table: the table may lose nothing the server said.
		rows.push(...layers.filter((l) => !l.id || left.has(l.id)));
		return rows;
	});
	/**
	 * The design for the drawing above (decision B8).
	 *
	 * A fetch of its own and not the page's store: this panel is not handed it, and
	 * just before starting you want to see what is on the bed *now* anyway, not what
	 * was there when the canvas last refreshed.
	 */
	let design = $state<Design | null>(null);

	// What the layer carries against what is being burned. This is the last moment at
	// which that difference still costs something you can undo.
	//
	// One line per layer: two objections about the same layer read as two layers,
	// because the name then sits above it twice. And the heaviest objection first — a
	// measured setting for the wrong material is worse than a calculated one for the
	// right material, and then that has to be at the top.
	let mismatch = $derived(
		layers
			.filter((l) => l.burns !== false && l.warnings?.length)
			.map((l) => ({
				layer: l.label,
				weight: Math.max(...(l.warnings ?? []).map((w) => w.weight ?? 1)),
				text: (l.warnings ?? []).map((w) => w.text).join(' ')
			}))
			.sort((a, b) => b.weight - a.weight)
	);
	// Only point when there is something to choose: between objections of equal weight
	// "this first" is an arbitrary instruction and therefore noise.
	let firstWeighsMore = $derived(
		mismatch.length > 1 && mismatch[0].weight > mismatch[mismatch.length - 1].weight
	);
	let sheetText = $derived.by(() => {
		const sheet = overview?.sheet;
		if (!sheet?.material_name) return null;
		const thickness = sheet.thickness_mm;
		return thickness === null || thickness === undefined
			? sheet.material_name
			: `${sheet.material_name} · ${String(thickness).replace('.', ',')} mm`;
	});

	/**
	 * Does it fit on the bed, and does it fit on the sheet? (gaps J5 and C2)
	 *
	 * Both questions are answered by the server and not here: it measures them for the
	 * canvas anyway, and two places computing it themselves can
	 * disagree about the edge. `bounds` therefore belongs in `/api/job/layers` and not
	 * only in `/api/job/estimate` — otherwise "falls off the bed" only appears once the
	 * clock is back, and on a heavy design that can take seconds.
	 *
	 * The message itself lives in `JobPreview`, directly under the drawing where the
	 * shape it is about can be seen.
	 */
	let bounds = $derived(overview?.bounds ?? null);

	/**
	 * Does this engine burn raster layers?
	 *
	 * No, headless: the converter from raster area to laser lines sits in the wxPython
	 * GUI. During planning the layer throws its own shapes away and produces no
	 * cutcode. That must not be a surprise *after* burning, and the time estimate must
	 * not promise seconds for it.
	 *
	 * The key is `raster` — the name `engine_report` (drawing.py) and the test-grid
	 * preview both write. It was read here as `grid`, which the API never sends, so this
	 * block could not appear on any server; `tests/no-raster.test.ts` holds the two names
	 * together now.
	 */
	let rasterOff = $derived(overview?.engine?.raster === false);
	/**
	 * The rotary, from the pre-flight's own answer.
	 *
	 * `/api/job/layers` carries it, so the sentence beside the start button is measured
	 * against the same design as the layer table. The store beside it (`rotary`) is what
	 * the *buttons* read — the home guard has to know before any estimate has come in.
	 */
	let rotaryOn = $derived(overview?.rotary?.active === true);
	let rotaryText = $derived.by(() => {
		const state = overview?.rotary;
		if (!state?.active) return null;
		const factor = i18n.number(Math.round(state.scale_y * 10000) / 10000);
		return state.kind === 'roller'
			? t('job.rotary.roller', {
					circumference: i18n.number(Math.round(state.circumference_mm * 10) / 10),
					factor
				})
			: t('job.rotary.chuck', { diameter: i18n.number(state.diameter_mm), factor });
	});
	/** The layers *this engine* cannot carry out — not the ones the user switched
	 *  off. Both read `burns === false`, and only the first is a fault of the
	 *  server the sentence beside it is about. */
	let blindLayers = $derived(layers.filter((l) => l.burns === false && l.output !== false));
	/**
	 * The afternoon behind the plate: what is still to come, in one sentence.
	 *
	 * Only when more than one burn is due. With one it would say the same number twice
	 * — the estimate above it — and a line that repeats the line above it teaches you
	 * to stop reading both.
	 */
	let seriesLeft = $derived.by(() => {
		const left = estimate?.burns_left ?? 1;
		const total = estimate?.seconds_total;
		if (left <= 1 || total === null || total === undefined) return null;
		return t('job.seriesLeft', {
			burns: t('count.burns', { n: left }),
			time: formatDuration(total)
		});
	});
	/**
	 * A series is going, so the ordinary Burn button is not the button to press.
	 *
	 * It would burn one plate and count nothing, and the operator would find out by
	 * counting plates against the burn list. The API refuses it, and this is the same
	 * sentence it refuses with — one fact, one wording, whether you read it in the
	 * tooltip before pressing or get it back after.
	 */
	let seriesRunning = $derived(series.running);
	// Whole millimetres where it can be; 0.5 mm stays 0.5 mm. Written in the
	// reader's own notation, because these numbers get typed into a machine.
	function size(value: number): string {
		return i18n.number(Math.round(value * 10) / 10);
	}

	// Settings that were not measured deserve a warning before the material is in
	// the machine — not after.
	const UNMEASURED: Record<string, MessageKey> = {
		geextrapoleerd: 'preset.source.extrapolated',
		handmatig: 'preset.source.manual',
		geimporteerd: 'preset.source.someoneElse'
	};
	// A layer that does not burn need not have trustworthy settings: nothing is
	// done with them. Counting it turns "3 layers were not measured" into a number
	// that does not match what is about to happen.
	let risky = $derived(layers.filter((l) => l.burns !== false && l.source !== 'testraster'));

	/**
	 * Where the numbers of this layer come from, in two words.
	 *
	 * "Measured" above a setting that was measured on *other* material reassures
	 * where it should not: the measuring is sound, the material is not. So this
	 * column says what is actually going on, and the line below it says why.
	 */
	function source(layer: Layer): string {
		const codes = (layer.warnings ?? []).map((w) => w.code);
		if (codes.includes('ander-materiaal')) return t('preset.source.otherMaterial');
		if (codes.includes('andere-dikte')) return t('preset.source.otherThickness');
		if (layer.source === 'testraster') return t('preset.source.measured');
		return t(UNMEASURED[layer.source ?? ''] ?? 'preset.source.unmeasured');
	}
	let estimating = $state(false);
	let estimateSlow = $state(false);
	/** Has an estimate ever come in? Before that neither verdict is honest. */
	
	// The engine builds the whole cut plan for this estimate. On a heavy design that
	// took more than three minutes here, and meanwhile the pre-flight sat on a dot. An
	// estimate must never be the reason you cannot start, so after ten seconds we
	// simply say so.
	const ESTIMATE_PATIENCE = 10_000;

	// The engine's estimate before starting: until now the pre-flight only showed the
	// time of a job that was already running, which is exactly too late.
	//
	// Two requests, deliberately not one: the overview (layers, material, objections)
	// arrives at once, the clock may come afterwards. The other way round the
	// warning about the wrong material waiting minutes behind a time estimate on a
	// heavy design.
	async function loadEstimate() {
		estimating = true;
		estimateSlow = false;
		try {
			// Side by side: the drawing and the layer table should appear on screen
			// together, not one half a second after the other.
			const [layers, snapshot] = await Promise.all([
				fetch('/api/job/layers'),
				fetch('/api/design')
			]);
			overview = layers.ok ? await layers.json() : null;
			design = snapshot.ok ? await snapshot.json() : null;
		} catch {
			overview = null;
			design = null;
		}
		const slow = setTimeout(() => (estimateSlow = true), ESTIMATE_PATIENCE);
		try {
			const response = await fetch('/api/job/estimate');
			estimate = response.ok ? await response.json() : null;
		} catch {
			estimate = null;
		} finally {
			clearTimeout(slow);
			estimating = false;
			estimateSlow = false;
		}
	}

	/**
	 * Fetching the estimate as long as the preparation is on screen.
	 *
	 * It hung off the `preflight` flag, and that only flipped once. Now the block is
	 * always open when nothing is in flight, so it has to keep up with the design —
	 * otherwise there is a time on screen for a drawing you have already replaced.
	 *
	 * With a brake on it: every shape you draw gives a signal, and `plan` is not free.
	 * 400 ms after the last change is fast enough to feel fresh and slow enough not to
	 * type along.
	 */
	let schatKlok: ReturnType<typeof setTimeout> | null = null;
	/**
	 * Is the preparation on screen at all — as a boolean, and that matters.
	 *
	 * Reading `device.spooler.queue_length` inside the effect below re-ran it on
	 * every snapshot, and the engine pushes a full snapshot every two seconds
	 * (`HEARTBEAT_SECONDS`). So the estimate was refetched twice a minute on a
	 * design nobody had touched, and `estimating` flipped along with it: on an empty
	 * bed the whole block swapped between "nothing to burn" and the full checklist,
	 * and with work on it the time on the start button blinked in and out. Measured:
	 * twelve requests in twelve seconds on an idle page.
	 *
	 * A `$derived` only wakes its readers when its *value* changes, so a heartbeat
	 * that says the same thing as the last one now changes nothing.
	 */
	let idle = $derived((device?.spooler?.queue_length ?? 0) === 0);
	$effect(() => {
		// Deliberately *not* looking at `busyWithWork`: that hangs off the estimate via
		// `empty`, and then this effect would be its own trigger. The queue length says
		// the same thing without the loop.
		const visible = idle;
		void revision;
		if (!visible) {
			if (schatKlok) clearTimeout(schatKlok);
			return;
		}
		if (schatKlok) clearTimeout(schatKlok);
		schatKlok = setTimeout(loadEstimate, 400);
		return () => {
			if (schatKlok) clearTimeout(schatKlok);
		};
	});

	// Without a token every write action yields a 401. Offering a button that is
	// guaranteed to fail is an empty promise, so it is blocked here already. The
	// same goes for a server that has dropped out: nothing arrives then, and a
	// button that looks operable promises something that will not happen.
	let blocked = $derived(
		control.tokenProbleem || control.busy !== null || !connection.online
	);
	let blockedReason = $derived(
		!connection.online
			? t('job.blocked.noServer')
			: control.tokenProbleem
				? t('job.blocked.token')
				: undefined
	);

	// Moving the head while burning ruins the job at best.
	let movingBlocked = $derived(
		!connection.online
			? t('job.blocked.noServerMove')
			: running
				? t('job.blocked.duringJob')
				: undefined
	);
	let movingOff = $derived(running || !connection.online);

	// ------------------------------------------- bewaarde posities (gat J6)

	let posities = $state<Position[]>([]);
	let saving = $state(false);
	let newName = $state('');
	let currentMm = $derived(device?.position.mm ?? null);

	async function ophalenPosities() {
		posities = await control.listPositions();
	}
	// On opening the panel *and* after a machine switch: positions belong to the
	// machine, so the previous one's are nonsense here. The same holds for the zero
	// point (J12) and for the adjustment (J11) — both live on the machine and not in
	// the browser.
	$effect(() => {
		void device?.path;
		ophalenPosities();
		control.loadOrigin();
		// Print and cut lives on the machine as well, and a pose measured on another
		// bed means nothing here.
		control.loadPrintCut();
		// The rotary too: it is bolted into *this* bed, so switching machine switches
		// the answer to "is homing safe".
		rotary.load(true);
		if (control.canAdjust) control.loadAdjustment();
	});

	/** The two quantities that can be adjusted during a job (J11). */
	const ADJUSTABLE = [
		{ what: 'power' as const, key: 'job.adjust.power' as MessageKey },
		{ what: 'speed' as const, key: 'job.adjust.speed' as MessageKey }
	];

	async function save() {
		const name = newName.trim();
		if (!name) return;
		if (await control.savePosition(name)) {
			saving = false;
			newName = '';
			await ophalenPosities();
		}
	}

	async function vergeet(name: string) {
		if (await control.deletePosition(name)) await ophalenPosities();
	}

	async function confirmStart() {
		if (!actions?.start || blocked || seriesRunning || device?.connection?.state === 'disconnected') return;
		if (await control.start()) preflight = false;
	}

	/**
	 * Homing with a rotary in the bed.
	 *
	 * The API refuses it (rotary.py: the head drives into the chuck), and a refusal you
	 * only see after pressing is a poor way to learn that. So the question comes first,
	 * here, and the answer travels as `force`. The refusal stays in the API: this dialog
	 * is advice, and a second tab or a curl command does not see it.
	 */
	let askHome = $state(false);

	function home() {
		if (rotary.active) {
			askHome = true;
			return;
		}
		onHome?.();
	}

	/**
	 * Is there anything to burn?
	 *
	 * On an empty bed the pre-flight cheerfully showed "Estimated time 0:00", the full
	 * safety checklist and a green "Start now". That is wrong twice over: you only
	 * hear there was nothing there after starting, and meanwhile you learn to click
	 * away a safety list that is about nothing. A checklist you get used to ticking off
	 * protects nobody any more.
	 *
	 * `parts` is the number of parts in the built cut plan; zero means the machine
	 * would do nothing. Until the first estimate has come in we do not know, and then
	 * we keep quiet.
	 *
	 * Deliberately *not* "and no estimate is running": a recalculation would then
	 * undo the verdict for as long as it lasted, and on an empty bed the block
	 * swapped to the full checklist and back on every recalculation. What we knew a
	 * moment ago stays on screen until the new answer replaces it.
	 */
	// One question, asked of the design and not of the estimate: see `burnsNothing` in
	// `$lib/design.svelte`. It used to be `estimate.parts === 0` here and
	// `elements.length === 0` in the top bar, and on a bed with every layer switched off
	// the bar said "ready" while this panel said "nothing". Asking the design also
	// settles what the comment below used to guard against — there is no recalculation
	// that could briefly undo the verdict.
	let empty = $derived(nothingBurns);

	/**
	 * The phase, from one source (`jobPhase` in `$lib/api.ts`).
	 *
	 * Before this, this panel read `job.running` and the top bar read the machine
	 * state, and for a job that had been spooled but not yet picked up (`status:
	 * "Waiting"`, `running: false`) those two disagreed: the bar disabled starting,
	 * this panel left it on. One tap here then spooled a second job on top of the
	 * first.
	 */
	let phase = $derived(jobPhase(device, job, empty));
	let busyWithWork = $derived(jobBusy(phase));
	let machineOpen = $state(false);
	$effect(() => {
		if (busyWithWork) machineOpen = false;
	});
	let progressPart = $derived.by(() => {
		const part = job?.progress;
		if (part === null || part === undefined || !Number.isFinite(part)) return null;
		// A job that is finished but not signed off by the engine sits at 0.998; we show
		// that as full, because that is what has happened.
		return phase === 'done' ? 1 : Math.min(1, Math.max(0, part));
	});
	let remaining = $derived(phase === 'done' ? 0 : remainingSeconds(job));
	/** A Ruida's progress: its burning time over the plan's estimate, said as such.
	 *  Its step count is packets on the line, not work, and is left out with it. */
	let estimated = $derived(progressFromEstimate(job));
	let outrun = $derived(pastEstimate(job));

	/**
	 * Is the card reporting, or remembering?
	 *
	 * The job keeps its state when the link to the controller drops, but then its figures
	 * are the last thing we heard. A confident "Burning 42%" in the accent beside a
	 * machine nobody can reach says the laser is doing something we do not know; so the
	 * card says "last known" in muted ink, and the bar stands still. Stop is untouched:
	 * `transportAllowed` decides that, here as in the top bar.
	 */
	let live = $derived(progressIsLive(device, connection.online));
	let stale = $derived(!live && busyWithWork);
	/** When we last heard, if anything says: the server's own outage clock, or how long
	 *  the controller link has read the same. */
	let heardAt = $derived.by(() => {
		if (!connection.online) return connection.since;
		const held = device?.connection?.held_ms;
		return typeof held === 'number' ? Date.now() - held : null;
	});
	let lastKnown = $derived(
		progressPart === null
			? t('job.lastKnown.noProgress', { phase: phaseTitle(phase) })
			: t('job.lastKnown', {
					phase: phaseTitle(phase),
					percent: i18n.number(Math.round(progressPart * 100))
				})
	);

	// ------------------------------------------------ sending it to the machine

	/**
	 * The name the machine will keep, ready-made from the name of the sheet.
	 *
	 * `typed` and not one `$state` seeded once: this panel is not rebuilt when you
	 * switch sheets, so a field filled at mount goes on offering the name of the sheet
	 * you have left. Whoever has typed a name keeps it; whoever has not follows the
	 * sheet. Either way `uploadName` is what the machine will keep — eight characters,
	 * capitals, no spaces — so the field promises nothing the panel will not show.
	 *
	 * What `typed` holds is what stands in the box, in the case it was typed in, and
	 * the capitals on screen come from `text-transform` in the style below. That
	 * division is not cosmetic: writing the upper-cased text back into the field on
	 * every keystroke moves the cursor to the end of it. Measured on `ABCD` with the
	 * cursor between B and C — an ordinary lower-case `x` gave `ABXCD` with the cursor
	 * at 5 instead of 3, and a capital `X`, which the filter leaves alone, kept it at
	 * 3. Nearly every keystroke is a lower-case letter, so in practice you could only
	 * type at the end: correcting `SHEET1` to `SHEETS1` meant retyping the whole name,
	 * in the one field this screen is about.
	 */
	let typed = $state<string | null>(null);
	let fieldText = $derived(typed ?? machineName(sheetName));
	let uploadName = $derived(machineName(fieldText));

	/**
	 * The characters of a name the machine can keep, in the case they were typed.
	 *
	 * Asked of `machineName` per character rather than written out a second time: a
	 * character survives exactly when the rule keeps it, and the length is the length
	 * that same rule leaves — so there is no second copy here of which characters are
	 * printable or of how long a name may be.
	 */
	function keepable(raw: string): string {
		const kept = [...raw].filter((c) => machineName(c) !== '').join('');
		return kept.slice(0, machineName(kept).length);
	}

	/**
	 * A keystroke in the name field: drop what the machine cannot keep, leave the rest
	 * where it stands.
	 *
	 * The field is only written back to when the filter really dropped something —
	 * a space, an accented letter, a ninth character — and then the cursor is put back
	 * where it was, minus what fell away in front of it. Measured, cursor between B and
	 * C of `ABCD`: `x` → `ABxCD` and the cursor at 3, a space → `ABCD` and the cursor
	 * still at 2 (before this it went to the end, 5 and 4).
	 *
	 * A composition is left alone until it is finished. Somebody typing Japanese has a
	 * half-built word in the field — `に` and the `h` of the next syllable — and every
	 * one of those intermediate steps arrives as an `input` event. Writing to the field
	 * then takes the composition apart: measured over CDP with `にほん` composed and
	 * `日本` confirmed, the box went `"n"`, `"ni"`, `"h"`, and stayed `"h"` after the
	 * confirmation — the Japanese never arrived at all, and what was left was a letter
	 * from the romaji buffer that nobody typed as a name and that the filter is happy
	 * to send to the machine as `H`. So the keystrokes are ignored while `isComposing`
	 * is true and the finished text is filtered once, at `compositionend`. Measured
	 * again: the box follows the composition and ends up empty, because none of `日本`
	 * is a character the panel can show — which is the same thing a dead key does.
	 */
	function nameTyped(event: Event & { currentTarget: HTMLInputElement; isComposing?: boolean }) {
		// Optional, because `isComposing` lives on `InputEvent` and the same handler also
		// serves `compositionend` — where there is no such field, and the composition is
		// over by definition.
		if (event.isComposing) return;
		const field = event.currentTarget;
		const raw = field.value;
		const at = field.selectionStart ?? raw.length;
		const kept = keepable(raw);
		typed = kept;
		if (kept === raw) return;
		const before = keepable(raw.slice(0, at)).length;
		field.value = kept;
		field.setSelectionRange(before, before);
	}
	let uploaded = $state<string | null>(null);
	$effect(() => {
		// The confirmation is about one name. The moment the field says something else —
		// because you typed, or because you are on another sheet — it would be a green
		// line about a file nobody just sent, so it goes.
		uploadName;
		uploaded = null;
	});
	/**
	 * Why sending is off, in a sentence.
	 *
	 * No server and no token are the two that stop starting as well, and for the same
	 * reason as there: `/api/machine/upload` is in `WRITE_ROUTES`, so without a token
	 * it is a guaranteed 401, and a button that cannot succeed is an empty promise.
	 * That one was missing here while the start button beside it had it — the
	 * comment that used to stand here said "the first three are the ones that stop
	 * starting as well", which was three counted off a list that did not include it.
	 *
	 * `actions.upload` is about the machine itself and comes from the same check that
	 * refuses the route (`CommandRunner.keeps_files`), so the button is not offered
	 * where it could only fail. What is deliberately *not* here: whether the machine
	 * is a Ruida that is merely busy with somebody else's file. That is not knowable
	 * from here, and the refusal for it is a whole sentence.
	 */
	let uploadOff = $derived(
		!connection.online
			? t('transport.noServer')
			: control.tokenProbleem
				? t('job.blocked.token')
				: actions?.upload === false
					? t('api.upload.notRuida')
					: busyWithWork
						? t('job.blocked.duringJob')
						: empty
							? t('job.nothing.title')
							: undefined
	);
	/**
	 * The arrow beside the start button, and the menu it opens.
	 *
	 * "Send to the machine" used to be a fold in the footer, and it was not found there:
	 * a hand looking for a way to run the job looks at the button that runs it. So the
	 * other way sits beside that button, behind an arrow, the way the project menu hangs
	 * off its button in the top bar — same cover, same fixed position, because the panel
	 * scrolls and would clip an absolute menu. The arrow itself burns nothing and the
	 * start button keeps its two taps, so nothing about the safety rule changes.
	 */
	let moreOpen = $state(false);
	let morePos = $state({ x: 0, y: 0, upward: false });
	let uploadOpen = $state(false);
	/** The menu is the shared context menu (`Menu.svelte`): the same keys, the same
	 *  flip at an edge, the same reason in the tooltip of a row that cannot be done. */
	let moreMenu = $derived<MenuList>([
		{
			items: [
				{
					id: 'upload',
					label: t('job.upload'),
					off: uploadOff,
					explain: t('job.upload.why'),
					run: chooseUpload
				}
			]
		}
	]);
	function openMore(button: HTMLElement) {
		if (moreOpen) {
			moreOpen = false;
			return;
		}
		const box = button.getBoundingClientRect();
		// Aligned to the arrow's right edge — the menu flips left of `x` when it meets the
		// edge of the window — and above the button when there is no room below it.
		const below = window.innerHeight - box.bottom > 120;
		morePos = { x: box.right, y: below ? box.bottom + 6 : box.top - 6, upward: !below };
		moreOpen = true;
	}
	function chooseUpload() {
		moreOpen = false;
		uploaded = null;
		uploadOpen = true;
	}
	async function sendToMachine() {
		// The name that comes back, not the one that went in: the machine's copy of the
		// rule is the one that counts, and reporting our own would be a screen agreeing
		// with itself.
		const result = await control.upload(uploadName);
		uploaded = result?.name ?? null;
	}
</script>

<div class="section">
	<!-- The heading said "Controls", and that is true: these are controls. But it
	     says nothing about what is going on right now, and that is exactly what
	     you come to this tab for. A group label, the same one the Edit and Layers
	     tabs head their groups with. -->
	<h2 class="label-section job-heading">
		{busyWithWork || phase === 'done' ? t('job.section.theJob') : t('job.section.preparing')}
	</h2>

	{#if control.canAdjust && Object.values(control.adjust).some(value => value !== null && value !== 1)}
		<Notice tone="warn" live class="adjust-status">
			<strong>{t('job.adjust.title')}</strong>
			{#each ADJUSTABLE as axis (axis.what)}
				{@const level = control.adjust[axis.what]}
				{#if level !== null && level !== 1}
					<div>{t(axis.key)}: <span class="mono">{level > 1 ? '+' : '−'}{i18n.number(Math.abs(Math.round((level - 1) * 100)))}%</span></div>
				{/if}
			{/each}
		</Notice>
	{/if}

	{#if control.tokenProbleem}
		<!-- The API is reachable from the network; without a token everything stays
		     read-only. A refused token counts too: it *was* in the browser, so this
		     field disappeared and there was no way back — every action failed with a
		     401 and there was nowhere to put a different token. -->
		<div class="card token" class:afgewezen={control.rejected}>
			<label class="field-label" for="token">
				{control.rejected ? t('job.token.rejected') : t('job.token.label')}
			</label>
			<div class="token-row">
				<input id="token" type="password" bind:value={tokenDraft} placeholder={t('job.token.placeholder')} />
				<button class="btn" onclick={() => control.saveToken(tokenDraft)}>{t('common.save')}</button>
			</div>
			<!-- An instruction: where to find the token. You need it to act, so it stays. -->
			<p class="help">
				{control.rejected
					? t('job.token.rejectedHint')
					: t('job.token.hint')}
			</p>
		</div>
	{/if}

	{#if !busyWithWork && phase !== 'done'}
		<!--
			The preparation is always there, not only after a click.

			Top to bottom it is read the way you check a job: what it burns on (the
			material line and where the work goes), what is wrong with it (the warnings),
			the one action (Prepare job, with the time on it), and then the evidence you
			can work down — the cut path, the layer table and the drawing.

			The two deliberate taps stay: no single click burns. "Prepare job" arms,
			"Start now" fires — and nothing disappears from view on that first tap.
		-->
		<div class="preflight" class:none={empty}>
			{#if !empty}
				<!-- *What* is being burned, first. Always a line, even without material:
				     saying nothing reads as "not needed", and then you run a birch preset on
				     acrylic. -->
				<div class="pf-time sheet" class:unknown={!sheetText}>
					<span class="field-label">{t('job.material')}</span>
					<span class="v">{sheetText ?? t('job.material.none')}</span>
				</div>
				{#if control.origin}
					<!-- Gap J12: a zero point moves the work on the bed, and the pre-flight
					     is the last moment you can still see that. -->
					<div class="pf-time sheet">
						<span class="field-label">{t('job.origin')}</span>
						<span class="v mono"
							>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
						>
					</div>
				{/if}
				{#if cut?.aligned}
					<div class="pf-time sheet">
						<span class="field-label">{t('job.printcut')}</span>
						<span class="v mono">{size(cut.offset_mm?.x_mm ?? 0)}, {size(cut.offset_mm?.y_mm ?? 0)} mm · {i18n.number(Math.round((cut.angle_deg ?? 0) * 100) / 100)}°</span>
					</div>
				{/if}

				<!-- The warnings, heaviest first, all above the button they are about. -->
				{#if rasterOff && blindLayers.length}
					<!-- The converter that turns a raster area into laser lines lives in the
					     wxPython version of the engine. The same words as the block in the
					     test-grid wizard. -->
					<Notice tone="danger" live>
						<strong>{t('job.noRaster.title')}</strong>
						<span>
							{blindLayers.length === 1
								? t('job.noRaster.one', { label: blindLayers[0].label })
								: t('job.noRaster.many', { n: blindLayers.length })}
						</span>
					</Notice>
				{/if}
				{#if device?.connection?.state === 'disconnected'}
					<!-- A confirmed disconnection blocks the final start. -->
					<Notice tone="warn" live>{t('job.notResponding')}</Notice>
				{/if}
				{#if mismatch.length}
					<!-- A setting from *other* material is not a matter of trust but of the
					     wrong board, so it is named by layer. A measured value from the
					     wrong material outranks a calculated value on the right one; when
					     both stand here the badge says which to fix first. -->
					<Notice tone="warn" live>
						<ul class="pf-mismatch">
							{#each mismatch as notice, i (i)}
								<li class:lighter={notice.weight < 2}>
									{#if i === 0 && firstWeighsMore}
										<span class="badge warn">{t('job.first')}</span>
									{/if}<strong>{notice.layer}</strong> — {notice.text}
								</li>
							{/each}
						</ul>
					</Notice>
				{/if}
				{#if rotaryText}
					<!-- The rotary changes the shape of what comes out, and what it does to
					     the frame is said with it. Two whole sentences beside each other,
					     not two halves of one. -->
					<Notice tone="warn">{rotaryText} {t('job.rotary.frame')}</Notice>
					{#if overview?.rotary?.overlap}
						<Notice tone="warn">
							{t('rotary.overlap', {
								work: i18n.number(overview.rotary.overlap.burns_mm),
								circumference: i18n.number(overview.rotary.overlap.circumference_mm)
							})}
						</Notice>
					{/if}
				{/if}
				{#if !cut?.aligned && cut?.lapsed}
					<Notice tone="warn">{t(cut.lapsed === 'gone' ? 'job.printcut.lapsed.marks' : 'job.printcut.lapsed.machine')}</Notice>
				{/if}
				{#if pfLayers.length && risky.length}
					<p class="help warn">{t('job.risky', { n: risky.length })}</p>
				{/if}
			{/if}

			{#if empty && designLoaded}
				<!-- No checklist, no start button: there is nothing to run through. -->
				<EmptyState title={t('job.nothing.title')} text={t('job.nothing.body')} />
			{:else if designLoaded}
				<!--
					The one action, directly under what it is about.

					It sat in a sticky footer at the end of the column, because the column
					was longer than the panel and the button stood last. It stands after the
					warnings now, and stays sticky: should the warnings ever run past the
					foot of the panel, the button stops at the bottom edge instead of
					scrolling away.
				-->
				<div class="pf-stick">
					<!-- The checklist comes up on the tap that arms the burn: between
					     "Prepare job" and "Start now" is when you walk round the machine. -->
					{#if preflight}
						<div class="card inset pf-check">
							<p class="label-section">{t('job.checklist.title')}</p>
							<ul>
								<li>{t('job.checklist.lid')}</li>
								<li>{t('job.checklist.air')}</li>
								<li>{t('job.checklist.workpiece')}</li>
							</ul>
						</div>
					{/if}
					<div class="pf-actions">
					{#if preflight}
						<!-- Two deliberate taps, in the same place. The first arms, the second
						     fires. -->
						<button class="btn" onclick={() => (preflight = false)}>{t('common.cancel')}</button>
						<button
							class="btn primary big"
							onclick={confirmStart}
							disabled={!actions?.start || blocked || seriesRunning || device?.connection?.state === 'disconnected'}
							title={device?.connection?.state === 'disconnected' ? t('job.notResponding') : seriesRunning
								? t('api.series.runGoing')
								: connection.online
									? undefined
									: blockedReason}
						>
							{control.busy === 'start' ? t('job.starting') : t('job.startNow')}
						</button>
					{:else}
						<!-- One control in two parts: the button that arms the burn — the one
						     primary on this tab — and beside it, quiet, the arrow with the other
						     thing you can do with a ready job: send it to the machine's memory. -->
						<div class="pf-split">
							<button
								class="btn primary big"
								disabled={!actions?.start || blocked || seriesRunning}
								aria-busy={estimating}
								title={seriesRunning ? t('api.series.runGoing') : blockedReason}
								onclick={() => (preflight = true)}
							>
								<!-- The last known time stays while a new one is worked out; the
								     ellipsis after it only turns visible, so the button does not
								     change width on an edit. The word is for a reader who has no
								     ellipsis to see. -->
								{t('job.startJob')}{#if estimate?.seconds ?? job?.estimate_seconds}
									<span class="pf-start-time"
										>{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}</span
									><span class="pf-start-busy" class:rekent={estimating} aria-hidden="true"></span
									>{/if}{#if estimating}<span class="pf-start-word">{t('job.estimating')}</span>{/if}
							</button>
							<button
								class="btn big pf-more"
								aria-haspopup="menu"
								aria-expanded={moreOpen}
								aria-label={t('job.more')}
								title={t('job.more')}
								onclick={(e) => openMore(e.currentTarget as HTMLElement)}
							>
								<Icon name="chevron-down" />
							</button>
						</div>
						{#if moreOpen}
							<Menu
								menu={moreMenu}
								x={morePos.x}
								y={morePos.y}
								upward={morePos.upward}
								onClose={() => (moreOpen = false)}
							/>
						{/if}
					{/if}
					</div>
				</div>
			{/if}

			{#if !empty}
				<!-- What the time on the button does not say: the afternoon behind one
				     plate, an estimate still on its way, jobs ahead in the queue. -->
				{#if seriesLeft}
					<p class="pf-series">{seriesLeft}</p>
				{/if}
				{#if estimateSlow}
					<p class="help">{t('job.estimateSlow')}</p>
				{/if}
				{#if queued > 0}
					<p class="help">{t('job.queueAhead', { n: queued })}</p>
				{/if}

				<!-- What the machine is going to *do*: speed, power and passes, headed by
				     the way in to the order they burn in. -->
				{#if pfLayers.length}
					{#if onCutPath}
						<button class="btn mini pf-order" title={t('cutpath.show.title')} onclick={() => onCutPath?.()}>
							{t('cutpath.show')}
						</button>
					{/if}
					<table class="pf-layers">
						<thead>
							<tr><th>{t('job.layer')}</th><th>mm/s</th><th>%</th><th>{t('queue.passes')}</th><th>{t('job.source')}</th></tr>
						</thead>
						<tbody>
							<!-- Keyed on the index, not on the label: two operations of the same
							     type are both called "Engrave". -->
							{#each pfLayers as layer, i (i)}
								<tr>
									<td class="pf-name" title={layer.label}>
										<!-- Gap J7: the swatch carries the layer number from
										     `layerNumber()`, the same source as the layer panel and
										     the canvas, so colour is never the only signal. -->
										{#if colorFor}
											{@const number = layerNumber(design, layer.id)}
											{#if number === null}
												<span class="swatch" style:background={colorFor(layer.id)} aria-hidden="true"
												></span>
											{:else}
												<span
													class="swatch mono numbered"
													style:background={colorFor(layer.id)}
													style:color={inkOn(colorFor(layer.id))}
													role="img"
													aria-label={t('job.layerAria', { n: number })}
												>{number}</span>
											{/if}
										{/if}{layer.label}
									</td>
									<!-- A layer this engine does not carry out shows no speed and
									     power as if something is going to happen. -->
									{#if layer.burns === false}
										<td class="pf-blind" colspan="4">{t('panel.tag.doesNotBurn')}</td>
									{:else}
										<td class="mono">{layer.speed_mm_s ?? '—'}</td>
										<td class="mono">{layer.power_percent ?? '—'}</td>
										<td class="mono">{layer.passes}</td>
										<td class:unsure={layer.source !== 'testraster' || (layer.warnings?.length ?? 0) > 0}>
											{source(layer)}
										</td>
									{/if}
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}

				<!-- The drawing, with the bed and sheet messages under the shape they are
				     about (gaps J5 and C2). -->
				<JobPreview
					design={design}
					sheet={overview?.sheet ?? null}
					bounds={bounds}
					{colorFor}
				/>
			{/if}
		</div>
	{:else}
		<!--
			The progress block.

			The phase leads (`jobPhase` in `$lib/api.ts`): what is going on is at the top,
			with the buttons that do something at *this* moment directly under the bar.
			On a tablet beside the machine, Stop and Pause are on screen without
			scrolling; the sentence about the phase stands under them.
		-->
		<div class="now" class:burns={live && phase === 'burning'} class:pause={live && phase === 'paused'} class:stale>
			<div class="now-head">
				{#if stale}
					<span class="now-phase">{lastKnown}</span>
				{:else}
					<span class="now-phase">{phaseTitle(phase)}</span>
				{/if}
				{#if job}
					<span class="current-job mono" title={job.label}>{job.label}</span>
				{/if}
			</div>

			{#if progressPart !== null}
				<div class="now-bar" role="progressbar" aria-valuenow={Math.round(progressPart * 100)} aria-valuemin="0" aria-valuemax="100" aria-label={t('job.progressAria')}>
					<span class="now-vol" style="width: {Math.round(progressPart * 1000) / 10}%"></span>
				</div>
				<div class="now-figures mono">
					<span class="now-pct">{Math.round(progressPart * 100)}%</span>
					{#if job?.steps_total && !estimated}
						<span class="now-step">{t('job.steps', { done: job.steps_done ?? 0, total: job.steps_total })}</span>
					{/if}
					{#if (job?.loops ?? 1) > 1}
						<span class="now-pass">{t('job.pass', { n: (job?.loops_executed ?? 0) + 1, total: job?.loops })}</span>
					{/if}
				</div>
				<div class="now-time">
					<span>{t('job.elapsed', { time: formatDuration(job?.elapsed_seconds ?? null) })}</span>
					{#if outrun}<span class="now-rest"
							>{t('status.pastEstimate', { total: formatDuration(job?.estimate_seconds ?? null) })}</span
						>{:else if remaining !== null}<span class="now-rest"
							>{estimated
								? t('status.remaining.estimated', { remaining: formatDuration(remaining) })
								: t('status.remaining', { remaining: formatDuration(remaining) })}</span
						>{/if}
				</div>
				{#if estimated}
					<p class="help">{t('job.progressEstimated')}</p>
				{/if}
			{/if}

			<!-- Stop stands at the start of the row and pause at the end: the button that
			     cannot be undone is never on the spot the eye and the thumb end at. The
			     keys sit in the tooltips of the buttons they work. -->
			<div class="now-actions">
				<button
					class="btn danger stop"
					class:dood={!connection.online}
					disabled={!actions?.stop || control.tokenProbleem || !connection.online}
					title={!connection.online
						? `${t('transport.noServer')} ${t('transport.noServer.stop')}`
						: `${blockedReason ?? t('job.stop.now')} · ${STOP_KEY}\n${t('job.keysHere')}`}
					onclick={() => control.stop()}
				>
					<!-- One key, not two glued together. -->
					{connection.online ? t('transport.stop') : t('transport.stop.onMachine')}
				</button>
				<span class="now-stretch"></span>
				{#if paused}
					<button
						class="btn primary"
						disabled={!transportAllowed('resume', { able: actions, phase, blocked })}
						title={`${blockedReason ?? t('job.pause.keepGoing')} · ${PAUSE_KEY}\n${t('job.keysHere')}`}
						onclick={() => control.resume()}
					>{t('transport.resume')}</button>
				{:else}
					<!-- On the phase and not on `job.running`: a job that has been spooled
					     but not picked up sits at `running: false`. -->
					<button
						class="btn"
						disabled={!transportAllowed('pause', { able: actions, phase, blocked })}
						title={busyWithWork
							? `${blockedReason ?? t('job.pause.stopHead')} · ${PAUSE_KEY}\n${t('job.keysHere')}`
							: t('transport.pause.nothing')}
						onclick={() => control.pause()}
					>{t('transport.pause')}</button>
				{/if}
			</div>

			{#if stale && heardAt}
				<p class="help">{t('job.lastKnown.ago', { ago: i18n.ago(heardAt) })}</p>
			{/if}
			<p class="help">{phaseBody(phase)}</p>
			<!-- Where there is no pointer the tooltips cannot be read, and the part only
			     they carry — the keys stop working outside this window — is the part you
			     discover at the wrong moment. -->
			{#if screen.noHover}
				<p class="toetsen help">{t('job.keysHere')}</p>
			{/if}

			<!-- As soon as there is anything in the queue: with exactly one job in the row
			     the queue must still be clearable. Not on a machine without a queue — a
			     Ruida holds its one job on the line, and the capabilities say so
			     (`clear_queue: false`); Stop is what ends it. -->
			{#if queued > 0 && actions?.clear_queue !== false}
				<button
					class="btn wachtrij"
					disabled={!actions?.clear_queue || queued === 0 || blocked}
					title={queued === 0 ? t('job.queueEmpty') : blockedReason}
					onclick={() => control.clearQueue()}
				>
					{t('job.clearQueue', { n: queued })}
				</button>
			{/if}
		</div>
	{/if}

	{#if !control.tokenProbleem}
		<!--
			The machine controls: moving, going to a point, the zero point, adjusting.

			Getting-ready work. It sits *under* what is happening, starts closed, and folds
			shut when work begins — shut and not gone, so it is there the moment you need
			it again.
		-->
		<details class="fold machinevouw" bind:open={machineOpen}>
			<summary>
				{t('job.machineControls')}
				{#if busyWithWork}<span class="group-value">{t('job.machineControls.notNow')}</span>{/if}
			</summary>
		<div class="motion">
			<p class="label-section">{t('job.move')}</p>
			<!-- Inverted T, like the arrow keys on a keyboard. Home sits next to it and not
			     in the middle, because it is not a direction. -->
			<div class="pad" class:metz={control.capabilities?.motion?.focus}>
				<button class="btn jog up" aria-label={t('job.jog.up')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(0, -step)}><Icon name="arrow-up" /></button>
				<button class="btn jog left" aria-label={t('job.jog.left')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(-step, 0)}><span class="turn-left"><Icon name="arrow-up" /></span></button>
				<button class="btn jog down" aria-label={t('job.jog.down')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(0, step)}><Icon name="arrow-down" /></button>
				<button class="btn jog right" aria-label={t('job.jog.right')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(step, 0)}><span class="turn-right"><Icon name="arrow-up" /></span></button>
				<button class="btn jog home" disabled={movingOff} title={movingBlocked ?? (rotary.active ? t('rotary.safety.home') : undefined)} onclick={home}>{t('job.home')}</button>
				{#if control.capabilities?.motion?.focus}
					<!-- The Z axis is in the same pad: the same operation with a third
					     direction, and the same step size. -->
					<button
						class="btn jog zup"
						disabled={movingOff}
						aria-label={t('job.jog.z', { step, direction: t('job.jog.zUp') })}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zUp') })}
						onclick={() => onFocus?.(-step)}
					>Z<Icon name="arrow-up" /></button>
					<button
						class="btn jog zdown"
						disabled={movingOff}
						aria-label={t('job.jog.z', { step, direction: t('job.jog.zDown') })}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zDown') })}
						onclick={() => onFocus?.(step)}
					>Z<Icon name="arrow-down" /></button>
				{/if}
			</div>
			<div class="steps">
				<Segmented
					label={t('job.stepSize')}
					mono
					bind:value={step}
					options={[0.1, 1, 10, 50].map((size) => ({ value: size, label: `${size} mm` }))}
				/>
				<!-- The pair, not half of it: unlocking lets you push the head aside, and
				     holding it again is the other half. -->
				<button
					class="btn mini"
					disabled={movingOff || !control.capabilities?.motion?.unlock}
					title={movingBlocked ?? t('job.unlock.why')}
					onclick={() => onUnlock?.()}
				>
					{t('job.unlock')}
				</button>
				<button
					class="btn mini"
					disabled={movingOff || !control.capabilities?.motion?.lock}
					title={movingBlocked ?? t('job.lock.why')}
					onclick={() => onLock?.()}
				>
					{t('job.lock')}
				</button>
			</div>

			<!-- To a point instead of in a direction (gap J6). -->
			{#if control.capabilities?.motion?.move}
				<details class="fold machine-group points">
					<summary>{t('job.toPoint')}<span class="group-value mono">{posities.length}</span></summary>
					<div class="puntrij">
						<button
							class="btn mini"
							disabled={movingOff}
							title={movingBlocked ?? t('job.toOrigin.title')}
							onclick={() => control.moveTo(0, 0)}
						>
							{t('job.toOrigin')}
						</button>
						{#each posities as place (place.name)}
							<span class="place">
								<button
									class="btn mini mono name"
									disabled={movingOff}
									title={movingBlocked ??
										t('job.toSpot.title', { x: size(place.x_mm), y: size(place.y_mm) })}
									onclick={() => control.moveTo(place.x_mm, place.y_mm)}
								>
									{place.name}
									<!-- The coordinates with it, not only in the tooltip: on a
									     touch screen there is no hover. -->
									<span class="coord mono">{size(place.x_mm)},&#8239;{size(place.y_mm)}</span>
								</button>
								<button
									class="btn mini gone"
									aria-label={t('job.forgetSpotAria', { name: place.name })}
									title={t('job.forgetSpot')}
									onclick={() => vergeet(place.name)}
								><Icon name="close" /></button>
							</span>
						{/each}
					</div>
					{#if saving}
						<div class="bewaarrij">
							<!-- svelte-ignore a11y_autofocus -->
							<input
								class="naamveld"
								placeholder={t('job.spotName.placeholder')}
								maxlength="40"
								autofocus
								bind:value={newName}
								onkeydown={(e) => {
									if (e.key === 'Enter') save();
									if (e.key === 'Escape') saving = false;
								}}
							/>
							<button class="btn mini" onclick={save} disabled={!newName.trim()} title={t('reason.needsName')}>
								{t('job.keep')}
							</button>
							<button class="btn mini" onclick={() => (saving = false)}>{t('common.cancel')}</button>
						</div>
					{:else}
						<button
							class="btn mini"
							disabled={movingOff || currentMm === null}
							title={currentMm === null
								? t('job.noPosition.keep')
								: t('job.keepSpot.title', { x: size(currentMm[0]), y: size(currentMm[1]) })}
							onclick={() => {
								newName = '';
								saving = true;
							}}
						>
							{t('job.keepSpot')}
						</button>
					{/if}
				</details>
			{/if}
			<!-- The zero point (gap J12): "measure from there", where the saved positions
			     say "go there". When it is set the group says so with a badge — a state
			     you see at the edge of your eye without reading the numbers. -->
			{#if control.capabilities?.motion?.move}
				<details class="fold machine-group card inset origin" class:gezet={control.origin !== null} open={control.origin !== null}>
					<summary>{t('job.workOrigin')}{#if control.origin}<span class="group-value"><span class="badge mono">{size(control.origin.x_mm)}, {size(control.origin.y_mm)} mm</span></span>{:else}<span class="group-value">{t('job.state.off')}</span>{/if}</summary>
					{#if control.origin}
						<!-- The number is always with it. -->
						<p class="originPoint">
							<span class="mono"
								>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
							>
							— {t('job.origin.here')}
						</p>
					{:else}
						<!-- Not set: a value with the sentence behind it. Where a pointer can
						     hover the dotted underline says a sentence is there; where one
						     cannot, the sentence is the line. -->
						<p class="help" class:off={!screen.noHover} title={t('job.origin.off')}>{screen.noHover ? t('job.origin.off') : t('job.state.off')}</p>
					{/if}
					<div class="puntrij">
						<button
							class="btn mini"
							disabled={movingOff || currentMm === null}
							title={currentMm === null
								? t('job.noPosition.origin')
								: t('job.origin.setTitle', { x: size(currentMm[0]), y: size(currentMm[1]) })}
							onclick={() => control.setOrigin()}
						>
							{control.origin ? t('job.origin.reset') : t('job.origin.set')}
						</button>
						{#if control.origin}
							<button
								class="btn mini"
								disabled={movingOff}
								title={movingBlocked ?? t('job.origin.goTitle')}
								onclick={() =>
									control.origin && control.moveTo(control.origin.x_mm, control.origin.y_mm)}
							>
								{t('job.toZero')}
							</button>
							<button
								class="btn mini"
								title={t('job.origin.clearTitle')}
								onclick={() => control.clearOrigin()}
							>
								{t('job.clearZero')}
							</button>
						{/if}
					</div>
				</details>
			{/if}

			<!-- Print and cut (gap H2). The same family as the zero point and right under
			     it: both answer "where does the work go". The marks come from the canvas
			     selection. -->
			{#if control.capabilities?.motion?.move}
				<details class="fold machine-group card inset origin printcut" class:gezet={cut?.aligned === true} open={Boolean(cut?.aligned || cut?.lapsed || cutMarks.length)}>
					<summary>{t('job.printcut')}{#if cut?.aligned}<span class="group-value"><span class="badge">{t('job.printcut.pose', { angle: i18n.number(Math.round((cut.angle_deg ?? 0) * 100) / 100) })}</span></span>{:else}<span class="group-value">{cutMarks.length ? `${cut?.marks.filter((m) => m.measured).length ?? 0} / 2` : t('job.state.off')}</span>{/if}</summary>
					{#if cut?.aligned}
						<p class="originPoint">
							<span class="mono"
								>{size(cut.offset_mm?.x_mm ?? 0)},&#8239;{size(cut.offset_mm?.y_mm ?? 0)} mm</span
							>
							— {t('job.printcut.pose', {
								angle: i18n.number(Math.round((cut.angle_deg ?? 0) * 100) / 100)
							})}
						</p>
						<Why><p>{t('job.printcut.instead')}</p></Why>
					{:else if cut?.lapsed === 'gone'}
						<p class="help warn">{t('job.printcut.lapsed.marks')}</p>
					{:else if cut?.lapsed === 'machine'}
						<p class="help warn">{t('job.printcut.lapsed.machine')}</p>
					{:else if cutMarks.length === 2}
						<!-- An instruction: what to do next. It stays. -->
						<p class="help">
							{t('job.printcut.driveTo', {
								n: cut?.marks.filter((m) => m.measured).length ?? 0
							})}
						</p>
					{:else}
						<p class="help" class:off={!screen.noHover} title={t('job.printcut.off')}>{screen.noHover ? t('job.printcut.off') : t('job.state.off')}</p>
					{/if}
					<div class="puntrij">
						{#if cutMarks.length === 2}
							{#each cutMarks as mark, index (mark.id)}
								<button
									class="btn mini"
									disabled={movingOff || currentMm === null}
									title={currentMm === null
										? t('job.noPosition.printcut')
										: t('job.printcut.captureTitle', {
												n: index + 1,
												x: size(currentMm[0]),
												y: size(currentMm[1])
											})}
									onclick={() => control.measurePrintCut(index)}
								>
									{mark.measured
										? t('job.printcut.again', { n: index + 1 })
										: t('job.printcut.capture', { n: index + 1 })}
								</button>
							{/each}
							<button
								class="btn mini"
								title={t('job.printcut.clearTitle')}
								onclick={() => control.clearPrintCut()}
							>
								{t('job.printcut.clear')}
							</button>
						{:else}
							<button
								class="btn mini"
								disabled={selectedIds.length !== 2}
								title={selectedIds.length === 2
									? t('job.printcut.useTitle')
									: t('job.printcut.needsTwo')}
								onclick={() => control.setPrintCutMarks(selectedIds)}
							>
								{t('job.printcut.use')}
							</button>
							<!-- Why the button is dead, on the screen where a tooltip cannot be
							     read. On a desk the tooltip is enough. -->
							{#if screen.noHover && selectedIds.length !== 2}
								<p class="help reason">{t('job.printcut.needsTwo')}</p>
							{/if}
						{/if}
					</div>
				</details>
			{/if}

			<!-- Adjusting during a running job (gap J11). Only where the driver can do it:
			     only grbl has realtime overrides; a button that does nothing next to a
			     burning laser is worse than no button. -->
			{#if control.canAdjust}
				<details class="fold machine-group bijstellen" open={Object.values(control.adjust).some(value => value !== null && value !== 1)}>
					<summary>{t('job.adjust.title')}</summary>
					{#each ADJUSTABLE as axis (axis.what)}
						{#if control.capabilities?.adjust?.[axis.what]}
							{@const level = control.adjust[axis.what] ?? 1}
							<div class="stelrij">
								<span class="stelnaam">
									{t(axis.key)}
									<span class="stelwaarde" class:mono={level !== 1}
										>{level === 1
											? t('job.adjust.asDesigned')
											: `${level > 1 ? '+' : '−'}${Math.abs(
													Math.round((level - 1) * 100)
												)}%`}</span
									>
								</span>
								<div class="stelknoppen">
									{#each [-0.1, -0.01, 0.01, 0.1] as step (step)}
										<button
											class="btn mini mono adjust"
											disabled={!connection.online}
											title={t(step > 0 ? 'job.adjust.more' : 'job.adjust.less', {
												what: t(axis.key).toLowerCase()
											})}
											onclick={() => control.setAdjustment(axis.what, level + step)}
											>{step > 0 ? '+' : '−'}{Math.abs(Math.round(step * 100))}%</button
										>
									{/each}
									<button
										class="btn mini adjust terug"
										disabled={!connection.online || level === 1}
										title={t('job.adjust.resetTitle')}
										onclick={() => control.setAdjustment(axis.what, 1)}
										>{t('job.adjust.reset')}</button
									>
								</div>
							</div>
						{/if}
					{/each}
					<Why><p>{t('job.adjust.hint')}</p></Why>
				</details>
			{/if}
			{#if !control.capabilities?.motion?.focus && profile?.has_z}
				<!-- The profile says Z, the driver has no command for it: missing support,
				     said once. -->
				<p class="help">{t('job.zAxis.noCommand')}</p>
			{/if}
			{#if profile?.has_autofocus}
				<!-- MeerK40t has no command to start an autofocus; we say where it is. -->
				<p class="help">{t('job.autofocus')}</p>
			{/if}
		</div>
		</details>
	{/if}

	{#if actions && !actions.pause}
		<p class="help no-pause">{t('job.noPause')}</p>
	{/if}

	<!-- The error message lives in the status bar, visible on every tab. -->
</div>

<!-- Homing with the rotary in the bed. The head goes to the corner over the place where
     the rotary stands, so this is a question and not a confirmation of a click. -->
<Dialog title={t('job.home.rotary.title')} bind:open={askHome} size="s">
	<p class="dialog-text">{t('job.home.rotary.body')}</p>
	{#snippet footer()}
		<button class="btn" onclick={() => (askHome = false)}>{t('job.home.rotary.cancel')}</button>
		<button
			class="btn primary"
			onclick={() => {
				askHome = false;
				onHome?.(true);
			}}>{t('job.home.rotary.confirm')}</button
		>
	{/snippet}
</Dialog>


<!-- Sending the job to the machine's memory instead of burning it: one tap, not two.
     This puts a file down and moves nothing, and a confirmation in front of something
     that sets nothing in motion only teaches people to click through confirmations. -->
<Dialog title={t('job.upload')} bind:open={uploadOpen} size="s">
	<Why><p>{t('job.upload.why')}</p></Why>
	<div class="pf-uploadrow">
		<label class="field-label">
			<span>{t('job.upload.name')}</span>
			<!-- Cut to what the machine keeps while you type: eight capitals, no spaces.
			     The capitals are shown, not stored — see `nameTyped`. -->
			<input
				class="mono"
				type="text"
				maxlength="8"
				style:text-transform="uppercase"
				value={fieldText}
				disabled={Boolean(uploadOff)}
				title={uploadOff ?? t('job.upload.name')}
				oninput={nameTyped}
				oncompositionend={nameTyped}
			/>
		</label>
		<button
			class="btn primary"
			disabled={Boolean(uploadOff) || control.busy !== null || uploadName === ''}
			title={uploadOff ??
				(control.busy !== null
					? t('reason.busy')
					: uploadName === ''
						? t('reason.needsName')
						: t('job.upload.why'))}
			onclick={sendToMachine}
		>
			{control.busy === 'upload' ? t('job.upload.sending') : t('job.upload.send')}
		</button>
	</div>
	{#if uploaded}
		<!-- `role="status"`: the answer to something that went well. -->
		<Notice tone="ok" live>{t('job.upload.done', { name: uploaded })}</Notice>
	{/if}
</Dialog>

<style>
	/* The face of every notice, badge, help line, label and button here is the shared
	   one in tokens.css; this block says only where things sit and how wide they are. */
	.job-heading {
		margin-bottom: var(--space-3);
	}
	.section > :global(.notice) {
		margin-bottom: var(--space-3);
	}
	.dialog-text {
		margin: 0 0 var(--space-4);
		font-size: var(--text-sm);
	}

	/* ── The pre-flight ──────────────────────────────────────────────────────── */
	.preflight {
		display: grid;
		gap: var(--space-2);
	}
	/* A label and its value on one line: the material, the zero point, print and cut. */
	.pf-time {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-3);
	}
	.pf-time .v {
		font-size: var(--text-sm);
		text-align: right;
	}
	/* A missing material is a gap, not a material called "not filled in". */
	.pf-time.unknown .v {
		color: var(--text-2);
		font-style: italic;
	}
	.pf-mismatch {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: var(--space-1);
	}
	.pf-mismatch .badge {
		margin-right: var(--space-1h);
	}
	/* The mildest objection — calculated, but on the right material — belongs here and
	   must not shout as loudly as the wrong plate. */
	.pf-mismatch .lighter {
		color: var(--text-2);
	}
	.pf-mismatch .lighter strong {
		color: var(--text-1);
		font-weight: 500;
	}
	/* The afternoon behind the plate is not an aside: it is the number somebody plans
	   their evening around. */
	.pf-series {
		margin: 0;
		font-size: var(--text-sm);
	}
	.pf-order {
		width: 100%;
		margin-top: var(--space-2);
	}
	.pf-layers {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
	}
	.pf-layers th {
		text-align: left;
		font-weight: 500;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
		padding: 0 var(--space-1) var(--space-1) 0;
	}
	.pf-layers td {
		padding: var(--space-1) var(--space-1) var(--space-1) 0;
	}
	.pf-layers td.mono {
		text-align: right;
		padding-right: var(--space-2);
		font-variant-numeric: tabular-nums;
	}
	.pf-name {
		max-width: 9em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The layer's colour, small; with its number in it a square block (gap J7). The ink
	   on it comes from `inkOn`. */
	.swatch {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-sharp);
		margin-right: var(--space-1h);
		vertical-align: baseline;
	}
	.swatch.numbered {
		width: 16px;
		height: 16px;
		line-height: 16px;
		text-align: center;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		border-radius: var(--radius-sharp);
		vertical-align: -3px;
	}
	.unsure {
		color: var(--warn);
	}
	/* A layer that does nothing, in the calm tone, directly beside its name. */
	.pf-blind {
		color: var(--text-2);
		font-style: italic;
		text-align: left;
	}

	/*
	 * The action row. Sticky at the bottom of the panel, though it no longer stands at
	 * the end of the column: where it fits, it stays where it is; when the warnings above
	 * it run past the foot of the panel, it stops at the bottom edge instead of scrolling
	 * away. Edge to edge, around `.panel-scroll`'s padding, so nothing shows beside it.
	 */
	.pf-stick {
		position: sticky;
		bottom: calc(-1 * var(--space-4));
		z-index: 2;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: var(--space-1) calc(-1 * var(--space-4));
		padding: var(--space-3) var(--space-4);
		background: var(--surface-1);
	}
	.pf-check ul {
		margin: var(--space-1) 0 0;
		padding-left: 1.1em;
		font-size: var(--text-sm);
	}
	.pf-actions {
		display: flex;
		/* The row may fold rather than run past the panel: `tests/footer-fit.test.ts`
		   measures it in both languages. */
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.pf-actions .btn {
		flex: 1 1 auto;
		white-space: nowrap;
	}
	/* The start button and its arrow are one unit: joined corners, one line. The arrow
	   is the quiet half — a second verb, not a second primary. */
	.pf-split {
		display: flex;
		flex: 1 1 auto;
	}
	.pf-split .btn.primary {
		flex: 1 1 auto;
		border-radius: var(--radius-field) 0 0 var(--radius-field);
	}
	.pf-split .btn.pf-more {
		/* One width in every language; a glove-sized target. */
		flex: 0 0 48px;
		min-width: 48px;
		padding-left: 0;
		padding-right: 0;
		border-left: none;
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
	}
	/* The time on the start button: what it is going to do, and for how long. */
	.pf-start-time {
		margin-left: var(--space-1h);
		font-size: var(--text-xs);
		font-weight: 400;
		opacity: 0.85;
	}
	/* A new time is being worked out. The ellipsis is always in the button and only
	   becomes visible, so the button cannot change width on an edit. It is punctuation
	   after a number, not an icon, so it is written as content rather than as a glyph in
	   the markup. */
	.pf-start-busy {
		font-size: var(--text-xs);
		font-weight: 400;
		visibility: hidden;
	}
	.pf-start-busy::after {
		content: '\2026';
	}
	.pf-start-busy.rekent {
		visibility: visible;
	}
	/* The same state in words, for a reader who has no ellipsis to see. */
	.pf-start-word {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	/* ── The token ──────────────────────────────────────────────────────────── */
	.token {
		display: grid;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
		border-color: var(--warn-edge);
	}
	.token.afgewezen {
		border-color: var(--danger-edge);
	}
	.token-row {
		display: flex;
		gap: var(--space-2);
	}
	.token-row input {
		flex: 1;
	}

	/* ── The progress block ─────────────────────────────────────────────────
	   What is going on *now*. Sizes are generous: this is read from two metres away. */
	.now {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}
	/* Burning: the accent edge and tint. Paused: the warning edge and tint, because
	   standing still with work in the machine is a state you have to act on. Last
	   known: neither — muted, and the bar stands still. */
	.now.burns {
		border-color: var(--accent-edge);
	}
	.now.pause {
		border-color: var(--warn-edge);
		background: var(--warn-tint);
	}
	.now-head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	.now-phase {
		font-size: var(--text-md);
		font-weight: 600;
		color: var(--text-1);
	}
	.now.burns .now-phase {
		color: var(--accent);
	}
	.now.pause .now-phase {
		color: var(--warn);
	}
	.now.stale .now-phase {
		color: var(--text-2);
		font-weight: 500;
	}
	.current-job {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.now-bar {
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		overflow: hidden;
	}
	.now-vol {
		display: block;
		height: 100%;
		border-radius: var(--radius-dot);
		background: var(--accent);
		transition: width var(--transition);
	}
	.now.pause .now-vol {
		background: var(--warn-solid);
	}
	.now.stale .now-vol {
		background: var(--text-2);
		transition: none;
	}
	.now-figures {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* The percentage is the number you read from a distance; the rest is caption. */
	.now-pct {
		font-size: var(--text-lg);
		font-weight: 500;
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	.now.stale .now-pct {
		color: var(--text-2);
	}
	.now-step,
	.now-pass {
		font-variant-numeric: tabular-nums;
	}
	.now-time {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.now-rest {
		color: var(--text-1);
		font-weight: 500;
	}
	.now-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	/* Stop keeps its distance from pause: a bad tap here costs the workpiece. */
	.now-stretch {
		flex: 1;
		min-width: var(--space-6);
	}
	/* 40 on a desk; the touch floor beside the machine — Stop is the one button that
	   may never be smaller than a glove. */
	.now-actions .btn {
		min-height: max(40px, var(--target-min));
		padding: 0 var(--space-4);
	}
	/* The stop button in the job block is solid red, like the one in the top bar. */
	.now-actions .btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
	}
	/* The server is gone: the button says where to stop instead, and is drained to a
	   dashed outline — readable, because here the text *is* the message. */
	.now-actions .btn.danger.dood,
	.now-actions .btn.danger.dood:disabled {
		background: transparent;
		border: 1px dashed var(--text-2);
		color: var(--text-2);
	}
	.wachtrij {
		align-self: flex-start;
	}

	/* ── The machine controls ───────────────────────────────────────────────── */
	.machinevouw {
		margin-top: var(--space-4);
		border-top: 1px solid var(--line);
		padding-top: var(--space-3);
	}
	.machine-group > summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.group-value {
		margin-left: auto;
		color: var(--text-2);
		font-size: var(--text-xs);
		font-weight: 400;
	}
	.machinevouw > summary .group-value {
		margin-left: 0;
	}
	.motion {
		display: grid;
		gap: var(--space-2);
	}
	.pad {
		display: grid;
		/* Four columns; the fifth only when there is a Z axis. */
		grid-template-columns: repeat(4, max(40px, var(--target-min)));
		grid-template-rows: repeat(2, auto);
		gap: var(--space-1);
	}
	/* Placed explicitly: with implicit placement ↓ slid into the first column. */
	.pad .up { grid-area: 1 / 2; }
	.pad .left { grid-area: 2 / 1; }
	.pad .down { grid-area: 2 / 2; }
	.pad .right { grid-area: 2 / 3; }
	.pad .home { grid-area: 1 / 4 / 3 / 5; }
	.pad.metz { grid-template-columns: repeat(5, max(40px, var(--target-min))); }
	.pad .zup { grid-area: 1 / 5; }
	.pad .zdown { grid-area: 2 / 5; }
	.jog {
		padding-left: 0;
		padding-right: 0;
		gap: 0;
	}
	.jog.home,
	.jog.zup,
	.jog.zdown {
		font-size: var(--text-xs);
	}
	/* One arrow, turned: left and right are the up arrow on its side. */
	.turn-left,
	.turn-right {
		display: inline-flex;
	}
	.turn-left { transform: rotate(-90deg); }
	.turn-right { transform: rotate(90deg); }
	.steps {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.machine-group {
		margin-top: var(--space-1);
	}
	.puntrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-2) 0;
	}
	/* Name and cross are one thing with two targets, joined by a hairline. */
	.place {
		display: inline-flex;
	}
	.place .name {
		border-radius: var(--radius-field) 0 0 var(--radius-field);
	}
	.place .gone {
		border-left: none;
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		padding: 0 var(--space-2);
		color: var(--text-2);
	}
	.place .gone:hover:not(:disabled) {
		color: var(--danger);
	}
	.coord {
		color: var(--text-2);
		margin-left: var(--space-1h);
	}
	.bewaarrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	.naamveld {
		flex: 1;
		min-width: 10ch;
	}
	/* The state of a feature nobody switched on: a word with a sentence behind it. The
	   dotted underline says the sentence can be read, so only where a pointer hovers. */
	.help.off {
		text-decoration: underline dotted;
		text-underline-offset: 3px;
		cursor: help;
	}
	.reason {
		flex-basis: 100%;
	}
	.originPoint {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.originPoint .mono {
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	/* The zero point and print and cut sit in a sunken group, because each is a state
	   that moves your work. Set, the group takes the accent tint as a chosen thing does. */
	.origin.gezet {
		background: var(--accent-tint);
	}
	/* ── Adjusting during the job (gap J11) ────────────────────────────────── */
	.stelrij {
		margin-top: var(--space-2);
	}
	.stelnaam {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-xs);
	}
	.stelwaarde {
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	.stelknoppen {
		display: flex;
		gap: var(--space-1h);
		margin-top: var(--space-1h);
	}
	/* Five buttons in a narrow panel: each may shrink; the air beside the number comes
	   off, the number stays on the type scale. */
	.adjust {
		flex: 1;
		min-width: 0;
		padding-left: var(--space-1);
		padding-right: var(--space-1);
	}
	.adjust.terug {
		flex: 1.3;
	}
	.no-pause {
		margin-top: var(--space-3);
	}

	/* ── Sending it to the machine ─────────────────────────────────────────── */
	.pf-uploadrow {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
		margin: var(--space-3) 0;
	}
	/* The eight characters as the machine writes them: a fixed pitch, spaced out. The
	   capitals themselves are a `style:` on the field — shown, not stored. */
	.pf-uploadrow input {
		width: 11ch;
		font-family: var(--font-mono);
		letter-spacing: 0.08em;
	}
</style>
