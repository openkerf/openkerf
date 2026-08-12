/**
 * Eén waarheid over "doet de server het nog".
 *
 * De statusverbinding weet het (haar WebSocket valt weg), maar de knoppen die
 * erop moeten reageren zitten in componenten die die verbinding niet krijgen
 * doorgegeven — en het doorlussen van een vlaggetje langs vijf componenten
 * raakt bestanden die van andere mensen zijn. Vandaar één module die iedereen
 * mag lezen: wie iets naar de server stuurt kijkt hier eerst.
 *
 * Waarom dit ertoe doet: zonder dit bleven Stop, Pauze en Home er volledig
 * bedienbaar uitzien nadat de server was weggevallen. Iemand naast de machine
 * drukt op Stop, ziet geen enkele reactie, en gelooft dat de machine stopt.
 */

export const verbinding = $state({
	/** Is de OpenKerf-server bereikbaar? */
	online: true,
	/** Sinds wanneer niet meer (ms sinds epoch), voor "al 2 minuten weg". */
	sinds: null as number | null,
	/** Seconden tot de volgende poging; 0 = we proberen nu. */
	overSeconden: 0,
	/** Nu opnieuw proberen, in plaats van de backoff af te wachten. */
	nuProberen: (() => {}) as () => void,
	/**
	 * De server is herstart sinds deze pagina geladen werd (gat E2).
	 *
	 * De socket verbindt vanzelf terug en de balk wordt weer groen, maar de
	 * engine erachter heeft een lege elementenboom: het ontwerp dat je op het
	 * scherm ziet bestaat aan de andere kant niet meer. Alles wat je daarna
	 * doet gaat over niets. Dat mag niet stil gebeuren, en het mag ook niet
	 * vanzelf herladen — dat gooit werk weg zonder dat iemand erom vroeg. Dus
	 * één vlag, één zin, één knop.
	 */
	herstart: false
});
