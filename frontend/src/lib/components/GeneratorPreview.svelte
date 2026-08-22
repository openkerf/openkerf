<script module lang="ts">
	/** What the server sends back: outlines in mm, and where they will lie. */
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
		/** The living hinge: how many slits, in how many rows, and how wide the bridge is. */
		slits?: number;
		rows?: number;
		bridge_mm?: number;
	};
</script>

<script lang="ts">
	/**
	 * The shape beside the form that makes it.
	 *
	 * This is no longer a sketch but the real result: the engine computes the same thing
	 * as for the real work (`Generators.preview`, the same `_plan_*` functions) and sends
	 * the outlines back in millimetres. So what you see here is what will be burned —
	 * including the place on the sheet, because "does this still fit" is the question you
	 * put to a generator.
	 *
	 * Two rules that come from the previous round and hold here again:
	 *
	 * 1. **On invalid input the image does not jump away.** Half-typed numbers are just
	 *    as invalid; the last valid image stays up with the reason above it. See
	 *    `TestGrid.svelte`, `previewError`.
	 * 2. **The preview shows no more than what burns.** The sheet is a thin guide line,
	 *    not a shape, and is recognisable as such.
	 *
	 * For repeat and circle there is a fallback: those two need the chosen elements, and
	 * as long as the dialog does not get them the old sketch stays there. Repeating an
	 * invented shape would be a preview that looks like yours and is not.
	 */

	import { t } from '$lib/i18n/index.svelte';
	let {
		kind,
		values,
		preview = null,
		failure = null,
		children
	}: {
		kind: string;
		/** The raw form fields, for the fallback sketch. */
		values: Record<string, unknown>;
		preview?: Voorbeeld | null;
		/** Why the last image was not refreshed; the image stays up. */
		failure?: string | null;
		children?: import('svelte').Snippet;
	} = $props();

	function n(key: string, standaard: number): number {
		const v = Number(values[key]);
		return Number.isFinite(v) && v !== 0 ? v : standaard;
	}

	// --- terugvalschets: herhalen en cirkel
	let kolommen = $derived(Math.min(6, Math.max(1, Math.round(n('columns', 4)))));
	let rijen = $derived(Math.min(6, Math.max(1, Math.round(n('rows', 3)))));
	let herhalingen = $derived(Math.min(16, Math.max(2, Math.round(n('repeats', 8)))));
	let draait = $derived(values.rotate !== false);

	// The shapes you want to see as an *area*: a QR code of separate little outlines is
	// no longer a QR code. The rest is a line, because that is what the laser follows.
	const FILLED = new Set(['qrcode', 'barcode']);

	/**
	 * The window onto the drawing, in mm.
	 *
	 * Zooming in on the work itself, not on the sheet: a 30 mm QR code on a 500 mm bed
	 * would otherwise be four pixels across. The sheet edge *is* drawn, so as soon as you
	 * come near it you see it lying there.
	 */
	let viewBox = $derived.by(() => {
		if (!preview) return null;
		const [x0, y0, x1, y1] = preview.bounds;
		const margin = Math.max((x1 - x0) * 0.08, (y1 - y0) * 0.08, 1);
		return {
			x: x0 - margin,
			y: y0 - margin,
			w: Math.max(x1 - x0 + margin * 2, 0.01),
			h: Math.max(y1 - y0 + margin * 2, 0.01)
		};
	});

	let wide = $derived(preview ? preview.bounds[2] - preview.bounds[0] : 0);
	let high = $derived(preview ? preview.bounds[3] - preview.bounds[1] : 0);

	/** Does something stick out beyond the sheet? On a laser that is not a detail. */
	let offSheet = $derived.by(() => {
		if (!preview) return false;
		const [x0, y0, x1, y1] = preview.bounds;
		return x0 < -0.01 || y0 < -0.01 || x1 > preview.sheet.width_mm + 0.01
			|| y1 > preview.sheet.height_mm + 0.01;
	});

	const size = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1));

	/** What is under the drawing: the count, in the unit of this thing. */
	let telling = $derived.by(() => {
		if (!preview) return null;
		if (preview.what === 'box')
			return preview.sheets > 1
				? t('genPreview.panelsSheets', { n: preview.parts.length, sheets: preview.sheets })
				: t('genPreview.panels', { n: preview.parts.length });
		if (preview.what === 'grid' || preview.what === 'radial')
			return t('genPreview.pieces', { n: preview.parts.length });
		if (preview.what === 'hinge')
			return t('genPreview.slits', { n: preview.slits ?? 0, rows: preview.rows ?? 0 });
		if (preview.modules) return t('genPreview.modules', { n: preview.modules });
		if (preview.bars) return t('genPreview.bars', { n: preview.bars });
		return null;
	});

	function polygonPoints(sides: number, radius: number, innerRadius: number) {
		const points: string[] = [];
		const total = innerRadius ? sides * 2 : sides;
		for (let i = 0; i < total; i++) {
			const r = innerRadius && i % 2 ? innerRadius : radius;
			const corner = (i / total) * Math.PI * 2 - Math.PI / 2;
			points.push(`${(50 + Math.cos(corner) * r).toFixed(1)},${(50 + Math.sin(corner) * r).toFixed(1)}`);
		}
		return points.join(' ');
	}
</script>

<figure class="proef">
	{#if failure}
		<!-- While typing, an intermediate state is nearly always briefly invalid: you
		     delete a digit and the radius is zero until you type the next one. The image
		     stays, with the reason above it — dropping a hole teaches you nothing and
		     makes half the window jump. -->
		<p class="unfinished" role="status">
			{failure}
			{#if preview}<br /><span class="quiet">{t('genPreview.lastValid')}</span>{/if}
		</p>
	{/if}

	{#if preview && viewBox}
		<svg
			viewBox="{viewBox.x} {viewBox.y} {viewBox.w} {viewBox.h}"
			role="img"
			aria-label={t('genPreview.aria', { width: size(wide), height: size(high) })}
		>
			<!-- The sheet as a guide, not as a shape: it does not get burned. -->
			<rect
				class="sheet"
				x="0"
				y="0"
				width={preview.sheet.width_mm}
				height={preview.sheet.height_mm}
			/>
			<g class:area={FILLED.has(preview.what)}>
				{#each preview.parts as part (part)}
					<path
						class="shape"
						d={preview.shapes[part.shape]}
						transform="translate({part.x} {part.y}) rotate({part.rot} {part.rx ?? 0} {part.ry ?? 0})"
					/>
				{/each}
			</g>
		</svg>
	{:else if kind === 'grid'}
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
						class="shape"
					/>
				{/each}
			{/each}
			{#if kolommen > 1}
				<line class="size" x1={12 + 76 / kolommen - 76 / kolommen / 4} y1="8" x2={12 + 76 / kolommen} y2="8" />
				<text class="bij" x={12 + 76 / kolommen - 76 / kolommen / 8} y="6"
					>{t('genPreview.space')}</text
				>
			{/if}
		</svg>
	{:else if kind === 'radial'}
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.sketchAria')}>
			<circle class="hulp" cx="50" cy="50" r="32" />
			{#each Array(herhalingen) as _, i}
				{@const corner = (i / herhalingen) * Math.PI * 2 - Math.PI / 2}
				<rect
					class="shape"
					x={50 + Math.cos(corner) * 32 - 5}
					y={50 + Math.sin(corner) * 32 - 3.5}
					width="10"
					height="7"
					transform={draait
						? `rotate(${(i / herhalingen) * 360} ${50 + Math.cos(corner) * 32} ${50 + Math.sin(corner) * 32})`
						: undefined}
				/>
			{/each}
		</svg>
	{:else if kind === 'polygon'}
		<!-- Only until the first answer is in; after that the real image takes its
		     place. An empty box would make the window jump. -->
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.sketchAria')}>
			<polygon class="hulp" points={polygonPoints(6, 34, 0)} />
		</svg>
	{:else}
		<svg viewBox="0 0 100 100" role="img" aria-label={t('genPreview.calculatingAria')}>
			<rect class="hulp" x="14" y="20" width="72" height="60" />
		</svg>
	{/if}

	{#if preview}
		<figcaption class="figures">
			<span class="mono">{size(wide)} × {size(high)} mm</span>
			{#if telling}<span class="quiet">{telling}</span>{/if}
		</figcaption>
		{#if offSheet}
			<figcaption class="waarschuwing">{t('genPreview.offSheet')}</figcaption>
		{/if}
		{#each preview.notes as note (note)}
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
	/* All the measures in here are in millimetres, not in pixels — hence
	   non-scaling-stroke, otherwise the line weight changes with the zoom. */
	.shape, .hulp {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	.hulp { stroke: var(--text-2); stroke-dasharray: 3 2; }
	/* Nobody reads a QR code of separate little outlines; it should be solid. */
	.area .shape { fill: var(--accent); stroke: none; }
	.sheet {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
		opacity: 0.6;
	}
	.size { stroke: var(--text-2); stroke-width: 0.8; vector-effect: non-scaling-stroke; }
	/* @svg-space: this fallback sketch computes in viewBox units (100 wide on
	   190 px), niet in CSS-pixels. */
	.bij { font-size: 7.5px; fill: var(--text-2); font-family: var(--font-mono); }
	figcaption { font-size: var(--text-xs); color: var(--text-2); text-align: center; }
	.figures { display: flex; gap: var(--space-2); justify-content: center; flex-wrap: wrap; }
	.figures .mono { color: var(--text-1); font-family: var(--font-mono); }
	.quiet { color: var(--text-2); }
	.waarschuwing { color: var(--warn); }
	.unfinished { margin: 0; font-size: var(--text-xs); color: var(--warn); text-align: left; line-height: 1.4; }
</style>
