/**
 * Rotary arithmetic, without a screen and without a fetch.
 *
 * The API is the authority on what is stored and what gets scaled; these functions exist
 * so that a form can say what a number will do *before* it is sent, and so that the
 * sentence beside the field can be tested under `node --test`. Every one of them mirrors a
 * function in `api/openkerf_api/rotary.py`, which in turn uses the engine's own
 * `rotary_cam.py` — so if the two ever disagree, the tests say which.
 */

/** What the API stores and reports. Mirrors `RotaryControl.state()`. */
export type RotaryState = {
	active: boolean;
	kind: 'chuck' | 'roller';
	diameter_mm: number;
	circumference_mm: number;
	scale_source: 'none' | 'manual' | 'steps';
	manual_scale_y: number;
	flat_steps_per_mm: number;
	rotary_steps_per_mm: number;
	last_calibration: { commanded_mm: number; measured_mm: number; factor: number } | null;
	scale_y: number;
	scale_x: number;
	engine_rotary: boolean;
	overlap?: { work_mm: number; burns_mm: number; circumference_mm: number };
};

/** The state a machine without a rotary has. Also what a server that is away looks like. */
export const ROTARY_OFF: RotaryState = {
	active: false,
	kind: 'chuck',
	diameter_mm: 0,
	circumference_mm: 0,
	scale_source: 'none',
	manual_scale_y: 1,
	flat_steps_per_mm: 0,
	rotary_steps_per_mm: 0,
	last_calibration: null,
	scale_y: 1,
	scale_x: 1,
	engine_rotary: false
};

/** How far it is once round. `Math.PI * d` for a chuck; a roller carries its own number. */
export function circumferenceMm(state: {
	kind: string;
	diameter_mm: number;
	circumference_mm: number;
}): number {
	if (state.kind === 'chuck') {
		return state.diameter_mm > 0 ? Math.PI * state.diameter_mm : 0;
	}
	return state.circumference_mm > 0 ? state.circumference_mm : 0;
}

/**
 * "I meant 100 mm and I measured 96.5" -> the new factor.
 *
 * The engine's `calibrate_rotary_steps`, so the form can show the answer before it is
 * saved: current * commanded / measured. Zero or negative measurements give the factor
 * back unchanged, because there is nothing to learn from them.
 */
export function calibrationFactor(current: number, commandedMm: number, measuredMm: number): number {
	if (!(commandedMm > 0) || !(measuredMm > 0) || !(current > 0)) return current;
	return current * (commandedMm / measuredMm);
}

/** The engine's `y_steps_factor`: flat steps/mm over rotary steps/mm. */
export function stepsFactor(flatStepsPerMm: number, rotaryStepsPerMm: number): number {
	if (!(flatStepsPerMm > 0) || !(rotaryStepsPerMm > 0)) return 1;
	return flatStepsPerMm / rotaryStepsPerMm;
}

/** What a rotary calibration may be. Beyond this it is a resize, and the API refuses it. */
export const SCALE_MIN = 0.5;
export const SCALE_MAX = 2;

export function scaleIsSane(factor: number): boolean {
	return Number.isFinite(factor) && factor >= SCALE_MIN && factor <= SCALE_MAX;
}

/**
 * How tall this job comes off the object, in surface millimetres.
 *
 * The factor is a calibration, so with a rotary that needs none this is the number you
 * drew — and that is the whole point of the convention: the canvas keeps telling the truth.
 */
export function burnedHeightMm(workHeightMm: number, scaleY: number): number {
	return workHeightMm * scaleY;
}

/**
 * Does the work go round once without running into itself?
 *
 * `null` when there is nothing to compare: no work on the bed, or an object whose
 * circumference we do not know. A `false` is the one thing the circumference decides, and
 * it is a warning and not a refusal — you may deliberately burn a band that overlaps.
 */
export function goesRound(
	workHeightMm: number | null | undefined,
	scaleY: number,
	circumference: number
): boolean | null {
	if (!workHeightMm || workHeightMm <= 0 || circumference <= 0) return null;
	return burnedHeightMm(workHeightMm, scaleY) <= circumference;
}
