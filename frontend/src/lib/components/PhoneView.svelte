<script lang="ts">
	/**
	 * De telefoon: monitor en noodrem.
	 *
	 * No canvas, no tools, no layers. Whoever comes here wants to know how things
	 * stand and, if need be, intervene — with one thumb, while standing beside the
	 * machine. Designing happens on the desktop, and this screen says so in as many
	 * words instead of cramming a canvas in as well.
	 *
	 * Three rules that decide the shape:
	 * 1. The emergency stop is *fixed* at the bottom and never scrolls away —
	 *    otherwise you will not make the two seconds once the photo list grows longer
	 *    than the screen.
	 * 2. Every block earns its height. An empty 130 px stage saying "no active job"
	 *    while the header already said so is wasted room.
	 * 3. What you measure, you show once. Progress was here three times and the
	 *    remaining time — the one number you are waiting for — not at all.
	 */
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import {
		currentJob,
		gridSummary,
		formatDuration,
		jobLabel,
		remainingSeconds,
		machineStateLabel,
		type Device,
		type GridAxis,
		type Job,
		type MachineState
	} from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import type { CameraStore } from '$lib/camera.svelte';
	import ConnectionCard from './ConnectionCard.svelte';
	import { connection } from '$lib/connection.svelte';
	import AlarmCard from './AlarmCard.svelte';
	import NotificationCard from './NotificationCard.svelte';
	import type { Notifications, Watchdog } from '$lib/notifications.svelte';
	import type { DesignStore } from '$lib/design.svelte';

	let {
		device,
		state: machineState,
		job,
		control,
		camera,
		notifications,
		watchdog,
		connected,
		position,
		design = null,
		sheet = null
	}: {
		device: Device | null;
		state: MachineState;
		/** Only the *running* job, and therefore unused here: this screen reads
		 *  `currentJob(device)`, because a paused job belongs with it too (J8). */
		job: Job | null;
		control: Controller;
		camera: CameraStore;
		notifications: Notifications;
		watchdog: Watchdog;
		connected: boolean;
		position: string;
		/** What is on the bed (gap J10). Without this the phone drew an empty frame,
		 *  even with seven shapes on it. */
		design?: DesignStore | null;
		sheet?: { name: string; width_mm: number; height_mm: number } | null;
	} = $props();

	// `job` is only the *running* job. A paused job falls outside it, and so
	// disappeared from this screen entirely: you paused and the screen reported "no
	// active job", without a button to resume. `currentJob` is the shared definition
	// of "the job the controls are about".
	let huidig = $derived<Job | null>(currentJob(device));
	let running = $derived(Boolean(huidig?.running));
	/**
	 * Is work standing still? One source: `machineState()`, which already calls
	 * `isStalled()` and takes the device side (`laser_status === "pause"`) into
	 * account as well.
	 *
	 * There used to be a variant of its own here that dropped the requirement "there
	 * was progress already" (gap J8). Consequence: a freshly spooled job is not
	 * running yet and on the phone was called "Paused" for one polling round, while
	 * the rest of the app saw it sitting in the queue. Two screens saying different
	 * things about one job.
	 */
	let stil = $derived(machineState === 'paused');

	/**
	 * The pause button has to do something you can see.
	 *
	 * The Lihuiyu driver does not report a pause back in its status, so without this
	 * the screen stays exactly the same after the press and you press again. This is
	 * not a claim that it has stopped — the label says "requested".
	 */
	let pauzeGevraagd = $state(false);
	$effect(() => {
		if (stil || !huidig) pauzeGevraagd = false;
	});
	async function pauzeer() {
		pauzeGevraagd = true;
		const ok = await control.pause();
		if (!ok) pauzeGevraagd = false;
	}

	/**
	 * A camera that is "on" but delivers no image.
	 *
	 * Without this the browser shows its own broken-image icon with the alt text
	 * beside it, and at the same time everything that *was* worth reporting
	 * disappears. An unplugged USB cable should not cost half a screen.
	 */
	let beeldStuk = $state(false);
	$effect(() => {
		camera.generation;
		beeldStuk = false;
	});

	let camAan = $derived(
		camera.state.available && camera.shown && camera.state.running && !beeldStuk
	);
	let progress = $derived(huidig?.progress ?? 0);
	let percent = $derived(Math.round(progress * 100));

	/**
	 * Remaining time, not the total estimate.
	 *
	 * From `remainingSeconds()`: there used to be the same computation here with a
	 * threshold of its own (5% progress against the shared version's 10%), so phone
	 * and status bar switched from estimating to measuring at different moments and
	 * briefly showed two different remaining times for the same job.
	 */
	let resterend = $derived(remainingSeconds(huidig));

	// A countdown says how long you have to wait; a clock time says whether you can
	// still fetch coffee. Side by side they cost one line.
	let klaarOm = $derived.by(() => {
		if (resterend === null) return null;
		const eind = new Date(Date.now() + resterend * 1000);
		return eind.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
	});

	// The ring: one outline that carries the progress, instead of the same percentage
	// in three shapes side by side.
	const STRAAL = 78;
	const OMTREK = 2 * Math.PI * STRAAL;

	// Grids still waiting for a photo: that is the reason you are standing beside the
	// machine with a phone. The library does not hold on to them, so we fetch them
	// here.
	type Raster = {
		id: number;
		material_name: string | null;
		operation: string;
		photo_path: string | null;
		thickness_mm: number | null;
		speed_min: number;
		speed_max: number;
		power_min: number;
		power_max: number;
		speed_steps: number;
		power_steps: number;
		// Since B12 the user chooses the axes; which quantity sits where decides what
		// the summary line may claim.
		row_axis: GridAxis | null;
		column_axis: GridAxis | null;
		rows: number | null;
		columns: number | null;
		interval_min: number | null;
		interval_max: number | null;
		/** Where the board lies on the photo. Null = photo in, not yet aligned. */
		alignment: unknown;
		created_at: string;
	};
	let rasters = $state<Raster[]>([]);
	let bezig = $state<number | null>(null);
	/** A row that disappears is too quiet; this says what has just happened. */
	let gelukt = $state<string | null>(null);

	/** Many material names already carry the thickness ("Birch plywood 4 mm"); then do
	    not stick another "4 mm" on the end. */
	function rasterNaam(g: Raster): string {
		// Without a material this read "grid · engrave-raster": the same word twice,
		// and one of the two is an internal key.
		const naam = g.material_name ?? 'Testraster';
		if (!g.thickness_mm || /\bmm\b/i.test(naam)) return naam;
		return `${naam} ${g.thickness_mm} mm`;
	}

	/** The generator's keys are not words for the screen. */
	const BEWERKING: Record<string, MessageKey> = {
		snijden: 'phone.operation.cut',
		'graveren-vector': 'phone.operation.engrave',
		'graveren-raster': 'phone.operation.raster',
		markeren: 'phone.operation.mark'
	};

	function bewerking(kind: string): string {
		return kind in BEWERKING ? t(BEWERKING[kind]) : kind;
	}

	/** "2026-08-11 19:33:37" → "11 Aug 19:33". No seconds, no year. */
	function stempel(waarde: string): string {
		const d = new Date(waarde.replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return waarde;
		// Not toLocaleString: that puts a comma between them, and then the line breaks
		// exactly there — "11 Aug," on one line, "19:51" on the next.
		const dag = new Intl.DateTimeFormat(i18n.locale, { day: 'numeric', month: 'short' }).format(d);
		const tijd = new Intl.DateTimeFormat(i18n.locale, { timeStyle: 'short' }).format(d);
		// Hard space: date and time belong together and must not fall apart.
		return `${dag} ${tijd}`.replace(/ /g, ' ');
	}

	/**
	 * The photo list knew only two states: photo needed, or gone (gap P9).
	 *
	 * Since there is an alignment on the grid row there is a third — photo in, not
	 * aligned yet — and that one quietly disappeared from the list. A half-finished
	 * step should not disappear: the board is still there, the preset is not yet, and
	 * nobody looking only at their phone knew there was still something to do.
	 */
	let wachtend = $derived(rasters.filter((g) => !g.photo_path));
	let uitlijnen = $derived(rasters.filter((g) => g.photo_path && !g.alignment));
	/** First what the phone is needed for, then what is waiting for the desktop. */
	let lijst = $derived([...wachtend, ...uitlijnen]);

	async function haalRasters() {
		const r = await fetch('/api/library/testgrids');
		if (!r.ok) return;
		rasters = await r.json();
	}
	/**
	 * Keeping the grid list up to date, because this screen is the second one in the
	 * room.
	 *
	 * This fetched once, while building the page, and never again. Measured with two
	 * windows on the same server: the desktop makes a grid, you pick up the phone that
	 * was already on, and there is nothing there — the grid only appeared after a
	 * manual refresh. Exactly the order in which you use it: set up on the desktop
	 * first, then over to the machine with the phone.
	 *
	 * No WebSocket: that carries machine status, and the library sits in another
	 * database that gives no signals. Ten seconds is ample for something waiting on a
	 * burned board, and it is one small request. Coming back to the tab fetches
	 * straight away — that is the moment you are looking.
	 */
	$effect(() => {
		haalRasters();
		const klok = setInterval(haalRasters, 10_000);
		const terug = () => {
			if (document.visibilityState === 'visible') haalRasters();
		};
		document.addEventListener('visibilitychange', terug);
		return () => {
			clearInterval(klok);
			document.removeEventListener('visibilitychange', terug);
		};
	});

	async function foto(gridId: number, bestand: File) {
		bezig = gridId;
		try {
			const form = new FormData();
			form.append('file', bestand);
			const token = localStorage.getItem('openkerf.token') ?? '';
			await fetch(`/api/library/testgrids/${gridId}/photo`, {
				method: 'POST',
				headers: token ? { Authorization: `Bearer ${token}` } : {},
				body: form
			});
			await haalRasters();
			gelukt = t('phone.photoSaved');
		} finally {
			bezig = null;
		}
	}

	/**
	 * Here the permission question gets its occasion from the machine itself.
	 *
	 * On the phone you do not start a job (the desktop does), so "something is burning
	 * now" is the moment the question means anything. On an empty bed we ask nothing;
	 * then the setting simply sits waiting at the bottom.
	 */
	let vraagWeg = $state(false);
	let vraagNu = $derived(notifications.shouldAsk && !vraagWeg && Boolean(huidig));
	/** De instelkaart uitgeklapt? Ingeklapt kost hij één regel. */
	let instellingenOpen = $state(false);

	/**
	 * This screen's order of precedence (decision B13).
	 *
	 * If a job is running, "how far" is the question and the ring stays on top. If the
	 * machine is idle while a burned board is waiting for a photo, *that* is the work
	 * — and it is the only work in this whole app for which you physically have to
	 * hold a phone.
	 *
	 * Aligning does not count here: you do that on a big screen, so it changes nothing
	 * about why you are standing here.
	 */
	let fotoEerst = $derived(!huidig && wachtend.length > 0);
	/**
	 * The machine state may only shrink to one line when nothing is wrong. An
	 * unplugged cable or an alarm is not a subordinate clause; then the whole card
	 * comes back, *with* the sentence explaining why it is quiet.
	 */
	let standInEenRegel = $derived(fotoEerst && connected && machineState === 'ready');
	/** The bed drawing under that one line. Closed, because you came for the photo. */
	let bedOpen = $state(false);
	let meldStand = $derived(
		notifications.permission === 'denied'
			? 'geblokkeerd'
			: notifications.active
				? 'aan'
				: 'uit'
	);

	let bedW = $derived(device?.bed.width_mm ?? 0);
	let bedH = $derived(device?.bed.height_mm ?? 0);
	let kop = $derived(device?.position.mm ?? null);

	/**
	 * Wat er op het bed ligt (gat J10).
	 *
	 * This screen drew an empty frame, even with seven shapes on it — and then
	 * "looking beside the machine" is precisely the one question you do not get
	 * answered: *what* is about to be burned.
	 *
	 * The path data is in Tats, just as on the canvas; one scale transform converts it
	 * to the millimetres this drawing measures in. And because it measures in
	 * millimetres, every line gets `non-scaling-stroke` — otherwise a stroke of 1 on a
	 * 610 mm bed is a hair of nothing (or on a small bed a bar half a centimetre
	 * wide).
	 */
	let perMm = $derived(design?.design?.units_per_mm ?? 1);
	/**
	 * How wide this drawing really is, in pixels.
	 *
	 * The SVG measures in millimetres (viewBox = the bed), so without this number
	 * nothing in this file knows how big a millimetre is on screen. And that is needed:
	 * see `TEXT_MINIMUM`.
	 */
	let bedBreedtePx = $state(0);
	/**
	 * Below this displayed height we leave vector text out.
	 *
	 * The generator draws captions in millimetres, because it is burned in millimetres
	 * — nothing wrong with that. But 4 mm of letter height on a 610 mm bed in a 340 px
	 * drawing is a good 2 px, and a 2 px tall outline with a 1.5 px stroke is no longer
	 * a letter: it is a little bar. Visible as two solid blue streaks above the left of
	 * the test grid.
	 *
	 * Leaving it out is more honest than filling it in. What you are left with is the
	 * grid itself, and *that* is what you are looking at on your phone. 12 px is the
	 * height below which the counter of an `e` or an `a` closes up at this stroke
	 * weight.
	 */
	const TEXT_MINIMUM = 12;
	/**
	 * Colour and state come from `strokeFor` — the same helper the canvas uses. Working
	 * out the layer myself gave a different answer from the canvas: for a shape in two
	 * layers I took the first from the list and the canvas took the topmost in the
	 * tree. Two screens drawing the same work in a different colour is exactly the kind
	 * of difference that stops you trusting your phone.
	 */
	let vormen = $derived.by(() => {
		const store = design;
		if (!store) return [];
		return store.elements
			.filter((element) => !element.hidden && (element.path || element.image))
			.map((element) => {
				const streek = store.strokeFor(element);
				return {
					id: element.id,
					path: element.path,
					image: element.image,
					// The height in mm of a text element; null for everything else.
					// `font_size_mm` is what the generator meant; without it the shape's
					// bounding box is the best approximation.
					tekstMm: element.text
						? (element.text.font_size_mm ??
							(element.bounds ? (element.bounds[3] - element.bounds[1]) / perMm : 0))
						: null,
					kleur: streek.color,
					zichtbaar: streek.visible,
					// "Does not burn" covers two cases: in no layer at all, or in a layer
					// set to "does not burn". To somebody standing beside the machine that
					// is the same message.
					stil: streek.dashed || streek.dimmed
				};
			})
			.filter((vorm) => vorm.zichtbaar);
	});
	let brandt = $derived(vormen.filter((v) => !v.stil).length);
	let stille = $derived(vormen.filter((v) => v.stil).length);

	/**
	 * Work that falls off the bed or off the sheet (gap P8).
	 *
	 * Since C2 the canvas reports this in two sentences under the drawing; here the
	 * shape *was* drawn outside the sheet frame, but without a word beside it. Standing
	 * beside the machine in the sun, a difference in colour is the first thing you stop
	 * reading.
	 *
	 * The same sum as on the canvas, with the same tolerance and the same rule that
	 * only work that really burns counts: a shape in no layer costs no material, and
	 * false alarms teach people to ignore alarms. The computation is deliberately here
	 * and not from `/api/job/estimate`: this screen refreshes on signals, and a second
	 * source would give a second answer.
	 */
	const RAND_SPELING = 0.5;

	function buitenKader(
		doos: { x: number; y: number; width: number; height: number },
		kader: { width: number; height: number }
	) {
		return (
			doos.x < -RAND_SPELING ||
			doos.y < -RAND_SPELING ||
			doos.x + doos.width > kader.width + RAND_SPELING ||
			doos.y + doos.height > kader.height + RAND_SPELING
		);
	}

	let buitenstaanders = $derived.by(() => {
		const uit = { bed: 0, vel: 0 };
		if (!design || !bedW || !bedH) return uit;
		for (const element of design.elements) {
			if (!element.bounds || element.hidden) continue;
			const streek = design.strokeFor(element);
			if (streek.dashed || streek.dimmed || !streek.visible) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			const doos = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
			if (buitenKader(doos, { width: bedW, height: bedH })) uit.bed += 1;
			else if (
				sheet &&
				sheet.width_mm > 0 &&
				sheet.height_mm > 0 &&
				buitenKader(doos, { width: sheet.width_mm, height: sheet.height_mm })
			) {
				uit.vel += 1;
			}
		}
		return uit;
	});

	/**
	 * What gets *drawn*. That is not the same as what burns: captions that are too
	 * small drop out here (`TEXT_MINIMUM`), but they do burn, so the count above is
	 * left alone. A drawing may leave something out; a number that says what the
	 * machine is going to do may not.
	 */
	let getekend = $derived.by(() => {
		const perPx = bedW > 0 && bedBreedtePx > 0 ? bedBreedtePx / bedW : 0;
		if (perPx === 0) return vormen;
		return vormen.filter((v) => v.tekstMm === null || v.tekstMm * perPx >= TEXT_MINIMUM);
	});

	/** One sentence for anybody who does not get the image; it is under the drawing too. */
	let bedUitleg = $derived.by(() => {
		const parts = [
			t('phone.bedAria.size', { width: Math.round(bedW), height: Math.round(bedH) })
		];
		if (vormen.length === 0) parts.push(t('phone.bedAria.empty'));
		else {
			parts.push(t('preview.shapesBurn', { n: brandt }));
			if (stille) parts.push(t('phone.bedAria.noLayer', { n: stille }));
		}
		if (buitenstaanders.bed) parts.push(t('phone.bedAria.offBed', { n: buitenstaanders.bed }));
		if (buitenstaanders.vel) parts.push(t('phone.bedAria.offSheet', { n: buitenstaanders.vel }));
		parts.push(t('phone.bedAria.head', { position }));
		return parts.join(', ') + '.';
	});
</script>

<ConnectionCard brandt={running} />

<div class="telefoon">
	<!--
		At the top and outside the scroll area: an alarm you can scroll away is not an
		alarm (decision B3). Deliberately not an overlay: as a fixed block it pushes
		the rest down instead of covering the header and half the bed drawing. At
		390 px the floating version cost 270 px of cut-off content, and the machine
		status — precisely the first thing you want to see with a connection alarm —
		was permanently out of reach.
	-->
	<AlarmCard {watchdog} large />
	<header>
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="staat"
			>{connected ? machineStateLabel(machineState) : t('phone.noConnection')}</span
		>
		<span class="machine mono">{device?.label ?? t('phone.noMachine')}</span>
	</header>

	<!--
		The ranking follows what you do here, not what the screen is called
		(decision B13).

		With a running job the progress stays on top: then "how far" is the question.
		If the machine is idle and a burned board is waiting, there is exactly one
		thing to do for which you need a phone in your hand — taking a photo of
		something lying on the bed. That goes on top, and the machine state falls back
		to one line.

		The emergency brake does not move with it. See "The emergency brake: a
		trade-off with a price" in DESIGN-SYSTEM.md: findable blind weighs more than
		the dead button.
	-->
	{#snippet beeld()}
		<!-- Camera: if you can look, you look. -->
		<div class="podium">
			<img src={camera.src} alt={t('phone.cameraAlt')} onerror={() => (beeldStuk = true)} />
		</div>
	{/snippet}

	{#snippet bedkaart()}
		<!-- What is on the bed: the bed to scale, the sheet in it, the work in layer
		     colour and a cross on the head. -->
		<div class="rust">
			{#if bedW > 0 && bedH > 0}
				<svg
					class="bedje"
					viewBox="0 0 {bedW} {bedH}"
					role="img"
					aria-label={bedUitleg}
					bind:clientWidth={bedBreedtePx}
				>
					<rect class="vlak" x="0" y="0" width={bedW} height={bedH} vector-effect="non-scaling-stroke" />
					<!-- The sheet: where the material is. Without that frame the work floats
					     somewhere in a 610 mm bed and you cannot see whether it fits on your
					     offcut. -->
					{#if sheet && sheet.width_mm > 0 && sheet.height_mm > 0}
						<rect
							class="vel"
							x="0"
							y="0"
							width={sheet.width_mm}
							height={sheet.height_mm}
							vector-effect="non-scaling-stroke"
						/>
					{/if}
					<!-- The work itself, in the layer colour. One scale from Tats to mm,
					     exactly as the canvas does it. -->
					{#if getekend.length}
						<g transform="scale({1 / perMm})">
							{#each getekend as vorm (vorm.id)}
								{#if vorm.image}
									<image
										href="/api/design/elements/{encodeURIComponent(vorm.id)}/image.png"
										x={vorm.image.x_mm * perMm}
										y={vorm.image.y_mm * perMm}
										width={vorm.image.width_mm * perMm}
										height={vorm.image.height_mm * perMm}
										preserveAspectRatio="none"
										opacity={vorm.stil ? 0.35 : 1}
									/>
								{:else}
									<path
										d={vorm.path}
										class="vorm"
										class:stil={vorm.stil}
										style:stroke={vorm.stil ? undefined : vorm.kleur}
									/>
								{/if}
							{/each}
						</g>
					{/if}
					{#if kop}
						<g class="kop">
							<line x1={kop[0]} y1="0" x2={kop[0]} y2={bedH} vector-effect="non-scaling-stroke" />
							<line x1="0" y1={kop[1]} x2={bedW} y2={kop[1]} vector-effect="non-scaling-stroke" />
							<circle cx={kop[0]} cy={kop[1]} r={Math.max(bedW, bedH) / 80} />
						</g>
					{/if}
				</svg>
			{/if}
			<dl class="feiten">
				<div><dt>{t('phone.bed')}</dt><dd class="mono">{bedW && bedH
						? `${Math.round(bedW)} × ${Math.round(bedH)} mm`
						: '—'}</dd></div>
				<div><dt>{t('phone.head')}</dt><dd class="mono">{position}</dd></div>
				<!-- What is there, in words. A grey dotted line among seven coloured ones
				     cannot be seen on a phone in the sun; the number can. -->
				<div>
					<dt>{t('phone.onTheBed')}</dt>
					<dd>
						{#if vormen.length === 0}
							{t('phone.nothing')}
						{:else}
							{t('preview.shapesBurn', { n: brandt })}{#if stille}<span class="stilnoot"
									>{t('phone.noLayer', { n: stille })}</span
								>{/if}
						{/if}
					</dd>
				</div>
			</dl>
			<!-- Gap P8: the same as the strip under the canvas (C2), in the same two
			     sentences. Outside the bed the head does not go; outside the sheet it
			     does, but there is no material. That difference decides whether you move
			     the work or replace your board, so it is two lines and not one "careful". -->
			{#if buitenstaanders.bed || buitenstaanders.vel}
				<div class="buiten" role="status">
					{#if buitenstaanders.bed}
						<p class="bedrand">
							<span class="teken" aria-hidden="true">!</span>
							{t('canvas.outsideBed', { n: buitenstaanders.bed })}
						</p>
					{/if}
					{#if buitenstaanders.vel}
						<p class="velrand">
							<span class="teken" aria-hidden="true">!</span>
							{t('canvas.outsideSheet', {
								n: buitenstaanders.vel,
								sheet: sheet ? sheet.name : t('canvas.theSheet')
							})}
						</p>
					{/if}
				</div>
			{/if}
			<!-- A bed without a job only said "Ready" at the top. That is a state, not an
			     answer: whoever looks here wants to know whether it is quiet because it is
			     finished, or quiet because something is wrong. -->
			<p class="waarom">
				{#if !connected}
					{t('phone.lastSeen')}
				{:else if machineState === 'unplugged'}
					{t('phone.unplugged')}
				{:else}
					{t('phone.idle')}
				{/if}
			</p>
		</div>
	{/snippet}

	{#snippet camerablok()}
		{#if beeldStuk}
			<p class="uitleg">{t('phone.cameraNoImage')}</p>
		{/if}
		{#if camera.state.available && !camAan}
			<button class="camknop" onclick={() => camera.start()} disabled={camera.busy}>
				{camera.busy
					? t('phone.cameraStarting')
					: beeldStuk
						? t('phone.cameraRetry')
						: t('phone.cameraOn')}
			</button>
		{:else if !camera.state.available}
			<p class="uitleg">{camera.state.reason ?? t('phone.noCamera')}</p>
		{/if}
		{#if camera.error}
			<p class="failure">{camera.error}</p>
		{/if}
	{/snippet}

	{#snippet fotolijst()}
		{#if gelukt}
			<p class="goed" role="status">{gelukt}</p>
		{/if}
		{#if lijst.length}
			<section class="rasters">
				<h2>
					{#if wachtend.length}
						{t('phone.waitingPhoto', { n: wachtend.length })}
					{:else}
						{t('phone.waitingAlign', { n: uitlijnen.length })}
					{/if}
				</h2>
				{#each lijst as grid (grid.id)}
					<label class="raster" class:gedaan={Boolean(grid.photo_path)}>
						<span class="naam">
							<span class="kop">{rasterNaam(grid)} · {bewerking(grid.operation)}</span>
							{#if grid.photo_path}
								<!-- Halfway, and that may be visible. The next step is not yours:
								     aligning is done on a big screen. -->
								<span class="detail rest">{t('phone.photoIn')}</span>
							{:else}
								<span class="detail mono">
									{gridSummary(grid)} · {stempel(grid.created_at)}
								</span>
							{/if}
						</span>
						<span class="knop" class:zacht={Boolean(grid.photo_path)}>
							{#if bezig === grid.id}
								{t('common.busy')}
							{:else if grid.photo_path}
								{t('phone.again')}
							{:else}
								{t('phone.takePhoto')}
							{/if}
						</span>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							aria-label={grid.photo_path
								? t('phone.newPhotoOf', { id: grid.id })
								: t('library.photo.alt', { id: grid.id })}
							onchange={(e) => {
								const f = e.currentTarget.files?.[0];
								e.currentTarget.value = '';
								if (f) foto(grid.id, f);
							}}
						/>
					</label>
				{/each}
			</section>
		{/if}
	{/snippet}

	<div class="rol">
		{#if fotoEerst}
			<!-- There is a burned board on the bed and the machine is idle: this is what
			     you have the phone in your hand for. -->
			{@render fotolijst()}
			{#if standInEenRegel}
				<section class="standsectie">
					<button
						class="standrij"
						aria-expanded={bedOpen}
						onclick={() => (bedOpen = !bedOpen)}
					>
						<span class="dot {machineState}" aria-hidden="true"></span>
						<span class="naam">{t('phone.notBurning')}</span>
						<span class="stand mono">{position}</span>
						<span class="pijl" aria-hidden="true">{bedOpen ? '▴' : '▾'}</span>
					</button>
					{#if bedOpen}
						{@render bedkaart()}
					{/if}
				</section>
			{:else}
				<!-- Not simply idle: then the machine state is no longer a subclause. -->
				{@render bedkaart()}
			{/if}
			{#if camAan}
				{@render beeld()}
			{/if}
			{@render camerablok()}
		{:else}
			{#if camAan}
				{@render beeld()}
				{#if huidig}
					<div class="strook" role="progressbar" aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100">
						<div class="vol" style="width: {percent}%"></div>
					</div>
				{/if}
			{:else if huidig}
				<!-- One ring carries the progress; the number inside it is the same story,
				     not a second one. -->
				<div class="podium">
					<svg class="ring" viewBox="0 0 200 200" role="progressbar"
						aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100"
						aria-label={t('job.progressAria')}>
						<circle class="baan" cx="100" cy="100" r={STRAAL} />
						<circle
							class="voor"
							class:pauze={stil}
							cx="100" cy="100" r={STRAAL}
							stroke-dasharray="{OMTREK}"
							stroke-dashoffset={OMTREK * (1 - progress)}
						/>
					</svg>
					<div class="binnen">
						<span class="groot mono">{percent}<span class="pct">%</span></span>
						{#if stil}
							<span class="onder">{t('phone.paused')}</span>
						{:else if pauzeGevraagd}
							<span class="onder">{t('phone.pauseAsked')}</span>
						{:else if resterend !== null}
							<span class="onder">{t('phone.remaining', { time: formatDuration(resterend) })}</span>
							<span class="klaar">{t('phone.doneAt', { time: klaarOm })}</span>
						{:else}
							<span class="onder">{t('phone.burning')}</span>
						{/if}
					</div>
				</div>
				<div class="jobregel">
					<span class="titel">{jobLabel(huidig)}</span>
					<span class="mono muted">{huidig.steps_done} / {huidig.steps_total}</span>
				</div>
			{:else}
				{@render bedkaart()}
			{/if}

			{#if vraagNu}
				<!-- The occasion is here now: there is work in the machine. -->
				<NotificationCard {notifications} variant="prompt" onDone={() => (vraagWeg = true)} />
			{/if}

			{@render camerablok()}
			{@render fotolijst()}
		{/if}

		<!-- The fixed place where notifications go on and off, and where it says what
		     the browser makes of it. Collapsed that costs one line; blocked is a state
		     you see *and* undo here. -->
		<section class="meldsectie">
			<button
				class="meldrij"
				aria-expanded={instellingenOpen}
				onclick={() => (instellingenOpen = !instellingenOpen)}
			>
				<span class="naam">{t('notifications.title')}</span>
				<span class="stand {meldStand}">{meldStand}</span>
				<span class="pijl" aria-hidden="true">{instellingenOpen ? '▴' : '▾'}</span>
			</button>
			{#if instellingenOpen}
				<div class="meldbody">
					<NotificationCard {notifications} />
				</div>
			{/if}
		</section>

		<p class="elders">{t('phone.designElsewhere')}</p>
	</div>

	<!-- The emergency brake: fixed at the bottom, does not scroll, far apart. What
	     the machine refuses belongs here and must not disappear into the console. -->
	<div class="noodrem">
		{#if !connected}
			<!-- The only brake that still works is not on this screen. You should not
			     have to conclude that yourself from two grey buttons. -->
			<p class="failure" role="alert">
				{t('phone.stopOnMachine')}
				<button class="opnieuw" onclick={() => connection.retryNow()}>
					{connection.inSeconds > 0
						? t('phone.retry.auto', { seconds: connection.inSeconds })
						: t('phone.retry')}
				</button>
			</p>
		{/if}
		{#if control.error}
			<p class="failure" role="alert">{control.error}</p>
		{/if}
		<div class="knoppen">
			{#if stil}
				<button class="rem hervat" disabled={control.needsToken || !connected} onclick={() => control.resume()}>
					{t('phone.resume')}
				</button>
			{:else}
				<button class="rem pauze" disabled={!huidig || control.needsToken || !connected} onclick={pauzeer}>
					{pauzeGevraagd ? t('phone.pausing') : t('job.pause')}
				</button>
			{/if}
			<!-- Without a connection this tap arrives nowhere. A red button that looks
			     pressable and does nothing is the most dangerous thing on this screen:
			     you press, you walk away, and you believe it stops. -->
			<button
				class="rem stop"
				class:scherp={Boolean(huidig) && connected}
				disabled={control.needsToken || !connected}
				onclick={() => control.stop()}
			>
				{t('job.stop')}
			</button>
		</div>
	</div>
</div>

<style>
	.telefoon {
		display: flex;
		flex-direction: column;
		height: 100%;
		box-sizing: border-box;
		background: var(--surface-0);
		overflow: hidden;
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex: none;
		padding: var(--space-3);
	}
	.staat { font-weight: 600; font-size: var(--text-md); }
	.machine { margin-left: auto; color: var(--text-2); font-size: var(--text-xs); }
	.dot { width: 10px; height: 10px; border-radius: var(--radius-dot); background: var(--text-2); }
	.dot.ready { background: var(--ok); }
	/* Was `.dot.running`, and that class did not exist: MachineState is called
	   `busy`. The dot therefore stayed grey while the machine was burning. */
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	/* `unplugged` did not exist yet when this dot was written; without a rule it
	   fell back to grey and a dead port read as "nothing wrong". */
	.dot.unplugged { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }
	.dot.unplugged { background: var(--warn-solid); }
	.opnieuw {
		display: block;
		width: 100%;
		min-height: 44px;
		margin-top: var(--space-2);
		font: inherit;
		font-weight: 600;
		color: var(--text-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	/* Gap P8: the same two lines as under the canvas, with the same colour *and* the
	   same sign. Colour alone must never carry it — this phone lies beside the
	   machine, often with the sun on it. */
	.buiten {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}
	.buiten p {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		margin: 0;
		padding-left: var(--space-2);
		font-size: var(--text-sm);
		line-height: 1.4;
		color: var(--text-1);
		border-left: 4px solid var(--danger-solid);
	}
	.buiten p.velrand { border-left-color: var(--warn-solid); }
	.buiten .teken {
		flex: none;
		width: 18px;
		height: 18px;
		margin-top: 1px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		font-weight: 700;
		font-size: var(--text-xs);
		color: var(--on-color);
		background: var(--danger-solid);
	}
	.buiten p.velrand .teken { background: var(--warn-solid); color: var(--void); }

	.waarom {
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
	}

	/* Only this part scrolls; the header and the emergency stop stay put. */
	.rol {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: 0 var(--space-3) var(--space-3);
	}

	.podium {
		flex: none;
		position: relative;
		border-radius: var(--radius-card);
		background: var(--stage);
		box-shadow: var(--lift-1);
		display: grid;
		place-items: center;
		overflow: hidden;
		aspect-ratio: 4 / 3;
		max-height: 40vh;
	}
	.podium img { width: 100%; height: 100%; object-fit: contain; }
	.ring { width: min(72vw, 240px); height: auto; transform: rotate(-90deg); }
	.ring .baan { fill: none; stroke: var(--surface-2); stroke-width: 10; }
	.ring .voor {
		fill: none;
		stroke: var(--accent);
		stroke-width: 10;
		stroke-linecap: round;
		transition: stroke-dashoffset var(--transition-panel);
	}
	.ring .voor.pauze { stroke: var(--warn-solid); }
	.binnen {
		position: absolute;
		display: grid;
		gap: var(--space-1);
		justify-items: center;
		text-align: center;
	}
	.groot { font-size: var(--text-display); line-height: 1; color: var(--text-1); font-variant-numeric: tabular-nums; }
	.pct { font-size: var(--text-lg); color: var(--text-2); }
	.binnen .onder { color: var(--text-1); font-size: var(--text-md); }
	.binnen .klaar { color: var(--text-2); font-size: var(--text-xs); }

	.strook { flex: none; height: 8px; border-radius: var(--radius-dot); background: var(--surface-2); overflow: hidden; }
	.strook .vol { height: 100%; background: var(--accent); transition: width var(--transition-panel); }

	.jobregel { flex: none; display: flex; align-items: baseline; gap: var(--space-2); }
	.jobregel .titel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.muted { margin-left: auto; color: var(--text-2); font-size: var(--text-xs); }

	/* Resting state: the bed to scale with a cross on the head. Costs the same room as
	   the empty grey rectangle that used to be here, and says something. */
	.rust {
		flex: none;
		display: grid;
		gap: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	/* Keep it tight: the waiting grids are the reason you pick up the phone, and they
	   are below. The bed only has to be recognisable. */
	.bedje { width: 100%; height: auto; max-height: 30vh; display: block; }
	/* --bed is white and so is the card: in the light theme the bed was therefore
	   invisible. --canvas-bg is separate from the card in both themes. */
	.bedje .vlak { fill: var(--canvas-bg); stroke: var(--line); stroke-width: 1; }
	.bedje .kop line { stroke: var(--accent); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.7; }
	.bedje .kop circle { fill: var(--accent); }
	/* The edge of the sheet is the boundary of your material. Against `--canvas-bg`,
	   `--line` reaches too little to read as a boundary; `--text-2` is the same choice
	   as in the pre-flight. */
	.bedje .vel {
		fill: var(--bed);
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 5 4;
	}
	.bedje .vorm {
		fill: none;
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	/* In no burning layer: the same language as on the canvas and in the pre-flight —
	   grey dashed means "the machine skips this". */
	.bedje .vorm.stil {
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 4 3;
	}
	.feiten .stilnoot { color: var(--text-2); font-weight: 400; }
	.feiten { margin: 0; display: grid; gap: var(--space-1); }
	.feiten > div { display: flex; justify-content: space-between; align-items: baseline; }
	.feiten dt { color: var(--text-2); }
	.feiten dd { margin: 0; font-weight: 500; }

	.camknop {
		flex: none;
		min-height: 48px;
		font: inherit;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.camknop:disabled { opacity: 0.5; }
	.uitleg { flex: none; margin: 0; color: var(--text-2); font-size: var(--text-xs); }
	.failure { margin: 0; color: var(--danger); font-size: var(--text-xs); }

	/* 12px between the rows: every row is a target in itself, and 8px was too close to
	   hit the right one with a thumb without looking. */
	.rasters { flex: none; display: grid; gap: var(--space-3); }
	.rasters h2 {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.raster {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 60px;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.raster .naam { min-width: 0; display: grid; gap: var(--space-1); }
	.raster .kop { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* Two lines rather than a truncated sweep: this is exactly the fact by which you
	   tell two grids of the same material apart. */
	.raster .detail { color: var(--text-2); font-size: var(--text-xs); line-height: 1.3; }
	.goed { flex: none; margin: 0; color: var(--ok); font-size: var(--text-xs); }
	/* It looked like a text link while the whole row is the target. Now a button in
	   shape, so the thumb knows where it stands. */
	.raster .knop {
		margin-left: auto;
		flex: none;
		white-space: nowrap;
		display: grid;
		place-items: center;
		min-height: 44px;
		padding: 0 var(--space-3);
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		color: var(--accent);
		font-weight: 600;
	}
	.raster input { position: absolute; width: 0; height: 0; opacity: 0; }
	/* Photo in, not yet aligned (gap P9). Stays in the list because the step is half
	   done, but does not carry the emphasis of a row that still wants something from
	   you: the border is the same, the button is quiet. */
	.raster.gedaan { background: var(--surface-0); }
	.raster .detail.rest { color: var(--text-2); font-size: var(--text-xs); line-height: 1.3; }
	.raster .knop.zacht {
		border-color: var(--line);
		color: var(--text-2);
		font-weight: 500;
	}

	/* The machine state as one line (decision B13): the same shape as the notices row
	   below it, so that "a row that opens" means one thing on this screen. */
	.standsectie { flex: none; display: grid; gap: var(--space-2); }
	.standrij {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 52px;
		padding: 0 var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
		font: inherit;
		text-align: left;
	}
	.standrij .dot { flex: none; }
	.standrij .naam { font-weight: 500; }
	.standrij .stand { margin-left: auto; font-size: var(--text-xs); color: var(--text-2); }
	.standrij .pijl { flex: none; color: var(--text-2); }

	.meldsectie { flex: none; display: grid; gap: var(--space-2); }
	.meldrij {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 52px;
		padding: 0 var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
		text-align: left;
	}
	.meldrij .naam { font-weight: 500; }
	.meldrij .stand {
		margin-left: auto;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.meldrij .stand.aan { color: var(--ok); }
	/* Blocked is not the user's mistake but is something you have to see: amber,
	   because there is something to put right. */
	.meldrij .stand.geblokkeerd { color: var(--warn); }
	.meldrij .pijl { flex: none; color: var(--text-2); }
	.meldbody {
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}

	.elders {
		flex: none;
		/* `auto` on top: when there is little on the screen — two grids and a collapsed
		   machine state — this line drops to the bottom edge of the scroll area instead
		   of leaving a 200 px hole behind. When the content fills up, the auto margin
		   falls back to zero and nothing changes. */
		margin: auto 0 0;
		padding-top: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
	}

	/* 24 px between the two buttons: opposite consequences must not sit beside each
	   other when you are aiming with a thumb. */
	.noodrem {
		flex: none;
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		padding-bottom: max(var(--space-3), env(safe-area-inset-bottom));
		background: var(--surface-0);
		border-top: 1px solid var(--line);
	}
	.knoppen { display: flex; gap: var(--space-6); }
	.rem {
		flex: 1;
		min-height: 64px;
		font: inherit;
		font-size: var(--text-md);
		font-weight: 600;
		border-radius: var(--radius-card);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.rem:disabled { opacity: 0.4; }
	.rem.hervat { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
	/* At rest, stop is an outline and not a red block: a bright red button on a screen
	   where nothing is running pulls the thumb towards the one action that solves
	   nothing. As soon as there is something to stop, it fills in. */
	.rem.stop { background: transparent; border-color: var(--danger); color: var(--danger); }
	.rem.stop.scherp { background: var(--danger-solid); border-color: var(--danger-solid); color: var(--on-color); }

	/* The ring is a report, not decoration: the position stays, the sliding towards
	   the position goes. */
	@media (prefers-reduced-motion: reduce) {
		.ring .voor,
		.strook .vol {
			transition: none;
		}
	}
</style>
