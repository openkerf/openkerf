/**
 * Eén bron voor "op wat voor scherm zit ik, en wat betekent dat".
 *
 * Gat J9: waar een actie woont verschilde per apparaat, en die afspraak stond
 * op twee plekken. JobControls verborg zijn eigen start/pauze/stop met
 * `@media (max-width: 1199px)`; TopBar toonde de zijne op een JS-prop `tablet`
 * die de pagina uitrekende. Twee getallen voor één regel — en dus twee plekken
 * die uit de pas kunnen lopen, met als slechtste uitkomst dat de pauzeknop op
 * één breedte nergens staat of twee keer.
 *
 * Hier staan de grenzen één keer, en daarnaast de *regels* die eruit volgen.
 * Componenten lezen liever `apparaat.bedieningInBalk` dan `apparaat.tablet`:
 * een regel met een naam legt uit waarom hij bestaat, een breedte niet.
 */

/** Onder deze breedte neemt PhoneView het over. */
export const TELEFOON_MAX = 767;
/** Tot hier is het een tablet; daarboven een werkblad met een muis. */
export const TABLET_MAX = 1199;

function meet(query: string): boolean {
	if (typeof window === 'undefined' || !window.matchMedia) return false;
	return window.matchMedia(query).matches;
}

const TELEFOON = `(max-width: ${TELEFOON_MAX}px)`;
const TABLET = `(min-width: ${TELEFOON_MAX + 1}px) and (max-width: ${TABLET_MAX}px)`;

class Apparaat {
	telefoon = $state(meet(TELEFOON));
	tablet = $state(meet(TABLET));

	get desktop() {
		return !this.telefoon && !this.tablet;
	}

	/**
	 * Dragen starten, pauzeren en stoppen in de bovenbalk?
	 *
	 * Op tablet wel: het rechterpaneel kan ingeklapt zijn en de statusbalk past
	 * op 768 niet met knoppen erbij. De bovenbalk klapt nooit dicht, dus daar
	 * staat de bediening vast. Op de desktop staat ze in het Job-paneel, waar
	 * ook de pre-flight zit.
	 */
	get bedieningInBalk() {
		return this.tablet;
	}

	/** Het omgekeerde, met een eigen naam zodat de lezer niet hoeft te negeren. */
	get bedieningInPaneel() {
		return this.desktop;
	}

	/** Volgen; geeft een opruimfunctie terug. Aanroepen in een `$effect`. */
	volg(): () => void {
		if (typeof window === 'undefined' || !window.matchMedia) return () => {};
		const t = window.matchMedia(TELEFOON);
		const b = window.matchMedia(TABLET);
		const bij = () => {
			this.telefoon = t.matches;
			this.tablet = b.matches;
		};
		bij();
		t.addEventListener('change', bij);
		b.addEventListener('change', bij);
		return () => {
			t.removeEventListener('change', bij);
			b.removeEventListener('change', bij);
		};
	}
}

export const apparaat = new Apparaat();
