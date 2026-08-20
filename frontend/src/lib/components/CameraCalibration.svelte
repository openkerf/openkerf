<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import type { CameraStore } from '$lib/camera.svelte';

	let {
		open = $bindable(),
		camera
	}: { open: boolean; camera: CameraStore } = $props();

	// Vier hoeken in beeldpixels, linksboven met de klok mee. Die volgorde is
	// niet vrij: de engine trekt ze in precies deze volgorde naar een rechthoek,
	// dus door elkaar gooien geeft een gespiegeld of gedraaid beeld.
	const NAMES = ['linksboven', 'rechtsboven', 'rechtsonder', 'linksonder'];

	let points = $state<{ x: number; y: number }[]>([]);
	let box = $state({ width: 640, height: 480 });
	let dragging = $state<number | null>(null);
	let frame = $state<HTMLImageElement | null>(null);
	let ready = false;

	// Bij openen het onbewerkte beeld tonen: hoeken aanwijzen doe je in het
	// beeld zoals de camera het ziet, niet in het al rechtgetrokken beeld.
	$effect(() => {
		if (!open) {
			ready = false;
			return;
		}
		if (ready) return;
		ready = true;
		camera.setCorrected(false);
		const size = camera.state.frame;
		if (size) box = { width: size.width, height: size.height };
		const known = camera.state.perspective;
		points =
			known && known.length === 4
				? known.map(([x, y]) => ({ x, y }))
				: [
						{ x: box.width * 0.2, y: box.height * 0.2 },
						{ x: box.width * 0.8, y: box.height * 0.2 },
						{ x: box.width * 0.8, y: box.height * 0.8 },
						{ x: box.width * 0.2, y: box.height * 0.8 }
					];
	});

	function at(event: PointerEvent) {
		if (!frame) return null;
		const rect = frame.getBoundingClientRect();
		return {
			x: ((event.clientX - rect.left) / rect.width) * box.width,
			y: ((event.clientY - rect.top) / rect.height) * box.height
		};
	}

	function move(event: PointerEvent) {
		if (dragging === null) return;
		const spot = at(event);
		if (!spot) return;
		points = points.map((point, index) => (index === dragging ? spot : point));
	}

	async function save() {
		const saved = await camera.calibrate(points.map((p) => [p.x, p.y]));
		if (saved) {
			camera.generation += 1;
			open = false;
		}
	}

	async function cancel() {
		// Back to how it was: the corrected image if there is a calibration.
		await camera.setCorrected(Boolean(camera.state.calibrated));
		open = false;
	}
</script>

<Dialog title={t('calibrate.title')} bind:open width="720px">
	<p class="lead">{t('calibrate.lead')}</p>

	{#if camera.error}
		<p class="error" role="alert">{camera.error}</p>
	{/if}

	<div
		class="stage"
		role="application"
		aria-label={t('calibrate.stageAria')}
		style="aspect-ratio: {box.width} / {box.height}"
		onpointermove={move}
		onpointerup={() => (dragging = null)}
		onpointerleave={() => (dragging = null)}
	>
		<img
			bind:this={frame}
			src="/api/camera/stream.mjpeg?v={camera.generation}"
			alt={t('calibrate.rawAlt')}
			draggable="false"
		/>
		<svg viewBox="0 0 {box.width} {box.height}" preserveAspectRatio="none">
			<polygon
				points={points.map((p) => `${p.x},${p.y}`).join(' ')}
				fill="none"
			/>
			{#each points as point, index (index)}
				<circle
					class="grip"
					cx={point.x}
					cy={point.y}
					r={Math.max(box.width, box.height) / 55}
					role="button"
					tabindex="0"
					aria-label="Hoek {NAMES[index]}"
					onpointerdown={(e) => {
						(e.target as Element).setPointerCapture?.(e.pointerId);
						dragging = index;
					}}
				/>
				<text x={point.x + 10} y={point.y - 10}>{index + 1}</text>
			{/each}
		</svg>
	</div>

	<div class="numbers">
		{#each points as point, index (index)}
			<div>
				<span>{index + 1}. {NAMES[index]}</span>
				<span class="mono">{Math.round(point.x)}, {Math.round(point.y)}</span>
			</div>
		{/each}
	</div>

	<div class="actions">
		<button class="btn" onclick={() => camera.resetCalibration()}>IJking wissen</button>
		<button class="btn" onclick={cancel}>Annuleren</button>
		<button class="btn primary" disabled={camera.busy} onclick={save}>Opslaan</button>
	</div>
</Dialog>

<style>
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.error { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--danger); }
	.stage {
		position: relative;
		width: 100%;
		background: var(--void);
		border-radius: var(--radius-field);
		overflow: hidden;
		touch-action: none;
	}
	.stage img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: fill;
		user-select: none;
	}
	.stage svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}
	polygon {
		/* Bewust géén kerflijn (6/4): die is voorbehouden aan de selectie op het
		   canvas, de jobvoortgang en de actieve tab. Dit is een ijkkader, geen
		   snede. */
		stroke: var(--accent);
		stroke-width: 2;
		vector-effect: non-scaling-stroke;
		stroke-dasharray: 5 3;
	}
	.grip {
		fill: color-mix(in srgb, var(--accent) 70%, transparent);
		stroke: var(--on-color);
		stroke-width: 2;
		vector-effect: non-scaling-stroke;
		cursor: grab;
	}
	text {
		fill: var(--on-color);
		font-size: 18px;
		font-family: var(--font-mono);
		paint-order: stroke;
		stroke: rgb(0 0 0 / 0.6);
		stroke-width: 3;
	}
	.numbers {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-2);
		margin-top: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.numbers div { display: grid; gap: 1px; }
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.btn {
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
</style>
