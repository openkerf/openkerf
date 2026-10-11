/**
 * What a drag box on the bed selects, and which shape a click under a pile takes.
 *
 * Pure functions, so the rules can be measured without a browser
 * (`frontend/tests/selecting.test.ts`). The canvas reads them; it does no sums of its own.
 *
 * The convention is the one CAD programs and LightBurn share:
 *
 * - dragged **left to right** the box is a *window*: only shapes lying entirely inside it
 *   are selected. Drawn with a solid edge.
 * - dragged **right to left** it is a *crossing* box: every shape it touches is selected.
 *   Drawn with a dashed edge.
 *
 * "Touches" means the drawn geometry, not the shape's bounding box. An outline is a line
 * (see the hit zone in `Canvas.svelte`), so a box drawn in the empty middle of a rectangle
 * touches nothing of that rectangle. Before this, the test was the overlap of two
 * bounding boxes, so a box around the text inside a cut outline always took the outline
 * with it — whichever way you dragged.
 */

export type BandMode = 'window' | 'crossing';

/** A box in whatever units the caller measures in; x0 ≤ x1, y0 ≤ y1. */
export interface Box {
	x0: number;
	y0: number;
	x1: number;
	y1: number;
}

/** What the box needs to know about one element. Coordinates in the same units as the box. */
export interface Selectable {
	id: string;
	/** [x0, y0, x1, y1]. */
	bounds: [number, number, number, number] | number[] | null;
	/** The SVG path data the canvas draws; absent for an image. */
	path?: string | null;
	/** Burned as an area (a filled shape on a raster layer) or an image: the face counts. */
	face?: boolean;
	hidden?: boolean;
	group_id?: string | null;
}

/** Window when dragged to the right, crossing when dragged to the left. */
export function bandMode(fromX: number, toX: number): BandMode {
	return toX < fromX ? 'crossing' : 'window';
}

/** The box spanned by two corners, normalised. */
export function boxOf(x1: number, y1: number, x2: number, y2: number): Box {
	return {
		x0: Math.min(x1, x2),
		y0: Math.min(y1, y2),
		x1: Math.max(x1, x2),
		y1: Math.max(y1, y2)
	};
}

/** How finely a curve is cut into straight pieces for the touch test. */
const CURVE_STEPS = 16;

/**
 * Path data as polylines, one per subpath, curves flattened.
 *
 * Handles the whole SVG path grammar (absolute and relative M L H V C S Q T A Z), since
 * the engine writes what `svgelements` writes and that is not limited to M L C.
 */
export function flatten(d: string): number[][][] {
	const tokens = d.match(/[a-df-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/gi) ?? [];
	const out: number[][][] = [];
	let line: number[][] = [];
	let i = 0;
	let cmd = '';
	let x = 0;
	let y = 0;
	let sx = 0;
	let sy = 0;
	// The last control point, for S and T.
	let cx = 0;
	let cy = 0;
	let prev = '';
	const num = () => Number(tokens[i++]);
	const isCmd = (t: string | undefined) => t !== undefined && /^[a-z]$/i.test(t);
	const push = (px: number, py: number) => line.push([px, py]);
	const close = () => {
		if (line.length) out.push(line);
		line = [];
	};
	while (i < tokens.length) {
		if (isCmd(tokens[i])) cmd = tokens[i++];
		else if (!cmd) {
			i++;
			continue;
		}
		const rel = cmd === cmd.toLowerCase();
		const ox = rel ? x : 0;
		const oy = rel ? y : 0;
		const up = cmd.toUpperCase();
		if (up === 'Z') {
			if (line.length) push(sx, sy);
			close();
			x = sx;
			y = sy;
			prev = 'Z';
			// Z takes no numbers; a number after it would be malformed.
			cmd = '';
			continue;
		}
		if (i >= tokens.length || isCmd(tokens[i])) {
			// A command without its numbers: nothing to draw.
			continue;
		}
		if (up === 'M') {
			close();
			x = ox + num();
			y = oy + num();
			sx = x;
			sy = y;
			push(x, y);
			// Further pairs after a moveto are linetos.
			cmd = rel ? 'l' : 'L';
		} else if (up === 'L') {
			x = ox + num();
			y = oy + num();
			push(x, y);
		} else if (up === 'H') {
			x = ox + num();
			push(x, y);
		} else if (up === 'V') {
			y = oy + num();
			push(x, y);
		} else if (up === 'C' || up === 'S') {
			let x1: number;
			let y1: number;
			if (up === 'C') {
				x1 = ox + num();
				y1 = oy + num();
			} else if (prev === 'C' || prev === 'S') {
				x1 = 2 * x - cx;
				y1 = 2 * y - cy;
			} else {
				x1 = x;
				y1 = y;
			}
			const x2 = ox + num();
			const y2 = oy + num();
			const ex = ox + num();
			const ey = oy + num();
			for (let k = 1; k <= CURVE_STEPS; k++) {
				const t = k / CURVE_STEPS;
				const u = 1 - t;
				push(
					u * u * u * x + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * ex,
					u * u * u * y + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * ey
				);
			}
			cx = x2;
			cy = y2;
			x = ex;
			y = ey;
		} else if (up === 'Q' || up === 'T') {
			let x1: number;
			let y1: number;
			if (up === 'Q') {
				x1 = ox + num();
				y1 = oy + num();
			} else if (prev === 'Q' || prev === 'T') {
				x1 = 2 * x - cx;
				y1 = 2 * y - cy;
			} else {
				x1 = x;
				y1 = y;
			}
			const ex = ox + num();
			const ey = oy + num();
			for (let k = 1; k <= CURVE_STEPS; k++) {
				const t = k / CURVE_STEPS;
				const u = 1 - t;
				push(u * u * x + 2 * u * t * x1 + t * t * ex, u * u * y + 2 * u * t * y1 + t * t * ey);
			}
			cx = x1;
			cy = y1;
			x = ex;
			y = ey;
		} else if (up === 'A') {
			const rx = num();
			const ry = num();
			const phi = num();
			const large = num();
			const sweep = num();
			const ex = ox + num();
			const ey = oy + num();
			for (const p of arcPoints(x, y, rx, ry, phi, large !== 0, sweep !== 0, ex, ey)) push(p[0], p[1]);
			x = ex;
			y = ey;
		} else {
			// Unknown command: skip one token so the loop always advances.
			i++;
		}
		prev = up;
	}
	close();
	return out;
}

/** An elliptical arc in endpoint form, as points after the start (SVG 1.1, F.6.5). */
function arcPoints(
	x1: number,
	y1: number,
	rx: number,
	ry: number,
	phiDeg: number,
	large: boolean,
	sweep: boolean,
	x2: number,
	y2: number
): number[][] {
	rx = Math.abs(rx);
	ry = Math.abs(ry);
	if (!rx || !ry || (x1 === x2 && y1 === y2)) return [[x2, y2]];
	const phi = (phiDeg * Math.PI) / 180;
	const cos = Math.cos(phi);
	const sin = Math.sin(phi);
	const dx = (x1 - x2) / 2;
	const dy = (y1 - y2) / 2;
	const px = cos * dx + sin * dy;
	const py = -sin * dx + cos * dy;
	const lambda = (px * px) / (rx * rx) + (py * py) / (ry * ry);
	if (lambda > 1) {
		rx *= Math.sqrt(lambda);
		ry *= Math.sqrt(lambda);
	}
	const num = rx * rx * ry * ry - rx * rx * py * py - ry * ry * px * px;
	const den = rx * rx * py * py + ry * ry * px * px;
	let co = Math.sqrt(Math.max(0, num / den));
	if (large === sweep) co = -co;
	const cxp = (co * rx * py) / ry;
	const cyp = (-co * ry * px) / rx;
	const ccx = cos * cxp - sin * cyp + (x1 + x2) / 2;
	const ccy = sin * cxp + cos * cyp + (y1 + y2) / 2;
	const angle = (ux: number, uy: number, vx: number, vy: number) =>
		Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
	const t1 = angle(1, 0, (px - cxp) / rx, (py - cyp) / ry);
	let dt = angle((px - cxp) / rx, (py - cyp) / ry, (-px - cxp) / rx, (-py - cyp) / ry);
	if (!sweep && dt > 0) dt -= 2 * Math.PI;
	if (sweep && dt < 0) dt += 2 * Math.PI;
	const steps = Math.max(4, Math.ceil((Math.abs(dt) / (Math.PI / 2)) * CURVE_STEPS));
	const pts: number[][] = [];
	for (let k = 1; k <= steps; k++) {
		const t = t1 + (dt * k) / steps;
		const ex = rx * Math.cos(t);
		const ey = ry * Math.sin(t);
		pts.push([cos * ex - sin * ey + ccx, sin * ex + cos * ey + ccy]);
	}
	pts[pts.length - 1] = [x2, y2];
	return pts;
}

function inBox(b: Box, x: number, y: number): boolean {
	return x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1;
}

/** Whether segment (ax,ay)-(bx,by) touches the box: Liang–Barsky clipping. */
export function segmentTouchesBox(b: Box, ax: number, ay: number, bx: number, by: number): boolean {
	if (inBox(b, ax, ay) || inBox(b, bx, by)) return true;
	const dx = bx - ax;
	const dy = by - ay;
	let t0 = 0;
	let t1 = 1;
	const edges: [number, number][] = [
		[-dx, ax - b.x0],
		[dx, b.x1 - ax],
		[-dy, ay - b.y0],
		[dy, b.y1 - ay]
	];
	for (const [p, q] of edges) {
		if (p === 0) {
			if (q < 0) return false;
			continue;
		}
		const r = q / p;
		if (p < 0) {
			if (r > t1) return false;
			if (r > t0) t0 = r;
		} else {
			if (r < t0) return false;
			if (r < t1) t1 = r;
		}
	}
	return t0 <= t1;
}

/** Non-zero winding: the same fill rule the canvas paints a face with. */
function insideFace(lines: number[][][], x: number, y: number): boolean {
	let winding = 0;
	for (const line of lines) {
		for (let k = 0; k < line.length; k++) {
			const [ax, ay] = line[k];
			const [bx, by] = line[(k + 1) % line.length];
			if (ay <= y) {
				if (by > y && (bx - ax) * (y - ay) - (x - ax) * (by - ay) > 0) winding++;
			} else if (by <= y && (bx - ax) * (y - ay) - (x - ax) * (by - ay) < 0) winding--;
		}
	}
	return winding !== 0;
}

function boundsOf(element: Selectable): Box | null {
	const b = element.bounds;
	if (!b || b.length < 4) return null;
	return { x0: b[0], y0: b[1], x1: b[2], y1: b[3] };
}

/** Lies entirely inside the box. */
export function enclosed(box: Box, element: Selectable): boolean {
	const b = boundsOf(element);
	if (!b) return false;
	return b.x0 >= box.x0 && b.x1 <= box.x1 && b.y0 >= box.y0 && b.y1 <= box.y1;
}

/**
 * The box touches what is drawn of the element.
 *
 * An outline is touched when one of its lines runs through the box. A face (a filled
 * shape on a raster layer, an image) is touched as well when the box lies on that face.
 */
export function touched(box: Box, element: Selectable): boolean {
	const b = boundsOf(element);
	if (!b) return false;
	if (b.x0 > box.x1 || b.x1 < box.x0 || b.y0 > box.y1 || b.y1 < box.y0) return false;
	// Fully inside is touched, whatever the geometry.
	if (enclosed(box, element)) return true;
	if (!element.path) return Boolean(element.face);
	const lines = flatten(element.path);
	for (const line of lines) {
		if (line.length === 1 && inBox(box, line[0][0], line[0][1])) return true;
		for (let k = 1; k < line.length; k++) {
			if (segmentTouchesBox(box, line[k - 1][0], line[k - 1][1], line[k][0], line[k][1])) return true;
		}
	}
	// No line crosses the box, so the box lies wholly inside or wholly outside the face:
	// one corner decides.
	return Boolean(element.face) && insideFace(lines, box.x0, box.y0);
}

/**
 * The ids a drag box selects.
 *
 * Hidden shapes are left out. In window mode a group counts only when all its visible
 * members lie inside, because selecting one member selects the whole group and a window
 * promises only what it encloses.
 */
export function bandSelection(box: Box, mode: BandMode, elements: Selectable[]): string[] {
	const visible = elements.filter((e) => !e.hidden && e.bounds);
	const test = mode === 'window' ? enclosed : touched;
	const hit = new Set(visible.filter((e) => test(box, e)).map((e) => e.id));
	if (mode === 'window') {
		for (const e of visible) {
			if (e.group_id && !hit.has(e.id)) {
				for (const other of visible) if (other.group_id === e.group_id) hit.delete(other.id);
			}
		}
	}
	return visible.filter((e) => hit.has(e.id)).map((e) => e.id);
}

function segmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
	const dx = bx - ax;
	const dy = by - ay;
	const len = dx * dx + dy * dy;
	const t = len ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len)) : 0;
	return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/**
 * How far the pointer is from what is drawn of the element: 0 on a face, otherwise the
 * distance to the nearest line. An element without a path (an image) is all face.
 */
export function distanceTo(element: Selectable, x: number, y: number): number {
	const b = boundsOf(element);
	if (!element.path) {
		if (!b) return Infinity;
		return Math.hypot(Math.max(b.x0 - x, 0, x - b.x1), Math.max(b.y0 - y, 0, y - b.y1));
	}
	const lines = flatten(element.path);
	if (element.face && insideFace(lines, x, y)) return 0;
	let best = Infinity;
	for (const line of lines) {
		if (line.length === 1) best = Math.min(best, Math.hypot(x - line[0][0], y - line[0][1]));
		for (let k = 1; k < line.length; k++) {
			best = Math.min(best, segmentDistance(x, y, line[k - 1][0], line[k - 1][1], line[k][0], line[k][1]));
		}
	}
	return best;
}

function area(element: Selectable): number {
	const b = boundsOf(element);
	return b ? (b.x1 - b.x0) * (b.y1 - b.y0) : Infinity;
}

/**
 * The shape a plain click takes from the pile under the pointer.
 *
 * `stack` is every shape whose hit zone is under the pointer, topmost first, as
 * `elementsFromPoint` gives it. The hit zone of an outline is a few pixels wider than its
 * line, so the pile can hold shapes the pointer is merely *near*. The one actually under
 * the pointer wins: nearest drawn geometry first (0 on a face), where `slack` (in the
 * same units, about a pixel) counts as the same distance. Between shapes that are equally
 * near, the smallest wins, then the topmost.
 *
 * So the text inside a cut outline is taken even where the outline's hit zone lies over
 * its letters, and a hole drawn on a filled panel is taken when you click its line.
 */
export function pickAt(stack: Selectable[], x: number, y: number, slack: number): string | null {
	let best: Selectable | null = null;
	let bestDistance = Infinity;
	let bestArea = Infinity;
	for (const element of stack) {
		const d = distanceTo(element, x, y);
		const a = area(element);
		const nearer = d < bestDistance - slack;
		const asNear = Math.abs(d - bestDistance) <= slack;
		if (!best || nearer || (asNear && a < bestArea)) {
			best = element;
			bestDistance = Math.min(d, bestDistance);
			bestArea = a;
		}
	}
	return best?.id ?? null;
}
