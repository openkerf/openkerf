<script lang="ts">
	/**
	 * De vorm naast het formulier dat hem maakt.
	 *
	 * Een parameter zonder beeld is een gok: "vinger 10 mm" begrijp je niet
	 * zonder eerst hout te verbranden. Dit is geen versiering maar de uitleg —
	 * de alinea's eronder mogen erdoor krimpen. Zie DESIGN-SYSTEM v3,
	 * "Een formulier dat vorm maakt, toont die vorm".
	 *
	 * De tekening is schematisch, niet op schaal: hij laat de verhoudingen en
	 * de betekenis van elk veld zien, niet het eindresultaat in millimeters.
	 */
	let {
		soort,
		waarden,
		children
	}: {
		soort: string;
		/** De ruwe formuliervelden; alles is tekst omdat het uit invoervelden komt. */
		waarden: Record<string, unknown>;
		children?: import('svelte').Snippet;
	} = $props();

	function n(sleutel: string, standaard: number): number {
		const v = Number(waarden[sleutel]);
		return Number.isFinite(v) && v !== 0 ? v : standaard;
	}

	// --- herhalen: kolommen, rijen en de ruimte ertussen
	let kolommen = $derived(Math.min(6, Math.max(1, Math.round(n('columns', 4)))));
	let rijen = $derived(Math.min(6, Math.max(1, Math.round(n('rows', 3)))));

	// --- cirkel: hoeveel kopieën rond het midden
	let herhalingen = $derived(Math.min(16, Math.max(2, Math.round(n('repeats', 8)))));
	let draait = $derived(waarden.rotate !== false);

	// --- veelhoek
	let hoeken = $derived(Math.min(12, Math.max(3, Math.round(n('corners', 6)))));
	let ster = $derived(Number(waarden.inner) > 0);

	// --- doos
	let deksel = $derived(waarden.lid !== false);

	function veelhoekPunten(zijden: number, straal: number, binnen: number) {
		const punten: string[] = [];
		const totaal = binnen ? zijden * 2 : zijden;
		for (let i = 0; i < totaal; i++) {
			const r = binnen && i % 2 ? binnen : straal;
			const hoek = (i / totaal) * Math.PI * 2 - Math.PI / 2;
			punten.push(`${(50 + Math.cos(hoek) * r).toFixed(1)},${(50 + Math.sin(hoek) * r).toFixed(1)}`);
		}
		return punten.join(' ');
	}
</script>

<figure class="proef">
	<svg viewBox="0 0 100 100" role="img" aria-label="Schets van wat deze generator maakt">
		{#if soort === 'grid'}
			{#each Array(rijen) as _, r}
				{#each Array(kolommen) as _, c}
					<rect
						x={12 + c * (76 / kolommen)}
						y={12 + r * (76 / rijen)}
						width={76 / kolommen - 76 / kolommen / 4}
						height={76 / rijen - 76 / rijen / 4}
						class="vorm"
					/>
				{/each}
			{/each}
			<!-- De maat die verwarring geeft: de ruimte tússen de vormen. -->
			{#if kolommen > 1}
				<line class="maat" x1={12 + 76 / kolommen - 76 / kolommen / 4} y1="8" x2={12 + 76 / kolommen} y2="8" />
				<text class="bij" x={12 + 76 / kolommen - 76 / kolommen / 8} y="6">ruimte</text>
			{/if}
		{:else if soort === 'radial'}
			<circle class="hulp" cx="50" cy="50" r="32" />
			{#each Array(herhalingen) as _, i}
				{@const hoek = (i / herhalingen) * Math.PI * 2 - Math.PI / 2}
				<rect
					class="vorm"
					x={50 + Math.cos(hoek) * 32 - 5}
					y={50 + Math.sin(hoek) * 32 - 3.5}
					width="10"
					height="7"
					transform={draait
						? `rotate(${(i / herhalingen) * 360} ${50 + Math.cos(hoek) * 32} ${50 + Math.sin(hoek) * 32})`
						: undefined}
				/>
			{/each}
		{:else if soort === 'polygon'}
			<polygon class="vorm" points={veelhoekPunten(hoeken, 34, ster ? 17 : 0)} />
		{:else if soort === 'box'}
			<!-- Isometrische doos met de drie maten en de vingerlassen op de rand. -->
			<g class="vorm">
				<path d="M22 42 L50 28 L78 42 L50 56 Z" />
				<path d="M22 42 v22 l28 14 v-22" />
				<path d="M78 42 v22 l-28 14" />
				{#if !deksel}
					<path class="hulp" d="M28 39 L50 28 L72 39" stroke-dasharray="3 2" />
				{/if}
			</g>
			<g class="tanden">
				<path d="M26 62 v6 M33 65.5 v6 M40 69 v6" />
			</g>
			<g class="bemating">
				<path d="M22 88 H50 M50 88 H78" />
				<text class="bij" x="30" y="95">breedte</text>
				<text class="bij" x="58" y="95">diepte</text>
				<text class="bij" x="82" y="60">hoogte</text>
				<text class="bij tand" x="16" y="82">vinger</text>
			</g>
		{:else if soort === 'arctext'}
			<path class="hulp" d="M14 66 A36 36 0 0 1 86 66" />
			{#each 'ABCDE'.split('') as letter, i}
				{@const hoek = Math.PI - (i / 4) * Math.PI}
				<text
					class="letter"
					x={50 + Math.cos(hoek) * 36}
					y={66 - Math.sin(hoek) * 36}
					transform="rotate({90 - (hoek * 180) / Math.PI} {50 + Math.cos(hoek) * 36} {66 - Math.sin(hoek) * 36})"
				>{letter}</text>
			{/each}
		{:else if soort === 'qrcode'}
			<g class="vorm">
				<rect x="16" y="16" width="20" height="20" /><rect x="64" y="16" width="20" height="20" />
				<rect x="16" y="64" width="20" height="20" />
				<rect x="46" y="46" width="8" height="8" /><rect x="64" y="56" width="8" height="8" />
				<rect x="74" y="70" width="8" height="8" /><rect x="56" y="74" width="8" height="8" />
			</g>
		{:else if soort === 'barcode'}
			<g class="vorm">
				{#each [16, 22, 25, 32, 38, 41, 48, 55, 58, 64, 71, 78, 81] as x, i}
					<rect {x} y="24" width={i % 3 === 0 ? 4 : 2} height="46" />
				{/each}
			</g>
		{/if}
	</svg>
	<figcaption>{@render children?.()}</figcaption>
</figure>

<style>
	.proef {
		margin: 0;
		display: grid;
		gap: var(--space-2);
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	svg { width: 190px; height: 150px; display: block; margin: 0 auto; }
	/* Alle maten hierin staan in viewBox-eenheden, niet in pixels — daarom
	   non-scaling-stroke, anders verandert de lijndikte met de kolombreedte. */
	.vorm, .vorm > :global(path), .hulp, .tanden > :global(path), .bemating > :global(path) {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	.hulp { stroke: var(--text-2); stroke-dasharray: 3 2; }
	.tanden > :global(path) { stroke-width: 2.6; }
	.bemating > :global(path) { stroke: var(--text-2); stroke-width: 0.8; }
	/* @svg-space: deze SVG rekent in viewBox-eenheden (100 breed op 190 px), niet
	   in CSS-pixels. Wat er op het scherm van terechtkomt, wordt gemeten door
	   criticus 2 — een uitzondering zonder meting is precies hoe het reuzenlabel
	   uit ronde 4 drie rondes lang onopgemerkt bleef. */
	.bij { font-size: 7.5px; fill: var(--text-2); font-family: var(--font-mono); }
	.bij.tand { fill: var(--accent); }
	/* @svg-space: zie hierboven. */
	.letter { font-size: 10px; fill: var(--accent); text-anchor: middle; font-weight: 600; }
	figcaption { font-size: var(--text-xs); color: var(--text-2); text-align: center; }
</style>
