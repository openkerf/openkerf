<script lang="ts">
	import type { Device } from '$lib/api';
	import type { DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';

	let {
		device,
		design,
		edits,
		canEdit = false,
		tool = 'select',
		onEdited,
		onDrawn,
		onTextAt,
		cropping = $bindable(false),
		onCrop,
		onPath,
		cameraSrc = null,
		cameraOpacity = 0.6
	}: {
		device: Device | null;
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		tool?: string;
		onEdited?: () => void;
		onDrawn?: (shape: Record<string, unknown>) => void;
		onTextAt?: (at: { x: number; y: number }) => void;
		/** Aan tijdens bijsnijden: het sleepkader knipt in plaats van te selecteren. */
		cropping?: boolean;
		onCrop?: (rect: { x: number; y: number; width: number; height: number }) => void;
		onPath?: (points: number[][], closed: boolean) => Promise<void> | void;
		/** Bron van het camerabeeld, of null als de camera uit staat. */
		cameraSrc?: string | null;
		cameraOpacity?: number;
	} = $props();

	const FALLBACK = { width: 500, height: 300 };

	let bed = $derived({
		width: device?.bed?.width_mm ?? FALLBACK.width,
		height: device?.bed?.height_mm ?? FALLBACK.height
	});

	// Passend: het bed vult 640px breed. Zoom en pan komen daar bovenop, zodat
	// werken op een bed van 500x300 mm niet betekent dat je op 2px per mm zit.
	let fitScale = $derived(640 / bed.width);
	let zoom = $state(1);
	let pan = $state({ x: 0, y: 0 });
	let scale = $derived(fitScale * zoom);

	function zoomAt(factor: number, clientX?: number, clientY?: number) {
		const next = Math.min(20, Math.max(0.2, zoom * factor));
		if (next === zoom) return;
		if (clientX !== undefined && clientY !== undefined && frame) {
			// Houd het punt onder de cursor op zijn plek.
			const rect = frame.getBoundingClientRect();
			const px = clientX - rect.left - pan.x;
			const py = clientY - rect.top - pan.y;
			const ratio = next / zoom;
			pan = { x: pan.x - px * (ratio - 1), y: pan.y - py * (ratio - 1) };
		}
		zoom = next;
	}

	function fit() {
		zoom = 1;
		pan = { x: 0, y: 0 };
	}

	let frame = $state<HTMLElement | null>(null);
	let panning = $state<{ x: number; y: number; from: { x: number; y: number } } | null>(null);

	function startPan(event: PointerEvent) {
		panning = { x: event.clientX, y: event.clientY, from: { ...pan } };
		(event.target as Element).setPointerCapture?.(event.pointerId);
	}

	function movePan(event: PointerEvent) {
		if (!panning) return;
		pan = {
			x: panning.from.x + (event.clientX - panning.x),
			y: panning.from.y + (event.clientY - panning.y)
		};
	}
	let head = $derived(device?.position.mm ?? null);
	let selection = $derived(design.selectedSize);

	// Alleen bij precies één geselecteerde lijn: die bewerk je op zijn punten.
	let selectedLine = $derived(
		design.selectedIds.length === 1 ? (design.selected?.line ?? null) : null
	);
	let endpointDrag = $state<{ index: number } | null>(null);
	let lineHandles = $derived.by(() => {
		if (!selectedLine || !canEdit) return null;
		const live = endpointPreview ?? selectedLine;
		return [
			{ x: live.x1_mm, y: live.y1_mm },
			{ x: live.x2_mm, y: live.y2_mm }
		];
	});
	let endpointPreview = $state<
		{ x1_mm: number; y1_mm: number; x2_mm: number; y2_mm: number } | null
	>(null);

	function startEndpoint(event: PointerEvent, index: number) {
		if (!selectedLine) return;
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		endpointDrag = { index };
		endpointPreview = { ...selectedLine };
	}

	function moveEndpoint(event: PointerEvent) {
		if (!endpointDrag || !endpointPreview) return;
		const at = pointerMm(event, true);
		endpointPreview =
			endpointDrag.index === 0
				? { ...endpointPreview, x1_mm: at.x, y1_mm: at.y }
				: { ...endpointPreview, x2_mm: at.x, y2_mm: at.y };
	}

	async function endEndpoint() {
		const drag = endpointDrag;
		const target = endpointPreview;
		endpointDrag = null;
		endpointPreview = null;
		if (!drag || !target || !design.selectedId) return;
		await edits.updateLine(design.selectedId, target);
		onEdited?.();
	}

	// Knooppunten: de punten van de vorm zelf, niet het omhullende kader. Ze
	// komen van de API omdat de engine de vorm als segmenten bewaart en een
	// rechthoek pas punten krijgt zodra je er een pad van maakt.
	let nodePoints = $state<{ index: number; x_mm: number; y_mm: number }[]>([]);
	let nodeDrag = $state<{ index: number; x: number; y: number } | null>(null);

	$effect(() => {
		const id = tool === 'nodes' && design.selectedIds.length === 1 ? design.selectedId : null;
		// design.revision: na een wijziging kunnen de punten verschoven zijn.
		void design.revision;
		if (!id) {
			nodePoints = [];
			return;
		}
		let cancelled = false;
		fetch(`/api/design/elements/${encodeURIComponent(id)}/nodes`)
			.then((r) => (r.ok ? r.json() : null))
			.then((data) => {
				if (!cancelled) nodePoints = data?.editable ? data.points : [];
			});
		return () => {
			cancelled = true;
		};
	});

	// De pen: klikken zet een punt, Enter of een klik op het beginpunt sluit af.
	// Escape gooit weg wat er staat — halverwege stoppen moet zonder rommel.
	let penPoints = $state<{ x: number; y: number }[]>([]);

	function penClick(at: { x: number; y: number }) {
		const first = penPoints[0];
		if (first && penPoints.length > 2 && Math.hypot(at.x - first.x, at.y - first.y) < 3) {
			finishPen(true);
			return;
		}
		penPoints = [...penPoints, at];
	}

	async function finishPen(closed: boolean) {
		const points = penPoints;
		penPoints = [];
		if (points.length < 2) return;
		await onPath?.(points.map((p) => [p.x, p.y]), closed);
	}

	// Meten: twee klikken, en de afstand blijft staan tot je opnieuw begint.
	// Nuttig om te controleren of een uitsparing echt past voordat je snijdt.
	let measureFrom = $state<{ x: number; y: number } | null>(null);
	let measureTo = $state<{ x: number; y: number } | null>(null);

	let measured = $derived.by(() => {
		if (!measureFrom || !measureTo) return null;
		const dx = measureTo.x - measureFrom.x;
		const dy = measureTo.y - measureFrom.y;
		return { dx, dy, length: Math.hypot(dx, dy) };
	});

	function startNode(event: PointerEvent, index: number) {
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);
		const point = nodePoints.find((p) => p.index === index);
		if (point) nodeDrag = { index, x: point.x_mm, y: point.y_mm };
	}

	function moveNode(event: PointerEvent) {
		if (!nodeDrag) return;
		const at = pointerMm(event, true);
		nodeDrag = { ...nodeDrag, x: at.x, y: at.y };
	}

	async function endNode() {
		const drag = nodeDrag;
		nodeDrag = null;
		const id = design.selectedId;
		if (!drag || !id) return;
		const moved = await edits.moveNode(id, drag.index, drag.x, drag.y);
		// Een vorm wordt bij het verslepen een pad en krijgt dan een nieuw id;
		// zonder dit verliest de gebruiker zijn selectie midden in het werk.
		if (moved?.id && moved.id !== id) design.select(moved.id);
		onEdited?.();
	}

	// Slepen. De voorbeeld-offset is puur visueel; pas bij loslaten gaat er één
	// opdracht naar de engine, zodat we hem niet met tussenstanden bestoken.
	type Drag = {
		mode: 'move' | 'scale' | 'rotate';
		corner: number;
		startX: number;
		startY: number;
		dx: number;
		dy: number;
		/** Alleen bij roteren: middelpunt op het scherm en de gedraaide hoek. */
		centerX: number;
		centerY: number;
		startAngle: number;
		angle: number;
		origin: { x: number; y: number; width: number; height: number };
	};
	let drag = $state<Drag | null>(null);

	let preview = $derived.by(() => {
		if (!drag || !selection) return null;
		// Bij roteren blijft het kader waar het staat; alleen de draaiing is
		// voorvertoning. De echte bounds kunnen we pas na de engine weten.
		if (drag.mode === 'rotate') return { ...drag.origin };
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
	let rotation = $derived(drag?.mode === 'rotate' ? drag.angle : 0);
	let center = $derived(
		outline ? { x: outline.x + outline.width / 2, y: outline.y + outline.height / 2 } : null
	);

	// Deel de voorvertoning zodat de bovenbalk de coördinaten live meetelt.
	$effect(() => {
		design.preview = preview;
	});

	/** Waar op het bed is geklikt, in millimeters. */
	function pointerMm(event: MouseEvent, fromChild = false) {
		const target = event.currentTarget as SVGElement;
		const svg = fromChild ? target.ownerSVGElement : (target as SVGSVGElement);
		const rect = (svg ?? target).getBoundingClientRect();
		return {
			x: ((event.clientX - rect.left) / rect.width) * bed.width,
			y: ((event.clientY - rect.top) / rect.height) * bed.height
		};
	}

	// Klik plaatst een vorm van een vaste maat; daarna sleep of schaal je hem.
	// Slepen om te tekenen komt samen met de sleepselectie.
	const DEFAULT_MM = 20;

	// Eerste punt van een lijn in aanbouw, plus waar de muis nu is voor de
	// voorvertoning.
	let lineStart = $state<{ x: number; y: number } | null>(null);
	let hover = $state<{ x: number; y: number } | null>(null);

	$effect(() => {
		if (tool !== 'line') lineStart = null;
	});

	function drawAt(event: MouseEvent) {
		const at = pointerMm(event);
		const half = DEFAULT_MM / 2;
		if (tool === 'rect') {
			onDrawn?.({
				type: 'rect',
				x_mm: at.x - half,
				y_mm: at.y - half,
				width_mm: DEFAULT_MM,
				height_mm: DEFAULT_MM
			});
		} else if (tool === 'circle') {
			onDrawn?.({ type: 'circle', cx_mm: at.x, cy_mm: at.y, r_mm: half });
		} else if (tool === 'line') {
			// Een lijn heeft twee punten: eerste klik zet het begin, tweede het
			// eind. Een vaste horizontale lijn plaatsen was onzin.
			if (!lineStart) {
				lineStart = at;
				return;
			}
			const from = lineStart;
			lineStart = null;
			onDrawn?.({ type: 'line', x1_mm: from.x, y1_mm: from.y, x2_mm: at.x, y2_mm: at.y });
		} else if (tool === 'text') {
			// De opties (lettertype, hoogte, spatiëring) komen uit een eigen
			// venster; een browserprompt kan alleen een kale regel tekst.
			onTextAt?.({ x: at.x, y: at.y });
		}
	}

	function mmPerPixel() {
		return 1 / scale;
	}

	function startDrag(event: PointerEvent, mode: 'move' | 'scale' | 'rotate', corner = 0) {
		if (!canEdit || !selection) return;
		event.stopPropagation();
		(event.target as Element).setPointerCapture?.(event.pointerId);

		// Voor roteren hebben we het middelpunt in schermcoördinaten nodig; het
		// canvas schaalt mm naar pixels, dus reken die om via de SVG-rect.
		const svg = (event.target as SVGElement).ownerSVGElement;
		const rect = svg?.getBoundingClientRect();
		const cx = rect ? rect.left + ((selection.x + selection.width / 2) / bed.width) * rect.width : 0;
		const cy = rect ? rect.top + ((selection.y + selection.height / 2) / bed.height) * rect.height : 0;

		drag = {
			mode,
			corner,
			startX: event.clientX,
			startY: event.clientY,
			dx: 0,
			dy: 0,
			centerX: cx,
			centerY: cy,
			startAngle: Math.atan2(event.clientY - cy, event.clientX - cx),
			angle: 0,
			origin: { ...selection }
		};
	}

	function moveDrag(event: PointerEvent) {
		if (!drag) return;
		if (drag.mode === 'rotate') {
			const now = Math.atan2(event.clientY - drag.centerY, event.clientX - drag.centerX);
			let degrees = ((now - drag.startAngle) * 180) / Math.PI;
			// Shift klikt vast op stappen van 15 graden.
			if (event.shiftKey) degrees = Math.round(degrees / 15) * 15;
			drag.angle = degrees;
			return;
		}
		drag.dx = (event.clientX - drag.startX) * mmPerPixel();
		drag.dy = (event.clientY - drag.startY) * mmPerPixel();
	}

	async function endDrag(event: PointerEvent) {
		if (!drag) return;
		const finished = drag;
		const target = preview;
		drag = null;
		design.preview = null;
		if (design.selectedIds.length === 0 || !target) return;

		if (finished.mode === 'rotate') {
			// Onder een halve graad is het getril, geen rotatie.
			if (Math.abs(finished.angle) >= 0.5) {
				await edits.rotate(design.selectedIds, finished.angle);
				onEdited?.();
			}
			return;
		}

		// Onder een halve pixel is het een klik, geen sleep.
		if (Math.abs(finished.dx) < 0.05 && Math.abs(finished.dy) < 0.05) return;

		if (finished.mode === 'move') {
			await edits.move(design.selectedIds, finished.dx, finished.dy);
		} else if (target.width > 0.1 && target.height > 0.1) {
			await edits.resize(design.selectedIds, target.x, target.y, target.width, target.height);
		}
		onEdited?.();
	}

	// Sleepselectie: alles wat het kader raakt, wordt geselecteerd.
	let band = $state<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
	// Na het loslaten vuurt er nog een klik op dezelfde plek. Zonder deze vlag
	// wist die de selectie die het sleepkader net gemaakt heeft.
	let bandJustEnded = false;

	function startBand(event: PointerEvent) {
		const at = pointerMm(event);
		band = { x1: at.x, y1: at.y, x2: at.x, y2: at.y };
		(event.target as Element).setPointerCapture?.(event.pointerId);
	}

	function moveBand(event: PointerEvent) {
		if (!band) return;
		const at = pointerMm(event);
		band = { ...band, x2: at.x, y2: at.y };
	}

	function endBand() {
		if (!band) return;
		const box = {
			x0: Math.min(band.x1, band.x2),
			y0: Math.min(band.y1, band.y2),
			x1: Math.max(band.x1, band.x2),
			y1: Math.max(band.y1, band.y2)
		};
		const dragged = box.x1 - box.x0 > 0.5 || box.y1 - box.y0 > 0.5;
		band = null;
		if (!dragged || !design.design) return;
		bandJustEnded = true;

		if (cropping) {
			cropping = false;
			onCrop?.({
				x: box.x0,
				y: box.y0,
				width: box.x1 - box.x0,
				height: box.y1 - box.y0
			});
			return;
		}

		const perMm = design.design.units_per_mm;
		const hit = design.elements.filter((element) => {
			if (!element.bounds || element.hidden) return false;
			const [ex0, ey0, ex1, ey1] = element.bounds.map((v) => v / perMm);
			// Overlap, niet volledig omsluiten: zo hoef je niet exact te slepen.
			return ex0 <= box.x1 && ex1 >= box.x0 && ey0 <= box.y1 && ey1 >= box.y0;
		});
		design.selectMany(hit.map((element) => element.id));
	}

	// Linialen. Twee dingen die de vorige versie niet deed: de streepjes staan
	// op het bed uitgelijnd (het bed wordt gecentreerd én gepand, dus alleen de
	// pan verrekenen klopt niet), en de stapgrootte volgt de zoom — op 50 mm
	// vast zie je uitgezoomd een muur van cijfers en ingezoomd bijna niets.
	let canvasWidth = $state(0);
	let canvasHeight = $state(0);

	const STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500];
	/** Breedte van de liniaalstrook; ook in de CSS gebruikt. */
	const RULER = 20;

	/** Linkerbovenhoek van het bed in schermpixels, binnen het canvasvlak. */
	let bedOrigin = $derived({
		x: (canvasWidth - bed.width * scale) / 2 + pan.x,
		y: (canvasHeight - bed.height * scale) / 2 + pan.y
	});

	/** De kleinste stap waarbij twee labels minstens 55 px uit elkaar staan. */
	let rulerStep = $derived(STEPS.find((step) => step * scale >= 55) ?? 500);

	function ticks(lengthMm: number, step: number) {
		const marks = [];
		for (let value = 0; value <= lengthMm + 0.001; value += step / 5) {
			const major = Math.abs(value % step) < 0.001;
			marks.push({ value, major, label: major ? String(Math.round(value)) : '' });
		}
		return marks;
	}

	let ticksX = $derived(ticks(bed.width, rulerStep));
	let ticksY = $derived(ticks(bed.height, rulerStep));

	/** Waar de muis staat, als streepje op beide linialen. */
	let pointer = $state<{ x: number; y: number } | null>(null);

	// Niet via pointerMm: die rekent vanaf de SVG, en dit gebeurt op het
	// omhullende vlak dat óók de linialen bevat. Rekenen vanaf de bedhoek.
	function pointerOnRulers(event: PointerEvent) {
		if (!frame) return null;
		const rect = frame.getBoundingClientRect();
		return {
			x: (event.clientX - rect.left - RULER - bedOrigin.x) / scale,
			y: (event.clientY - rect.top - RULER - bedOrigin.y) / scale
		};
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (tool !== 'pen' || !penPoints.length) return;
		if (e.key === 'Enter') {
			e.preventDefault();
			finishPen(false);
		} else if (e.key === 'Escape') {
			e.preventDefault();
			penPoints = [];
		}
	}}
/>

<!-- Wiel zoomt, alt of middelste knop pant. Toetsenbord: de zoomknoppen
     rechtsonder zijn gewone knoppen. -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="canvas-wrap"
	bind:this={frame}
	onwheel={(e) => {
		e.preventDefault();
		zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY);
	}}
	onpointerdown={(e) => {
		// Middelste knop of alt: slepen om te pannen.
		if (e.button === 1 || e.altKey) {
			e.preventDefault();
			startPan(e);
		}
	}}
	onpointermove={(e) => {
		movePan(e);
		pointer = pointerOnRulers(e);
	}}
	onpointerleave={() => (pointer = null)}
	onpointerup={() => (panning = null)}
>
	<div class="corner" aria-hidden="true">mm</div>
	<svg class="ruler-x" aria-hidden="true">
		{#each ticksX as tick (tick.value)}
			{@const at = bedOrigin.x + tick.value * scale}
			{#if at >= -40 && at <= canvasWidth + 40}
				<line x1={at} x2={at} y1={tick.major ? 8 : 14} y2="20" />
				{#if tick.label}
					<text x={at + 2} y="9">{tick.label}</text>
				{/if}
			{/if}
		{/each}
		{#if pointer}
			<line class="here" x1={bedOrigin.x + pointer.x * scale} x2={bedOrigin.x + pointer.x * scale} y1="0" y2="20" />
		{/if}
	</svg>
	<svg class="ruler-y" aria-hidden="true">
		{#each ticksY as tick (tick.value)}
			{@const at = bedOrigin.y + tick.value * scale}
			{#if at >= -40 && at <= canvasHeight + 40}
				<line y1={at} y2={at} x1={tick.major ? 8 : 14} x2="20" />
				{#if tick.label}
					<text x="2" y={at - 2} transform="rotate(-90 2 {at - 2})">{tick.label}</text>
				{/if}
			{/if}
		{/each}
		{#if pointer}
			<line class="here" y1={bedOrigin.y + pointer.y * scale} y2={bedOrigin.y + pointer.y * scale} x1="0" x2="20" />
		{/if}
	</svg>

	<div class="canvas" bind:clientWidth={canvasWidth} bind:clientHeight={canvasHeight}>
		<div
			class="bed"
			style="width: {bed.width * scale}px; height: {bed.height * scale}px;
			       background-size: {50 * scale}px {50 * scale}px;
			       transform: translate({pan.x}px, {pan.y}px)"
		>
			{#if cameraSrc}
				<!-- Het beeld is al rechtgetrokken naar de bedrechthoek door de
				     cameraplugin, dus het past één-op-één op het bed. Een gewone
				     <img> met een MJPEG-bron: de browser decodeert zelf, wij
				     hoeven niets te verversen. -->
				<img
					class="camera"
					src={cameraSrc}
					alt="Camerabeeld van het bed"
					style="opacity: {cameraOpacity}"
				/>
			{/if}

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
				style="position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible"
				role="img"
				aria-label={head
					? `Laserkop op ${head[0].toFixed(1)}, ${head[1].toFixed(1)} millimeter`
					: 'Positie van de laserkop onbekend'}
				onclick={(e) => {
					if (e.target !== e.currentTarget) return;
					if (tool === 'pen' && canEdit) {
						penClick(pointerMm(e));
						return;
					}
					if (tool === 'measure') {
						const at = pointerMm(e);
						if (!measureFrom || measureTo) {
							measureFrom = at;
							measureTo = null;
						} else {
							measureTo = at;
						}
						return;
					}
					if (tool !== 'select' && tool !== 'nodes' && tool !== 'pen' && canEdit) {
						drawAt(e);
						return;
					}
					// Klikken naast een element heft de selectie op — behalve de klik
					// die direct volgt op een sleepkader.
					if (bandJustEnded) {
						bandJustEnded = false;
						return;
					}
					design.select(null);
				}}
				onpointerdown={(e) => {
					if (cropping && e.button === 0) {
						startBand(e);
						return;
					}
					if (e.target === e.currentTarget && tool === 'select' && !e.altKey && e.button === 0) {
						startBand(e);
					}
				}}
				onpointermove={(e) => {
					if (tool === 'measure' && measureFrom && !measureTo) hover = pointerMm(e);
					if (tool === 'pen' && penPoints.length) hover = pointerMm(e);
					if (lineStart) hover = pointerMm(e);
					moveBand(e);
				}}
				onpointerup={endBand}
			>
				<!-- Het ontwerp. Eén schaaltransform rekent Tats om naar mm; de
				     paddata zelf blijft onaangeroerd zoals de engine hem gaf. -->
				{#if design.design}
					<g transform="scale({1 / design.design.units_per_mm})">
						{#each design.elements as element (element.id)}
							{#if !element.hidden && element.image}
								<!-- Afbeeldingen hebben geen pad; de pixels komen van de API.
								     De transform hierboven rekent in Tats, dus terugschalen. -->
								<image
									href="/api/design/elements/{encodeURIComponent(element.id)}/image.png?v={design.revision}"
									x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
									y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
									width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
									height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
									preserveAspectRatio="none"
								/>
								<rect
									class="hit"
									role="button"
									tabindex="0"
									aria-label="Selecteer afbeelding"
									x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
									y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
									width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
									height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
									fill="transparent"
									onclick={(e) => {
										e.stopPropagation();
										if (e.shiftKey) design.toggle(element.id);
										else design.select(element.id);
									}}
									onkeydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											design.select(element.id);
										}
									}}
								/>
							{:else if !element.hidden}
								<path
									d={element.path}
									fill="none"
									stroke={element.stroke ?? 'var(--text-2)'}
									stroke-width={design.isSelected(element.id) ? 2 : 1.2}
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
									aria-pressed={design.isSelected(element.id)}
									onclick={(e) => {
										e.stopPropagation();
										// Shift houdt de bestaande selectie vast.
										if (e.shiftKey) design.toggle(element.id);
										else design.select(element.id);
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
						<!-- Tijdens het roteren draait het hele kader mee als voorvertoning;
						     de echte vorm volgt zodra de engine het heeft toegepast. -->
						<g
							class="selection"
							transform={rotation && center
								? `rotate(${rotation} ${center.x} ${center.y})`
								: undefined}
						>
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
							{#if canEdit && center}
							<!-- Rotatiegreep: een steel boven het kader, zoals bij resizen
							     een hoekgreep. Shift klikt vast op 15 graden. -->
							<line
								class="stalk"
								x1={center.x}
								y1={outline.y}
								x2={center.x}
								y2={outline.y - 8}
							/>
							<circle
								class="rotator"
								cx={center.x}
								cy={outline.y - 8}
								r="2"
							/>
							<!-- Ruimere trefzone eromheen: 2 mm is bij deze schaal maar een
							     paar pixels, en dat is niet te pakken met een muis, laat
							     staan met een vinger. -->
							<circle
								class="rotator-hit"
								role="button"
								tabindex="-1"
								aria-label="Sleep om te draaien"
								cx={center.x}
								cy={outline.y - 8}
								r="5"
								onpointerdown={(e) => startDrag(e, 'rotate')}
								onpointermove={moveDrag}
								onpointerup={endDrag}
							/>
						{/if}
						<!-- Bij een lijn zijn de eindpunten de grepen; hoekgrepen van een
						     denkbeeldig kader zouden daar bovenop liggen. -->
						{#each selectedLine ? [] : [[outline.x, outline.y], [outline.x + outline.width, outline.y], [outline.x, outline.y + outline.height], [outline.x + outline.width, outline.y + outline.height]] as [hx, hy], corner (corner)}
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

				{#if lineStart && hover}
					<line
						class="pending"
						x1={lineStart.x}
						y1={lineStart.y}
						x2={hover.x}
						y2={hover.y}
					/>
				{/if}

				{#if endpointPreview}
					<!-- De lijn zelf volgt de greep tijdens het slepen; alleen een
					     verspringend bolletje zegt niets over wat je maakt. -->
					<line
						class="pending"
						x1={endpointPreview.x1_mm}
						y1={endpointPreview.y1_mm}
						x2={endpointPreview.x2_mm}
						y2={endpointPreview.y2_mm}
					/>
					<text
						class="mono measure"
						x={(endpointPreview.x1_mm + endpointPreview.x2_mm) / 2}
						y={(endpointPreview.y1_mm + endpointPreview.y2_mm) / 2 - 3}
						text-anchor="middle"
					>
						{Math.hypot(
							endpointPreview.x2_mm - endpointPreview.x1_mm,
							endpointPreview.y2_mm - endpointPreview.y1_mm
						).toFixed(1)} mm
					</text>
				{/if}

				{#if lineHandles}
					<!-- Een lijn pak je bij een eindpunt, niet bij een hoek van een
					     denkbeeldig kader. -->
					{#each lineHandles as point, index (index)}
						<circle
							class="endpoint"
							role="button"
							tabindex="-1"
							aria-label="Eindpunt {index + 1} verslepen"
							cx={point.x}
							cy={point.y}
							r="2.5"
							onpointerdown={(e) => startEndpoint(e, index)}
							onpointermove={moveEndpoint}
							onpointerup={endEndpoint}
						/>
					{/each}
				{/if}

				{#if tool === 'nodes' && nodePoints.length}
					{#each nodePoints as point (point.index)}
						{@const live = nodeDrag?.index === point.index ? nodeDrag : null}
						<circle
							class="knot"
							role="button"
							tabindex="-1"
							aria-label="Knooppunt {point.index + 1} verslepen"
							cx={live ? live.x : point.x_mm}
							cy={live ? live.y : point.y_mm}
							r="2.5"
							onpointerdown={(e) => startNode(e, point.index)}
							onpointermove={moveNode}
							onpointerup={endNode}
						/>
					{/each}
				{/if}

				{#if tool === 'pen' && penPoints.length}
					{@const live = hover ? [...penPoints, hover] : penPoints}
					<polyline
						class="pen-line"
						points={live.map((p) => `${p.x},${p.y}`).join(' ')}
						fill="none"
					/>
					{#each penPoints as point, index (index)}
						<circle class="pen-dot" cx={point.x} cy={point.y} r="1.6" />
					{/each}
				{/if}

				{#if tool === 'measure' && measureFrom}
					{@const to = measureTo ?? hover ?? measureFrom}
					<line
						class="measure"
						x1={measureFrom.x}
						y1={measureFrom.y}
						x2={to.x}
						y2={to.y}
					/>
					<text
						class="measure-label"
						x={(measureFrom.x + to.x) / 2}
						y={(measureFrom.y + to.y) / 2 - 2}
						text-anchor="middle"
					>
						{Math.hypot(to.x - measureFrom.x, to.y - measureFrom.y).toFixed(1)} mm
					</text>
				{/if}

				{#if cropping}
					<!-- Vangt de muis af, anders start het slepen op de afbeelding zelf. -->
					<rect
						class="crop-catch"
						x="0"
						y="0"
						width={bed.width}
						height={bed.height}
						onpointerdown={(e) => startBand(e as PointerEvent)}
						onpointermove={(e) => moveBand(e as PointerEvent)}
						onpointerup={endBand}
						role="presentation"
					/>
				{/if}
				{#if band}
					<rect
						class="band"
						x={Math.min(band.x1, band.x2)}
						y={Math.min(band.y1, band.y2)}
						width={Math.abs(band.x2 - band.x1)}
						height={Math.abs(band.y2 - band.y1)}
					/>
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

	<div class="zoom">
		<button title="Uitzoomen" aria-label="Uitzoomen" onclick={() => zoomAt(1 / 1.25)}>−</button>
		<button class="val mono" title="Passend maken" onclick={fit}>{Math.round(zoom * 100)}%</button>
		<button title="Inzoomen" aria-label="Inzoomen" onclick={() => zoomAt(1.25)}>+</button>
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
		/* Zonder dit valt een inline SVG terug op zijn standaardmaat van
		   300x150 en houdt de liniaal halverwege op. */
		display: block;
		width: 100%;
		height: 100%;
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
		width: calc(100% - 20px);
		height: 20px;
		border-bottom: 1px solid var(--line);
	}
	.ruler-y {
		top: 20px;
		left: 0;
		width: 20px;
		height: calc(100% - 20px);
		border-right: 1px solid var(--line);
	}
	.ruler-x line,
	.ruler-y line {
		stroke: var(--line-strong, var(--line));
		stroke-width: 1;
		shape-rendering: crispEdges;
	}
	.ruler-x .here,
	.ruler-y .here {
		stroke: var(--accent);
	}
	.ruler-x text,
	.ruler-y text {
		fill: var(--text-2);
		font-size: 9px;
		font-family: var(--font-mono);
		dominant-baseline: hanging;
	}
	.corner {
		position: absolute;
		top: 0;
		left: 0;
		width: 20px;
		height: 20px;
		z-index: 3;
		display: grid;
		place-items: center;
		font-size: 8px;
		font-family: var(--font-mono);
		color: var(--text-2);
		background: var(--surface-1);
		border-right: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
		user-select: none;
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
	.camera {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: fill;
		pointer-events: none;
		user-select: none;
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
	.pending {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.pen-line {
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
	}
	.pen-dot { fill: var(--accent); }
	.measure {
		fill: var(--text-2);
		font-size: 3.5px;
	}
	.endpoint {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		cursor: grab;
	}
	.pen-line {
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
	}
	.pen-dot { fill: var(--accent); }
	.measure {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 3 2;
		vector-effect: non-scaling-stroke;
	}
	.measure-label {
		font-size: 4px;
		fill: var(--accent);
		font-family: var(--font-mono, monospace);
	}
	.knot {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		cursor: grab;
	}
	.knot:hover { fill: var(--accent); }
	.crop-catch {
		fill: rgb(0 0 0 / 0.18);
		cursor: crosshair;
	}
	.band {
		fill: color-mix(in srgb, var(--accent) 12%, transparent);
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.zoom {
		position: absolute;
		right: var(--space-3);
		bottom: var(--space-3);
		display: flex;
		gap: 2px;
		padding: 2px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		box-shadow: var(--shadow-float);
		z-index: 3;
	}
	.zoom button {
		min-width: 28px;
		height: 28px;
		border-radius: 4px;
		color: var(--text-2);
	}
	.zoom button:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.zoom .val {
		font-size: 11px;
		padding: 0 6px;
		color: var(--text-1);
	}
	/* De globale :focus-visible-regel uit tokens.css tekent een outline van 2 px
	   met offset. Op een SVG-vorm rendert die als rechthoek om de bounding box,
	   en juist tijdens het slepen ligt de focus op het sleepvlak of een
	   hoekgreep — dat gaf een dikke rand om de hele selectie. Hier dus uit voor
	   alle vormen in het canvas; wat geselecteerd is blijft zichtbaar via de
	   kerflijn-contour, ook bij toetsenbordbediening. */
	svg :focus,
	svg :focus-visible {
		outline: none;
	}
	/* Toetsenbordfocus blijft wel zichtbaar: zonder muis moet je kunnen zien
	   welk element je op het punt staat te selecteren. */
	.hit:focus-visible {
		stroke: color-mix(in srgb, var(--accent) 30%, transparent);
		stroke-width: 4;
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
	.selection .stalk {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: none;
		vector-effect: non-scaling-stroke;
	}
	.selection .rotator {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		cursor: grab;
	}
	.selection .rotator {
		pointer-events: none;
	}
	.selection .rotator-hit {
		fill: transparent;
		stroke: none;
		cursor: grab;
	}
	.selection .rotator-hit:active {
		cursor: grabbing;
	}
	/* `rect.grab` en niet `.grab`: `.selection rect` hierboven is specifieker en
	   won anders, waardoor het sleepvlak dezelfde gestreepte accentlijn kreeg
	   als de contour. Twee strepen over elkaar, en tijdens het slepen animeert
	   alleen de contour — dan lopen ze uit fase en loopt de rand dicht tot een
	   dikke balk. */
	.selection rect.grab {
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
