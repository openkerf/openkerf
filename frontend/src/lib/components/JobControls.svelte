<script lang="ts">
	import {
		phaseBody,
		phaseTitle,
		formatDuration,
		jobBusy,
		jobPhase,
		isStalled,
		remainingSeconds,
		transportAllowed,
		machineName,
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

	let {
		control,
		device,
		series,
		job,
		nothingBurns = false,
		sheetName = '',
		revision = 0,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock,
		onLock,
		onFocus,
		onFrame,
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
		/** Sending the head around the outline, without burning. */
		onFrame?: () => void;
		/** Opening the cut-path window (gap S1). Beside "Show frame", because this is
		 *  the moment you want to know in what order it burns — and unlike the frame
		 *  it costs no movement of the machine. */
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
		/** Does this engine actually execute the layer? See `gridOff`. */
		burns?: boolean;
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
		engine?: { grid: boolean } | null;
		/** Machine-wide, and it changes what burns — so the pre-flight says it out loud
		 *  rather than leaving it on a settings page nobody opens twice. */
		rotary?: RotaryState | null;
	} | null>(null);
	let layers = $derived(overview?.layers ?? []);
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
	 * canvas and the phone anyway, and three places computing it themselves can
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
	 * No, headless: the converter from grid area to laser lines sits in the wxPython
	 * GUI. During planning the layer throws its own shapes away and produces no
	 * cutcode. That must not be a surprise *after* burning, and the time estimate must
	 * not promise seconds for it.
	 */
	let gridOff = $derived(overview?.engine?.grid === false);
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
	let blindLayers = $derived(layers.filter((l) => l.burns === false));
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
	let progressPart = $derived.by(() => {
		const part = job?.progress;
		if (part === null || part === undefined || !Number.isFinite(part)) return null;
		// A job that is finished but not signed off by the engine sits at 0.998; we show
		// that as full, because that is what has happened.
		return phase === 'done' ? 1 : Math.min(1, Math.max(0, part));
	});
	let remaining = $derived(phase === 'done' ? 0 : remainingSeconds(job));

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
	     you come to this tab for. -->
	<h2 class="section-title">
		{busyWithWork || phase === 'done' ? t('job.section.theJob') : t('job.section.preparing')}
	</h2>

	{#if control.tokenProbleem}
		<!-- The API is reachable from the network; without a token everything stays
		     read-only. A refused token counts too: it *was* in the browser, so this
		     field disappeared and there was no way back — every action failed with a
		     401 and there was nowhere to put a different token. -->
		<div class="token" class:afgewezen={control.rejected}>
			<label for="token">
				{control.rejected ? t('job.token.rejected') : t('job.token.label')}
			</label>
			<div class="token-row">
				<input id="token" type="password" bind:value={tokenDraft} placeholder={t('job.token.placeholder')} />
				<button class="btn" onclick={() => control.saveToken(tokenDraft)}>{t('common.save')}</button>
			</div>
			<p class="hint">
				{control.rejected
					? t('job.token.rejectedHint')
					: t('job.token.hint')}
			</p>
		</div>
	{/if}

	{#if !busyWithWork && phase !== 'done'}
		<!--
			The preparation is always there, not only after a click.

			This block sat behind the "Start job" button: you pressed, and the whole panel
			was replaced by an overview — "everything goes off screen", as the complaint
			put it. While this is precisely the image you look at *before* you burn
			anything. It is now open as long as nothing is in flight.

			The two deliberate taps stay: VEILIGHEID.md lays down that no single click
			burns directly. "Start job" arms, "Start now" fires — and unlike before,
			nothing disappears from view on that first tap.
		-->
		<div class="preflight" class:none={empty}>
			<!-- "Estimated time 0:00" above an empty bed reads as a job of zero
			     seconds instead of as no job. With nothing to do the clock keeps
			     quiet and the message below it speaks. -->
			<!-- The workpiece first, the numbers about it after (decision B8).
			     Whoever sees something hanging off the sheet need not read the time
			     any more — and on tablet and phone the canvas is not beside it. -->
			{#if !empty}
				<!-- The messages about bed and sheet belong to the drawing and so
				     live in it, right under the shape they are about (gaps J5 and C2).
				     They used to be here as two equally red cards in a row; that made
				     "there is no material there" as serious as "the head does not get
				     there", and then neither carries any weight. -->
				<JobPreview
					design={design}
					sheet={overview?.sheet ?? null}
					bounds={bounds}
					{colorFor}
				/>
				<!-- Under the drawing, because it is the same drawing with the order in
				     it (gap S1). Deliberately *not* in the sticky row with the frame and
				     the start button: measured at 1440 px with three buttons in that row,
				     "Start job 1:26" was clipped at the right edge of the panel — the
				     primary action half off screen, which is the very thing the second
				     usability round fixed. -->
				{#if onCutPath}
					<button class="pf-order" title={t('cutpath.show.title')} onclick={() => onCutPath?.()}>
						{t('cutpath.show')}
					</button>
				{/if}
				<!-- The converter that turns a grid area into laser lines lives in
				     the wxPython version of the engine. When it is missing, the layer
				     throws its own shapes away during planning and nothing comes out
				     of the machine. The same words as the block in the test-grid
				     wizard: whoever read them there recognises them here — and the
				     other way round. -->
				{#if gridOff && blindLayers.length}
					<p class="pf-no-raster" role="alert">
						<strong>{t('job.noRaster.title')}</strong>
						{blindLayers.length === 1
							? t('job.noRaster.one', { label: blindLayers[0].label })
							: t('job.noRaster.many', { n: blindLayers.length })}
					</p>
				{/if}
				<div class="pf-time">
					<span class="muted">{t('job.estimatedTime')}</span>
					<span class="v mono">
						{#if estimating}
							<span class="rekent">{t('job.calculating')}</span>
						{:else}{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}{/if}
					</span>
				</div>
				{#if seriesLeft}
					<!-- The clock above is one plate; a series of fifty must never show the
					     time of one. Both numbers come off the estimate itself — see
					     `seriesLeft` — so this line and that one cannot disagree. -->
					<p class="pf-row series">{seriesLeft}</p>
				{/if}
				<!-- *What* is being burned, right above the settings it is burned
				     with. Without it there is a table of numbers with no subject. -->
				<!-- Always a line, even without material. Saying nothing reads as
				     "not needed"; and then you run a birch preset on acrylic. -->
				<div class="pf-time sheet" class:unknown={!sheetText}>
					<span class="muted">{t('job.material')}</span>
					<span class="v">{sheetText ?? t('job.material.none')}</span>
				</div>
					{#if control.origin}
						<!-- Gap J12: a zero point moves the work on the bed, and the
						     preflight is the last moment you can still see that. So it is
						     here as a line of its own — saying nothing would mean the one
						     screen before burning does not say *where* it burns. -->
						<div class="pf-time sheet">
							<span class="muted">{t('job.origin')}</span>
							<span class="v mono"
								>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
							>
						</div>
					{/if}
					{#if rotaryText}
						<!-- The rotary changes the shape of what comes out, so it belongs on
						     the one screen you read before burning. A job that silently comes
						     out stretched costs the workpiece, and you have one of those. -->
						<p class="pf-warn strong">{rotaryText}</p>
						{#if overview?.rotary?.overlap}
							<p class="pf-warn">
								{t('rotary.overlap', {
									work: i18n.number(overview.rotary.overlap.burns_mm),
									circumference: i18n.number(overview.rotary.overlap.circumference_mm)
								})}
							</p>
						{/if}
					{/if}
					<!-- No second line with the job size: the view above already puts
				     "work 120 × 80 mm" under the drawing (decision B8). That same
				     number again as a row of its own, ninety pixels lower, is not
				     information but noise. What the view does *not* do is hold the work
				     up against the bed — that is below. -->
			{/if}
			{#if !empty && device?.connection?.state === 'disconnected'}
				<!-- Starting is allowed: the engine queues the job and connects as
				     soon as the machine is there. But whoever presses "Start now" and
				     walks over to a silent machine has to know the waiting is down to
				     that and not to the job. -->
				<p class="pf-warn strong">{t('job.notResponding')}</p>
			{/if}
			{#if estimateSlow}
				<p class="pf-row">{t('job.estimateSlow')}</p>
			{/if}
			<!-- Only shown when there is something in it: "In queue: 0" just before
			     starting is the normal situation, and therefore not news. -->
			{#if queued > 0}
				<div class="pf-row">{t('job.queueAhead', { n: queued })}</div>
			{/if}

			<!-- What the machine is going to *do*. Time and count alone is theatre: a
			     laser cutter checks speed, power and passes before putting anything in
			     the machine. -->
			{#if layers.length}
				<!-- The general warning above the table and not under it.
				     Not a matter of taste: this is the last thing in the column, and the
				     footer is sticky, so the last thing in the column is what the footer
				     lies over. Measured at 1280 x 800 with the panel as it opens, four
				     layers on unmeasured presets — the line stood at y 662-726 with the
				     footer's top at 581, `elementFromPoint` on it answering
				     `DIV.pf-check`: a warning you only meet by scrolling to it, in a
				     pre-flight, which is the one screen whose whole job is to say
				     unasked what is wrong. Above the table it is the table that goes
				     under the footer instead, and a table is something you work down
				     anyway.

				     The concrete objections stay below the table, beside the rows they
				     name. So the order is: what is wrong in one line, the settings, then
				     which layer is wrong and why. -->
				{#if risky.length}
					<p class="pf-warn strong">{t('job.risky', { n: risky.length })}</p>
				{/if}
				<table class="pf-layers">
					<thead>
						<tr><th>{t('job.layer')}</th><th>mm/s</th><th>%</th><th>×</th><th>{t('job.source')}</th></tr>
					</thead>
					<tbody>
						<!-- Keyed on the index, not on the label: two operations of the same
						     type are both called "Engrave", and a duplicate key makes Svelte
						     update the table wrongly. -->
						{#each layers as layer, i (i)}
							<tr>
								<td class="pf-name" title={layer.label}>
										<!-- Two cut layers are both called "Cut"; the chip is the only
										     thing telling them apart, and it is the same colour as on the
										     canvas and in the layer list.

										     Gap J7: with the layer number in it. The design system forbids
										     information that lives in colour alone, and of ten layer
										     colours two collide under deuteranopia. The number comes from
										     `layerNumber()` — the same source as the chip in the layer panel
										     and the digit beside the shape on the canvas, so they cannot
										     drift apart. -->
										{#if colorFor}
											{@const number = layerNumber(design, layer.id)}
											<!-- Without `aria-hidden` a screen reader would otherwise hear a
											     bare digit in front of the layer name: "1 Cut". `role="img"`
											     with a name turns it into "Layer 1, Cut"; without a role most
											     screen readers ignore an aria-label on a span. With no number
											     the chip is colour only, and therefore decoration — that one
											     stays hidden. -->
											{#if number === null}
												<span class="chip mono" style:background={colorFor(layer.id)} aria-hidden="true"
												></span>
											{:else}
												<span
													class="chip mono numbered"
													style:background={colorFor(layer.id)}
													style:color={inkOn(colorFor(layer.id))}
													role="img"
													aria-label={t('job.layerAria', { n: number })}
												>{number}</span>
											{/if}
										{/if}{layer.label}
									</td>
								<!-- A layer this engine does not carry out must not show speed and
								     power as if something is going to happen. The provenance goes
								     too: where the numbers come from is beside the point when they
								     are not used. -->
								{#if layer.burns === false}
									<td class="pf-blind" colspan="4">{t('panel.tag.doesNotBurn')}</td>
								{:else}
									<td class="mono">{layer.speed_mm_s ?? '—'}</td>
									<td class="mono">{layer.power_percent ?? '—'}</td>
									<td class="mono">{layer.passes}</td>
									<!-- "measured" in calm text above a setting that was measured on
									     *other* material reassures where it should not. The line below
									     says what is wrong with it; here the colour says at least that
									     there is something. -->
									<td class:unsure={layer.source !== 'testraster' || (layer.warnings?.length ?? 0) > 0}>
										{source(layer)}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
				<!-- The concrete objection first, the general one after. A setting from
				     *other* material is not a matter of trust but of the wrong board:
				     that belongs at the top, and by name.

				     Within the list not everything weighs the same. A measured value
				     from the wrong material outranks a calculated value on the right
				     one, and when those two state side by side the tag says which to
				     fix first. -->
				{#if mismatch.length}
					<ul class="pf-mismatch" role="alert">
						{#each mismatch as notice, i (i)}
							<li class:lighter={notice.weight < 2}>
								{#if i === 0 && firstWeighsMore}
									<span class="first">{t('job.first')}</span>
								{/if}<strong>{notice.layer}</strong> — {notice.text}
							</li>
						{/each}
					</ul>
				{/if}
			{/if}

			{#if empty}
				<!-- No checklist, no start button: there is nothing to run through. -->
				<div class="pf-empty">
					<strong>{t('job.nothing.title')}</strong>
					<p>{t('job.nothing.body')}</p>
				</div>
				<!-- This used to say "Back to the design", which was the only way out
				     of an overview that had taken over the panel. The panel takes
				     nothing over now, so there is nothing to return from. -->
			{:else}
			<!-- This used to be a second yellow block under the risk warning. Two
			     warnings in a row of the same colour devalue each other: the routine
			     check made the real message invisible. Neutral now, and as a list,
			     because you work down it. -->
			<!--
				The buttons stick to the bottom of the panel.

				Since the preparation is always open, the column is taller than the
				panel is high (measured: 1,427 px of content in 788 px). Without this
				sticky footer the start button sat below the fold — the primary action
				out of sight, which is exactly what this round had to solve, not cause.

				Showing the frame is on the same line: it is the last check before that
				same button, so it belongs beside it and not three blocks higher.
			-->
			<div class="pf-stick">
				<!--
					Sending the job to the machine's memory instead of burning it.

					What LightBurn calls "send": the file goes down the cable, the
					machine keeps it, and you start it there. The other thing you can do
					with a job that is ready, so it lives beside the button that burns
					one — folded shut, because it is not the one you came for.

					In the footer, and that is the whole of this block's history. It sat
					just above the footer, which is the one place in this column where a
					control cannot be seen: the footer is sticky, and when the column is
					longer than the panel it floats up over whatever is last in the
					flow. Measured at 1440 x 900 with the panel as it opens — the fold at
					y=738 and the footer's top at y=705, `elementFromPoint` in the middle
					of the summary answering `LI` (a line of the checklist), and a real
					mouse click on those coordinates leaving `details.open` false. At
					1280 x 800 the same click landed on `DIV.pf-actions`; only at
					1920 x 1080, where the column fits, did it answer `SUMMARY` and open.
					Scrolling did reach it — the summary is on top from 60 px of scroll
					onwards, over a band of 600 of the 763 the panel scrolls — but a
					control you cannot see at rest is one nobody scrolls for. The
					checklist below learned this same lesson one round earlier and moved
					here for the same reason.

					No test saw it, and that is worth its own line: `locator.click()`
					scrolls the element into view first, so Playwright clicks a control
					under a sticky footer perfectly happily. The measurement has to be a
					mouse click on coordinates.

					One tap, not two. VEILIGHEID.md asks for two deliberate taps for
					everything that burns; this puts a file down and moves nothing, and a
					confirmation in front of something that sets nothing in motion only
					teaches people to click through confirmations.
				-->
				<details class="pf-upload">
					<summary>{t('job.upload')}</summary>
					<p class="pf-row">{t('job.upload.why')}</p>
					<div class="pf-uploadrow">
						<label class="name">
							<span>{t('job.upload.name')}</span>
							<!-- Cut to what the machine keeps while you type, not afterwards:
							     the panel of the machine shows eight capitals without spaces,
							     and the first place to find that out is the keyboard, not the
							     machine. -->
							<input
								class="mono"
								type="text"
								maxlength="8"
								value={fieldText}
								disabled={Boolean(uploadOff)}
								title={uploadOff ?? t('job.upload.name')}
								oninput={nameTyped}
								oncompositionend={nameTyped}
							/>
						</label>
						<button
							class="btn"
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
						<!-- `role="status"` and not `alert`: this is the answer to something
						     that went well, and it says where the job is now — on the machine,
						     waiting for a hand on its own panel. -->
						<p class="pf-row good" role="status">{t('job.upload.done', { name: uploaded })}</p>
					{/if}
				</details>
				<!-- The checklist travels with the button.

				     It used to stand in the column above this footer, and with four
				     layers the column is longer than the panel is high: measured at
				     1440 x 900, "Extraction and air assist on" answered `DIV.pf-stick`
				     under `elementFromPoint` and "Workpiece is clamped and flat"
				     answered the start button itself. Three lines to work down, two of
				     them under the thing you press. Here they cannot be scrolled away
				     from the button they belong to. -->
				<div class="pf-check">
					<span class="pf-head">{t('job.checklist.title')}</span>
					<ul>
						<li>{t('job.checklist.lid')}</li>
						<li>{t('job.checklist.air')}</li>
						<li>{t('job.checklist.workpiece')}</li>
					</ul>
				</div>
				<div class="pf-actions">
				{#if preflight}
					<!-- Two deliberate taps, in the same place: VEILIGHEID.md lays down that
					     no single click burns. The first arms, the second fires — and unlike
					     before, that first tap does not make anything disappear. -->
					<button class="btn" onclick={() => (preflight = false)}>{t('common.cancel')}</button>
					<button
						class="btn primary big"
						onclick={confirmStart}
						disabled={control.busy !== null || !connection.online || seriesRunning}
						title={seriesRunning
							? t('api.series.runGoing')
							: connection.online
								? undefined
								: blockedReason}
					>
						{control.busy === 'start' ? t('job.starting') : t('job.startNow')}
					</button>
				{:else}
					{#if onFrame}
						<button
							class="btn"
							disabled={control.busy !== null || running}
							title={rotary.active
								? `${t('job.frame.title')} ${t('job.rotary.frame')}`
								: t('job.frame.title')}
							onclick={() => onFrame?.()}
						>
							{t('job.frame')}
						</button>
					{/if}
					<button
						class="btn primary big"
						disabled={!actions?.start || blocked || seriesRunning}
						title={seriesRunning ? t('api.series.runGoing') : blockedReason}
						onclick={() => (preflight = true)}
					>
						<!-- The last known time stays while a new one is being worked out.
						     Hiding it during the recalculation made the button change width
						     on every edit — a button that jumps under your cursor. -->
						{t('job.startJob')}{#if estimate?.seconds ?? job?.estimate_seconds}
							<span class="pf-start-time"
								>{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}</span
							>{/if}
					</button>
				{/if}
				</div>
			</div>
			{/if}
		</div>
	{:else}
		<!--
			The progress block.

			There used to be four buttons here (start, pause, clear queue, stop) plus
			four lines explaining shortcuts, and they were there regardless of what the
			machine was doing. Three of the four were dead as long as nothing was
			running, and the moment something *was* running the only information that
			then means anything — the progress — sat at 700px, under the jog buttons,
			out of sight.

			Now the phase leads (`jobPhase` in `$lib/api.ts`): what is going on is at
			the top, with the buttons that do something at *this* moment. The shortcuts
			are on the buttons themselves, because that is where you learn them.
		-->
		<div class="now" class:burns={phase === 'burning'} class:pause={phase === 'paused'}>
			<div class="now-head">
				<span class="now-phase">{phaseTitle(phase)}</span>
				{#if job}
					<span class="current-job mono" title={job.label}>{job.label}</span>
				{/if}
			</div>

			{#if progressPart !== null}
				<!-- The bar and the percentage belong together and so sit on one line;
				     the times below in the same columns as always. -->
				<div class="now-bar" role="progressbar" aria-valuenow={Math.round(progressPart * 100)} aria-valuemin="0" aria-valuemax="100" aria-label={t('job.progressAria')}>
					<span class="now-vol" style="width: {Math.round(progressPart * 1000) / 10}%"></span>
				</div>
				<div class="now-figures mono">
					<span class="now-pct">{Math.round(progressPart * 100)}%</span>
					{#if job?.steps_total}
						<span class="now-step">{t('job.steps', { done: job.steps_done ?? 0, total: job.steps_total })}</span>
					{/if}
					{#if (job?.loops ?? 1) > 1}
						<span class="now-pass">{t('job.pass', { n: (job?.loops_executed ?? 0) + 1, total: job?.loops })}</span>
					{/if}
				</div>
				<div class="now-time">
					<span>{t('job.elapsed', { time: formatDuration(job?.elapsed_seconds ?? null) })}</span>
					{#if remaining !== null}<span class="now-rest"
							>{t('status.remaining', { remaining: formatDuration(remaining) })}</span
						>{/if}
				</div>
			{/if}

			<p class="now-hint">{phaseBody(phase)}</p>

			<div class="now-actions">
				{#if paused}
					<button
						class="btn primary"
						disabled={!transportAllowed('resume', { able: actions, phase, blocked })}
						title="{blockedReason ?? t('job.pause.keepGoing')} · {PAUSE_KEY}"
						onclick={() => control.resume()}
					>{t('transport.resume')}</button>
				{:else}
					<!-- On the phase and not on `job.running`: a job that has been spooled
					     but not picked up sits at `running: false`, and then the top bar
					     offered pause while this button was disabled. `pause` is a realtime
					     command; it lands the moment the machine starts. -->
					<button
						class="btn"
						disabled={!transportAllowed('pause', { able: actions, phase, blocked })}
						title={busyWithWork
							? `${blockedReason ?? t('job.pause.stopHead')} · ${PAUSE_KEY}`
							: t('transport.pause.nothing')}
						onclick={() => control.pause()}
					>{t('transport.pause')}</button>
				{/if}
				<span class="now-stretch"></span>
				<!-- Stop keeps its own space, away to the left of pause: a bad-tap here
				     costs the workpiece. See DESIGN-SYSTEM v2, "Touch as first-class
				     input". -->
				<button
					class="btn danger stop"
					class:dood={!connection.online}
					disabled={!actions?.stop || control.tokenProbleem || !connection.online}
					title={!connection.online
						? `${t('transport.noServer')} ${t('transport.noServer.stop')}`
						: `${blockedReason ?? t('job.stop.now')} · ${STOP_KEY}`}
					onclick={() => control.stop()}
				>
					<!-- One key, not two glued together: "Stop" plus "on the machine" only
					     works in a language with this word order, and the top bar has had
					     the whole sentence all along. -->
					{connection.online ? t('transport.stop') : t('transport.stop.onMachine')}
				</button>
			</div>

			<!-- As soon as there is anything in the queue. This used to say
			     `queued > 1`, and then with exactly one job in the row the queue could
			     not be cleared — an operation that disappeared instead of moving. -->
			{#if queued > 0}
				<button
					class="btn subtle wachtrij"
					disabled={!actions?.clear_queue || queued === 0 || blocked}
					title={queued === 0 ? t('job.queueEmpty') : blockedReason}
					onclick={() => control.clearQueue()}
				>
					{t('job.clearQueue', { n: queued })}
				</button>
			{/if}

			<!-- Gap J4, shortened. The keys are in the tooltips of the buttons above
			     now; what a tooltip cannot say is that they do not work outside this
			     window, and that is exactly the part you discover at the wrong
			     moment. -->
			<p class="toetsen">
				{t('job.keysWork', {
					pause: PAUSE_KEY,
					stop: STOP_KEY
				})}
			</p>
		</div>

	{/if}

	{#if !control.tokenProbleem}
		<!--
			The machine controls: moving, going to a point, the zero point, adjusting.

			This is getting-ready work. It used to sit above the progress and, during a
			running job, took up the whole visible panel — while its buttons are
			precisely then disabled, because you do not jog with a burning laser. Now it
			sits *under* what is happening, and folds shut as soon as work is under way.
			Shut and not gone: it has to be there the moment you need it again, and a
			block that disappears is not one you learn to find back.
		-->
		<details class="machinevouw" open={!busyWithWork}>
			<summary>
				{t('job.machineControls')}
				{#if busyWithWork}<span class="why">— {t('job.machineControls.notNow')}</span>{/if}
			</summary>
		<div class="motion">
			<span class="rot-label">{t('job.move')}</span>
			<!-- Inverted T, like the arrow keys on a keyboard: ↑ above ↓, with ← and →
			     beside them. Home sits next to it and not in the middle, because it is
			     not a direction. -->
			<div class="pad" class:metz={control.capabilities?.motion?.focus}>
				<button class="jog up" aria-label={t('job.jog.up')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(0, -step)}>↑</button>
				<button class="jog left" aria-label={t('job.jog.left')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(-step, 0)}>←</button>
				<button class="jog down" aria-label={t('job.jog.down')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(0, step)}>↓</button>
				<button class="jog right" aria-label={t('job.jog.right')} disabled={movingOff} title={movingBlocked} onclick={() => onJog?.(step, 0)}>→</button>
				<button class="jog home" disabled={movingOff} title={movingBlocked ?? (rotary.active ? t('rotary.safety.home') : undefined)} onclick={home}>{t('job.home')}</button>
				{#if control.capabilities?.motion?.focus}
					<!-- The Z axis is in the same pad as X and Y: it is the same operation
					     with a third direction, and it follows the same step size. -->
					<button
						class="jog zup"
						disabled={movingOff}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zUp') })}
						onclick={() => onFocus?.(-step)}
					>Z&nbsp;↑</button>
					<button
						class="jog zdown"
						disabled={movingOff}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zDown') })}
						onclick={() => onFocus?.(step)}
					>Z&nbsp;↓</button>
				{/if}
			</div>
			<div class="steps">
				<Segmented
					label={t('job.stepSize')}
					mono
					bind:value={step}
					options={[0.1, 1, 10, 50].map((size) => ({ value: size, label: `${size} mm` }))}
				/>
				<!-- The pair, not half of it: unlocking lets you push the head aside to lay
				     material down, and until now the only way to make it hold again was to
				     home the machine. Both hang on the same capability the driver reports. -->
				<button
					class="rot"
					disabled={movingOff || !control.capabilities?.motion?.unlock}
					title={movingBlocked ?? t('job.unlock.why')}
					onclick={() => onUnlock?.()}
				>
					{t('job.unlock')}
				</button>
				<button
					class="rot"
					disabled={movingOff || !control.capabilities?.motion?.lock}
					title={movingBlocked ?? t('job.lock.why')}
					onclick={() => onLock?.()}
				>
					{t('job.lock')}
				</button>
			</div>

			<!-- To a point instead of in a direction (gap J6). LightBurn's Move window
			     has "Go to Origin" and saved positions; whoever has a jig on the bed
			     otherwise jogs that corner together again every session. -->
			{#if control.capabilities?.motion?.move}
				<div class="points">
					<span class="rot-label">{t('job.toPoint')}</span>
					<div class="puntrij">
						<button
							class="rot"
							disabled={movingOff}
							title={movingBlocked ?? t('job.toOrigin.title')}
							onclick={() => control.moveTo(0, 0)}
						>
							{t('job.toOrigin')}
						</button>
						{#each posities as place (place.name)}
							<span class="place">
								<button
									class="rot name"
									disabled={movingOff}
									title={movingBlocked ??
										t('job.toSpot.title', { x: size(place.x_mm), y: size(place.y_mm) })}
									onclick={() => control.moveTo(place.x_mm, place.y_mm)}
								>
									{place.name}
									<!-- The coordinates with it, not only in the tooltip: on a touch
									     screen there is no hover, and then a saved position is a name
									     without a place. LightBurn puts them in a column of their own;
									     there is no column for that here, so they sit muted behind the
									     name in the same chip. -->
									<span class="coord mono">{size(place.x_mm)},&#8239;{size(place.y_mm)}</span>
								</button>
								<!-- Discarding is in the button itself, not in a menu: there are at
								     most twelve of them and you do it rarely. -->
								<button
									class="rot gone"
									aria-label={t('job.forgetSpotAria', { name: place.name })}
									title={t('job.forgetSpot')}
									onclick={() => vergeet(place.name)}
								>×</button>
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
							<button class="rot" onclick={save} disabled={!newName.trim()} title={t('reason.needsName')}>
								{t('job.keep')}
							</button>
							<button class="rot" onclick={() => (saving = false)}>{t('common.cancel')}</button>
						</div>
					{:else}
						<button
							class="rot"
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
				</div>
			{/if}
			<!-- The zero point (gap J12). LightBurn has Set Origin / Clear Origin / Go
			     to Origin; here "To origin" was literally 0,0 of the bed and there was
			     no way to set a zero point of your own. That is daily work: the offcut
			     lies where it lies, and you do not want to drag your whole drawing to
			     get it onto the board.

			     Deliberately a block of its own under "To a point" and not among them:
			     the saved positions say "go there", this says "measure from there".
			     Among the spots it would read as one more spot. -->
			{#if control.capabilities?.motion?.move}
				<div class="origin" class:gezet={control.origin !== null}>
					<span class="rot-label">{t('job.workOrigin')}</span>
					{#if control.origin}
						<!-- The number is always with it. A zero point you cannot read off is
						     a setting that quietly moves your work, and that is exactly the
						     kind of surprise that makes a laser expensive. -->
						<p class="originPoint">
							<span class="mono"
								>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
							>
							— {t('job.origin.here')}
						</p>
					{:else}
						<p class="hint">{t('job.origin.off')}</p>
					{/if}
					<div class="puntrij">
						<button
							class="rot"
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
								class="rot"
								disabled={movingOff}
								title={movingBlocked ?? t('job.origin.goTitle')}
								onclick={() =>
									control.origin && control.moveTo(control.origin.x_mm, control.origin.y_mm)}
							>
								{t('job.toZero')}
							</button>
							<button
								class="rot"
								title={t('job.origin.clearTitle')}
								onclick={() => control.clearOrigin()}
							>
								{t('job.clearZero')}
							</button>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Print and cut (gap H2). The same family as the zero point above and
			     deliberately right under it: both answer "where does the work go", and
			     they are mutually exclusive — with a measured pose the zero point stays
			     out of it, because doing both shifts twice.

			     The marks come from the canvas selection: pointing out two shapes is
			     something you do on the drawing, and a second shape picker inside this
			     panel would be a second way to do one thing. -->
			{#if control.capabilities?.motion?.move}
				<div class="origin" class:gezet={cut?.aligned === true}>
					<span class="rot-label">{t('job.printcut')}</span>
					{#if cut?.aligned}
						<p class="originPoint">
							<span class="mono"
								>{size(cut.offset_mm?.x_mm ?? 0)},&#8239;{size(cut.offset_mm?.y_mm ?? 0)} mm</span
							>
							— {t('job.printcut.pose', {
								angle: i18n.number(Math.round((cut.angle_deg ?? 0) * 100) / 100)
							})}
						</p>
						<p class="hint">{t('job.printcut.instead')}</p>
					{:else if cut?.lapsed === 'gone'}
						<p class="hint">{t('job.printcut.lapsed.marks')}</p>
					{:else if cut?.lapsed === 'machine'}
						<p class="hint">{t('job.printcut.lapsed.machine')}</p>
					{:else if cutMarks.length === 2}
						<p class="hint">
							{t('job.printcut.driveTo', {
								n: cut?.marks.filter((m) => m.measured).length ?? 0
							})}
						</p>
					{:else}
						<p class="hint">{t('job.printcut.off')}</p>
					{/if}
					<div class="puntrij">
						{#if cutMarks.length === 2}
							{#each cutMarks as mark, index (mark.id)}
								<button
									class="rot"
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
								class="rot"
								title={t('job.printcut.clearTitle')}
								onclick={() => control.clearPrintCut()}
							>
								{t('job.printcut.clear')}
							</button>
						{:else}
							<button
								class="rot"
								disabled={selectedIds.length !== 2}
								title={selectedIds.length === 2
									? t('job.printcut.useTitle')
									: t('job.printcut.needsTwo')}
								onclick={() => control.setPrintCutMarks(selectedIds)}
							>
								{t('job.printcut.use')}
							</button>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Adjusting during a running job (gap J11).
			     LightBurn has two columns here, "Adjust Speed" and "Adjust Power", with
			     which you *save* a job instead of redoing it: you see it going too dark
			     and dial ten per cent back without stopping.

			     Only visible when the driver can do it, and that is not tidiness but
			     necessity: only grbl has realtime overrides (0x90/0x99); the Ruida sets
			     speed and power per cut segment from the settings. A button that does
			     nothing next to a burning laser is worse than no button. See
			     FEATURE-GAPS J11. -->
			{#if control.canAdjust}
				<div class="bijstellen">
					<span class="rot-label">{t('job.adjust.title')}</span>
					{#each ADJUSTABLE as axis (axis.what)}
						{#if control.capabilities?.adjust?.[axis.what]}
							{@const level = control.adjust[axis.what] ?? 1}
							<div class="stelrij">
								<span class="stelnaam">
									{t(axis.key)}
									<!-- Only the number in mono; "as designed" is a phrase, and in a
									     figure font it sits oddly measured out. -->
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
											class="rot adjust"
											disabled={!connection.online}
											title={t(step > 0 ? 'job.adjust.more' : 'job.adjust.less', {
												what: t(axis.key).toLowerCase()
											})}
											onclick={() => control.setAdjustment(axis.what, level + step)}
											>{step > 0 ? '+' : '−'}{Math.abs(Math.round(step * 100))}%</button
										>
									{/each}
									<button
										class="rot adjust terug"
										disabled={!connection.online || level === 1}
										title={t('job.adjust.resetTitle')}
										onclick={() => control.setAdjustment(axis.what, 1)}
										>{t('job.adjust.reset')}</button
									>
								</div>
							</div>
						{/if}
					{/each}
					<p class="hint">{t('job.adjust.hint')}</p>
				</div>
			{/if}
			{#if !control.capabilities?.motion?.focus && profile?.has_z}
				<!-- The profile says this machine has a Z axis, but the engine's driver
				     has no command for it. That is not a missing button but missing
				     support; say so. -->
				<p class="hint">{t('job.zAxis.noCommand')}</p>
			{/if}
			{#if profile?.has_autofocus}
				<!-- MeerK40t has no command to start an autofocus. A button that does
				     something *else* instead is worse than no button — so we say where it
				     is, in one sentence. -->
				<p class="hint">{t('job.autofocus')}</p>
			{/if}
		</div>
		</details>
	{/if}

	{#if actions && !actions.pause}
		<p class="hint">{t('job.noPause')}</p>
	{/if}

	<!-- The error message now lives in the status bar, visible on every tab. Once more
	     here would show it twice whenever you happen to be on Job. -->
</div>

<!-- Homing with the rotary in the bed. The head goes to the corner over the place where
     the rotary stands, so this is a question and not a confirmation of a click. -->
<Dialog title={t('job.home.rotary.title')} bind:open={askHome} width="440px">
	<p class="dialog-text">{t('job.home.rotary.body')}</p>
	<div class="dialog-buttons">
		<button class="btn" onclick={() => (askHome = false)}>{t('job.home.rotary.cancel')}</button>
		<button
			class="btn primary"
			onclick={() => {
				askHome = false;
				onHome?.(true);
			}}>{t('job.home.rotary.confirm')}</button
		>
	</div>
</Dialog>

<style>
	.dialog-text {
		margin: 0 0 var(--space-4);
		font-size: var(--text-sm);
	}
	.dialog-buttons {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	/* Below 1200px start and pause live in the top bar and this block largely
	   disappears (see `.dubbel` further down). But a touch screen can be *wider* than
	   1200, and there everything sat at 8px — below the 12px DESIGN-SYSTEM sets as the
	   floor for touch targets.

	   Rows count as much as columns: "Pause" and "Clear queue" sit *under* each other
	   and are both usable during a job, and that second button throws your whole queue
	   away. So `gap`, not `column-gap`. (The start and pause buttons beside each other
	   are never usable at the same time, by the way — there the distance protects
	   against nothing. This one does.) Introduced by the tablet agent, widened here to
	   both axes. */
	@media (pointer: coarse) {
	}
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
	}
	.btn.subtle {
		grid-column: 1 / -1;
	}
	.btn.stop {
		grid-column: 1 / -1;
		margin-top: var(--space-6);
	}
	/* The reference exists only on tablet; on the desktop the buttons are here. */
	/* Gap J9. This was `@media (max-width: 1199px)` here and a JS prop in TopBar: two
	   sources for one agreement, which can drift apart with the worst outcome being
	   that the pause button sits nowhere or twice. Both now read
	   `screen.controlsInBar`; the class below is the consequence, not the rule. */
	/* A way in, not a command: this opens a window, it does not do anything to the
	   machine. So it is a quiet full-width row under the drawing rather than a third
	   button competing with "Start job". */
	.pf-order {
		display: block;
		width: 100%;
		margin: 0 0 var(--space-3);
		padding: 6px 10px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
		font-size: var(--text-xs);
		text-align: center;
	}
	.pf-order:hover {
		background: var(--surface-2);
	}
	.preflight {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.pf-layers {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
		margin: 8px 0;
	}
	.pf-layers th {
		text-align: left;
		font-weight: 500;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
		padding-bottom: 2px;
	}
	.pf-layers td { padding: 2px 0; }
	.pf-layers td.mono { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
	.chip {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-sharp);
		margin-right: var(--space-1h);
		vertical-align: baseline;
	}
	/* With a number in it the chip is no longer a dot but a small block (gap J7). As
	   wide as it is tall and with tabular figures, so that a 1 and a 10 do not make the
	   column jump. The ink (black or white) comes from `inkOn`: on yellow, white is
	   1.58:1 and then you simply cannot read the figure. */
	.chip.numbered {
		width: 15px;
		height: 15px;
		line-height: 15px;
		text-align: center;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		border-radius: var(--radius-field);
		vertical-align: -3px;
	}
	.pf-name {
		max-width: 9em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.unsure { color: var(--warn); }
	/* A layer that does nothing, in the calm tone: there is nothing to check, so this
	   is a statement and not an alarm. The alarm is above it. */
	.pf-blind {
		color: var(--text-2);
		font-style: italic;
		/* Left, directly beside the layer name: this is about the layer and not about a
		   column. Right-aligned it sat loose on the other side of the row, where the
		   reader expects a number. */
		text-align: left;
		padding-left: 8px;
	}
	.pf-warn.strong { color: var(--warn); font-weight: 500; }
	/* A kind of its own, not the fourth yellow wash. The left bar in the danger colour
	   says "this does not work" as against "watch out for this"; the text itself keeps
	   the ordinary colour, because --danger on this wash does not make the contrast
	   (the same measurement as at .pf-mismatch below). */
	.pf-no-raster {
		margin: var(--space-2) 0;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		border-left: 4px solid var(--danger-solid);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		background: color-mix(in srgb, var(--danger) 16%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.pf-time {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-bottom: var(--space-2);
		margin-bottom: 8px;
		border-bottom: 1px solid var(--line);
	}
	.pf-time .v {
		font-size: var(--text-md);
	}
	.rekent {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.pf-row {
		color: var(--text-2);
		font-size: var(--text-xs);
		padding: var(--space-1) 0;
	}
	/* The afternoon behind the plate is not an aside: it is the number somebody plans
	   their evening around, so it reads as text and not as fine print. */
	.pf-row.series {
		color: var(--text-1);
		margin: 0;
	}
	/* ── Sending it to the machine ─────────────────────────────────────────── */
	/* Folded shut: it is the other thing you can do with a ready job, not a second
	   start button, so it must not compete with the one on the footer below it. */
	/* No border and no margin of its own: it sits inside the footer, whose own top
	   border and gap already separate it from the column above. */
	.pf-upload {
		margin: 0;
	}
	.pf-upload > summary {
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
		list-style: none;
	}
	.pf-upload > summary::-webkit-details-marker { display: none; }
	.pf-upload > summary::before {
		content: '▸';
		display: inline-block;
		width: 1em;
		color: var(--text-2);
	}
	.pf-upload[open] > summary::before { content: '▾'; }
	.pf-upload > summary:hover { color: var(--text-1); }
	.pf-uploadrow {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-1h);
	}
	.pf-uploadrow .name {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* The eight characters as the machine writes them: a fixed pitch, spaced out, so
	   that what stands here reads as one label on a panel and not as a word. */
	.pf-uploadrow input {
		width: 11ch;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		padding: var(--space-1) var(--space-1h);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.pf-row.good {
		color: var(--ok);
	}
	.pf-warn {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn) 14%, transparent);
		font-size: var(--text-xs);
	}
	/* The only message here that is about a concrete mix-up, and therefore the only one
	   with a left bar: heavier than the general "not measured" note below it, and not in
	   the same flat yellow tone, because then they would weigh the same. */
	.pf-mismatch {
		margin: var(--space-2) 0;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		list-style: none;
		border-left: 4px solid var(--warn-solid);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		background: color-mix(in srgb, var(--warn) 22%, transparent);
		font-size: var(--text-xs);
		display: grid;
		gap: var(--space-1);
	}
	/* The mildest objection — calculated but on the right material — belongs there but
	   must not shout as loudly as the wrong plate. */
	.pf-mismatch .lighter { color: var(--text-2); }
	.pf-mismatch .lighter strong { color: var(--text-1); font-weight: 500; }
	/* Not a filled pill: according to tokens.css --warn-solid is a surface colour and
	   with white on it only reaches 3.25:1 (measured ourselves: 2.22 in dark). --warn
	   as text also stuck at 3.73 on this wash. So the border carries the colour and the
	   word the ordinary text colour — measured 9.79:1 light, 14.5:1 dark. */
	.first {
		display: inline-block;
		margin-right: var(--space-1h);
		padding: 0 var(--space-1h);
		border-radius: var(--radius-dot);
		border: 1px solid var(--warn-solid);
		color: var(--text-1);
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	/* The size is secondary but has to stay readable; no separate tone. */
	.pf-time.sheet { border-bottom: none; padding-bottom: 0; margin-bottom: var(--space-2); }
	.pf-time.sheet .v { font-size: var(--text-sm); }
	/* A missing material is not a fault but is a gap: the same muted tone as the
	   labels, so that it reads as "something still belongs here" and not as a material
	   called "not filled in". */
	.pf-time.sheet.unknown .v { color: var(--text-2); font-style: italic; }
	.pf-check {
		margin: var(--space-3) 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
	}
	.pf-head {
		display: block;
		font-weight: 600;
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-1);
	}
	.pf-check ul {
		margin: 0;
		padding-left: 1.1em;
		color: var(--text-1);
	}
	.pf-check li { padding: 1px 0; }
	/* The pre-flight's border is neutral; on "nothing to do" it may say so without
	   raising an alarm — this is not a fault, only an empty tray. */
	.preflight.none { border-color: var(--warn); }
	.pf-empty { margin-bottom: var(--space-3); }
	.pf-empty strong {
		display: block;
		font-size: var(--text-sm);
		margin-bottom: 2px;
	}
	.pf-empty p {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.muted {
		color: var(--text-2);
	}
	.token {
		border: 1px solid var(--warn);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		margin-bottom: var(--space-3);
	}
	.token label {
		display: block;
		font-weight: 500;
		margin-bottom: var(--space-2);
	}
	.token-row {
		display: flex;
		gap: var(--space-2);
	}
	.token input {
		flex: 1;
		min-width: 0;
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.token.afgewezen { border-color: var(--danger-solid); }
	.motion { margin-top: var(--space-4); }
	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.pad {
		display: grid;
		/* Four columns; the fifth exists only when there is a Z axis, otherwise an
		   empty column sits there taking up room. */
		grid-template-columns: repeat(4, 40px);
		grid-template-rows: repeat(2, 34px);
		gap: 4px;
		margin: var(--space-2) 0;
	}
	/* Placed explicitly: with implicit placement ↓ slid into the first column instead
	   of below ↑. */
	.pad .up { grid-area: 1 / 2; }
	.pad .left { grid-area: 2 / 1; }
	.pad .down { grid-area: 2 / 2; }
	.pad .right { grid-area: 2 / 3; }
	.pad .home { grid-area: 1 / 4 / 3 / 5; }
	.pad.metz { grid-template-columns: repeat(5, 40px); }
	.pad .zup { grid-area: 1 / 5; }
	.pad .zdown { grid-area: 2 / 5; }
	/* The Z buttons carry a letter *and* an arrow; that does not fit at 15px. */
	.pad .zup, .pad .zdown { font-size: var(--text-xs); }
	.jog {
		padding: 8px 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
	}
	.jog:hover:not(:disabled) { background: var(--surface-2); }
	/* Disabled has to be *visible*. These buttons were blocked but looked identical, so
	   you kept pressing them and nothing happened. */
	.jog:disabled { opacity: 0.4; cursor: not-allowed; }
	.rot:disabled { opacity: 0.4; cursor: not-allowed; }
	.jog.home { font-size: var(--text-xs); }
	.steps { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
	.rot {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	/* The same resting state as in the top bar: recognisable as the stop button (red
	   border, red square) without raising an alarm all day. */
	/* The same dead state as in the top bar: dashed border, no red, and readable — here
	   the text *is* the message, so it must not fade. */
	.btn.danger.dood {
		background: transparent;
		border: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		color: var(--text-2);
	}
	.btn.danger.dood:disabled { opacity: 1; }
	.btn.danger.dood strong { color: var(--text-1); }
	.hint {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* ── The progress block ───────────────────────────────────────────────────
	   What is going on *now*, at the top of the panel. The sizes are generous: this is
	   the block you look at from two metres away while standing at the machine, not
	   something you read from close up. */
	.now {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}
	/* Only a running job gets the accent. A paused one gets the warning colour, because
	   standing still with work in the machine is a state you have to do something
	   about. */
	.now.burns { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }
	.now.pause { border-color: color-mix(in srgb, var(--warn-solid) 55%, var(--line)); }
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
	.now.burns .now-phase { color: var(--accent); }
	.now.pause .now-phase { color: var(--warn); }
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
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.now-vol {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: var(--accent);
		transition: width var(--transition);
	}
	.now.pause .now-vol { background: var(--warn-solid); }
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
		font-weight: 600;
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	.now-step,
	.now-pass { font-variant-numeric: tabular-nums; }
	.now-time {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.now-rest { color: var(--text-1); font-weight: 500; }
	.now-hint {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
	.now-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-1);
	}
	/* Stop keeps its distance from pause: a bad-tap here costs the workpiece. */
	.now-stretch { flex: 1; min-width: var(--space-6); }
	.now-actions .btn { min-height: 40px; padding: 0 var(--space-4); }
	.wachtrij { align-self: flex-start; }

	/* The machine controls below the progress, closed while work is in flight. */
	.machinevouw {
		margin-top: var(--space-4);
		border-top: 1px solid var(--line);
		padding-top: var(--space-3);
	}
	.machinevouw > summary {
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
		list-style: none;
	}
	.machinevouw > summary::-webkit-details-marker { display: none; }
	.machinevouw > summary::before {
		content: '▸';
		display: inline-block;
		width: 1em;
		color: var(--text-2);
	}
	.machinevouw[open] > summary::before { content: '▾'; }
	.machinevouw > summary:hover { color: var(--text-1); }
	.machinevouw .why {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 400;
	}

	/* The button bar sticks to the bottom of the panel: the column is longer than the
	   panel and the primary action must never sit below the fold. Negative margins
	   around `.panel-scroll`'s padding, so the bar runs edge to edge and nothing shows
	   underneath it. */
	.pf-stick {
		position: sticky;
		bottom: calc(-1 * var(--space-4));
		z-index: 2;
		/* A column now: the checklist above the buttons. Both travel with the footer,
		   because the three lines are the last thing you read before you press and
		   they used to scroll out from under the button they belong to. */
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: var(--space-3) calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
		padding: var(--space-3) var(--space-4);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
	}
	.pf-actions {
		display: flex;
		gap: var(--space-2);
	}
	/* Inside the footer the checklist carries no margin of its own: the footer's gap
	   already sets the distance to the buttons. */
	.pf-stick .pf-check {
		margin: 0;
	}
	/* The secondary button keeps its word on one line; the primary gets the rest. With
	   `flex: 1` on both, "Show frame" broke over two lines and the row became
	   twee keer zo high. */
	.pf-actions .btn { flex: none; white-space: nowrap; }
	.pf-actions .btn.primary { flex: 1; }

	/* The start button says what it is going to do, with the time in it. */
	.btn.big { min-height: 44px; font-size: var(--text-md); }
	.pf-start-time {
		margin-left: 6px;
		font-size: var(--text-xs);
		font-weight: 400;
		opacity: 0.85;
	}

	.toetsen {
		grid-column: 1 / -1;
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		line-height: 1.5;
	}
	/* Four lines about keys on a screen without a keyboard is filling the app's most
	   expensive space with something you cannot do there. On a tablet the controls are
	   in the bar as well and this panel is already mostly prose. A tablet with a
	   separate keyboard keeps the shortcut — it is still in the button's tooltip, and
	   it simply works. */
	@media (pointer: coarse) {
		.toetsen { display: none; }
	}
	/* Jumping to a point, beside the direction buttons above. */
	.points { margin-top: var(--space-3); }
	.puntrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-2) 0;
	}
	/* Name and cross are one thing with two targets; the seam between them is a
	   hairline, so it reads as one chip and not as two loose buttons. */
	.place { display: inline-flex; }
	.place .name { border-radius: var(--radius-field) 0 0 var(--radius-field); }
	.place .gone {
		border-left: none;
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		padding: 4px var(--space-2);
		color: var(--text-2);
	}
	.place .gone:hover { color: var(--danger); }
	/* On a touch screen a 20px cross is a mistake waiting to happen: one bad-aimed tap
	   and your saved position is gone. It is
	   recoverable (jog there, save again) and therefore not worth a confirmation, but
	   the target may well be glove-sized. */
	@media (pointer: coarse) {
		.place .name,
		.place .gone { min-height: 44px; }
		.place .gone { padding: 0 var(--space-3); }
	}
	/* Muted and a size smaller: the name is what you aim at, the coordinates are the
	   confirmation that it is the right place. */
	.coord { color: var(--text-2); margin-left: var(--space-1h); }
	.bewaarrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	/* ── The zero point (gap J12) ─────────────────────────────────────────────
	   A little block of its own with a calm border around it: this is a state that is
	   on or off and that moves your work. Without the frame it reads as yet another row
	   of buttons among the saved places, and then you do not see that something is
	   on. */
	.origin {
		margin-top: var(--space-3);
		padding: var(--space-2h) var(--space-3);
		border: 1px solid var(--line-1);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	/* When a zero point is set, the left border carries that — so you see it at the
	   edge of your eye without reading the text. In the accent and not in a warning
	   colour: this is not dangerous, it is on. */
	.origin.gezet {
		border-left: 3px solid var(--accent);
	}
	.originPoint {
		margin: var(--space-1h) 0 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	.originPoint .mono {
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	/* ── Adjusting during the job (gap J11) ────────────────────────────────── */
	.bijstellen { margin-top: var(--space-3); }
	.stelrij { margin-top: var(--space-2); }
	.stelnaam {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-1);
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
	/* Five buttons on one row in a 280 px panel: each may shrink, but the text stays on
	   the type scale — only the air around it comes off. */
	.adjust {
		flex: 1;
		min-width: 0;
		padding: 4px 2px;
		/* Numbers in mono: these buttons sit beside each other and otherwise jump in
		   width as soon as +1% becomes +10%. */
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.adjust.terug { flex: 1.3; }
	.naamveld {
		flex: 1;
		min-width: 10ch;
		font: inherit;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
