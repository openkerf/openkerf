/**
 * Vastklikken op grid, shapes en randen.
 *
 * Everything here reckons in millimetres, because that is the unit of the bed. The
 * *snap distance* is the one exception: it arrives as millimetres the canvas has
 * converted back from screen pixels. That is how it works in LightBurn (Snap
 * Distance is in pixels, Edit → Settings → Units and Grids) and in Inkscape ("The
 * snap distance is in units of screen pixels"). It is also the only right measure:
 * zoomed in at 400% you want to aim more precisely, not more coarsely, and a fixed
 * margin in mm does exactly the opposite.
 *
 * The module is deliberately free of Svelte and of the DOM: the arithmetic can be
 * checked with loose values, and the canvas only does the conversion and the
 * tekenen.
 */

/**
 * The little word that goes with the guide line.
 *
 * More specific than the source alone: "edge" and "centre" are two very different
 * alignments, and with the centre in particular the answer to "why did it jump
 * there?" cannot otherwise be given.
 */
export type SnapKind =
	| 'grid'
	| 'edge'
	| 'centre'
	| 'bededge'
	| 'bedmidden'
	| 'sheetedge'
	| 'velmidden';

export type SnapTarget = {
	/** The coordinate on the axis being snapped to, in mm. */
	pos: number;
	kind: SnapKind;
	/**
	 * How far the guide line stretches perpendicular to this axis, in mm. With a
	 * shape the line runs from the shape to whatever it snaps to, as in Inkscape; with
	 * grid and bed lines there is nothing to span between and the canvas draws it
	 * across the whole bed.
	 */
	span?: [number, number];
};

export type SnapGuide = {
	axis: 'x' | 'y';
	pos: number;
	kind: SnapKind;
	span?: [number, number];
};

export type SnapHit = { delta: number; guide: SnapGuide };

export type Box = { x: number; y: number; width: number; height: number };

/** A box normalised to min/max, even when it has been scaled negatively. */
function edgesOf(box: Box) {
	return {
		x0: Math.min(box.x, box.x + box.width),
		x1: Math.max(box.x, box.x + box.width),
		y0: Math.min(box.y, box.y + box.height),
		y1: Math.max(box.y, box.y + box.height)
	};
}

/**
 * Snap points of the surroundings: bed, sheet and the boxes of every other shape.
 *
 * Of a shape both the edges *and* the centre count, as in Inkscape (corners,
 * zijmiddens, middelpunt). Alleen randen is te weinig: twee shapes op één
 * centre line is exactly what you cannot manage by hand.
 */
export function surroundingTargets(options: {
	bed: { width: number; height: number };
	sheet?: { width: number; height: number } | null;
	anderen: Box[];
}): { x: SnapTarget[]; y: SnapTarget[] } {
	const { bed, sheet, anderen } = options;
	const x: SnapTarget[] = [
		{ pos: 0, kind: 'bededge' },
		{ pos: bed.width / 2, kind: 'bedmidden' },
		{ pos: bed.width, kind: 'bededge' }
	];
	const y: SnapTarget[] = [
		{ pos: 0, kind: 'bededge' },
		{ pos: bed.height / 2, kind: 'bedmidden' },
		{ pos: bed.height, kind: 'bededge' }
	];

	// The sheet sits in the top-left corner of the bed; its left edge therefore
	// coincides with the bed's and adds nothing.
	if (sheet) {
		if (sheet.width < bed.width - 0.01) {
			x.push({ pos: sheet.width / 2, kind: 'velmidden' }, { pos: sheet.width, kind: 'sheetedge' });
		}
		if (sheet.height < bed.height - 0.01) {
			y.push({ pos: sheet.height / 2, kind: 'velmidden' }, { pos: sheet.height, kind: 'sheetedge' });
		}
	}

	for (const box of anderen) {
		const g = edgesOf(box);
		const langsY: [number, number] = [g.y0, g.y1];
		const langsX: [number, number] = [g.x0, g.x1];
		x.push(
			{ pos: g.x0, kind: 'edge', span: langsY },
			{ pos: (g.x0 + g.x1) / 2, kind: 'centre', span: langsY },
			{ pos: g.x1, kind: 'edge', span: langsY }
		);
		y.push(
			{ pos: g.y0, kind: 'edge', span: langsX },
			{ pos: (g.y0 + g.y1) / 2, kind: 'centre', span: langsX },
			{ pos: g.y1, kind: 'edge', span: langsX }
		);
	}
	return { x, y };
}

/**
 * The best hit for one axis.
 *
 * `candidates` are the points of the moving thing that may snap — on a move the left
 * edge, the centre and the right edge; on a corner handle only that corner. The
 * `delta` returned is added to the movement.
 *
 * A shape, sheet or bed edge beats a grid line at the same distance: the grid is
 * everywhere, so without that preference you would never snap to a shape as soon as
 * it happens to lie beside a grid line.
 */
export function snapAxis(
	as: 'x' | 'y',
	candidates: number[],
	targets: SnapTarget[],
	rasterstap: number,
	trefafstand: number
): SnapHit | null {
	let beste: SnapHit | null = null;
	const beter = (distance: number) => !beste || distance < Math.abs(beste.delta) - 1e-9;

	for (const candidate of candidates) {
		for (const point of targets) {
			const delta = point.pos - candidate;
			if (Math.abs(delta) > trefafstand) continue;
			if (!beter(Math.abs(delta))) continue;
			beste = { delta, guide: { axis: as, pos: point.pos, kind: point.kind, span: point.span } };
		}
	}

	if (rasterstap > 0) {
		for (const candidate of candidates) {
			const line = Math.round(candidate / rasterstap) * rasterstap;
			const delta = line - candidate;
			if (Math.abs(delta) > trefafstand) continue;
			if (!beter(Math.abs(delta))) continue;
			beste = { delta, guide: { axis: as, pos: line, kind: 'grid' } };
		}
	}
	return beste;
}

/**
 * Moving a whole box: edge, centre and edge may each snap, independently per axis.
 * That lets a shape align on the left to one neighbour and on the top to another —
 * the behaviour you expect from a drawing program.
 */
export function snapBox(
	box: Box,
	verplaatsing: { dx: number; dy: number },
	targets: { x: SnapTarget[]; y: SnapTarget[] },
	rasterstap: number,
	trefafstand: number
): { dx: number; dy: number; guides: SnapGuide[] } {
	const g = edgesOf(box);
	const x = snapAxis(
		'x',
		[g.x0 + verplaatsing.dx, (g.x0 + g.x1) / 2 + verplaatsing.dx, g.x1 + verplaatsing.dx],
		targets.x,
		rasterstap,
		trefafstand
	);
	const y = snapAxis(
		'y',
		[g.y0 + verplaatsing.dy, (g.y0 + g.y1) / 2 + verplaatsing.dy, g.y1 + verplaatsing.dy],
		targets.y,
		rasterstap,
		trefafstand
	);
	const guides: SnapGuide[] = [];
	if (x) guides.push(x.guide);
	if (y) guides.push(y.guide);
	return {
		dx: verplaatsing.dx + (x?.delta ?? 0),
		dy: verplaatsing.dy + (y?.delta ?? 0),
		guides
	};
}

/**
 * Snapping one point: a corner handle while scaling, a node, the end of a line, or
 * the place a new shape goes.
 */
export function snapPoint(
	point: { x: number; y: number },
	targets: { x: SnapTarget[]; y: SnapTarget[] },
	rasterstap: number,
	trefafstand: number
): { x: number; y: number; guides: SnapGuide[] } {
	const x = snapAxis('x', [point.x], targets.x, rasterstap, trefafstand);
	const y = snapAxis('y', [point.y], targets.y, rasterstap, trefafstand);
	const guides: SnapGuide[] = [];
	if (x) guides.push(x.guide);
	if (y) guides.push(y.guide);
	return { x: point.x + (x?.delta ?? 0), y: point.y + (y?.delta ?? 0), guides };
}

/** The word beside a guide line. Short, because it sits on the workpiece. */
export const SNAP_LABEL: Record<SnapKind, string> = {
	grid: 'grid',
	edge: 'edge',
	centre: 'centre',
	bededge: 'bededge',
	bedmidden: 'bedmidden',
	sheetedge: 'sheetedge',
	velmidden: 'velmidden'
};
