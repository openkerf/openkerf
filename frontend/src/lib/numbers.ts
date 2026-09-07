/**
 * A number somebody typed, handed on only when it is one — and an answer about whether
 * it was taken.
 *
 * A text field gives back text, and `Number('abc')` is NaN. Measured before this
 * existed: NaN travelled out of the DPI field of a raster layer and came back as that
 * field's own minimum — 500 dpi became 10 on one click of `+`, with no refusal and no
 * notice, and 10 dpi is an engraving you find ruined on the material.
 *
 * The empty box is nothing rather than zero. `Number('')` is 0, and 0 mm/s is a machine
 * standing still with the laser on; a caller that really means to clear a value says so
 * with `whenNumberOrBlank`.
 *
 * The answer is the third part, and it is what a box needs to stand on the truth. Being
 * a number is not the same as being taken: measured on a raster layer at 500 dpi,
 * `1,000` is the number 1 to a box whose comma is a decimal point, the engine refused
 * dpi 1 with a sentence, and the box that kept `"1,000"` standing stepped from 1 to
 * **dpi 11** on one click of `+`. So this says `false` when the value never left, and
 * `false` again when the caller says it did not take it.
 */
export async function whenNumber(
	text: string,
	then: (value: number) => unknown
): Promise<boolean> {
	const value = typedNumber(text);
	if (!Number.isFinite(value)) return false;
	return (await then(value)) !== false;
}

/** The same, for a value that may also be cleared: an empty box arrives as `null`. */
export async function whenNumberOrBlank(
	text: string,
	then: (value: number | null) => unknown
): Promise<boolean> {
	if (text.trim() === '') return (await then(null)) !== false;
	return whenNumber(text, then);
}

/**
 * What a box full of text is worth as a number: nothing and nonsense are both NaN, and a
 * decimal comma reads as a decimal point.
 *
 * Two traps in one function, because every guard in the app needs both. `Number('')` is
 * 0, so a test that only asks `Number.isFinite` calls an empty box a zero — measured, an
 * emptied DPI box and one click of `+` stepped from 0 and committed 10 dpi. And the boxes
 * are `type="text" inputmode="decimal"` precisely so that a reader who writes 12,5 can
 * type it, while `Number('12,5')` is NaN — measured in the Edit card, a width of 40.0 mm
 * typed as `12,5` came silently back as `40.0` and nothing was taken.
 *
 * What it deliberately does not do is judge whether the number is one anybody wants.
 * `1,000` reads as 1 here, and that is a number; whether 1 is a dpi is the engine's
 * question, and `whenNumber` carries its answer back.
 */
export function typedNumber(text: string): number {
	if (text.trim() === '') return Number.NaN;
	return Number(text.replace(',', '.'));
}
