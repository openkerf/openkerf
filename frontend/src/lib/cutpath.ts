/**
 * The cut path as data, and the arithmetic the window draws it with.
 *
 * Plain TypeScript, no runes: the drawing of a path is arithmetic, and arithmetic
 * belongs where `node --test` can reach it. The component above this file decides
 * what it looks like; this file decides what is true.
 *
 * The model comes straight from the engine's cut plan, and it has one shape worth
 * knowing before reading on: **a travel move is not a step, it is the gap between
 * two steps**. A step burns from (x0,y0) to (x1,y1); if its start is not where the
 * previous step ended, the head travelled there, and it did so between `t0` and
 * `t1`. That is exactly how `CutCode.provide_statistics` accounts for the time, so
 * the picture and the clock cannot disagree.
 */

/** One thing the machine does, in the order it does it. */
export type PathStep = {
	/** `cut` burns a line or a curve, `raster` sweeps a box, `move` is a rapid the
	 *  plan asked for, `dot` a dwell, `wait` a pause, `console` one of our own Z
	 *  steps between passes. */
	k: 'cut' | 'raster' | 'move' | 'dot' | 'wait' | 'console';
	/** The layer this belongs to, as the layer list knows it. */
	op: string | null;
	x0?: number;
	y0?: number;
	x1?: number;
	y1?: number;
	/** A raster's box, with x0/y0 as its corner. */
	w?: number;
	h?: number;
	/** Where a raster's sweep starts and ends. */
	sx?: number;
	sy?: number;
	ex?: number;
	ey?: number;
	/** Control points: four for a cubic, two for a quadratic. */
	c?: number[];
	/** When the head sets off, when it starts burning, when it is done. */
	t0: number;
	t1: number;
	t2: number;
	/** The first step of a contour — this is where the order becomes visible. */
	f?: boolean;
	/** Drawn as a chord because we do not know this shape. */
	approx?: boolean;
	/** For a console step: the command. */
	cmd?: string;
};

export type PathLayer = {
	id: string;
	label: string;
	color: string | null;
	type: string | null;
	speed_mm_s: number | null;
	power_percent: number | null;
};

export type CutPathAnswer = {
	state: 'ready' | 'building' | 'empty' | 'too_big' | 'busy' | 'failed';
	fingerprint: string;
	/** ready */
	steps?: PathStep[];
	steps_total?: number;
	seconds?: number;
	cut_mm?: number;
	travel_mm?: number;
	layers?: PathLayer[];
	built_in_s?: number;
	limited?: boolean;
	step_limit?: number;
	/** building */
	elapsed_s?: number;
	for_this_design?: boolean;
	/** too_big */
	planned_segments?: number;
	limit?: number;
	/** failed */
	message?: string;
};

/** Where a step begins, whatever kind it is. Null when it has no place on the bed. */
export function startOf(step: PathStep): [number, number] | null {
	if (step.k === 'raster')
		return step.sx === undefined || step.sy === undefined
			? step.x0 === undefined || step.y0 === undefined
				? null
				: [step.x0, step.y0]
			: [step.sx, step.sy];
	if (step.x0 === undefined || step.y0 === undefined) return null;
	return [step.x0, step.y0];
}

/** Where a step leaves the head. */
export function endOf(step: PathStep): [number, number] | null {
	if (step.k === 'raster')
		return step.ex === undefined || step.ey === undefined ? startOf(step) : [step.ex, step.ey];
	if (step.x1 === undefined || step.y1 === undefined) return startOf(step);
	return [step.x1, step.y1];
}

/** The SVG `d` of one step, in millimetres. Empty for a step with no shape. */
export function stepPath(step: PathStep): string {
	const start = startOf(step);
	if (!start) return '';
	if (step.k === 'raster') {
		if (step.w === undefined || step.h === undefined) return '';
		return `M${step.x0} ${step.y0}h${step.w}v${step.h}h${-step.w}Z`;
	}
	const end = endOf(step);
	if (!end) return '';
	if (step.c?.length === 4)
		return `M${start[0]} ${start[1]}C${step.c[0]} ${step.c[1]} ${step.c[2]} ${step.c[3]} ${end[0]} ${end[1]}`;
	if (step.c?.length === 2)
		return `M${start[0]} ${start[1]}Q${step.c[0]} ${step.c[1]} ${end[0]} ${end[1]}`;
	return `M${start[0]} ${start[1]}L${end[0]} ${end[1]}`;
}

/**
 * The jumps where the head moves without burning.
 *
 * Only the real ones: a step that starts where the previous ended is a
 * continuation, not a travel, and drawing a zero-length dash there would put a
 * dot on every corner of every rectangle.
 */
export function travelPath(steps: PathStep[]): string {
	const parts: string[] = [];
	let here: [number, number] | null = null;
	for (const step of steps) {
		const start = startOf(step);
		if (start && here && (here[0] !== start[0] || here[1] !== start[1]))
			parts.push(`M${here[0]} ${here[1]}L${start[0]} ${start[1]}`);
		here = endOf(step) ?? here;
	}
	return parts.join('');
}

/** How many steps are finished at this moment: the index of the first unfinished one. */
export function indexAt(steps: PathStep[], seconds: number): number {
	// Binary search, because the scrubber asks this on every frame and a design at
	// the ceiling holds thousands of steps.
	let low = 0;
	let high = steps.length;
	while (low < high) {
		const middle = (low + high) >> 1;
		if (steps[middle].t2 <= seconds) low = middle + 1;
		else high = middle;
	}
	return low;
}

/**
 * Where the head is at this moment.
 *
 * Three cases, and the middle one is the point of the whole window: on its way
 * (between t0 and t1 it is travelling, and travelling is what you are hunting
 * for), burning (between t1 and t2), or done.
 *
 * The interpolation over a curve runs along the chord. That is a dot a few tenths
 * of a millimetre off its curve at worst, and it costs no bezier arithmetic per
 * frame.
 */
export function headAt(
	steps: PathStep[],
	seconds: number
): { x: number; y: number; travelling: boolean } | null {
	if (!steps.length) return null;
	const index = indexAt(steps, seconds);
	if (index >= steps.length) {
		const end = endOf(steps[steps.length - 1]);
		return end ? { x: end[0], y: end[1], travelling: false } : null;
	}
	const step = steps[index];
	const start = startOf(step);
	if (!start) return null;
	if (seconds < step.t1) {
		// Travelling towards this step, from wherever the previous one left off.
		const from = index > 0 ? endOf(steps[index - 1]) : start;
		const span = step.t1 - step.t0;
		const part = span > 0 ? Math.min(1, Math.max(0, (seconds - step.t0) / span)) : 1;
		const origin = from ?? start;
		return {
			x: origin[0] + (start[0] - origin[0]) * part,
			y: origin[1] + (start[1] - origin[1]) * part,
			travelling: true
		};
	}
	const end = endOf(step) ?? start;
	const span = step.t2 - step.t1;
	const part = span > 0 ? Math.min(1, Math.max(0, (seconds - step.t1) / span)) : 1;
	return {
		x: start[0] + (end[0] - start[0]) * part,
		y: start[1] + (end[1] - start[1]) * part,
		travelling: false
	};
}

/**
 * The path already burned, per layer, up to this step.
 *
 * Per layer because a layer has its own colour, and one path element per layer
 * instead of one per step is the difference between a scrubber that drags and one
 * that does not: at the ceiling that is 7,680 elements against a handful.
 */
export function donePaths(steps: PathStep[], fragments: string[], upto: number): Map<string, string> {
	const done = new Map<string, string[]>();
	for (let i = 0; i < upto && i < steps.length; i++) {
		const fragment = fragments[i];
		if (!fragment) continue;
		const key = steps[i].op ?? '';
		const list = done.get(key);
		if (list) list.push(fragment);
		else done.set(key, [fragment]);
	}
	const joined = new Map<string, string>();
	for (const [key, list] of done) joined.set(key, list.join(''));
	return joined;
}

/** One contour of the design, in the order the machine walks it. */
export type Contour = {
	/** Its place in the cut order, counted over the design and not over the passes. */
	n: number;
	/** Where the machine starts it. */
	x: number;
	y: number;
	/** When the head sets off for it, the first time. */
	t: number;
	/** The layer it belongs to. */
	op: string | null;
	/** How wide and how tall it is, in millimetres. */
	w: number;
	h: number;
	/** How many times the plan walks it — the passes of its layer. */
	passes: number;
};

/** A number as it can be drawn: where it goes, and how many it stands for. */
export type ContourMark = {
	n: number;
	x: number;
	y: number;
	t: number;
	/** Contours whose own number would have fallen on top of this one. */
	more: number;
};

/** The box a number occupies, in millimetres, relative to the point it labels. */
export type NumberBox = {
	/** Width of one digit. */
	char: number;
	height: number;
	dx: number;
	dy: number;
};

/**
 * The contours of the design, in the order they are cut, one entry each.
 *
 * A contour here is **one continuous burn**: the head arrives somewhere, burns
 * without lifting, and lifts again. That is exactly where the drawing puts a dashed
 * jump, so every number on the picture sits at the end of a dash — and it is what
 * the reader is counting when they ask "does it cut inside before outside".
 *
 * Deliberately *not* the plan's own `first` flag, which was the first attempt. The
 * engine sets it per subpath and it does not mean "a new shape": measured on the
 * gauntlet seed, a circle of r=30 came back as two runs of six segments with the
 * flag on the *second* one, while its first segment carried no flag at all — so the
 * top half of the circle was counted as part of the rectangle before it (a contour
 * of 205 x 80 mm for a rectangle of 120 x 80) and the bottom half got a number of
 * its own. A gap between two steps is unambiguous, and it is the same test
 * `travelPath` draws its dashes from.
 *
 * A pass is not another shape. The plan walks a contour once per pass — measured on
 * the same seed, whose Outline layer has three: numbers 1, 3 and 5 sat at one and
 * the same box (x 406.0, y 192.9) and 2, 4, 6 at another. A repeat is recognised by
 * its start point within its layer (the plan walks a contour the same way every
 * time: three forced rebuilds gave byte-identical step arrays) and only raises
 * `passes`.
 */
export function contours(steps: PathStep[]): Contour[] {
	const found: Contour[] = [];
	// True bounds per contour, kept aside: a contour can run left of and above the
	// point it starts at, so its size is not the distance from its start.
	const bounds: [number, number, number, number][] = [];
	const seen = new Map<string, number>();
	let current = -1;
	let here: [number, number] | null = null;
	const stretch = (index: number, x: number, y: number) => {
		const box = bounds[index];
		box[0] = Math.min(box[0], x);
		box[1] = Math.min(box[1], y);
		box[2] = Math.max(box[2], x);
		box[3] = Math.max(box[3], y);
	};
	for (const step of steps) {
		const start = startOf(step);
		if (start) {
			const arrived = !here || here[0] !== start[0] || here[1] !== start[1];
			if (arrived) {
				const key = `${step.op ?? ''}|${start[0]},${start[1]}`;
				const earlier = seen.get(key);
				if (earlier === undefined) {
					found.push({
						n: found.length + 1,
						x: start[0],
						y: start[1],
						t: step.t0,
						op: step.op ?? null,
						w: 0,
						h: 0,
						passes: 1
					});
					bounds.push([start[0], start[1], start[0], start[1]]);
					current = found.length - 1;
					seen.set(key, current);
				} else {
					found[earlier].passes += 1;
					current = earlier;
				}
			}
		}
		if (current >= 0) {
			// The extent, so the list beside the drawing can say how big a contour is.
			// A raster carries its box; everything else its two ends.
			if (step.k === 'raster' && step.w !== undefined && step.h !== undefined) {
				if (step.x0 !== undefined && step.y0 !== undefined) {
					stretch(current, step.x0, step.y0);
					stretch(current, step.x0 + step.w, step.y0 + step.h);
				}
			} else {
				for (const point of [start, endOf(step)]) if (point) stretch(current, point[0], point[1]);
			}
		}
		here = endOf(step) ?? here;
	}
	return found.map((contour, i) => ({
		...contour,
		w: Math.round((bounds[i][2] - bounds[i][0]) * 100) / 100,
		h: Math.round((bounds[i][3] - bounds[i][1]) * 100) / 100
	}));
}

/**
 * The numbers as they can actually be drawn: one per contour, none on top of
 * another.
 *
 * Two things go wrong without this, both measured on the gauntlet seed (24 numbers,
 * 59 of 276 pairs overlapping, the worst pair covering each other completely).
 * First the passes, which `contours` above already folds away. Second crowding: the
 * eighteen letters of a caption all start inside a band of 96 x 29 px, and eighteen
 * numbers in that band answer nothing. So a number that would land on one already
 * placed is dropped and counted on the one that stayed — the lowest, because the
 * question is which comes *first*.
 *
 * The cap stays as a second line of defence, but it counts contours and crowding is
 * not the same thing: 24 contours were illegible and the cap is 120.
 */
export function contourStarts(
	steps: PathStep[],
	options: { limit?: number; box?: NumberBox } = {}
): ContourMark[] {
	const limit = options.limit ?? 120;
	const box = options.box ?? { char: 2, height: 5, dx: 1, dy: -1 };
	const list = contours(steps);
	if (list.length > limit) return [];
	const placed: ContourMark[] = [];
	const boxes: [number, number, number, number][] = [];
	for (const contour of list) {
		// Room for the suffix a fold adds ("7+15"), because the box is claimed before
		// it is known whether anything folds into it: three characters over the digits
		// of the number itself. Without the allowance the drawn labels overlapped again
		// where the numbers themselves did not — measured 5 overlapping pairs of 21 on
		// the gauntlet seed.
		const width = box.char * (String(contour.n).length + 3);
		const left = contour.x + box.dx;
		const top = contour.y + box.dy - box.height;
		const rect: [number, number, number, number] = [left, top, left + width, top + box.height];
		const clash = boxes.findIndex(
			(other) => rect[0] < other[2] && other[0] < rect[2] && rect[1] < other[3] && other[1] < rect[3]
		);
		if (clash >= 0) {
			placed[clash].more += 1;
			continue;
		}
		placed.push({ n: contour.n, x: contour.x, y: contour.y, t: contour.t, more: 0 });
		boxes.push(rect);
	}
	return placed;
}

/**
 * How many contours the path holds, whether or not they are numbered.
 *
 * The design's contours, not the plan's steps: a layer with three passes walks the
 * same rectangle three times and it is still one contour. Reporting six here was
 * the same mistake as numbering it three times.
 */
export function contourCount(steps: PathStep[]): number {
	return contours(steps).length;
}

/**
 * The share of the time the head spends travelling.
 *
 * The number that answers "where does the head go needlessly": a path where a
 * third of the clock is travel has an order problem, and no drawing says that as
 * quickly as one percentage.
 */
export function travelShare(steps: PathStep[]): number {
	let travelling = 0;
	let total = 0;
	for (const step of steps) {
		travelling += Math.max(0, step.t1 - step.t0);
		total = Math.max(total, step.t2);
	}
	return total > 0 ? travelling / total : 0;
}
