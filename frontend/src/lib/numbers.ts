/**
 * A number somebody typed, handed on only when it is one.
 *
 * A text field gives back text, and `Number('abc')` is NaN. Measured before this
 * existed: NaN travelled out of the DPI field of a raster layer and came back as that
 * field's own minimum — 500 dpi became 10 on one click of `+`, with no refusal and no
 * notice, and 10 dpi is an engraving you find ruined on the material.
 *
 * The empty box is nothing rather than zero. `Number('')` is 0, and 0 mm/s is a machine
 * standing still with the laser on; a caller that really means to clear a value says so
 * with `whenNumberOrBlank`.
 */
export function whenNumber(text: string, then: (value: number) => void): void {
  if (text.trim() === "") return;
  const value = Number(text);
  if (!Number.isFinite(value)) return;
  then(value);
}

/** The same, for a value that may also be cleared: an empty box arrives as `null`. */
export function whenNumberOrBlank(
  text: string,
  then: (value: number | null) => void,
): void {
  if (text.trim() === "") {
    then(null);
    return;
  }
  whenNumber(text, then);
}
