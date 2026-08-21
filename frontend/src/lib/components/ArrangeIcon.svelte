<script lang="ts">
	/**
	 * De pictogrammen voor schikken: uitlijnen, verdelen, spiegelen, groeperen
	 * en combineren.
	 *
	 * Ze zijn met opzet allemaal volgens dezelfde grammatica getekend, want dat
	 * is wat een icoon sneller leesbaar maakt dan een woord: een **dikke lijn**
	 * is de as waarnaar iets zich schikt, **open rechthoeken** zijn de vormen
	 * die verschuiven, en een **stippellijn** is een spiegelas — een as waar
	 * niets tegenaan gaat staan, maar waar doorheen gekeken wordt. Wie de
	 * grammatica één keer ziet, leest de rest zonder tooltip.
	 *
	 * Dezelfde grammatica gebruiken Inkscape, Illustrator en LightBurn (zie
	 * `Icon-Align-All.png` in hun documentatie). Afwijken zou betekenen dat een
	 * gebruiker die uit een van die drie komt opnieuw moet leren kijken.
	 */
	let { name, size = 20 }: { name: string; size?: number } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.6"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#if name === 'align-left'}
		<path d="M3 3v18" stroke-width="2.4" />
		<rect x="6" y="5" width="15" height="5.5" rx="1" />
		<rect x="6" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-centerh'}
		<path d="M12 2v20" stroke-width="2.4" stroke-dasharray="0 0" />
		<rect x="3.5" y="5" width="17" height="5.5" rx="1" />
		<rect x="7.5" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-right'}
		<path d="M21 3v18" stroke-width="2.4" />
		<rect x="3" y="5" width="15" height="5.5" rx="1" />
		<rect x="9" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-top'}
		<path d="M3 3h18" stroke-width="2.4" />
		<rect x="5" y="6" width="5.5" height="15" rx="1" />
		<rect x="13.5" y="6" width="5.5" height="9" rx="1" />
	{:else if name === 'align-centerv'}
		<path d="M2 12h20" stroke-width="2.4" />
		<rect x="5" y="3.5" width="5.5" height="17" rx="1" />
		<rect x="13.5" y="7.5" width="5.5" height="9" rx="1" />
	{:else if name === 'align-bottom'}
		<path d="M3 21h18" stroke-width="2.4" />
		<rect x="5" y="3" width="5.5" height="15" rx="1" />
		<rect x="13.5" y="9" width="5.5" height="9" rx="1" />
	{:else if name === 'space-h'}
		<!-- Verdelen: buitenste twee staan vast (dikke randen), de middelste
		     schuift tot de tussenruimtes gelijk zijn. De vormen zijn breder dan
		     in de eerste versie — drie smalle staafjes lazen als stippen. -->
		<path d="M2 5v14M22 5v14" stroke-width="2.4" />
		<rect x="4.5" y="7.5" width="4.5" height="9" rx="1" />
		<rect x="12" y="7.5" width="4.5" height="9" rx="1" />
	{:else if name === 'space-v'}
		<path d="M5 2h14M5 22h14" stroke-width="2.4" />
		<rect x="7.5" y="4.5" width="9" height="4.5" rx="1" />
		<rect x="7.5" y="12" width="9" height="4.5" rx="1" />
	{:else if name === 'mirror-h'}
		<!-- Spiegelen: de stippellijn is de as en steekt bewust uit boven en
		     onder de vormen, zodat hij als as leest en niet als rand. De linker
		     helft is gevuld: dan zie je wélke kant om klapt. Kleiner getekend
		     dan de eerste versie, want twee driehoeken tegen elkaar aan lazen
		     als één donkere ruit. -->
		<path d="M12 2v20" stroke-dasharray="3 3" />
		<path d="M9 6.5 4 12l5 5.5Z" fill="currentColor" stroke="none" />
		<path d="M15 6.5 20 12l-5 5.5Z" />
	{:else if name === 'mirror-v'}
		<path d="M2 12h20" stroke-dasharray="3 3" />
		<path d="M6.5 9 12 4l5.5 5Z" fill="currentColor" stroke="none" />
		<path d="M6.5 15 12 20l5.5-5Z" />
	{:else if name === 'group'}
		<!-- Groeperen versus opheffen: het verschil moet in de vórm zitten, niet
		     in een streepje. Groeperen = twee vormen die elkaar raken, met één
		     kader eromheen. Opheffen = dezelfde twee vormen uit elkaar, zonder
		     kader, met pijltjes die uiteen wijzen. -->
		<rect x="2.5" y="2.5" width="19" height="19" rx="2.5" stroke-dasharray="4 3" />
		<rect x="6" y="6" width="7.5" height="7.5" rx="1" />
		<rect x="11" y="11" width="7" height="7" rx="1" />
	{:else if name === 'ungroup'}
		<rect x="2" y="2" width="8.5" height="8.5" rx="1" />
		<rect x="13.5" y="13.5" width="8.5" height="8.5" rx="1" />
		<path d="M13.5 10.5 21 3" />
		<path d="M15.5 3H21v5.5" />
		<!-- Booleaans: twee vierkanten die elkaar overlappen, met het resultaat
		     gearceerd. Het gat wordt met `fill-rule="evenodd"` uit de vorm
		     gesneden en niet met een vlakje in de achtergrondkleur overgeschilderd
		     — dat last klopt alleen zolang de knop niet van kleur verandert,
		     en bij hover doet hij dat. -->
	{:else if name === 'union'}
		<path
			d="M3 3h12v6h6v12H9v-6H3Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M3 3h12v12H3Z" opacity="0.45" />
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M3 3h12v6h6v12H9v-6H3Z" />
	{:else if name === 'difference'}
		<path
			fill-rule="evenodd"
			d="M3 3h12v12H3Zm6 6h6v6H9Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M3 3h12v12H3Z" />
	{:else if name === 'intersection'}
		<path d="M9 9h6v6H9Z" fill="currentColor" opacity="0.45" stroke="none" />
		<path d="M3 3h12v12H3Z" opacity="0.45" />
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M9 9h6v6H9Z" />
	{:else if name === 'xor'}
		<path
			fill-rule="evenodd"
			d="M3 3h12v6h6v12H9v-6H3Zm6 6h6v6H9Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M3 3h12v6h6v12H9v-6H3Z" />
		<path d="M9 9h6v6H9Z" />
	{:else if name === 'rotate-ccw'}
		<path d="M4 9a8 8 0 1 1 .6 6" />
		<path d="M3.5 4v5h5" />
	{:else if name === 'rotate-cw'}
		<path d="M20 9a8 8 0 1 0-.6 6" />
		<path d="M20.5 4v5h-5" />
	{:else if name === 'undo'}
		<path d="M4 8h11a5 5 0 0 1 0 10H8" />
		<path d="M8 4 4 8l4 4" />
	{:else if name === 'redo'}
		<path d="M20 8H9a5 5 0 0 0 0 10h7" />
		<path d="m16 4 4 4-4 4" />
	{:else if name === 'restore'}
		<path d="M3 12a9 9 0 1 0 3-6.7" />
		<path d="M3 3v5h5" />
		<path d="M12 8v4.5l3 1.8" />
	{/if}
</svg>
