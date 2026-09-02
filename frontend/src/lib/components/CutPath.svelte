<script lang="ts">
	/**
	 * The cut path before burning: order, travel and clock, in a window of its own.
	 *
	 * The placement rule says a workspace you look at and compare in gets its own
	 * window, and this is one: you come here to answer three questions — does it cut
	 * inside before outside, where does the head travel needlessly, and how long
	 * until it is done — and none of them fit beside a 220 px panel.
	 *
	 * Deliberately separate from `JobPreview`, which shows *what* gets burned and is
	 * free. This one costs a whole cut plan (measured 2.5 s on 960 shapes, quadratic
	 * above it), so it is only built when somebody asks for it, and asking never
	 * holds up starting a job: the API answers "building" and this window polls.
	 *
	 * Drawing is per *layer*, not per step. One path element per layer for what is
	 * still to come and one for what is done: at the API's ceiling that is a handful
	 * of elements instead of 7,680, which is the difference between a scrubber that
	 * drags and one that does not.
	 */
	import { formatDuration } from '$lib/api';
	import {
		contourCount,
		contourStarts,
		contours as contourList,
		donePaths,
		headAt,
		indexAt,
		stepPath,
		travelPath,
		travelShare,
		type CutPathAnswer,
		type PathStep
	} from '$lib/cutpath';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';

	let {
		open = $bindable(),
		revision = 0,
		bed = null,
		sheet = null,
		colorFor
	}: {
		open: boolean;
		/** Goes up on every change in the design; the path follows it. */
		revision?: number;
		/** The machine's reach. Nullable per axis, because a device that has not said
		 *  yet reports nothing rather than zero. */
		bed?: { width_mm: number | null; height_mm: number | null } | null;
		sheet?: { name: string; width_mm: number; height_mm: number } | null;
		/** The same layer colour the canvas and the layer list show. */
		colorFor?: (operationId: string | null) => string;
	} = $props();

	/** How long a replay lasts, whatever the job lasts. A job of an hour played in
	 *  real time is not a preview; twenty seconds is long enough to follow the head
	 *  and short enough to watch twice. */
	const REPLAY_SECONDS = 20;
	/** The API answers within milliseconds; this is how often we ask again while it
	 *  is building. */
	const POLL_MS = 400;
	/**
	 * When a build is slow enough to say so.
	 *
	 * Was ten seconds, the pre-flight's patience, and at ten seconds the sentence was
	 * unreachable: the heaviest design the segment ceiling admits builds in 2.24 s
	 * (990 shapes, 7,920 segments, measured twice), 1.37 s for 500 shapes over four
	 * passes, and anything slower is refused before a build starts (0.08 s). So the
	 * patience is the build it was written for, not the estimate's.
	 */
	const PATIENCE_MS = 1_500;

	/**
	 * Three values, because there are three states and two of them used to share one.
	 *
	 * `undefined` is "not asked yet", `null` is "asked and the server did not answer".
	 * With both as null every open of the window flashed "the path cannot be fetched
	 * while the server is away" — measured in the DOM from t=5 ms to t=215 ms after
	 * Alt+P, on 127.0.0.1, for a design that was already cached. A false claim about
	 * the connection is worse than no claim.
	 */
	let answer = $state<CutPathAnswer | null | undefined>(undefined);
	/**
	 * The pre-flight's own clock, fetched beside the path.
	 *
	 * Not to show a second time but to name the difference: this window counts the
	 * plan step by step and the start button counts the geometry, and on a design with
	 * a raster layer those two are not close at all — measured on a filled 60 x 40 mm
	 * area, 7:30 here against 0:00 there, because the geometry estimate does not see a
	 * fill. A reader who sees both numbers and no explanation trusts neither, so both
	 * stand in the note at the bottom, as *this design's* numbers and not as the fixed
	 * measurement beside them.
	 */
	let estimate = $state<number | null>(null);
	let slow = $state(false);
	let now = $state(0);
	let playing = $state(false);

	let steps = $derived<PathStep[]>(answer?.state === 'ready' ? (answer.steps ?? []) : []);
	let total = $derived(answer?.state === 'ready' ? (answer.seconds ?? 0) : 0);
	let fragments = $derived(steps.map(stepPath));
	let travel = $derived(travelPath(steps));
	let reached = $derived(indexAt(steps, now));
	let done = $derived(donePaths(steps, fragments, reached));
	let head = $derived(headAt(steps, now));
	let share = $derived(travelShare(steps));
	let layers = $derived(answer?.state === 'ready' ? (answer.layers ?? []) : []);
	/** The areas a raster layer sweeps, with the moment each one is finished. */
	let rasters = $derived(
		steps
			.filter((step) => step.k === 'raster' && step.w !== undefined && step.h !== undefined)
			.map((step) => ({
				op: step.op,
				x: step.x0 as number,
				y: step.y0 as number,
				w: step.w as number,
				h: step.h as number,
				t: step.t2
			}))
	);
	/** The full path per layer, drawn once — this is what is still to come. */
	let whole = $derived.by(() => {
		const map = new Map<string, string[]>();
		steps.forEach((step, i) => {
			if (!fragments[i]) return;
			const key = step.op ?? '';
			const list = map.get(key);
			if (list) list.push(fragments[i]);
			else map.set(key, [fragments[i]]);
		});
		return [...map].map(([id, list]) => ({ id, d: list.join('') }));
	});
	/** How much faster than the machine the replay runs. */
	let rate = $derived(total > 0 ? total / REPLAY_SECONDS : 1);
	/**
	 * The scrubber's grain, and why it is not the clock divided by a thousand.
	 *
	 * A range's reachable values are min + n·step, so a step of total/1000 left the end
	 * unreachable (297.42 of 297.72 measured) and one ArrowRight moved 0.3 s — about
	 * two hundred presses per displayed minute. Whole seconds instead, which the arrow
	 * keys and the clock beside them agree on, with the top rounded up so the end is
	 * one of the reachable values. Under twenty seconds a whole second is too coarse to
	 * see anything, and there the hundredth of the job lands exactly on the end.
	 */
	let scrubStep = $derived(total >= 20 ? 1 : total / 100 || 0.01);
	let scrubMax = $derived(total >= 20 ? Math.ceil(total) : total);
	/**
	 * What the window is doing, for a reader who cannot see it.
	 *
	 * A live region has to be in the DOM *before* the change to announce it, so it
	 * stands outside the branches below. The refusals carry `role="alert"` of their
	 * own; this one is for the transitions nothing announced: building becoming ready,
	 * measured at 2.4 s on the heaviest design the ceiling admits.
	 */
	let status = $derived.by(() => {
		if (answer === undefined) return t('cutpath.building');
		if (answer === null) return t('cutpath.unreachable');
		if (answer.state === 'building') return t('cutpath.building');
		if (answer.state === 'ready')
			return t('cutpath.status.ready', {
				n: i18n.number(answer.steps_total ?? steps.length, 0),
				total: formatDuration(total)
			});
		return '';
	});

	/** What the canvas answers for a layer it does not know. Not a guess: it is the
	 *  literal fallback in `design.colorFor`, and it resolves to the same
	 *  rgb(91,100,112) as the travel stroke — measured on both. */
	const UNKNOWN_LAYER = 'var(--text-2)';

	function colour(id: string) {
		const given = colorFor?.(id || null);
		// A layer the design does not list — a hatch effect comes out of the plan with
		// its own id, and the engine gives it a fully transparent colour (#0000ff00,
		// measured). Drawing it in the travel grey put two different meanings in one
		// colour, with only a dash between them in the legend. Its own token instead.
		if (!given || given === UNKNOWN_LAYER) return 'var(--text-1)';
		return given;
	}

	/**
	 * The frame the drawing looks into, in millimetres.
	 *
	 * The bed, plus anything that falls outside it. A path that leaves the bed is
	 * exactly what you have come to see; cropping it to the bed would hide the one
	 * thing that goes wrong.
	 */
	/** The bed, but only when it has both its numbers; half a bed is not a rectangle. */
	let reach = $derived(
		bed && bed.width_mm && bed.height_mm
			? { width_mm: bed.width_mm, height_mm: bed.height_mm }
			: null
	);
	let frame = $derived.by(() => {
		let x0 = 0;
		let y0 = 0;
		let x1 = reach?.width_mm ?? sheet?.width_mm ?? 0;
		let y1 = reach?.height_mm ?? sheet?.height_mm ?? 0;
		for (const step of steps) {
			for (const [x, y] of [
				[step.x0, step.y0],
				[step.x1, step.y1]
			] as [number | undefined, number | undefined][]) {
				if (x === undefined || y === undefined) continue;
				x0 = Math.min(x0, x);
				y0 = Math.min(y0, y);
				x1 = Math.max(x1, x);
				y1 = Math.max(y1, y);
			}
		}
		if (x1 <= x0 || y1 <= y0) return null;
		const margin = Math.max(x1 - x0, y1 - y0) * 0.03;
		return { x: x0 - margin, y: y0 - margin, w: x1 - x0 + 2 * margin, h: y1 - y0 + 2 * margin };
	});
	/** Line widths and dot sizes are in millimetres like everything else here, so
	 *  they have to scale with the frame or a big bed gets hairlines. */
	let unit = $derived(frame ? Math.max(frame.w, frame.h) / 400 : 1);

	/**
	 * The numbers on the drawing, and the same order as text.
	 *
	 * The box is the one the `<text>` below really occupies: font-size 9 units, offset
	 * 3 units right and 3 up, 0.62 of the size per character in IBM Plex Mono and 1.4
	 * of it in height — measured on a drawn digit, whose box was 10.1 x 22 px, so the
	 * height is not one em but about 1.3 of it. Numbers that would land on each other
	 * are folded into the lowest of them (`contourStarts`), which is what the question
	 * "does it cut inside before outside" needs.
	 */
	let numbers = $derived(
		contourStarts(steps, {
			box: { char: unit * 9 * 0.62, height: unit * 9 * 1.4, dx: unit * 3, dy: unit * -3 }
		})
	);
	let order = $derived(contourList(steps));
	let contours = $derived(contourCount(steps));
	/** How many contours were folded into another number, for the note under the drawing. */
	let folded = $derived(numbers.reduce((sum, mark) => sum + mark.more, 0));
	/**
	 * The same order in sentences, one per contour.
	 *
	 * Each line is one whole sentence from the catalogue: the number, the layer, the
	 * size and where it starts. Built here and not in the markup so the two shapes of
	 * the sentence (with and without passes) stand beside each other.
	 */
	let orderLines = $derived.by(() => {
		const names = new Map(layers.map((layer) => [layer.id, layer.label]));
		return order.map((contour) => {
			const values = {
				n: i18n.number(contour.n, 0),
				layer: names.get(contour.op ?? '') ?? t('cutpath.order.noLayer'),
				w: mm(contour.w),
				h: mm(contour.h),
				x: mm(contour.x),
				y: mm(contour.y),
				passes: i18n.number(contour.passes, 0)
			};
			return {
				n: contour.n,
				text: contour.passes > 1 ? t('cutpath.order.itemPasses', values) : t('cutpath.order.item', values)
			};
		});
	});

	// ------------------------------------------------------------------ loading

	async function fetchEstimate() {
		try {
			const response = await fetch('/api/job/estimate');
			estimate = response.ok ? ((await response.json()).seconds ?? null) : null;
		} catch {
			estimate = null;
		}
	}

	/** Fetches, stores, and hands back what came in — the caller polls on it, and
	 *  reading `answer` back would only tell the type checker what it just assigned. */
	async function fetchOnce(): Promise<CutPathAnswer | null> {
		let latest: CutPathAnswer | null;
		try {
			const response = await fetch('/api/job/path');
			latest = response.ok ? await response.json() : null;
		} catch {
			// Unreachable is not an answer, and the window says so through `answer`
			// being null rather than pretending the design is empty.
			latest = null;
		}
		answer = latest;
		return latest;
	}

	/**
	 * Polling for as long as the window is open and the API is still building.
	 *
	 * Restarts on a design change, because a path of the drawing you have just
	 * edited is worse than no path: it looks right.
	 */
	$effect(() => {
		if (!open) return;
		void revision;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout> | null = null;
		const patience = setTimeout(() => (slow = true), PATIENCE_MS);
		playing = false;
		now = 0;
		slow = false;
		// Not the previous answer: after an edit the old path is a picture of a design
		// that no longer exists, and it looks right.
		answer = undefined;
		fetchEstimate();
		(async function poll() {
			while (!stopped) {
				const latest = await fetchOnce();
				if (stopped || latest?.state !== 'building') break;
				await new Promise((resolve) => (timer = setTimeout(resolve, POLL_MS)));
			}
			clearTimeout(patience);
			if (!stopped) slow = false;
		})();
		return () => {
			stopped = true;
			if (timer) clearTimeout(timer);
			clearTimeout(patience);
		};
	});

	// ------------------------------------------------------------------ playing

	$effect(() => {
		if (!playing || !total) return;
		let handle = 0;
		let last = performance.now();
		const tick = (stamp: number) => {
			const step = ((stamp - last) / 1000) * rate;
			last = stamp;
			now = now + step;
			if (now >= total) {
				now = total;
				playing = false;
				return;
			}
			handle = requestAnimationFrame(tick);
		};
		handle = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(handle);
	});

	function toggle() {
		if (!total) return;
		// Pressing play at the end starts over; otherwise the button would do nothing
		// and look broken. "At the end" is within a scrubber step of the end, not
		// exactly on it: the range steps in whole seconds, so dragging the thumb fully
		// right used to land on 4:57 of 4:58 and the first press replayed 0.3 s and
		// stopped — measured at 300, 900 and 1800 ms after the press.
		if (!playing && now >= total - Math.max(scrubStep, 0.01)) now = 0;
		playing = !playing;
	}

	function mm(value: number) {
		return i18n.number(Math.round(value * 10) / 10);
	}
</script>

<Dialog title={t('cutpath.title')} bind:open width="1040px">
	<!-- Outside the branches on purpose: a live region only announces changes that
	     happen while it is already on the page. -->
	<p class="offscreen" aria-live="polite">{status}</p>
	{#if answer === undefined}
		<p class="note working">{t('cutpath.building')}</p>
	{:else if answer === null}
		<p class="note" role="alert">{t('cutpath.unreachable')}</p>
	{:else if answer.state === 'building'}
		<p class="note working">{t('cutpath.building')}</p>
		{#if slow}
			<p class="note">{t('cutpath.building.slow')}</p>
		{/if}
	{:else if answer.state === 'empty'}
		<p class="note">{t('cutpath.empty')}</p>
	{:else if answer.state === 'busy'}
		<p class="note">{t('cutpath.busy')}</p>
	{:else if answer.state === 'too_big'}
		<p class="note" role="alert">
			{t('cutpath.tooBig', {
				n: i18n.number(answer.planned_segments ?? 0, 0),
				limit: i18n.number(answer.limit ?? 0, 0)
			})}
		</p>
		<p class="note">{t('cutpath.tooBig.hint')}</p>
	{:else if answer.state === 'failed'}
		<p class="note" role="alert">{t('cutpath.failed', { message: answer.message ?? '' })}</p>
	{:else if answer.limited}
		<p class="note" role="alert">
			{t('cutpath.limited', {
				n: i18n.number(answer.steps_total ?? 0, 0),
				limit: i18n.number(answer.step_limit ?? 0, 0)
			})}
		</p>
		<p class="note">{t('cutpath.limited.totals', {
			time: formatDuration(answer.seconds),
			travel: mm(answer.travel_mm ?? 0)
		})}</p>
	{:else if frame}
		<div class="cp">
			<svg
				viewBox="{frame.x} {frame.y} {frame.w} {frame.h}"
				preserveAspectRatio="xMidYMid meet"
				role="img"
				aria-label={t('cutpath.aria', {
					n: i18n.number(answer.steps_total ?? steps.length, 0),
					total: formatDuration(total)
				})}
			>
				<!-- The bed and the sheet, so the path has something to lie on. Both get
				     a non-scaling stroke: a line in millimetres would be invisible on a
				     large bed. -->
				{#if reach}
					<rect class="bed" x="0" y="0" width={reach.width_mm} height={reach.height_mm} />
				{/if}
				{#if sheet}
					<rect class="sheet" x="0" y="0" width={sheet.width_mm} height={sheet.height_mm} />
				{/if}

				<!-- Travel first, underneath: it is the thing you look for, but it must
				     not cover the work. Dashed and thin, because it burns nothing. -->
				<path class="travel" d={travel} style:stroke-width={unit} style:stroke-dasharray="{unit * 3} {unit * 3}" />

				<!-- A raster layer burns its *area*, so it is drawn as an area. Without
				     this a filled 60×40 mm rectangle looked exactly like a rectangle that
				     is cut out — measured on the first shot, and it is the one difference
				     that decides whether the head sweeps for six minutes or cuts for six
				     seconds. -->
				{#each rasters as box, i (i)}
					<rect
						class="raster"
						x={box.x}
						y={box.y}
						width={box.w}
						height={box.h}
						style:fill={colour(box.op ?? '')}
						style:stroke={colour(box.op ?? '')}
						style:stroke-width={unit}
						opacity={box.t <= now ? 0.55 : 0.18}
					/>
				{/each}

				<!-- What is still to come, faint, per layer. -->
				{#each whole as layer (layer.id)}
					<path class="ahead" d={layer.d} style:stroke={colour(layer.id)} style:stroke-width={unit * 1.2} />
				{/each}
				<!-- What is already burned, in full colour. -->
				{#each whole as layer (layer.id)}
					<path
						class="burned"
						d={done.get(layer.id) ?? ''}
						style:stroke={colour(layer.id)}
						style:stroke-width={unit * 2.4}
					/>
				{/each}

				<!-- The order. Numbers and not arrows: an arrow tells you a direction,
				     a number tells you *which* comes first, and that is the question
				     ("does it cut inside before outside"). -->
				{#each numbers as mark (mark.n)}
					<text
						class="order"
						class:passed={mark.t <= now}
						x={mark.x}
						y={mark.y}
						font-size={unit * 9}
						dx={unit * 3}
						dy={unit * -3}>{mark.more ? `${mark.n}+${mark.more}` : mark.n}</text
					>
				{/each}

				{#if head}
					<!-- The head. Hollow while it travels, solid while it burns: two codes
					     for one state, because on a busy path a colour alone is lost. -->
					<circle
						class="head"
						class:travelling={head.travelling}
						cx={head.x}
						cy={head.y}
						r={unit * 4}
						style:stroke-width={unit * 1.5}
					/>
				{/if}
			</svg>

			<!-- The transport. One row: play, the scrubber, the clock. -->
			<div class="transport">
				<button class="btn" onclick={toggle} aria-pressed={playing}>
					{playing ? t('cutpath.pause') : t('cutpath.play')}
				</button>
				<input
					type="range"
					min="0"
					max={scrubMax}
					step={scrubStep}
					value={now}
					aria-label={t('cutpath.scrub')}
					aria-valuetext={formatDuration(now)}
					oninput={(event) => {
						playing = false;
						// Clamped, because the range's top is rounded up to a whole step so the
						// end is reachable at all: without the rounding the highest value was
						// 297.42 of 297.72 and Play did nothing on the first press.
						now = Math.min(total, Number((event.currentTarget as HTMLInputElement).value));
					}}
				/>
				<span class="clock mono">{formatDuration(now)} / {formatDuration(total)}</span>
			</div>
			<p class="rate">
				{t('cutpath.rate', { n: i18n.number(Math.max(1, Math.round(rate)), 0) })}
			</p>

			<!-- The numbers under the picture. The travel share is the one that answers
			     "is my order any good": a third of the clock spent travelling is an
			     order problem, and no drawing says that as fast as one percentage. -->
			<dl class="sums">
				<div><dt>{t('cutpath.sum.time')}</dt><dd class="mono">{formatDuration(total)}</dd></div>
				<div>
					<dt>{t('cutpath.sum.burning')}</dt>
					<dd class="mono">{mm(answer.cut_mm ?? 0)} mm</dd>
				</div>
				<div>
					<dt>{t('cutpath.sum.travelling')}</dt>
					<dd class="mono">
						{mm(answer.travel_mm ?? 0)} mm · {i18n.number(Math.round(share * 100), 0)}%
					</dd>
				</div>
				<div>
					<dt>{t('cutpath.sum.contours')}</dt>
					<dd class="mono">{i18n.number(contours, 0)}</dd>
				</div>
			</dl>

			{#if !numbers.length && contours}
				<p class="note quiet">{t('cutpath.tooManyNumbers', { n: i18n.number(contours, 0) })}</p>
			{:else if folded}
				<p class="note quiet">{t('cutpath.cluster')}</p>
			{/if}

			<!-- The order in words. The drawing is one `role="img"` with one label, so
			     without this the answer to "what comes first" is graphics only — and on a
			     caption of eighteen letters the numbers are folded together anyway. -->
			{#if orderLines.length}
				<details class="order-list">
					<summary>{t('cutpath.order.title', { n: i18n.number(orderLines.length, 0) })}</summary>
					<ol>
						{#each orderLines as line (line.n)}
							<li>{line.text}</li>
						{/each}
					</ol>
				</details>
			{/if}

			<!-- The legend. Same colours as the canvas and the layer list, because a
			     third colour scheme for the same layers is a puzzle, not a legend. -->
			<ul class="legend">
				{#each layers as layer (layer.id)}
					<li>
						<span class="swatch" style:background={colour(layer.id)}></span>
						<span class="name">{layer.label}</span>
						<span class="mono spec"
							>{layer.speed_mm_s === null ? '—' : i18n.number(layer.speed_mm_s)} mm/s · {layer.power_percent ===
							null
								? '—'
								: i18n.number(layer.power_percent)}%</span
						>
					</li>
				{/each}
				<li>
					<span class="swatch travelswatch"></span>
					<span class="name">{t('cutpath.legend.travel')}</span>
				</li>
			</ul>

			<!-- What this cannot promise. The engine's own estimate mixes its burn model
			     with the measured pace of a finished pass (CLAUDE.md, LaserJob), and the
			     acceleration in the corners is in neither. Saying so here is cheaper
			     than a user standing beside a machine that is two minutes late. -->
			<!-- Two ideas, two sentences. They were one, and then the fixed measurement
			     took this design's live numbers: on a 990-square grid without a single
			     filled area the window claimed "measured on one design with a filled
			     area: 51:13 against 47:53". The measurement is the measurement; this
			     design's numbers are this design's. -->
			<p class="note quiet">
				<strong>{t('cutpath.honest.title')}</strong>
				{t('cutpath.honest.body')}
				{t('cutpath.honest.slower')}
			</p>
			{#if estimate !== null}
				<p class="note quiet">
					{t('cutpath.honest.here', {
						here: formatDuration(total),
						there: formatDuration(estimate)
					})}
				</p>
			{/if}
			<p class="note quiet">
				{t('cutpath.built', { seconds: i18n.number(answer.built_in_s ?? 0, 2) })}
			</p>
		</div>
	{/if}
</Dialog>

<style>
	svg {
		display: block;
		width: 100%;
		max-height: 58vh;
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	/* The bed is the machine's reach; the sheet is your material on it. Same
	   language as `JobPreview`, so the two windows do not each invent their own
	   bed. */
	.bed {
		fill: var(--bed);
		stroke: var(--text-2);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
	}
	.sheet {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 8 5;
		vector-effect: non-scaling-stroke;
	}
	.travel {
		fill: none;
		stroke: var(--text-2);
		opacity: 0.75;
	}
	/* Hatching would be truer to what a raster does, but a pattern that scales with
	   the frame costs a pattern element per layer and reads as noise at this size;
	   a translucent area says "this whole surface is worked" clearly enough. */
	.raster {
		stroke-linejoin: round;
	}
	.ahead {
		fill: none;
		opacity: 0.3;
		stroke-linejoin: round;
	}
	.burned {
		fill: none;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.order {
		fill: var(--text-2);
		font-family: var(--font-mono);
	}
	.order.passed {
		fill: var(--text-1);
		font-weight: 600;
	}
	.head {
		fill: var(--accent);
		stroke: var(--surface-1);
	}
	/* Hollow while travelling: the head is on its way to work, not at work. */
	.head.travelling {
		fill: none;
		stroke: var(--accent);
	}
	/* The twelfth component to define its own `.btn` (X1 in FEATURE-GAPS.md); the
	   same eight lines as the eleven before it, because a bare `.btn` in tokens.css
	   cannot outweigh a component selector. */
	.transport {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.transport input[type='range'] {
		flex: 1;
		min-width: 120px;
	}
	.clock {
		font-variant-numeric: tabular-nums;
		color: var(--text-1);
	}
	.rate {
		margin: var(--space-1) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.sums {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-6);
		margin: var(--space-3) 0 0;
	}
	/* Each sum is a little column of its own. Without this the browser lays the
	   `dt`s out as one line and the `dd`s underneath, and the screen read "On the
	   clockBurning" — measured on the first shot. */
	.sums > div {
		display: flex;
		flex-direction: column;
		gap: 2px;
		/* And wide enough for its own label: without `max-content` the column takes
		   the width of the number under it and the label runs into the next one — the
		   screen read "On the clockBurning". */
		min-width: max-content;
	}
	.sums dt {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.sums dd {
		margin: 0;
		font-variant-numeric: tabular-nums;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
		margin: var(--space-3) 0 0;
		padding: 0;
		list-style: none;
		font-size: var(--text-xs);
	}
	.legend li {
		display: flex;
		align-items: center;
		gap: var(--space-1h);
	}
	.swatch {
		width: 14px;
		height: 4px;
		border-radius: 2px;
	}
	/* The travel swatch has to read as the dashed line it stands for, or the legend
	   claims a colour that is not on the drawing. */
	.travelswatch {
		height: 0;
		border-top: 2px dashed var(--text-2);
		border-radius: 0;
	}
	.legend .spec {
		color: var(--text-2);
	}
	.mono {
		font-family: var(--font-mono);
	}
	.note {
		margin: var(--space-2) 0 0;
		font-size: var(--text-sm);
		line-height: 1.5;
	}
	.note.quiet {
		color: var(--text-2);
		font-size: var(--text-xs);
	}
	.note.working {
		color: var(--text-2);
	}
	/* A live region has to be in the DOM to announce anything, and it has nothing to
	   show: off the screen, not `display: none` (which is not announced either). */
	.offscreen {
		position: absolute;
		width: 1px;
		height: 1px;
		margin: -1px;
		padding: 0;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
		border: 0;
	}
	.order-list {
		margin-top: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.order-list summary {
		cursor: pointer;
	}
	.order-list ol {
		/* The number is in the sentence itself — the contour's place in the cut order,
		   which is the thing being named. A marker beside it would number it twice. */
		list-style: none;
		/* The list can be long (one line per contour); it gets its own scroll instead
		   of pushing the honesty note off the dialog. */
		max-height: 30vh;
		overflow-y: auto;
		margin: var(--space-2) 0 0;
		padding-left: 0;
		line-height: 1.6;
	}
</style>
