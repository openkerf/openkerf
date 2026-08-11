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
	nuProberen: (() => {}) as () => void
});
