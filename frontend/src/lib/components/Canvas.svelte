<script lang="ts">
	import type { Device } from '$lib/api';
	import type { DesignStore } from '$lib/design.svelte';

	let { device, design }: { device: Device | null; design: DesignStore } = $props();

	const FALLBACK = { width: 500, height: 300 };

	let bed = $derived({
		width: device?.bed?.width_mm ?? FALLBACK.width,
		height: device?.bed?.height_mm ?? FALLBACK.height
	});

	// Vaste schaal: het bed vult 640px breed, hoogte volgt de verhouding.
	let scale = $derived(640 / bed.width);
	let head = $derived(device?.position.mm ?? null);

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

			<svg
				viewBox="0 0 {bed.width} {bed.height}"
				style="position: absolute; inset: 0; width: 100%; height: 100%"
				role="img"
				aria-label={head
					? `Laserkop op ${head[0].toFixed(1)}, ${head[1].toFixed(1)} millimeter`
					: 'Positie van de laserkop onbekend'}
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
									stroke-width="1.2"
									vector-effect="non-scaling-stroke"
								/>
							{/if}
						{/each}
					</g>
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
	.empty {
		position: absolute;
		inset: auto 0 var(--space-6) 0;
		text-align: center;
		color: var(--text-2);
	}
</style>
