<script lang="ts">
	import type { Device } from '$lib/api';
	import type { DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';

	let {
		device,
		design,
		edits,
		canEdit = false,
		onEdited
	}: {
		device: Device | null;
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onEdited?: () => void;
	} = $props();

	const FALLBACK = { width: 500, height: 300 };

	let bed = $derived({
		width: device?.bed?.width_mm ?? FALLBACK.width,
		height: device?.bed?.height_mm ?? FALLBACK.height
	});

	// Vaste schaal: het bed vult 640px breed, hoogte volgt de verhouding.
	let scale = $derived(640 / bed.width);
	let head = $derived(device?.position.mm ?? null);
	let selection = $derived(design.selectedSize);

	// Slepen. De voorbeeld-offset is puur visueel; pas bij loslaten gaat er één
	// opdracht naar de engine, zodat we hem niet met tussenstanden bestoken.
	type Drag = {
		mode: 'move' | 'scale';
		corner: number;
		startX: number;
		startY: number;
		dx: number;
		dy: number;
		origin: { x: number; y: number; width: number; height: number };
	};
	let drag = $state<Drag | null>(null);

	let preview = $derived.by(() => {
		if (!drag || !selection) return null;
		if (drag.mode === 'move') {
			return { ...drag.origin, x: drag.origin.x + drag.dx, y: drag.origin.y + drag.dy };
		}
		// Schalen vanaf de tegenoverliggende hoek, zodat die blijft liggen.
		const { x, y, width, height } = drag.origin;
		const left = drag.corner % 2 === 0;
		const top = drag.corner < 2;
		const newX = left ? x + drag.dx : x;
		const newY = top ? y + drag.dy : y;
		const newWidth = left ? width - drag.dx : width + drag.dx;
		const newHeight = top ? height - drag.dy : height + drag.dy;
		return { x: newX, y: newY, width: newWidth, height: newHeight };
	});

	let outline = $derived(preview ?? selection);

	function mmPerPixel() {
		return 1 / scale;
	}

	function startDrag(event: PointerEvent, mode: 'move' | 'scale', corner = 0) {
		if (!canEdit || !selection) return;
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		drag = {
			mode,
			corner,
			startX: event.clientX,
			startY: event.clientY,
			dx: 0,
			dy: 0,
			origin: { ...selection }
		};
	}

	function moveDrag(event: PointerEvent) {
		if (!drag) return;
		drag.dx = (event.clientX - drag.startX) * mmPerPixel();
		drag.dy = (event.clientY - drag.startY) * mmPerPixel();
	}

	async function endDrag(event: PointerEvent) {
		if (!drag) return;
		const finished = drag;
		const target = preview;
		drag = null;
		if (!design.selectedId || !target) return;
		// Onder een halve pixel is het een klik, geen sleep.
		if (Math.abs(finished.dx) < 0.05 && Math.abs(finished.dy) < 0.05) return;

		if (finished.mode === 'move') {
			await edits.move(design.selectedId, finished.dx, finished.dy);
		} else if (target.width > 0.1 && target.height > 0.1) {
			await edits.resize(design.selectedId, target.x, target.y, target.width, target.height);
		}
		onEdited?.();
	}

	// Linialen elke 50 mm.
	let ticksX = $derived(
		Array.from({ length: Math.floor(bed.width / 50) + 1 }, (_, i) => i * 50)
	);
	let ticksY = $derived(
		Array.from({ length: Math.floor(bed.height / 50) + 1 }, (_, i) => i * 50)
	);
</script>

<div class="canvas-wrap">
	<div class="ruler-x" aria-hidden="true">
		{#each ticksX as tick (tick)}
			<span style="width: {50 * scale}px">{tick}</span>
		{/each}
	</div>
	<div class="ruler-y" aria-hidden="true">
		{#each ticksY as tick (tick)}
			<span style="height: {50 * scale}px">{tick}</span>
		{/each}
	</div>

	<div class="canvas">
		<div
			class="bed"
			style="width: {bed.width * scale}px; height: {bed.height * scale}px;
			       background-size: {50 * scale}px {50 * scale}px"
		>
			<span class="bed-label mono">
				bed {bed.width.toFixed(0)} × {bed.height.toFixed(0)} mm
			</span>

			<!-- Klikken op het lege canvas deselecteert. Het toetsenbord-equivalent
			     is Escape, afgevangen op window-niveau; de elementen zelf zijn
			     focusbaar en met Enter/spatie te selecteren. -->
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<svg
				viewBox="0 0 {bed.width} {bed.height}"
				style="position: absolute; inset: 0; width: 100%; height: 100%"
				role="img"
				aria-label={head
					? `Laserkop op ${head[0].toFixed(1)}, ${head[1].toFixed(1)} millimeter`
					: 'Positie van de laserkop onbekend'}
				onclick={(e) => {
					// Klikken naast een element heft de selectie op.
					if (e.target === e.currentTarget) design.select(null);
				}}
			>
				<!-- Het ontwerp. Eén schaaltransform rekent Tats om naar mm; de
				     paddata zelf blijft onaangeroerd zoals de engine hem gaf. -->
				{#if design.design}
					<g transform="scale({1 / design.design.units_per_mm})">
						{#each design.elements as element (element.id)}
							{#if !element.hidden}
								<path
									d={element.path}
									fill="none"
									stroke={element.stroke ?? 'var(--text-2)'}
									stroke-width={design.selectedId === element.id ? 2 : 1.2}
									vector-effect="non-scaling-stroke"
								/>
								<!-- Onzichtbare trefzone: een contour van 1 px is niet aan te
								     klikken, zeker niet op een touchscreen. -->
								<path
									class="hit"
									d={element.path}
									fill="none"
									stroke="transparent"
									stroke-width="12"
									vector-effect="non-scaling-stroke"
									role="button"
									tabindex="0"
									aria-label="Selecteer {element.label}"
									aria-pressed={design.selectedId === element.id}
									onclick={(e) => {
										e.stopPropagation();
										design.select(element.id);
									}}
									onkeydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											design.select(element.id);
										}
									}}
								/>
							{/if}
						{/each}
					</g>

					<!-- Selectiecontour: de kerflijn. Statisch gestreept, en alleen
					     geanimeerd terwijl je sleept — zoals DESIGN-SYSTEM.md voorschrijft. -->
					{#if outline}
						<g class="selection">
							<rect
								class:kerf-anim={drag !== null}
								x={outline.x}
								y={outline.y}
								width={Math.abs(outline.width)}
								height={Math.abs(outline.height)}
							/>
							<!-- Sleepvlak: het hele selectiekader verplaatst het element. -->
							{#if canEdit}
								<!-- Toetsenbord-equivalent: pijltjestoetsen verplaatsen de
								     selectie (0,1 mm, met shift 1 mm). -->
								<rect
									class="grab"
									role="button"
									tabindex="-1"
									aria-label="Sleep om te verplaatsen"
									x={outline.x}
									y={outline.y}
									width={Math.abs(outline.width)}
									height={Math.abs(outline.height)}
									onpointerdown={(e) => startDrag(e, 'move')}
									onpointermove={moveDrag}
									onpointerup={endDrag}
								/>
							{/if}
							{#each [[outline.x, outline.y], [outline.x + outline.width, outline.y], [outline.x, outline.y + outline.height], [outline.x + outline.width, outline.y + outline.height]] as [hx, hy], corner (corner)}
								<rect
									class="handle"
									class:grabbable={canEdit}
									role="button"
									tabindex="-1"
									aria-label="Sleep om te schalen"
									x={hx - 1.2}
									y={hy - 1.2}
									width="2.4"
									height="2.4"
									onpointerdown={(e) => startDrag(e, 'scale', corner)}
									onpointermove={moveDrag}
									onpointerup={endDrag}
								/>
							{/each}
							<text
								class="mono"
								x={outline.x + outline.width / 2}
								y={outline.y + Math.abs(outline.height) + 5}
								text-anchor="middle"
							>
								{Math.abs(outline.width).toFixed(1)} × {Math.abs(outline.height).toFixed(1)} mm
							</text>
						</g>
					{/if}
				{/if}

				{#if head}
					<!-- Live kop-positie. Er is nog geen ontwerp om te tonen: fase 1
					     leest alleen status, het canvas zelf komt in fase 3. -->
					<g class="head">
						<line x1={head[0]} y1="0" x2={head[0]} y2={bed.height} />
						<line x1="0" y1={head[1]} x2={bed.width} y2={head[1]} />
						<circle cx={head[0]} cy={head[1]} r="4" />
					</g>
				{/if}
			</svg>
		</div>
	</div>

	{#if !device}
		<p class="empty">Geen machine verbonden</p>
	{/if}
</div>

<style>
	.canvas-wrap {
		flex: 1;
		position: relative;
		background: var(--canvas-bg);
		overflow: hidden;
	}
	.ruler-x,
	.ruler-y {
		position: absolute;
		background: var(--surface-1);
		color: var(--text-2);
		font-family: var(--font-mono);
		font-size: 9px;
		z-index: 2;
		user-select: none;
	}
	.ruler-x {
		top: 0;
		left: 20px;
		right: 0;
		height: 20px;
		border-bottom: 1px solid var(--line);
		display: flex;
	}
	.ruler-y {
		top: 20px;
		left: 0;
		bottom: 0;
		width: 20px;
		border-right: 1px solid var(--line);
	}
	.ruler-x span {
		flex: none;
		padding: 4px 0 0 3px;
		border-left: 1px solid var(--line);
	}
	.ruler-y span {
		display: block;
		padding: 3px 0 0 2px;
		border-top: 1px solid var(--line);
	}
	.canvas {
		position: absolute;
		inset: 20px 0 0 20px;
		display: grid;
		place-items: center;
	}
	.bed {
		background: var(--bed);
		border: 1px solid var(--line);
		border-radius: 2px;
		position: relative;
		background-image:
			linear-gradient(var(--line) 1px, transparent 1px),
			linear-gradient(90deg, var(--line) 1px, transparent 1px);
		box-shadow: 0 1px 3px rgb(0 0 0 / 0.06);
	}
	.bed-label {
		position: absolute;
		top: -22px;
		right: 0;
		font-size: 10px;
		color: var(--text-2);
	}
	.head line {
		stroke: var(--accent);
		stroke-width: 0.5;
		opacity: 0.5;
	}
	.head circle {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1;
	}
	.hit {
		cursor: pointer;
	}
	.hit:focus-visible {
		outline: none;
		stroke: color-mix(in srgb, var(--accent) 35%, transparent);
	}
	/* De kerflijn als selectiecontour: statisch gestreept, animatie pas bij
	   slepen — dat komt in de volgende plak. */
	.selection rect {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 6 4;
		vector-effect: non-scaling-stroke;
	}
	.selection .handle {
		fill: var(--surface-1);
		stroke-dasharray: none;
	}
	.selection .handle.grabbable {
		cursor: nwse-resize;
	}
	.selection .grab {
		fill: transparent;
		stroke: none;
		cursor: move;
		touch-action: none;
	}
	.selection text {
		fill: var(--text-2);
		font-size: 3.5px;
	}
	.empty {
		position: absolute;
		inset: auto 0 var(--space-6) 0;
		text-align: center;
		color: var(--text-2);
	}
</style>
