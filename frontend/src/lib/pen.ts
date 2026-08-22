/**
 * The pen's drawing, as numbers — separate from the canvas that shows it.
 *
 * The pen has two jobs that must agree exactly: draw the line you are making, and hand
 * the same line to the API when you finish. Before this the second was `[x, y]` pairs and
 * the first a polyline, so a curve could not be drawn at all — the only way to get one
 * into OpenKerf was to import it.
 *
 * A point carries its **outgoing** handle, because that is what a drag makes: press,
 * pull, and the handle you see is the one leaving the point. The handle on the other side
 * is its mirror, so a point stays smooth — which is what a pen is for. A point without a
 * handle is a corner.
 *
 * The API reads a point's numbers as the segment *arriving* at it, exactly like SVG path
 * data (`C c1 c2 end`). Converting is therefore this file's whole job, and it is here and
 * not in the component so that a test can check it without a browser.
 */

/** A point of the line under construction. `handle` is an absolute place on the bed. */
export type PenPoint = { x: number; y: number; handle: { x: number; y: number } | null };

/** The mirror of a point's handle: the one the arriving segment uses. */
function incoming(point: PenPoint): { x: number; y: number } {
	if (!point.handle) return { x: point.x, y: point.y };
	return { x: 2 * point.x - point.handle.x, y: 2 * point.y - point.handle.y };
}

function outgoing(point: PenPoint): { x: number; y: number } {
	return point.handle ?? { x: point.x, y: point.y };
}

/**
 * The points for `POST /api/design/path`.
 *
 * A segment between two corners stays a straight line: two numbers. As soon as either end
 * has a handle it becomes a cubic, and the straight end simply puts its control on itself
 * — a cubic with a control on its own anchor leaves along the chord, which is exactly what
 * "this end is a corner" looks like.
 */
export function penPath(points: PenPoint[], closed: boolean): number[][] {
	if (points.length < 2) return [];
	const pairs: [PenPoint, PenPoint][] = [];
	for (let i = 1; i < points.length; i += 1) pairs.push([points[i - 1], points[i]]);
	if (closed) pairs.push([points[points.length - 1], points[0]]);

	// The first point never describes a segment of its own, unless the path closes: then
	// the last segment is the one arriving at it.
	const out: number[][] = [[points[0].x, points[0].y]];
	for (const [from, to] of pairs) {
		if (!from.handle && !to.handle) {
			out.push([to.x, to.y]);
			continue;
		}
		const c1 = outgoing(from);
		const c2 = incoming(to);
		out.push([to.x, to.y, c1.x, c1.y, c2.x, c2.y]);
	}
	// The closing segment's numbers belong to the first point; it is the only segment that
	// arrives there.
	if (closed) {
		const closing = out.pop();
		if (closing) out[0] = [points[0].x, points[0].y, ...closing.slice(2)];
	}
	return out;
}

/**
 * The same line as SVG path data, for the preview on the bed.
 *
 * Built from the same numbers the API will get, so what you see while drawing is what
 * lands. `hover` is where the pointer is now: the piece you have not clicked yet.
 */
export function penPreview(points: PenPoint[], hover: PenPoint | null, closed = false): string {
	const all = hover ? [...points, hover] : points;
	if (!all.length) return '';
	const rows = penPath(all, closed);
	if (rows.length < 2) return `M ${all[0].x} ${all[0].y}`;
	let d = `M ${rows[0][0]} ${rows[0][1]}`;
	for (const row of rows.slice(1)) {
		d +=
			row.length === 6
				? ` C ${row[2]} ${row[3]} ${row[4]} ${row[5]} ${row[0]} ${row[1]}`
				: ` L ${row[0]} ${row[1]}`;
	}
	if (closed) {
		const first = rows[0];
		d +=
			first.length === 6
				? ` C ${first[2]} ${first[3]} ${first[4]} ${first[5]} ${first[0]} ${first[1]} Z`
				: ' Z';
	}
	return d;
}

/**
 * Is this drag long enough to mean a curve?
 *
 * Four screen pixels: measured, a click on a trackpad moves one or two pixels between
 * press and release, and at two pixels every corner came out slightly bent.
 */
export const HANDLE_THRESHOLD_PX = 4;
