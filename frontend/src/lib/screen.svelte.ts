/**
 * One source for "what kind of screen am I on, and what does that mean".
 *
 * Gap J9: where an action lived differed per screen, and that agreement was in
 * two places. JobControls hid its own start/pause/stop with
 * `@media (max-width: 1199px)`; TopBar showed its own on a JS prop `tablet` the
 * page worked out. Two numbers for one rule — and therefore two places that can
 * drift, with the worst outcome being that the pause button sits nowhere at one
 * width, or twice.
 *
 * The bounds are here once, and beside them the *rules* that follow from them.
 * Components would rather read `screen.controlsInBar` than `screen.tablet`: a rule
 * with a name explains why it exists, a width does not.
 */

/** Below this width PhoneView takes over. */
export const PHONE_MAX = 767;
/** Up to here it is a tablet; above it a desk with a mouse. */
export const TABLET_MAX = 1199;

function matches(query: string): boolean {
	if (typeof window === 'undefined' || !window.matchMedia) return false;
	return window.matchMedia(query).matches;
}

const PHONE = `(max-width: ${PHONE_MAX}px)`;
const TABLET = `(min-width: ${PHONE_MAX + 1}px) and (max-width: ${TABLET_MAX}px)`;

class Screen {
	phone = $state(matches(PHONE));
	tablet = $state(matches(TABLET));

	get desktop() {
		return !this.phone && !this.tablet;
	}

	/**
	 * Do start, pause and stop live in the top bar?
	 *
	 * On a tablet they do: the right-hand panel can be collapsed and the status bar
	 * does not fit buttons at 768. The top bar never folds shut, so that is where
	 * the controls stay put. On the desktop they are in the Job panel, where the
	 * preflight is too.
	 */
	get controlsInBar() {
		return this.tablet;
	}

	/** The other way round, with a name of its own so the reader need not negate. */
	get controlsInPanel() {
		return this.desktop;
	}

	/** Follow along; returns a cleanup function. Call it inside an `$effect`. */
	follow(): () => void {
		if (typeof window === 'undefined' || !window.matchMedia) return () => {};
		const phone = window.matchMedia(PHONE);
		const tablet = window.matchMedia(TABLET);
		const update = () => {
			this.phone = phone.matches;
			this.tablet = tablet.matches;
		};
		update();
		phone.addEventListener('change', update);
		tablet.addEventListener('change', update);
		return () => {
			phone.removeEventListener('change', update);
			tablet.removeEventListener('change', update);
		};
	}
}

export const screen = new Screen();
