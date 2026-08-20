<script module lang="ts">
	/** Wat de server terugstuurt: omtrekken in mm, en waar ze komen te liggen. */
	export type Voorbeeld = {
		what: string;
		shapes: string[];
		parts: { shape: number; x: number; y: number; rot: number; rx?: number; ry?: number }[];
		bounds: [number, number, number, number];
		sheet: { width_mm: number; height_mm: number };
		sheets: number;
		notes: string[];
		labels?: string[];
		modules?: number;
		bars?: number;
	};
</script>

<script lang="ts">
	/**
	 * De vorm naast het formulier dat hem maakt.
	 *
	 * Dit is geen schets meer maar het werkelijke resultaat: de engine rekent
	 * hetzelfde uit als bij het echte werk (`Generators.preview`, dezelfde
	 * `_plan_*`-functies) en stuurt de omtrekken in millimeters terug. Wat je
	 * hier ziet is dus wat er straks gebrand wordt — inclusief de plek op het
	 * vel, want "past dit nog" is de vraag die je aan een generator stelt.
	 *
	 * Twee regels die uit de vorige ronde komen en hier weer gelden:
	 *
	 * 1. **Bij ongeldige invoer springt het beeld niet weg.** Half getypte
	 *    getallen zijn even ongeldig; het laatste geldige beeld blijft staan
	 *    met de reden erboven. Zie `TestGrid.svelte`, `voorbeeldFout`.
	 * 2. **Het voorbeeld toont niet meer dan er brandt.** Het vel is een dunne
	 *    hulplijn, geen vorm, en is als zodanig herkenbaar.
	 *
	 * Voor herhalen en cirkel is er een terugval: die twee hebben de gekozen
	 * elementen nodig, en zolang het venster die niet krijgt, blijft daar de
	 * oude schets staan. Een verzonnen vorm herhalen zou een voorbeeld zijn
	 * dat er wel uitziet als het jouwe en het niet is.
	 */

	import { t } from '$lib/i18n/index.svelte';
	let {
		soort,
		waarden,
		voorbeeld = null,
		fout = null,
		children
	}: {
		soort: string;
		/** De ruwe formuliervelden, voor de terugvalschets. */
		waarden: Record<string, unknown>;
		voorbeeld?: Voorbeeld | null;
		/** Waarom het laatste beeld niet ververst is; het beeld blijft staan. */
		fout?: string | null;
		children?: import('svelte').Snippet;
	} = $props();

	function n(sleutel: string, standaard: number): number {
		const v = Number(waarden[sleutel]);
		return Number.isFinite(v) && v !== 0 ? v : standaard;
	}

	// --- terugvalschets: herhalen en cirkel
	let kolommen = $derived(Math.min(6, Math.max(1, Math.round(n('columns', 4)))));
	let rijen = $derived(Math.min(6, Math.max(1, Math.round(n('rows', 3)))));
	let herhalingen = $derived(Math.min(16, Math.max(2, Math.round(n('repeats', 8)))));
	let draait = $derived(waarden.rotate !== false);

	// De vlakken die je als vlák wilt zien: een QR-code van losse omtrekjes is
	// geen QR-code meer. De rest is een lijn, want dat is wat de laser volgt.
	const GEVULD = new Set(['qrcode', 'barcode']);

	/**
	 * Het venster op de tekening, in mm.
	 *
	 * Inzoomen op het werk zelf, niet op het vel: een QR-code van 30 mm op een
	 * bed van 500 mm zou anders vier pixels groot zijn. De velrand wordt wél
	 * getekend, dus zodra je er in de buurt komt, zie je hem liggen.
	 */
	let venster = $derived.by(() => {
		if (!voorbeeld) return null;
		const [x0, y0, x1, y1] = voorbeeld.bounds;
		const marge = Math.max((x1 - x0) * 0.08, (y1 - y0) * 0.08, 1);
		return {
			x: x0 - marge,
			y: y0 - marge,
			w: Math.max(x1 - x0 + marge * 2, 0.01),
			h: Math.max(y1 - y0 + marge * 2, 0.01)
		};
	});

	let breed = $derived(voorbeeld ? voorbeeld.bounds[2] - voorbeeld.bounds[0] : 0);
	let hoog = $derived(voorbeeld ? voorbeeld.bounds[3] - voorbeeld.bounds[1] : 0);

	/** Steekt er iets buiten het vel uit? Dat is geen detail op een laser. */
	let buitenVel = $derived.by(() => {
		if (!voorbeeld) return false;
		const [x0, y0, x1, y1] = voorbeeld.bounds;
		return x0 < -0.01 || y0 < -0.01 || x1 > voorbeeld.sheet.width_mm + 0.01
			|| y1 > voorbeeld.sheet.height_mm + 0.01;
	});

	const maat = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1));

	/** What is under the drawing: the count, in the unit of this thing. */
	let telling = $derived.by(() => {
		if (!voorbeeld) return null;
		if (voorbeeld.what === 'box')
			return voorbeeld.sheets > 1
				? t('genPreview.panelsSheets', { n: voorbeeld.parts.length, sheets: voorbeeld.sheets })
				: t('genPreview.panels', { n: voorbeeld.parts.length });
		if (voorbeeld.what === 'grid' || voorbeeld.what === 'radial')
			return t('genPreview.pieces', { n: voorbeeld.parts.length });
		if (voorbeeld.modules) return t('genPreview.modules', { n: voorbeeld.modules });
		if (voorbeeld.bars) return t('genPreview.bars', { n: voorbeeld.bars });
		return null;
	});

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
	{#if fout}
		<!-- While typing, an intermediate state is nearly always briefly invalid: you
		     delete a digit and the radius is zero until you type the next one. The image
		     stays, with the reason above it — dropping a hole teaches you nothing and
		     makes half the window jump. -->
		<p class="onaf" role="status">
			{fout}
			{#if voorbeeld}<br /><span class="stil">{t('genPreview.lastValid')}</span>{/if}
		</p>
	{/if}

	{#if voorbeeld && venster}
		<svg
			viewBox="{venster.x} {venster.y} {venster.w} {venster.h}"
			role="img"
			aria-label={t('genPreview.aria', { width: maat(breed), height: maat(hoog) })}
		>
			<!-- The sheet as a guide, not as a shape: it does not get burned. -->
			<rect
				class="vel"
				x="0"
				y="0"
				width={voorbeeld.sheet.width_mm}
				height={voorbeeld.sheet.height_mm}
			/>
			<g class:vlak={GEVULD.has(voorbeeld.what)}>
				{#each voorbeeld.parts as deel (deel)}
					<path
						class="vorm"
						d={voorbeeld.shapes[deel.shape]}
						transform="translate({deel.x} {deel.y}) rotate({deel.rot} {deel.rx ?? 0} {deel.ry ?? 0})"
					/>
				{/each}
			</g>
		</svg>
	{:else if soort === 'grid'}
		<!-- Fallback: without the chosen elements we do not know what is being repeated,
		     so it stays at the meaning of the fields. -->
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.sketchAria')}>
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
			{#if kolommen > 1}
				<line class="maat" x1={12 + 76 / kolommen - 76 / kolommen / 4} y1="8" x2={12 + 76 / kolommen} y2="8" />
				<text class="bij" x={12 + 76 / kolommen - 76 / kolommen / 8} y="6"
					>{t('genPreview.space')}</text
				>
			{/if}
		</svg>
	{:else if soort === 'radial'}
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.sketchAria')}>
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
		</svg>
	{:else if soort === 'polygon'}
		<!-- Only until the first answer is in; after that the real image takes its
		     place. An empty box would make the window jump. -->
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.sketchAria')}>
			<polygon class="hulp" points={veelhoekPunten(6, 34, 0)} />
		</svg>
	{:else}
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.calculatingAria')}>
			<rect class="hulp" x="14" y="20" width="72" height="60" />
		</svg>
	{/if}

	{#if voorbeeld}
		<figcaption class="cijfers">
			<span class="mono">{maat(breed)} × {maat(hoog)} mm</span>
			{#if telling}<span class="stil">{telling}</span>{/if}
		</figcaption>
		{#if buitenVel}
			<figcaption class="waarschuwing">{t('genPreview.offSheet')}</figcaption>
		{/if}
		{#each voorbeeld.notes as note (note)}
			<figcaption class="waarschuwing">{note}</figcaption>
		{/each}
	{:else}
		<figcaption>{@render children?.()}</figcaption>
	{/if}
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
	/* Alle maten hierin staan in millimeters, niet in pixels — daarom
	   non-scaling-stroke, anders verandert de lijndikte met de zoom. */
	.vorm, .hulp {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	.hulp { stroke: var(--text-2); stroke-dasharray: 3 2; }
	/* Een QR-code van losse omtrekjes leest niemand; die hoort dicht te zijn. */
	.vlak .vorm { fill: var(--accent); stroke: none; }
	.vel {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
		opacity: 0.6;
	}
	.maat { stroke: var(--text-2); stroke-width: 0.8; vector-effect: non-scaling-stroke; }
	/* @svg-space: deze terugvalschets rekent in viewBox-eenheden (100 breed op
	   190 px), niet in CSS-pixels. */
	.bij { font-size: 7.5px; fill: var(--text-2); font-family: var(--font-mono); }
	figcaption { font-size: var(--text-xs); color: var(--text-2); text-align: center; }
	.cijfers { display: flex; gap: var(--space-2); justify-content: center; flex-wrap: wrap; }
	.cijfers .mono { color: var(--text-1); font-family: var(--font-mono); }
	.stil { color: var(--text-2); }
	.waarschuwing { color: var(--warn); }
	.onaf { margin: 0; font-size: var(--text-xs); color: var(--warn); text-align: left; line-height: 1.4; }
</style>
