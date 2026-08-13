<script lang="ts">
	import { currentJob } from '$lib/api';
	import type { Device } from '$lib/api';
	import { kopspoor } from '$lib/status.svelte';
	import { nulpunt } from '$lib/control.svelte';
	import type { DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import LagenPalet from './LagenPalet.svelte';
	import {
		omgevingstrefpunten,
		klikDoosVast,
		klikPuntVast,
		SNAP_LABEL,
		type SnapGuide
	} from '$lib/snapping';

	let {
		onPointerMm,
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
		cameraOpacity = 0.6,
		sheet = null
	}: {
		/** Waar de muis staat, in mm op het bed. `null` als hij weg is. */
		onPointerMm?: (punt: { x: number; y: number } | null) => void;
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
		/** Het actieve vel: het stuk materiaal binnen het bed. */
		sheet?: { name: string; width: number; height: number } | null;
	} = $props();

	const FALLBACK = { width: 500, height: 300 };

	// Boven de afgeleiden die hem gebruiken: de schaal hangt van de werkelijke
	// maat van het werkvlak af, niet andersom.
	let canvasWidth = $state(0);
	let canvasHeight = $state(0);

	let bed = $derived({
		width: device?.bed?.width_mm ?? FALLBACK.width,
		height: device?.bed?.height_mm ?? FALLBACK.height
	});

	/** Lucht tussen het bed en de rand van het werkvlak, in schermpixels. */
	const MARGE = 32;

	// Passend betekent: het bed vult het werkvlak dat er is. Een vaste 640px
	// (wat hier stond) laat op een breed scherm tweederde ongebruikt en loopt op
	// een tablet juist onder het rechterpaneel door — het bed werd afgesneden.
	let fitScale = $derived(
		Math.min(
			(Math.max(canvasWidth, 320) - MARGE * 2) / bed.width,
			(Math.max(canvasHeight, 240) - MARGE * 2) / bed.height
		)
	);
	let zoom = $state(1);
	let pan = $state({ x: 0, y: 0 });
	let scale = $derived(fitScale * zoom);

	/** Eén schermpixel, uitgedrukt in millimeters. */
	let mmPerPx = $derived(1 / scale);

	// Tekst in de bed-SVG rekent in millimeters, dus een vaste maat groeit mee
	// met de zoom: bij tien keer inzoomen wordt een label tien keer zo groot en
	// legt het het halve werkstuk toe. Terugrekenen naar een constante
	// schermmaat is de enige maat die klopt.
	let labelSize = $derived(11 / scale);

	// Dezelfde val als bij het label: een greep van "2.4" in een SVG die in
	// millimeters meet is 2,4 mm, dus 5 px uitgezoomd en 50 px ingezoomd. Alles
	// wat je met een muis of vinger moet raken rekenen we daarom terug naar
	// schermpixels. Maten in px: greep 10, trefzone 24 (raakdoel), steel 16.
	// Met een vinger is 24 px te klein; het ontwerpsysteem eist 44 px raakdoel op
	// aanraakschermen. De greep zelf blijft even klein — die moet je zien, niet
	// raken.
	let grofAanwijzen = $state(false);
	$effect(() => {
		if (typeof window === 'undefined' || !window.matchMedia) return;
		const vraag = window.matchMedia('(pointer: coarse)');
		grofAanwijzen = vraag.matches;
		const luister = () => (grofAanwijzen = vraag.matches);
		vraag.addEventListener('change', luister);
		return () => vraag.removeEventListener('change', luister);
	});

	let handleR = $derived(5 * mmPerPx);
	let hitR = $derived((grofAanwijzen ? 22 : 12) * mmPerPx);
	let stalk = $derived((grofAanwijzen ? 26 : 16) * mmPerPx);

	function zoomAt(factor: number, clientX?: number, clientY?: number) {
		const next = Math.min(20, Math.max(0.2, zoom * factor));
		if (next === zoom) return;
		if (clientX !== undefined && clientY !== undefined && frame) {
			// Houd het punt onder de cursor op zijn plek. Dat vraagt de afstand tot
			// het *midden van het bed*, want daaromheen groeit alles. Er stond de
			// afstand tot de hoek van het canvasvlak, en dat scheelt een halve
			// canvasbreedte: het punt onder de muis liep bij elke tik zo'n 15 px weg.
			// Het midden uitrekenen en niet opmeten: bij een reeks wieltikken loopt
			// de DOM een tik achter, en dan zoomt elke tik naar een punt dat de
			// vorige tik al verschoven had.
			const vlak = frame.getBoundingClientRect();
			const ratio = next / zoom;
			const dx = clientX - (vlak.left + RULER + canvasWidth / 2 + pan.x);
			const dy = clientY - (vlak.top + RULER + canvasHeight / 2 + pan.y);
			pan = { x: pan.x - dx * (ratio - 1), y: pan.y - dy * (ratio - 1) };
		}
		zoom = next;
	}

	/** Terug naar de stand waarin het bed netjes in beeld staat. */
	function honderd() {
		zoom = 1;
		pan = { x: 0, y: 0 };
	}

	/**
	 * Een rechthoek in millimeters vullend in beeld brengen.
	 *
	 * Het bed staat gecentreerd in het vlak; pan verschuift dat. Om een gebied
	 * te centreren rekenen we terug welke pan daarvoor nodig is bij de nieuwe
	 * schaal — anders springt het beeld weg zodra je inzoomt.
	 */
	function fitTo(x: number, y: number, w: number, h: number) {
		if (!canvasWidth || !canvasHeight || w <= 0 || h <= 0) return;
		// canvasWidth is het vlak *binnen* de linialen; die er nog eens van
		// aftrekken maakte alles wat "passend" heette een slag te klein.
		const doel = Math.min(
			(canvasWidth - MARGE * 2) / w,
			(canvasHeight - MARGE * 2) / h
		);
		zoom = Math.min(20, Math.max(0.2, doel / fitScale));

		// Centreren op de gerekende stand klopte niet: er zit meer tussen het
		// meetpunt van `canvasWidth` en de linkerbovenhoek van het bed dan alleen
		// de liniaal. In plaats van die keten na te rekenen (en bij de volgende
		// layoutwijziging weer mis te zitten) meten we ná het tekenen waar het
		// bed écht staat en corrigeren we het verschil in één stap.
		requestAnimationFrame(() => {
			if (!frame) return;
			const vlak = frame.getBoundingClientRect();
			const bedvlak = frame.querySelector('.bed')?.getBoundingClientRect();
			if (!bedvlak) return;
			const perMm = bedvlak.width / bed.width;
			const midX = bedvlak.x + (x + w / 2) * perMm;
			const midY = bedvlak.y + (y + h / 2) * perMm;
			pan = {
				x: pan.x + (vlak.x + vlak.width / 2 - midX),
				y: pan.y + (vlak.y + vlak.height / 2 - midY)
			};
		});
	}

	/** Alles wat er ligt, of het hele bed als er niets ligt. */
	function passend() {
		const doos = omvat(design.elements ?? []);
		if (doos) fitTo(doos.x, doos.y, doos.width, doos.height);
		else fitTo(0, 0, bed.width, bed.height);
	}

	function naarSelectie() {
		const gekozen = (design.elements ?? []).filter((e) => design.isSelected(e.id));
		const doos = omvat(gekozen);
		if (doos) fitTo(doos.x, doos.y, doos.width, doos.height);
	}

	/** De omhullende rechthoek in mm van een verzameling elementen. */
	function omvat(elementen: { bounds: [number, number, number, number] | null }[]) {
		const perMm = design.design?.units_per_mm ?? 1;
		let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
		for (const e of elementen) {
			if (!e.bounds) continue;
			x0 = Math.min(x0, e.bounds[0] / perMm);
			y0 = Math.min(y0, e.bounds[1] / perMm);
			x1 = Math.max(x1, e.bounds[2] / perMm);
			y1 = Math.max(y1, e.bounds[3] / perMm);
		}
		if (!Number.isFinite(x0)) return null;
		// Een enkele lijn heeft geen breedte; geef hem iets om in te passen.
		return { x: x0, y: y0, width: Math.max(x1 - x0, 1), height: Math.max(y1 - y0, 1) };
	}

	/** Alleen met het pijltje pak je vormen op; met een tekengereedschap in de
	 *  hand moet een klik binnen een bestaande vorm gewoon tekenen. */
	let selectTool = $derived(tool === 'select' || tool === 'nodes');

	/** Gereedschappen die iets op een plek zetten; daar hoort vastklikken bij. */
	let tekengereedschap = $derived(
		tool === 'rect' || tool === 'circle' || tool === 'line' || tool === 'text' ||
			tool === 'pen' || tool === 'measure'
	);

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

	// ── Voortgang op het canvas (gat J3) ───────────────────────────────────────
	//
	// De belofte uit DESIGN-SYSTEM v2 was dat de contour zich aftekent terwijl de
	// machine hem snijdt. Wat daarvoor nodig is — de volgorde waarin de engine de
	// vormen afwerkt — komt nergens naar buiten; wij krijgen een percentage en een
	// stroom kopposities. Dus tekenen we wat gemeten is en niet wat mooi is:
	// het spoor dat de kop werkelijk gereden heeft (zie `Kopspoor` in
	// status.svelte.ts), plus de voortgang als ring óm de kop.
	//
	// Wat dit bewust níet doet: doen alsof het een kerf is. Het signaal zegt niet
	// of de laser aan stond, dus de sprong tussen twee vormen staat er net zo goed
	// in. Daarom heet het een spoor, staat het in één dunne lijn en niet in de
	// laagkleur, en zegt de strook onder het canvas in woorden wat je ziet.
	let job = $derived(currentJob(device));
	let voortgang = $derived.by(() => {
		if (!job) return null;
		const deel = job.progress;
		if (deel === null || deel === undefined || !Number.isFinite(deel)) return null;
		return Math.min(1, Math.max(0, deel));
	});

	/** Het spoor in millimeters, klaar om als polyline neer te zetten. */
	let spoor = $derived.by(() => {
		if (!job) return '';
		const punten = kopspoor.punten;
		if (punten.length < 4) return '';
		const perMm = design.design?.units_per_mm ?? 1;
		const stukken = [];
		for (let i = 0; i < punten.length; i += 2) {
			stukken.push(`${(punten[i] / perMm).toFixed(2)},${(punten[i + 1] / perMm).toFixed(2)}`);
		}
		return stukken.join(' ');
	});

	/**
	 * De laatste meter van het spoor, vol aangezet: daar gebeurt het nu.
	 *
	 * Kort houden. Met zestig punten kleurde bij een rechthoek de hele omtrek
	 * op — gemeten op de proefjob — en dan is er geen verschil meer tussen
	 * "hier is hij geweest" en "hier is hij nu", terwijl dat juist het enige is
	 * wat dit stuk toevoegt.
	 */
	const VERS_PUNTEN = 14;
	let spoorKop = $derived.by(() => {
		if (!job) return '';
		const punten = kopspoor.punten;
		if (punten.length < 4) return '';
		const perMm = design.design?.units_per_mm ?? 1;
		const vanaf = Math.max(0, punten.length - 2 * VERS_PUNTEN);
		const stukken = [];
		for (let i = vanaf; i < punten.length; i += 2) {
			stukken.push(`${(punten[i] / perMm).toFixed(2)},${(punten[i + 1] / perMm).toFixed(2)}`);
		}
		return stukken.join(' ');
	});

	/** Straal en omtrek van de voortgangsring, in schermpixels teruggerekend. */
	const RING_PX = 13;
	let ringR = $derived(RING_PX * mmPerPx);
	let ringOmtrek = $derived(2 * Math.PI * ringR);

	// ── Het nulpunt van de gebruiker (gat J12) ─────────────────────────────────
	//
	// Het nulpunt verplaatst het werk op weg naar de machine. Dat mág niet
	// alleen in een paneel staan: dan teken je op de ene plek en brandt het op de
	// andere, en dat is precies het soort verrassing waar deze functie tegen
	// bedoeld is. Op het bed staat daarom het punt zelf én een gestippeld kader
	// waar het werk terechtkomt.
	$effect(() => {
		nulpunt.laad();
	});
	let nulstand = $derived(nulpunt.punt);
	/** Waar het werk komt te liggen: de omhullende, verschoven met het nulpunt. */
	let brandtHier = $derived.by(() => {
		if (!nulstand || (!nulstand.x_mm && !nulstand.y_mm)) return null;
		const doos = omvat(design.elements ?? []);
		if (!doos) return null;
		return { ...doos, x: doos.x + nulstand.x_mm, y: doos.y + nulstand.y_mm };
	});

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
		const at = snapPunt(pointerMm(event, true), event);
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
		guides = [];
		if (!drag || !target || !design.selectedId) return;
		await edits.updateLine(design.selectedId, target);
		onEdited?.();
	}

	// Knooppunten: de punten van de vorm zelf, niet het omhullende kader. Ze
	// komen van de API omdat de engine de vorm als segmenten bewaart en een
	// rechthoek pas punten krijgt zodra je er een pad van maakt.
	let nodePoints = $state<{ index: number; x_mm: number; y_mm: number }[]>([]);
	let nodeDrag = $state<{ index: number; x: number; y: number } | null>(null);
	/**
	 * Waarom er geen knooppunten staan.
	 *
	 * Het gereedschap heeft drie stille standen — niets gekozen, meer dan één
	 * ding gekozen, en een vorm die de engine niet per punt bewerkt — en in alle
	 * drie gebeurde er zichtbaar niets. Het gereedschap stond wel ingedrukt.
	 * Gemeten met twee vormen geselecteerd: het paneel toont de gewone
	 * meervoudsselectie en het woord "knooppunt" komt nergens in beeld voor.
	 * Eén regel onder het bed zegt waar je staat en wat de volgende stap is.
	 */
	let nodeReden = $state<'geen' | 'meerdere' | 'onbewerkbaar' | null>(null);

	$effect(() => {
		const id = tool === 'nodes' && design.selectedIds.length === 1 ? design.selectedId : null;
		// design.revision: na een wijziging kunnen de punten verschoven zijn.
		void design.revision;
		if (!id) {
			nodePoints = [];
			nodeReden =
				tool !== 'nodes' ? null : design.selectedIds.length === 0 ? 'geen' : 'meerdere';
			return;
		}
		let cancelled = false;
		fetch(`/api/design/elements/${encodeURIComponent(id)}/nodes`)
			.then((r) => (r.ok ? r.json() : null))
			.then((data) => {
				if (cancelled) return;
				nodePoints = data?.editable ? data.points : [];
				nodeReden = data?.editable ? null : 'onbewerkbaar';
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
		const at = snapPunt(pointerMm(event, true), event);
		nodeDrag = { ...nodeDrag, x: at.x, y: at.y };
	}

	async function endNode() {
		const drag = nodeDrag;
		nodeDrag = null;
		guides = [];
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

	/**
	 * De vorm zelf laten meelopen tijdens het verplaatsen.
	 *
	 * Alleen het kader bewoog mee en de vorm bleef staan tot de engine antwoordde.
	 * Zolang er niets vastklikte viel dat nauwelijks op; met hulplijnen erbij wél,
	 * want dan wijst de lijn naar een rand die op dat moment ergens anders ligt en
	 * lijkt het vastklikken mis te gaan. De paddata staat in Tats, dus de
	 * verschuiving in mm moet daarheen terug.
	 */
	function verschuiving(id: string) {
		if (!drag || !preview || !design.isSelected(id)) return undefined;
		const per = design.design?.units_per_mm ?? 1;
		if (drag.mode === 'move') return `translate(${drag.dx * per} ${drag.dy * per})`;
		if (drag.mode !== 'scale') return undefined;
		// Schalen gebeurt vanaf de tegenoverliggende hoek; die blijft dus liggen en
		// is het vaste punt van de vergroting.
		const o = drag.origin;
		if (!o.width || !o.height) return undefined;
		const vastX = (drag.corner % 2 === 0 ? o.x + o.width : o.x) * per;
		const vastY = (drag.corner < 2 ? o.y + o.height : o.y) * per;
		const sx = preview.width / o.width;
		const sy = preview.height / o.height;
		return `translate(${vastX} ${vastY}) scale(${sx} ${sy}) translate(${-vastX} ${-vastY})`;
	}

	/**
	 * Het selectiekader, een paar schermpixels ruim om de vorm heen.
	 *
	 * Precies op de contour lag de gestreepte accentlijn over de laagkleur van
	 * het element, en dan zie je niet meer in welke laag het zit. Het kader hoort
	 * eromheen te liggen, niet erop — zo blijven beide leesbaar.
	 */
	let frameBox = $derived.by(() => {
		if (!outline) return null;
		const pad = 5 * mmPerPx;
		return {
			x: Math.min(outline.x, outline.x + outline.width) - pad,
			y: Math.min(outline.y, outline.y + outline.height) - pad,
			width: Math.abs(outline.width) + pad * 2,
			height: Math.abs(outline.height) + pad * 2
		};
	});
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
		// Van gereedschap wisselen laat geen hulplijn achter die nergens meer bij hoort.
		void tool;
		guides = [];
	});

	function drawAt(event: MouseEvent) {
		// Plaatsen klikt net zo goed vast als slepen: een nieuwe vorm hoort op de
		// rasterlijn te landen waar je hem neerzet, niet op 3,7 mm ernaast.
		const at = snapPunt(pointerMm(event), event);
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
		let dx = (event.clientX - drag.startX) * mmPerPixel();
		let dy = (event.clientY - drag.startY) * mmPerPixel();

		if (snapUit(event)) {
			guides = [];
		} else if (drag.mode === 'move') {
			// Verplaatsen: randen én hartlijnen mogen vastklikken, per as apart.
			const uit = klikDoosVast(drag.origin, { dx, dy }, trefpunten, snapRaster, snapTolerantie);
			dx = uit.dx;
			dy = uit.dy;
			guides = uit.guides;
		} else {
			// Schalen: alleen de hoek die je vasthebt. De tegenoverliggende hoek
			// blijft liggen, dus die heeft niets te zoeken tussen de kandidaten.
			const links = drag.corner % 2 === 0;
			const boven = drag.corner < 2;
			const hoek = {
				x: (links ? drag.origin.x : drag.origin.x + drag.origin.width) + dx,
				y: (boven ? drag.origin.y : drag.origin.y + drag.origin.height) + dy
			};
			const uit = klikPuntVast(hoek, trefpunten, snapRaster, snapTolerantie);
			dx += uit.x - hoek.x;
			dy += uit.y - hoek.y;
			guides = uit.guides;
		}

		drag.dx = dx;
		drag.dy = dy;
	}

	async function endDrag(event: PointerEvent) {
		if (!drag) return;
		const finished = drag;
		const target = preview;
		drag = null;
		guides = [];
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

	/**
	 * Waar de muis wordt afgevangen zodra er écht gesleept wordt.
	 *
	 * Niet meteen bij het indrukken: een element dat de muis vangt, krijgt ook
	 * de daaropvolgende klik toegewezen. Vangen we die op de SVG, dan komt elke
	 * klik op een vorm binnen als "klik naast alles" en selecteerde niets meer.
	 * Dus pas vangen als de muis beweegt — dan is het een sleep, geen klik.
	 */
	let bandCatcher: Element | null = null;

	function startBand(event: PointerEvent) {
		const at = pointerMm(event);
		band = { x1: at.x, y1: at.y, x2: at.x, y2: at.y };
		bandCatcher = event.currentTarget as Element;
	}

	function moveBand(event: PointerEvent) {
		if (!band) return;
		const at = pointerMm(event);
		if (bandCatcher && (Math.abs(at.x - band.x1) > 0.5 || Math.abs(at.y - band.y1) > 0.5)) {
			bandCatcher.setPointerCapture?.(event.pointerId);
			bandCatcher = null;
		}
		band = { ...band, x2: at.x, y2: at.y };
	}

	function endBand(event: PointerEvent) {
		bandCatcher = null;
		const held = event.currentTarget as Element;
		// releasePointerCapture gooit als er niets gevangen is; loslaten vóór de
		// klik is nodig, anders wordt die klik alsnog naar de SVG omgeleid.
		if (held?.hasPointerCapture?.(event.pointerId)) held.releasePointerCapture(event.pointerId);
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

	/**
	 * De onderverdeling onder de hoofdstap: het grootste ronde getal dat er heel
	 * in past en dat op het scherm nog uit elkaar te houden is.
	 *
	 * Blind delen door vijf gaf bij een stap van 20 mm een raster van 4 mm — een
	 * maat waar niemand in denkt, en te dicht op elkaar om iets aan af te lezen.
	 */
	let subStep = $derived(
		[...STEPS]
			.filter((s) => s < rulerStep && rulerStep % s === 0 && s * scale >= 12)
			.sort((a, b) => b - a)
			.pop() ?? 0
	);

	/**
	 * Streepjes over de hele liniaal, ook naast het bed (gat C4).
	 *
	 * De schaal hield op bij de bedrand, en dan kun je van een vorm die
	 * ernaast ligt niet aflezen hóe ver ernaast — juist het getal dat je nodig
	 * hebt om hem terug te halen. LightBurn laat de schaal doorlopen met
	 * negatieve waarden; dat doen we hier ook.
	 *
	 * Tellen in stappen en niet in millimeters optellen: `value += 0.1`
	 * driehonderd keer levert 29,999999 op, en dan valt de modulo-toets voor
	 * "is dit een hoofdstreep" willekeurig om.
	 */
	function ticks(fromMm: number, toMm: number, step: number, sub: number, lengthMm: number) {
		const fijn = sub || step;
		const perHoofd = Math.max(1, Math.round(step / fijn));
		const marks: { value: number; major: boolean; buiten: boolean; label: string }[] = [];
		const eerste = Math.ceil(fromMm / fijn - 0.001);
		const laatste = Math.floor(toMm / fijn + 0.001);
		// Bij een absurde zoomstand niet duizenden knopen tekenen.
		if (laatste - eerste > 400) return marks;
		for (let i = eerste; i <= laatste; i++) {
			const value = i * fijn;
			const major = ((i % perHoofd) + perHoofd) % perHoofd === 0;
			marks.push({
				value,
				major,
				// Buiten het bed: wél een streepje en een cijfer, maar lichter —
				// zo zie je in één blik waar het werkgebied ophoudt.
				buiten: value < -0.001 || value > lengthMm + 0.001,
				label: major ? String(Math.round(value)) : ''
			});
		}
		return marks;
	}

	// Wat er van de liniaal in beeld staat, in millimeters. Nul ligt op de
	// bedhoek, dus links van het bed is negatief.
	let ticksX = $derived(
		ticks(
			-bedOrigin.x / scale,
			(canvasWidth - bedOrigin.x) / scale,
			rulerStep,
			subStep,
			bed.width
		)
	);
	let ticksY = $derived(
		ticks(
			-bedOrigin.y / scale,
			(canvasHeight - bedOrigin.y) / scale,
			rulerStep,
			subStep,
			bed.height
		)
	);

	// ── Buiten het bed of buiten het vel ───────────────────────────────────────
	//
	// Gat C2: een vorm die het bed of het vel overschrijdt werd nergens gemeld.
	// Twee verschillende fouten, en het verschil telt: buiten het bed kán de
	// machine niet komen, buiten het vel wél — maar daar ligt geen materiaal.
	// Daarom twee kleuren en twee zinnen, en niet één "let op".
	const RAND_SPELING = 0.5;

	function buitenKader(
		box: { x: number; y: number; width: number; height: number },
		kader: { width: number; height: number }
	) {
		return (
			box.x < -RAND_SPELING ||
			box.y < -RAND_SPELING ||
			box.x + box.width > kader.width + RAND_SPELING ||
			box.y + box.height > kader.height + RAND_SPELING
		);
	}

	/** Per element: valt het buiten het bed, of alleen buiten het vel? */
	let buitenstaanders = $derived.by(() => {
		const perMm = design.design?.units_per_mm;
		const uit = new Map<string, 'bed' | 'vel'>();
		if (!perMm) return uit;
		for (const element of design.elements) {
			if (!element.bounds || element.hidden) continue;
			// Alleen werk dat straks écht de machine in gaat. Een vorm die in geen
			// enkele laag zit of in een laag met "brandt niet mee" kost geen
			// materiaal en geen tijd — die rood omranden is een valse alarmbel, en
			// van valse alarmbellen leert een gebruiker ze te negeren. Dat hij niet
			// meebrandt staat er al: gestippeld grijs op het canvas.
			const streek = design.strokeFor(element);
			if (streek.dashed || streek.dimmed || !streek.visible) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			const doos = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
			if (buitenKader(doos, bed)) uit.set(element.id, 'bed');
			else if (sheet && buitenKader(doos, sheet)) uit.set(element.id, 'vel');
		}
		return uit;
	});

	let buitenBed = $derived([...buitenstaanders.values()].filter((v) => v === 'bed').length);
	let buitenVel = $derived([...buitenstaanders.values()].filter((v) => v === 'vel').length);

	// ── Laagnummers bij de vorm (gat C6) ───────────────────────────────────────
	//
	// Het design system verbiedt informatie die alleen in kleur zit, en op het
	// bed was de laag precies dat. Bij deuteranopie liggen laag 4 en 10 maar 24
	// eenheden uit elkaar (gemeten door c6-a11y) — op een lijn van 1,2 px is dat
	// niets. Het nummer is hetzelfde vangnet als op de chip in het paneel.
	//
	// Waarom een nummer en geen lijnstijl per laagsoort: gestreept betekent op
	// dit canvas al "zit in geen enkele laag", en half doorzichtig betekent
	// "brandt niet mee" (besluit B4). Nog een derde streepjespatroon erbij maakt
	// van drie betekenissen één raadsel, en het zou bovendien niet zeggen wélke
	// van de vier snijlagen je voor je hebt. Het nummer zegt dat wel, en het is
	// exact hetzelfde getal als in de lijst en in de pre-flight (gat J7).
	let nummersAan = $state(
		typeof window === 'undefined' || localStorage.getItem('openkerf.laagnummers') !== 'uit'
	);

	function nummersSchakel() {
		nummersAan = !nummersAan;
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.laagnummers', nummersAan ? 'aan' : 'uit');
		}
	}

	/**
	 * Waar de nummers komen te staan, in millimeters.
	 *
	 * Alleen bij vormen die er op het scherm ruimte voor hebben: een cijfer bij
	 * een vorm van vier pixels is een vlek, en vijftig vlekken maken het bed
	 * onleesbaar. Wie het van dichtbij wil zien, zoomt in — dan verschijnen ze
	 * vanzelf.
	 */
	let laagLabels = $derived.by(() => {
		if (!nummersAan) return [];
		const perMm = design.design?.units_per_mm;
		if (!perMm) return [];
		const labels = [];
		for (const element of design.elements) {
			if (element.hidden || !element.bounds) continue;
			const streek = design.strokeFor(element);
			if (!streek.visible) continue;
			const ids = element.operation_ids?.length
				? element.operation_ids
				: element.operation_id
					? [element.operation_id]
					: [];
			// De laag die de kleur bepaalt, is ook de laag die het nummer krijgt.
			let beste: string | null = null;
			let bestIndex = -1;
			for (const id of ids) {
				const i = design.operations.findIndex((o) => o.id === id);
				if (i < 0 || design.isLayerHidden(id)) continue;
				if (bestIndex < 0 || i < bestIndex) {
					bestIndex = i;
					beste = id;
				}
			}
			const nummer = design.numberFor(beste);
			if (!nummer) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			// Gat C8: een vorm die op het scherm kleiner is dan het cijfer, krijgt
			// er geen — bij vijftig kleine vormen wordt het bed anders een wolk
			// getallen die niets meer aanwijst. Maar wat je zelf hebt aangeklikt is
			// nooit ruis: één cijfer bij één vorm is precies de vraag die je stelde
			// toen je hem selecteerde. Dus de maatgrens geldt niet voor de selectie,
			// en daarmee is de dubbele codering van C6 op elke zoomstand bereikbaar
			// zonder in te zoomen.
			const klein = (x1 - x0) * scale < 22 || (y1 - y0) * scale < 14;
			if (klein && !design.isSelected(element.id)) continue;
			labels.push({
				id: element.id,
				nummer,
				kleur: streek.color,
				x: x0,
				y: y0,
				dim: streek.dimmed
			});
		}
		return labels;
	});

	// ── Vastklikken ────────────────────────────────────────────────────────────
	//
	// De trefafstand staat in schermpixels en wordt hier teruggerekend naar
	// millimeters. Dat is hoe LightBurn en Inkscape het doen, en het is de enige
	// maat die klopt: op 400% is een pixel een kwart millimeter, dus wordt het
	// vastklikken vanzelf vier keer preciezer in plaats van vier keer grover.
	const SNAP_PX = 9;
	let snapTolerantie = $derived(SNAP_PX * mmPerPx);

	// Op de fijnste rasterlijn die je op dat moment ook echt ziet. Staat de fijne
	// verdeling uit omdat hij te dicht op elkaar valt, dan is de hoofdstap de
	// enige lijn die er is — vastklikken op iets onzichtbaars is een raadsel.
	let snapRaster = $derived(subStep || rulerStep);

	/**
	 * De dozen van alle andere vormen, in mm.
	 *
	 * Wat je zelf versleept telt niet mee: een vorm klikt niet aan zichzelf vast.
	 * Verborgen vormen ook niet — die zie je niet, dus een hulplijn erop is
	 * onverklaarbaar.
	 */
	let andereDozen = $derived.by(() => {
		const perMm = design.design?.units_per_mm ?? 1;
		return design.elements
			.filter((e) => e.bounds && !e.hidden && !design.isSelected(e.id))
			.map((e) => {
				const [x0, y0, x1, y1] = e.bounds!;
				return { x: x0 / perMm, y: y0 / perMm, width: (x1 - x0) / perMm, height: (y1 - y0) / perMm };
			});
	});

	let trefpunten = $derived(
		omgevingstrefpunten({ bed, vel: sheet, anderen: andereDozen })
	);

	/** De hulplijnen die nú zichtbaar zijn. Leeg zodra je loslaat. */
	let guides = $state<SnapGuide[]>([]);

	/**
	 * De hulplijnen als tekenbare lijnstukken.
	 *
	 * Een lijn die aan een vorm hangt loopt van die vorm tot voorbij wat eraan
	 * vastklikt, zodat je ziet wélke twee dingen zijn uitgelijnd — dat is wat
	 * Inkscape en Illustrator ook doen. Een raster-, vel- of bedlijn heeft geen
	 * tegenhanger en loopt daarom over het hele bed door.
	 */
	let guideLines = $derived.by(() => {
		const marge = 14 * mmPerPx;
		const live = preview ?? selection;
		// Waar het oog is: het ding dat je verplaatst, of anders de cursor.
		const anker = live
			? {
					x0: Math.min(live.x, live.x + live.width),
					x1: Math.max(live.x, live.x + live.width),
					y0: Math.min(live.y, live.y + live.height),
					y1: Math.max(live.y, live.y + live.height)
				}
			: hover
				? { x0: hover.x, x1: hover.x, y0: hover.y, y1: hover.y }
				: { x0: 0, x1: bed.width, y0: 0, y1: bed.height };
		const klem = (v: number, laag: number, hoog: number) => Math.min(Math.max(v, laag), hoog);

		return guides.map((g) => {
			let van = 0;
			let tot = g.axis === 'x' ? bed.height : bed.width;
			if (g.span) {
				van = Math.min(g.span[0], g.axis === 'x' ? anker.y0 : anker.x0);
				tot = Math.max(g.span[1], g.axis === 'x' ? anker.y1 : anker.x1);
				van -= marge;
				tot += marge;
			}
			// Het woordje hangt aan de vorm die je beweegt, niet aan het uiteinde
			// van de lijn: bij een lijn die het hele bed doorloopt viel dat uiteinde
			// achter het rechterpaneel en las je "bedra…".
			const tekst = SNAP_LABEL[g.kind];
			const breed = tekst.length * labelSize * 0.55;
			const vertical = g.axis === 'x';
			let tx = vertical ? g.pos : anker.x1 + labelSize * 0.5;
			let anchor = vertical ? 'middle' : 'start';
			if (!vertical && tx + breed > bed.width) {
				tx = anker.x0 - labelSize * 0.5;
				anchor = 'end';
			}
			return {
				key: `${g.axis}:${g.kind}:${g.pos.toFixed(3)}`,
				label: tekst,
				x1: vertical ? g.pos : van,
				x2: vertical ? g.pos : tot,
				y1: vertical ? van : g.pos,
				y2: vertical ? tot : g.pos,
				tx: vertical ? klem(tx, breed / 2, bed.width - breed / 2) : klem(tx, 0, bed.width),
				ty: vertical
					? klem(anker.y0 - labelSize * 1.1, labelSize, bed.height - labelSize * 0.3)
					: klem(g.pos - labelSize * 0.4, labelSize, bed.height - labelSize * 0.3),
				anchor
			};
		});
	});

	/**
	 * Staat het vastklikken aan? De knop naast de zoomregeling zet het uit voor
	 * langer dan één beweging, en die keuze blijft staan tussen sessies —
	 * LightBurn en xTool hebben er allebei een schakelaar voor, en wie zonder
	 * wil werken moet niet elke keer een toets vast hoeven houden.
	 */
	let snapAan = $state(
		typeof window === 'undefined' || localStorage.getItem('openkerf.snap') !== 'uit'
	);

	function snapSchakel() {
		snapAan = !snapAan;
		guides = [];
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.snap', snapAan ? 'aan' : 'uit');
		}
	}

	/**
	 * Alt keert de stand om voor die ene beweging: aan het vastklikken tegen,
	 * uit het juist even aan. Dat laatste is hoe LightBurn het ook doet — een
	 * modifier die niets doet zodra je de functie hebt uitgezet, is een dode toets.
	 */
	function snapUit(event: { altKey?: boolean } | null | undefined) {
		return snapAan === (event?.altKey === true);
	}

	/** Een los punt vastklikken en meteen de hulplijnen zetten. */
	function snapPunt(at: { x: number; y: number }, event?: { altKey?: boolean } | null) {
		if (snapUit(event)) {
			guides = [];
			return at;
		}
		const uit = klikPuntVast(at, trefpunten, snapRaster, snapTolerantie);
		guides = uit.guides;
		return { x: uit.x, y: uit.y };
	}

	// Het grid volgde de zoom niet: het stond vast op 50 mm terwijl de liniaal
	// op 20 of 100 sprong. Dan valt er geen lijn op een cijfer en kun je niets
	// van het bed aflezen. Nu deelt het grid de stap van de liniaal, met een
	// fijne onderverdeling die verdwijnt zodra hij te dicht op elkaar staat.
	let gridMajor = $derived(rulerStep * scale);
	let gridMinor = $derived(subStep * scale);
	let gridStyle = $derived(
		`background-size: ${gridMajor}px ${gridMajor}px, ${gridMajor}px ${gridMajor}px,` +
			(gridMinor > 0
				? ` ${gridMinor}px ${gridMinor}px, ${gridMinor}px ${gridMinor}px`
				: ' 0 0, 0 0')
	);

	/** Waar de muis staat, als streepje op beide linialen. */
	let pointer = $state<{ x: number; y: number } | null>(null);

	/**
	 * De hoogte van alles onder het canvas, als CSS-variabele op de wortel.
	 *
	 * De camerapil zweeft boven het canvas met een vaste afstand tot de
	 * onderkant en leest deze maat. Er staat inmiddels meer dan één strook
	 * onder het bed — de kleurenstrook (B2) en de waarschuwing over werk buiten
	 * het bed (C2) — dus meten we het blok als geheel. Opmeten en niet
	 * uitrekenen: de hoogte verschilt per apparaat, want op aanraakschermen zijn
	 * de knoppen groter en breekt de regel.
	 */
	let onderrandHoogte = $state(0);
	$effect(() => {
		if (typeof document === 'undefined') return;
		document.documentElement.style.setProperty('--palet-hoogte', `${onderrandHoogte}px`);
		return () => document.documentElement.style.removeProperty('--palet-hoogte');
	});

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
		// Zoomsneltoetsen: alleen buiten invoervelden, en zonder modifiers die
		// bij de browser horen.
		const doel = e.target as HTMLElement | null;
		const tikt = doel && /^(INPUT|TEXTAREA|SELECT)$/.test(doel.tagName);
		if (!tikt && !e.ctrlKey && !e.metaKey && !e.altKey) {
			if (e.key === '1' && !e.shiftKey) { honderd(); return; }
			if (e.key === '!' || (e.key === '1' && e.shiftKey)) { passend(); return; }
			if (e.key === '@' || (e.key === '2' && e.shiftKey)) { naarSelectie(); return; }
		}
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
			onPointerMm?.(pointer);
	}}
	onpointerleave={() => {
		pointer = null;
		if (!drag) guides = [];
	}}
	onpointerup={() => (panning = null)}
>
	<div class="corner" aria-hidden="true">mm</div>
	<svg class="ruler-x" aria-hidden="true">
		<!-- Het werkgebied als band op de liniaal zelf (gat C4). De schaal loopt
		     nu door tot voorbij het bed, dus er moet iets zeggen wáár het bed
		     ophoudt — anders lees je een getal af zonder te weten of het nog op
		     de machine ligt. -->
		<rect
			class="werkgebied"
			x={bedOrigin.x}
			y="0"
			width={Math.max(0, bed.width * scale)}
			height="20"
		/>
		{#each ticksX as tick (tick.value)}
			{@const at = bedOrigin.x + tick.value * scale}
			{#if at >= -40 && at <= canvasWidth + 40}
				<!-- Streepjes onder de cijferband, niet erdoorheen: met streepjes
				     die tot y=8 liepen sneed er altijd een door "100" en las je
				     "109". Cijfers wonen boven, streepjes beneden. -->
				<line class:buiten={tick.buiten} x1={at} x2={at} y1={tick.major ? 11 : 15} y2="20" />
				{#if tick.label}
					<text class:buiten={tick.buiten} x={at + 3} y="1">{tick.label}</text>
				{/if}
			{/if}
		{/each}
		{#if pointer}
			<line class="here" x1={bedOrigin.x + pointer.x * scale} x2={bedOrigin.x + pointer.x * scale} y1="0" y2="20" />
		{/if}
	</svg>
	<svg class="ruler-y" aria-hidden="true">
		<rect
			class="werkgebied"
			x="0"
			y={bedOrigin.y}
			width="20"
			height={Math.max(0, bed.height * scale)}
		/>
		{#each ticksY as tick (tick.value)}
			{@const at = bedOrigin.y + tick.value * scale}
			{#if at >= -40 && at <= canvasHeight + 40}
				<line class:buiten={tick.buiten} y1={at} y2={at} x1={tick.major ? 11 : 15} x2="20" />
				{#if tick.label}
					<text class:buiten={tick.buiten} x="1" y={at - 3} transform="rotate(-90 1 {at - 3})">{tick.label}</text>
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
			       left: {bedOrigin.x}px; top: {bedOrigin.y}px;
			       {gridStyle}"
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

			{#if sheet && (sheet.width < bed.width - 0.5 || sheet.height < bed.height - 0.5)}
				<!-- Het vel ligt binnen het bed; alles daarbuiten brandt niet mee. -->
				<div
					class="sheet"
					style="width: {sheet.width * scale}px; height: {sheet.height * scale}px"
				>
					<span class="sheet-label mono">{sheet.name}</span>
				</div>
			{/if}

			<span class="bed-label mono">
				bed {bed.width.toFixed(0)} × {bed.height.toFixed(0)} mm
			</span>

			<!-- `!job`: tijdens een lopende job is "Leeg bed — kies Importeren" een
			     uitnodiging op het verkeerde moment. Gezien op een foto waarop het
			     spoor van de kop over het bed liep terwijl er "Leeg bed" onder stond;
			     dat kan zodra het ontwerp gewist wordt terwijl de machine nog bezig is
			     met wat er al gespoold was. -->
			{#if design.isEmpty && !cameraSrc && !job}
				<!-- Een leeg bed is een lege bladzijde: zonder tekst weet niemand
				     waar hij moet beginnen. Vangt geen muis af, want je moet er
				     doorheen kunnen tekenen. -->
				<div class="blank">
					<h2>Leeg bed</h2>
					<p>
						Kies <strong>Importeren</strong> bovenin voor een bestaand ontwerp,
						of pak links een vorm en klik op het bed.
					</p>
				</div>
			{/if}

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
						penClick(snapPunt(pointerMm(e), e));
						return;
					}
					if (tool === 'measure') {
						const at = snapPunt(pointerMm(e), e);
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
					// Ook boven een element: slepen trekt een kader, klikken zonder
					// te slepen selecteert. Zonder dit kon je binnen een groot kader
					// geen selectie meer trekken zodra dat kader klikbaar werd.
					if (tool === 'select' && !e.altKey && e.button === 0) {
						startBand(e);
					}
				}}
				onpointermove={(e) => {
					// Waar het gereedschap zou landen, mét vastklikken — zo zie je de
						// hulplijn vóór de klik en niet pas erna.
						if (tool === 'measure' && measureFrom && !measureTo) hover = snapPunt(pointerMm(e), e);
					else if (tool === 'pen' && penPoints.length) hover = snapPunt(pointerMm(e), e);
					else if (lineStart) hover = snapPunt(pointerMm(e), e);
						else if (canEdit && tekengereedschap) snapPunt(pointerMm(e), e);
					moveBand(e);
				}}
				onpointerup={endBand}
			>
				<!-- Het spoor van de kop, ónder het ontwerp (gat J3).
				     Eerst als brede, zachte baan in het accent en pas daarna de vormen
				     eroverheen: zo licht op wat de machine gehad heeft, zonder dat de
				     laagkleur eronder verdwijnt — en die kleur is het enige dat zegt
				     wélke bewerking het was. Bovenop een lijn van 1,2 px was het spoor
				     in --text-2 op de proefjob letterlijk onzichtbaar; gemeten en
				     weggegooid. -->
				{#if spoor}
					<polyline
						class="spoor-baan"
						points={spoor}
						vector-effect="non-scaling-stroke"
						aria-hidden="true"
					/>
				{/if}

				<!-- Het ontwerp. Eén schaaltransform rekent Tats om naar mm; de
				     paddata zelf blijft onaangeroerd zoals de engine hem gaf. -->
				{#if design.design}
					<g transform="scale({1 / design.design.units_per_mm})">
						{#each design.elements as element (element.id)}
							<!-- Tijdens het verplaatsen loopt de vorm mee met het kader; zonder
							     dat wijzen de hulplijnen naar een rand die er nog niet ligt. -->
							<g transform={verschuiving(element.id)}>
							{#if !element.hidden && element.image && design.strokeFor(element).visible}
								{#if buitenstaanders.get(element.id)}
									<!-- Zelfde melding als bij een pad, maar een afbeelding heeft
									     geen contour om te laten gloeien: dan is het kader het
									     onderwerp. -->
									<rect
										class="buiten-gloed"
										class:velrand={buitenstaanders.get(element.id) === 'vel'}
										x={element.image.x_mm * (design.design?.units_per_mm ?? 1)}
										y={element.image.y_mm * (design.design?.units_per_mm ?? 1)}
										width={element.image.width_mm * (design.design?.units_per_mm ?? 1)}
										height={element.image.height_mm * (design.design?.units_per_mm ?? 1)}
										fill="none"
										vector-effect="non-scaling-stroke"
									/>
								{/if}
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
									class:passive={!selectTool}
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
										if (bandJustEnded) {
											bandJustEnded = false;
											return;
										}
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
							{:else if !element.hidden && design.strokeFor(element).visible}
								<!-- De kleur van de laag, niet die van het element: zo zie je in
								     één blik wat gesneden en wat gegraveerd wordt. Zonder laag
								     gestippeld grijs — die vorm wordt niet gebrand.
								     Besluit B4: de stippellijn blijft dáárvoor gereserveerd. Een
								     laag met "brandt niet mee" is een andere staat en krijgt een
								     eigen weergave — dunner en half doorzichtig — zodat je hem
								     wel ziet liggen maar nooit aanziet voor werk dat straks de
								     machine in gaat. -->
								{@const streek = design.strokeFor(element)}
								{@const buiten = buitenstaanders.get(element.id)}
								{#if buiten}
									<!-- Gat C2: een gloed in de kleur van het bezwaar, onder de
									     vorm door. De laagkleur blijft dus zichtbaar — je moet
									     nog steeds kunnen zien in welke laag het ding zit — maar
									     de vorm zelf draagt nu de waarschuwing, en niet alleen
									     een regel tekst in een paneel dat je dicht kunt klappen. -->
									<path
										class="buiten-gloed"
										class:velrand={buiten === 'vel'}
										d={element.path}
										fill="none"
										vector-effect="non-scaling-stroke"
									/>
								{/if}
								<!-- Een rasterlaag brandt het vlak weg, geen omtrek. Dat als
								     lijn tonen zegt iets anders dan wat er gebeurt, dus krijgt
								     zo'n vorm zijn vlak: in de laagkleur, half doorzichtig,
								     zodat je er nog doorheen ziet wat eronder ligt en de
								     contour zelf de laagkleur blijft dragen. Het blijft één
								     `fill` op het pad dat er toch al staat — geen tweede
								     tekening, geen rasteraar in de lus, dus de kosten per
								     muisbeweging veranderen niet. -->
								<path
									class:vlak={streek.filled}
									class:gedempt={streek.dimmed}
									d={element.path}
									fill={streek.filled ? streek.color : 'none'}
									fill-rule="nonzero"
									stroke={streek.color}
									stroke-dasharray={streek.dashed ? '6 4' : undefined}
									stroke-opacity={streek.dimmed ? 0.4 : 1}
									stroke-width={design.isSelected(element.id) ? 2 : streek.dimmed ? 0.9 : 1.2}
									vector-effect="non-scaling-stroke"
								/>
								<!-- Onzichtbare trefzone: een contour van 1 px is niet aan te
								     klikken, zeker niet op een touchscreen. -->
								<path
									class="hit"
									class:passive={!selectTool}
									d={element.path}
									fill="transparent"
									stroke="transparent"
									stroke-width="12"
									vector-effect="non-scaling-stroke"
									role="button"
									tabindex="0"
									aria-label="Selecteer {element.label}"
									aria-pressed={design.isSelected(element.id)}
									onclick={(e) => {
										e.stopPropagation();
										// De klik na een sleepkader mag de selectie die dat kader
										// net maakte niet vervangen.
										if (bandJustEnded) {
											bandJustEnded = false;
											return;
										}
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
							</g>
						{/each}
					</g>

					<!-- Het laagnummer bij de vorm (gat C6). Buiten de Tat-schaal, want
					     de tekst moet even groot blijven bij elke zoomstand. Het cijfer
					     krijgt een rand in de bedkleur mee (`paint-order`), anders valt
					     het weg tegen een rasterlijn of tegen de vorm eronder. -->
					{#each laagLabels as label (label.id)}
						<!-- @svg-space: millimeter-ruimte, geen CSS-pixels; `labelSize` is de
						     teruggerekende schermmaat van --text-xs. -->
						<text
							style="font-size: {labelSize}px; fill: {label.kleur}; fill-opacity: {label.dim ? 0.5 : 1}"
							class="laagnummer mono"
							x={label.x + 2 * mmPerPx}
							y={label.y - 3 * mmPerPx}
						>{label.nummer}</text>
					{/each}

					<!-- Selectiecontour: de kerflijn. Statisch gestreept, en alleen
					     geanimeerd terwijl je sleept — zoals DESIGN-SYSTEM.md voorschrijft. -->
					{#if outline && frameBox}
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
								x={frameBox.x}
								y={frameBox.y}
								width={frameBox.width}
								height={frameBox.height}
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
									x={frameBox.x}
									y={frameBox.y}
									width={frameBox.width}
									height={frameBox.height}
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
								y1={frameBox.y}
								x2={center.x}
								y2={frameBox.y - stalk}
							/>
							<circle
								class="rotator"
								cx={center.x}
								cy={frameBox.y - stalk}
								r={handleR}
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
								cy={frameBox.y - stalk}
								r={hitR}
								onpointerdown={(e) => startDrag(e, 'rotate')}
								onpointermove={moveDrag}
								onpointerup={endDrag}
							/>
						{/if}
						<!-- Bij een lijn zijn de eindpunten de grepen; hoekgrepen van een
						     denkbeeldig kader zouden daar bovenop liggen. -->
						{#each selectedLine ? [] : [[frameBox.x, frameBox.y], [frameBox.x + frameBox.width, frameBox.y], [frameBox.x, frameBox.y + frameBox.height], [frameBox.x + frameBox.width, frameBox.y + frameBox.height]] as [hx, hy], corner (corner)}
								<rect
									class="handle"
									x={hx - handleR}
									y={hy - handleR}
									width={handleR * 2}
									height={handleR * 2}
								/>
								<!-- De trefzone is ruimer dan de greep: 10 px zichtbaar is
								     precies genoeg om te zien, en veel te weinig om met een
								     vinger te raken. -->
								<rect
									class="handle-hit"
									class:grabbable={canEdit}
									role="button"
									tabindex="-1"
									aria-label="Sleep om te schalen"
									x={hx - hitR}
									y={hy - hitR}
									width={hitR * 2}
									height={hitR * 2}
									onpointerdown={(e) => startDrag(e, 'scale', corner)}
									onpointermove={moveDrag}
									onpointerup={endDrag}
								/>
							{/each}
							<text
								class="mono"
								x={frameBox.x + frameBox.width / 2}
								y={frameBox.y + frameBox.height + labelSize * 1.3}
								text-anchor="middle"
								style="font-size: {labelSize}px"
							>
								{Math.abs(outline.width).toFixed(1)} × {Math.abs(outline.height).toFixed(1)} mm
							</text>
						</g>
					{/if}
				{/if}

				<!-- Hulplijnen: waaróp iets vastklikt. Zonder deze terugkoppeling is
				     snapping een raadsel — je ziet iets wegspringen en weet niet
				     waarheen. Ze vangen geen muis af. -->
				<!-- Het label staat op volle --text-xs (11 px): kleiner maken om ruimte te
				     winnen is precies wat de pixelrechter afkeurt. -->
				{#each guideLines as lijn (lijn.key)}
					<g class="guide">
						<line x1={lijn.x1} y1={lijn.y1} x2={lijn.x2} y2={lijn.y2} />
						<text
							class="mono"
							x={lijn.tx}
							y={lijn.ty}
								text-anchor={lijn.anchor}
							style="font-size: {labelSize}px"
						>
							{lijn.label}
						</text>
					</g>
				{/each}

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
					<!-- `.measure-label` en niet `.measure`: die tweede is de gestippelde
					     meetlijn, en tekst met een stippelrand eromheen is onleesbaar. -->
					<text
						class="mono measure-label"
						x={(endpointPreview.x1_mm + endpointPreview.x2_mm) / 2}
						y={(endpointPreview.y1_mm + endpointPreview.y2_mm) / 2 - labelSize}
						text-anchor="middle"
						style="font-size: {labelSize}px"
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
						<circle class="endpoint" cx={point.x} cy={point.y} r={handleR} />
						<circle
							class="grip"
							role="button"
							tabindex="-1"
							aria-label="Eindpunt {index + 1} verslepen"
							cx={point.x}
							cy={point.y}
							r={hitR}
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
							cx={live ? live.x : point.x_mm}
							cy={live ? live.y : point.y_mm}
							r={handleR}
						/>
						<circle
							class="grip"
							role="button"
							tabindex="-1"
							aria-label="Knooppunt {point.index + 1} verslepen"
							cx={live ? live.x : point.x_mm}
							cy={live ? live.y : point.y_mm}
							r={hitR}
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
						<!-- `handleR` en niet een vast getal: 1,6 in deze SVG is 1,6 mm,
						     dus de punten van het pentekenen groeiden mee met de zoom en
						     bedekten ingezoomd het pad dat je aan het zetten was. -->
						<circle class="pen-dot" cx={point.x} cy={point.y} r={handleR} />
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
						y={(measureFrom.y + to.y) / 2 - labelSize * 0.6}
						text-anchor="middle"
						style="font-size: {labelSize}px"
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

				<!-- De oorsprong (gat C5). LightBurn zet er een vast hoekmerk met
				     asletters neer, en met reden: bij ons viel 0,0 samen met de
				     kopmarkering, dus zodra de kop bewoog was er niets meer dat zei
				     waar de machine vandaan telt. Dit merk beweegt nooit.

				     Alle maten teruggerekend naar schermpixels — in een SVG die in
				     millimeters meet is "6" zes millimeter, en dan groeit het merk
				     met de zoom mee tot het het halve bed beslaat. -->
				<!-- @svg-space: asletters in millimeter-ruimte, teruggerekend naar de
				     schermmaat van --text-xs. -->
				<g class="oorsprong" aria-hidden="true">
					<!-- Twee assen met een pijlpunt: X naar rechts, Y omlaag. Dat is de
					     richting waarin de machine telt, en die staat er dus in. -->
					<line x1="0" y1="0" x2={14 * mmPerPx} y2="0" />
					<line x1="0" y1="0" x2="0" y2={14 * mmPerPx} />
					<path class="punt" d="M{14 * mmPerPx} 0 L{10 * mmPerPx} {-2.4 * mmPerPx} L{10 * mmPerPx} {2.4 * mmPerPx} Z" />
					<path class="punt" d="M0 {14 * mmPerPx} L{-2.4 * mmPerPx} {10 * mmPerPx} L{2.4 * mmPerPx} {10 * mmPerPx} Z" />
					<!-- Een vierkantje op het punt zelf, geen ring: de kopmarkering is
					     al een ring in het accent, en die twee vlak op elkaar (de kop
					     staat na homen precies hier) waren niet uit elkaar te houden. -->
					<rect
						class="knoop"
						x={-1.8 * mmPerPx}
						y={-1.8 * mmPerPx}
						width={3.6 * mmPerPx}
						height={3.6 * mmPerPx}
					/>
					<text class="as mono" x={18.5 * mmPerPx} y={3.5 * mmPerPx} style="font-size: {labelSize}px">X</text>
					<text class="as mono" x={2.5 * mmPerPx} y={21 * mmPerPx} style="font-size: {labelSize}px">Y</text>
				</g>

				<!-- Het nulpunt van de gebruiker (gat J12).
				     Een kruis met een open midden, in --text-1 en niet in het accent:
				     het accent is de kop en het merk op 0,0 (C5) is óók al een vast
				     teken, dus dit derde punt moet van allebei te onderscheiden zijn.
				     Alle maten teruggerekend naar schermpixels — anders groeit het
				     kruis met de zoom mee. -->
				{#if nulstand}
					<g class="nulpunt-merk" aria-hidden="true">
						<line
							x1={nulstand.x_mm - 9 * mmPerPx}
							y1={nulstand.y_mm}
							x2={nulstand.x_mm - 3 * mmPerPx}
							y2={nulstand.y_mm}
						/>
						<line
							x1={nulstand.x_mm + 3 * mmPerPx}
							y1={nulstand.y_mm}
							x2={nulstand.x_mm + 9 * mmPerPx}
							y2={nulstand.y_mm}
						/>
						<line
							x1={nulstand.x_mm}
							y1={nulstand.y_mm - 9 * mmPerPx}
							x2={nulstand.x_mm}
							y2={nulstand.y_mm - 3 * mmPerPx}
						/>
						<line
							x1={nulstand.x_mm}
							y1={nulstand.y_mm + 3 * mmPerPx}
							x2={nulstand.x_mm}
							y2={nulstand.y_mm + 9 * mmPerPx}
						/>
						<text
							class="as mono"
							x={nulstand.x_mm + 11 * mmPerPx}
							y={nulstand.y_mm - 5 * mmPerPx}
							style="font-size: {labelSize}px">0</text
						>
					</g>
					{#if brandtHier}
						<!-- Waar het werk terechtkomt. Zonder dit kader zegt het nulpunt
						     alleen dát er iets verschuift en niet waarheen, en dan moet je
						     het uitrekenen terwijl je juist wilde kunnen kijken. -->
						<g class="brandt-hier" aria-hidden="true">
							<!-- Het vel schuift mee. Dat is geen opsmuk maar de betekenis van
							     het nulpunt: je legt het op de hoek van het materiaal dat
							     erin ligt, dus het materiaal ligt daar. Zonder dit kader
							     stond het werk zichtbaar naast het vel terwijl er nergens
							     "buiten het vel" gemeld werd — een tekening die zichzelf
							     tegenspreekt. -->
							{#if sheet}
								<rect
									class="velschets"
									x={nulstand.x_mm}
									y={nulstand.y_mm}
									width={sheet.width}
									height={sheet.height}
									vector-effect="non-scaling-stroke"
								/>
							{/if}
							<rect
								x={brandtHier.x}
								y={brandtHier.y}
								width={brandtHier.width}
								height={brandtHier.height}
								vector-effect="non-scaling-stroke"
							/>
							<text
								class="mono"
								x={brandtHier.x + 2 * mmPerPx}
								y={brandtHier.y - 3 * mmPerPx}
								style="font-size: {labelSize}px">brandt hier</text
							>
						</g>
					{/if}
				{/if}

				<!-- Het verse stuk, bovenop: waar de kop nú is. Kort gehouden (zie
				     VERS_PUNTEN) zodat er verschil blijft tussen "hier is hij geweest"
				     en "hier is hij nu". -->
				{#if spoorKop}
					<g class="spoor" aria-hidden="true">
						<polyline class="vers" points={spoorKop} vector-effect="non-scaling-stroke" />
					</g>
				{/if}

				{#if head}
					<!-- Live kop-positie. Er is nog geen ontwerp om te tonen: fase 1
					     leest alleen status, het canvas zelf komt in fase 3. -->
					<g class="head">
						<line x1={head[0]} y1="0" x2={head[0]} y2={bed.height} />
						<line x1="0" y1={head[1]} x2={bed.width} y2={head[1]} />
						<!-- Ook de kop is een schermmarkering, geen vorm van 4 mm: op
						     twintig keer inzoomen was hij anders een cirkel van 26 cm. -->
						<circle cx={head[0]} cy={head[1]} r={7 * mmPerPx} />
						<!-- De voortgang van de job, als ring om de kop (gat J3). Dit is
						     het enige getal dat de engine echt geeft, en het staat waar je
						     tijdens een job toch al naar kijkt. Beginnend bovenaan en met
						     de klok mee, want dat leest iedereen als "hoe ver". -->
						{#if voortgang !== null}
							<circle
								class="ring-baan"
								cx={head[0]}
								cy={head[1]}
								r={ringR}
								vector-effect="non-scaling-stroke"
							/>
							<circle
								class="ring"
								cx={head[0]}
								cy={head[1]}
								r={ringR}
								vector-effect="non-scaling-stroke"
								stroke-dasharray="{ringOmtrek * voortgang} {ringOmtrek}"
								transform="rotate(-90 {head[0]} {head[1]})"
							/>
						{/if}
					</g>
				{/if}
			</svg>
		</div>
	</div>

	<div class="zoom">
		<!-- Laagnummers bij de vorm aan of uit (gat C6). Standaard aan, want het
		     nummer is het vangnet dat het design system voorschrijft; uit kan,
		     want bij vijftig vormen op een vel is het een wolk cijfers. -->
		<button
			class="snap"
			class:aan={nummersAan}
			aria-pressed={nummersAan}
			title={nummersAan
				? 'Laagnummers bij de vormen staan aan'
				: 'Laagnummers bij de vormen staan uit'}
			aria-label="Laagnummers bij de vormen"
			onclick={nummersSchakel}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M5 9h14M5 15h14M10 4 8 20M17 4l-2 16" />
			</svg>
		</button>
		<span class="scheiding" aria-hidden="true"></span>
		<!-- Vastklikken aan of uit. Een magneet, want dat is het beeld dat elk
		     tekenprogramma ervoor gebruikt; de stand staat er in woorden bij in de
		     titel, want een icoon alleen zegt niet of het aan- of uitstaat. -->
		<button
			class="snap"
			class:aan={snapAan}
			aria-pressed={snapAan}
			title={snapAan
				? 'Vastklikken staat aan — houd Alt ingedrukt om het even over te slaan'
				: 'Vastklikken staat uit — houd Alt ingedrukt om het even te gebruiken'}
			aria-label="Vastklikken op raster en vormen"
			onclick={snapSchakel}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M6 4v8a6 6 0 0 0 12 0V4" />
				<path d="M6 10h4M14 10h4" />
			</svg>
		</button>
		<span class="scheiding" aria-hidden="true"></span>
		<button title="Uitzoomen" aria-label="Uitzoomen" onclick={() => zoomAt(1 / 1.25)}>−</button>
		<!-- 100% is de stand waarin het hele bed in beeld staat; dat is nu ook
		     echt zo, sinds de schaal het werkvlak volgt in plaats van 640 px. -->
		<button class="val mono" title="Het hele bed in beeld (toets 1)" onclick={honderd}
			>{Math.round(zoom * 100)}%</button
		>
		<button class="fit" title="Alles passend in beeld (Shift+1)" onclick={passend}>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>
			Passend
		</button>
		<button title="Inzoomen" aria-label="Inzoomen" onclick={() => zoomAt(1.25)}>+</button>
	</div>

	{#if !device}
		<p class="empty">Geen machine verbonden</p>
	{/if}
</div>

<!-- Gat C2 in woorden, als eigen strook onder het bed.
     De gloed op het bed is de eerste waarschuwing, maar kleur alleen mag het
     nooit dragen: wie in de werkplaats bij een raam staat ziet die gloed als
     eerste niet meer, en met deuteranopie is rood op een oranje lijn geen
     verschil. Twee aparte zinnen, want buiten het bed (daar komt de kop niet)
     en buiten het vel (daar ligt geen materiaal) zijn twee problemen.

     Bewust géén zwevend kaartje op het canvas: daar botste hij op de camerapil
     links en op de zoombalk rechts — gemeten op 1024, de melding viel er half
     achter. Een strook in de stroom dekt niets af en verdwijnt weer zodra het
     werk binnen de randen ligt. -->
<!-- Alles wat ónder het bed hangt in één blok, en dat blok meet zichzelf op.
     De camerapil zweeft boven het canvas met een vaste afstand tot de onderkant
     en rekent met `--palet-hoogte`; stond de kleurenstrook alleen in die maat,
     dan lag de pil over deze waarschuwing heen zodra hij verscheen (gemeten op
     1440: overlap van 34 px). Eén maat voor de hele onderrand is de enige die
     klopt, want er kan meer dan één strook staan. -->
<div class="onderrand" bind:clientHeight={onderrandHoogte}>
<!-- Het knooppuntgereedschap staat ingedrukt maar doet niets: zeg waarom.
     Zonder deze regel was het verschil tussen "je moet nog een vorm kiezen" en
     "deze vorm kán het niet" onzichtbaar, en beide zagen eruit als een kapot
     gereedschap. -->
{#if nodeReden}
	<p class="tool-uitleg" role="status">
		{#if nodeReden === 'geen'}
			Knooppunten werkt op één vorm. Klik er een aan op het bed.
		{:else if nodeReden === 'meerdere'}
			Knooppunten werkt op één vorm tegelijk; er staan er {design.selectedIds.length}
			gekozen. Klik er één aan.
		{:else}
			Deze vorm heeft geen losse punten. Maak er eerst een pad van met
			<em>Combineren</em> in het paneel rechts.
		{/if}
	</p>
{/if}
<!-- Wat het spoor op het bed is, in woorden (gat J3).
     Een lijn die tijdens een job over het bed groeit, leest als "dit is er al
     gesneden" — en dat kunnen we niet waarmaken: `driver;position` zegt niet of
     de laser aan stond, dus de sprong tussen twee vormen zit er net zo goed in.
     Een beeld dat meer belooft dan het weet is erger dan geen beeld, dus staat
     hier wat je voor je hebt. Alleen tijdens een job; daarbuiten is er niets te
     zeggen. -->
{#if job && spoor}
	<p class="spoor-uitleg" role="status">
		<span class="spoor-merk" aria-hidden="true"></span>
		<!-- Alle tekst in één kind: met losse tekstknopen ernaast wordt elk stuk
		     een eigen flex-item, en dan stond "62%" op een tablet in een eigen
		     kolom naast een afgebroken zin (gemeten op 1024). -->
		<span
			>Spoor van de kop — gemeten, inclusief de sprongen tussen de vormen.{#if voortgang !== null}{' '}<span
					class="mono">{Math.round(voortgang * 100)}%</span
				> staat als ring om de kop.{/if}</span
		>
	</p>
{/if}
{#if buitenBed || buitenVel}
	<div class="buiten-strook" role="status">
		{#if buitenBed}
			<span class="regel bedrand">
				<span class="teken" aria-hidden="true">!</span>
				<span
					>{buitenBed === 1 ? 'Eén vorm ligt' : `${buitenBed} vormen liggen`} buiten het
					bed — daar komt de kop niet.</span
				>
			</span>
		{/if}
		{#if buitenVel}
			<span class="regel velrand">
				<span class="teken" aria-hidden="true">!</span>
				<span
					>{buitenVel === 1 ? 'Eén vorm ligt' : `${buitenVel} vormen liggen`} buiten {sheet
						? sheet.name
						: 'het vel'} — daar ligt geen materiaal.</span
				>
			</span>
		{/if}
	</div>
{/if}

<!-- Besluit B2: de kleurenstrook hoort ónder het canvas, niet in het paneel.
     Daar hoort hij bij de vorm die je vasthebt, en niet bij een tabblad dat je
     eerst moet opzoeken. Een eigen rij, geen zwevende balk over het bed heen:
     hij mag nooit iets afdekken wat je aan het uitlijnen bent. -->
<LagenPalet {design} {edits} {canEdit} onChanged={() => onEdited?.()} />
</div>

<style>
	.canvas-wrap {
		flex: 1;
		position: relative;
		/* v2: het bed ligt ergens. Een verloop in de omgeving en één schaduw
		   eronder — geen drie. */
		background: var(--stage);
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
		font-size: var(--text-xs);
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
	/* Buiten het bed loopt de schaal door, maar zachter: het getal is er als je
	   het nodig hebt en dringt zich niet op als je binnen het bed werkt (C4). */
	.ruler-x line.buiten,
	.ruler-y line.buiten {
		stroke: color-mix(in srgb, var(--line-strong, var(--line)) 55%, transparent);
	}
	.ruler-x text.buiten,
	.ruler-y text.buiten {
		fill: color-mix(in srgb, var(--text-2) 60%, transparent);
	}
	/* De band die zegt hoe ver het bed reikt. Geen rand: dat zou een vierde
	   lijnsoort op een liniaal van 20 px zijn. */
	.werkgebied {
		fill: color-mix(in srgb, var(--text-2) 8%, transparent);
	}
	.ruler-x text,
	.ruler-y text {
		/* Getallen op een liniaal zijn waarden: mono met tabulaire cijfers,
		   anders springt de schaalverdeling bij het pannen. */
		font-variant-numeric: tabular-nums;
		fill: var(--text-2);
		font-size: var(--text-xs);
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
		font-size: var(--text-xs);
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
	}
	.bed {
		background: var(--bed);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		/* Absoluut op een gerekende plek, niet gecentreerd door de grid: zodra het
		   bed groter werd dan het vlak klemde de browser de linkerrand vast, en
		   dan klopte elke omrekening van pixels naar millimeters niet meer —
		   linialen, muispositie en zoomen naar de cursor liepen alle drie mis. */
		position: absolute;
		/* Twee niveaus, zoals elk tekenprogramma: de hoofdlijnen staan op de
		   stap van de liniaal, de fijne verdeling op een vijfde daarvan. Kleur
		   komt uit het token; de fijne lijn is dezelfde kleur, verdund. */
		background-image:
			linear-gradient(var(--line) 1px, transparent 1px),
			linear-gradient(90deg, var(--line) 1px, transparent 1px),
			linear-gradient(color-mix(in srgb, var(--line) 45%, transparent) 1px, transparent 1px),
			linear-gradient(90deg, color-mix(in srgb, var(--line) 45%, transparent) 1px, transparent 1px);
		box-shadow: var(--lift-1), 0 10px 24px rgb(16 20 26 / 0.10);
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
	.sheet {
		position: absolute;
		left: 0;
		top: 0;
		border: 1px dashed var(--accent);
		background: color-mix(in srgb, var(--accent) 4%, transparent);
		pointer-events: none;
	}
	.sheet-label {
		font-variant-numeric: tabular-nums;
		position: absolute;
		left: 3px;
		bottom: 2px;
		font-size: var(--text-xs);
		color: var(--accent);
	}
	.bed-label {
		font-variant-numeric: tabular-nums;
		position: absolute;
		top: -22px;
		right: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.blank {
		position: absolute;
		inset: 0;
		display: grid;
		align-content: center;
		justify-items: center;
		gap: var(--space-2);
		padding: var(--space-4);
		text-align: center;
		pointer-events: none;
		user-select: none;
	}
	.blank h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--text-1);
	}
	.blank p {
		max-width: 34ch;
		font-size: var(--text-sm);
		line-height: 1.45;
		color: var(--text-2);
	}
	.blank strong {
		color: var(--text-1);
		font-weight: 600;
	}
	/* De oorsprong (C5). Bewust níet in het accent en niet in rood: het accent
	   is de kopmarkering — dat was juist de verwarring — en rood betekent in dit
	   systeem gevaar. Dit is een vast punt op de machine, dus de tekstkleur van
	   de app, half doorzichtig zodat hij nooit boven het werk uit schreeuwt. */
	.oorsprong {
		pointer-events: none;
	}
	.oorsprong line {
		stroke: var(--text-1);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
		opacity: 0.55;
	}
	.oorsprong .punt {
		fill: var(--text-1);
		opacity: 0.55;
	}
	.oorsprong .knoop {
		fill: var(--text-1);
		opacity: 0.8;
	}
	.oorsprong text {
		fill: var(--text-1);
		opacity: 0.75;
		font-family: var(--font-mono);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	/* Een vorm in een rasterlaag: die brandt zijn vlak weg, dus tonen we het
	   vlak. Half doorzichtig, want je moet er nog doorheen kunnen zien wat
	   eronder ligt.

	   De dekking verschilt per thema, en dat is geen smaak maar meting. Dezelfde
	   38 % gaf op het lichte bed een contrast van 2,96:1 en op het donkere maar
	   1,68:1 — dezelfde vulling die licht overtuigt, is donker een vermoeden.
	   Met 62 % komt donker op 2,12:1. Hoger kan niet veel: op een donker bed
	   haalt zelfs een volledig dekkende laagkleur maar ~2,65:1, en het vlak mag
	   niet ondoorzichtig worden. De contour draagt de vorm; de vulling zegt
	   alleen wat ermee gebeurt. */
	.vlak {
		fill-opacity: 0.38;
	}

	/* Laag op "brandt niet mee": wel te zien, nooit aan te zien voor werk dat
	   straks de machine in gaat. Zelfde regel als bij de lijn ernaast. */
	.vlak.gedempt {
		fill-opacity: 0.14;
	}

	:global([data-theme='dark']) .vlak {
		fill-opacity: 0.62;
	}

	:global([data-theme='dark']) .vlak.gedempt {
		fill-opacity: 0.24;
	}

	/* Het laagnummer bij de vorm (C6). Zelfde kleur als de lijn, met een rand in
	   de bedkleur eromheen — anders leest een 8 op een rasterlijn als een 3. */
	.laagnummer {
		pointer-events: none;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	/* Buiten het bed of buiten het vel (C2): een gloed ónder de vorm, zodat de
	   laagkleur zelf leesbaar blijft. Twee kleuren, twee betekenissen — rood
	   voor "daar komt de kop niet", amber voor "daar ligt geen materiaal". */
	.buiten-gloed {
		stroke: var(--danger-solid);
		stroke-width: 6;
		stroke-opacity: 0.32;
		stroke-linejoin: round;
		pointer-events: none;
	}
	/* Buiten het vel: amber én onderbroken. Twee coderingen, want amber op een
	   gele laaglijn (--layer-3) is een verschil dat bij deuteranopie en in fel
	   werkplaatslicht verdwijnt. Onderbroken past ook bij wat het zegt: het
	   materiaal onder deze vorm houdt op. De vorm zelf blijft doorgetrokken —
	   gestreepte lijnen betekenen op dit canvas "zit in geen laag". */
	.buiten-gloed.velrand {
		stroke: var(--warn-solid);
		stroke-dasharray: 3 3;
		stroke-opacity: 0.55;
	}
	.buiten-strook {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-top: 1px solid var(--line);
		background: var(--surface-1);
	}
	.buiten-strook .regel {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		padding-left: var(--space-2);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-1);
		border-left: 4px solid var(--danger-solid);
	}
	.buiten-strook .regel.velrand {
		border-left-color: var(--warn-solid);
	}
	/* Het teken is de tweede codering náást de kleur: ook zwart-wit afgedrukt
	   blijft het een uitroepteken in een cirkel. */
	.buiten-strook .teken {
		flex: none;
		width: 16px;
		height: 16px;
		margin-top: 1px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		font-weight: 700;
		font-size: var(--text-xs);
		color: var(--on-color);
		background: var(--danger-solid);
	}
	.buiten-strook .regel.velrand .teken {
		background: var(--warn-solid);
		color: var(--void);
	}
	.head line {
		stroke: var(--accent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		opacity: 0.4;
	}
	.head circle {
		fill: none;
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
	}
	/* ── Voortgang tijdens een job (gat J3) ────────────────────────────────────
	   Het spoor is dun en flauw: het is context onder het werk, geen tweede
	   tekening erbovenop. Bewust in --text-2 en niet in het accent of een
	   laagkleur — het accent is de kop, en een laagkleur zou beweren dat dit
	   stuk in díe laag gebrand is, en dat weten we niet. */
	/* De afgelegde baan: breed en zacht, onder het ontwerp door. Breed genoeg om
	   ook op een uitgezoomd bed te lezen, zacht genoeg om de laagkleur erboven
	   niet te verdringen. */
	.spoor-baan {
		fill: none;
		stroke: var(--accent);
		stroke-width: 6;
		stroke-opacity: 0.38;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	/* Het verse stuk in het accent: daar is de machine nu bezig, en dat is het
	   enige stuk waarvan je zeker weet dat het net gebeurd is. */
	.spoor polyline.vers {
		stroke: var(--accent);
		stroke-width: 1.6;
		stroke-opacity: 0.9;
	}
	/* De ring om de kop: de baan als flauwe cirkel zodat je ziet hoe ver 100%
	   ligt, en de voortgang erin. */
	.head circle.ring-baan {
		stroke: var(--accent);
		stroke-width: 2.5;
		stroke-opacity: 0.16;
	}
	.head circle.ring {
		stroke: var(--accent);
		stroke-width: 2.5;
		stroke-linecap: round;
	}
	/* ── Het nulpunt van de gebruiker (gat J12) ─────────────────────────────── */
	.nulpunt-merk line {
		stroke: var(--text-1);
		stroke-width: 1.4;
		vector-effect: non-scaling-stroke;
	}
	.nulpunt-merk text {
		fill: var(--text-1);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3;
		stroke-linejoin: round;
	}
	/* Waar het werk terechtkomt: gestippeld en gedempt, want het is geen vorm
	   maar een aankondiging. Niet in --danger of --warn — er is niets mis; het
	   is precies wat je gevraagd hebt. */
	.brandt-hier rect {
		fill: none;
		stroke: var(--text-1);
		stroke-width: 1;
		stroke-dasharray: 5 4;
		stroke-opacity: 0.55;
	}
	/* Het vel op zijn nieuwe plek staat een stap zachter dan het werk erin: het
	   is de ondergrond, niet het onderwerp. */
	.brandt-hier rect.velschets {
		stroke-opacity: 0.3;
		stroke-dasharray: 2 5;
	}
	.brandt-hier text {
		fill: var(--text-2);
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3;
		stroke-linejoin: round;
	}
	/* Zelfde plek en zelfde toon als de spooruitleg: een regel die zegt wat je
	   voor je hebt, niet een waarschuwing. */
	.tool-uitleg {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		border-top: 1px solid var(--line-1);
	}
	.tool-uitleg em {
		font-style: normal;
		color: var(--text-1);
	}
	.spoor-uitleg {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		border-top: 1px solid var(--line-1);
	}
	/* Het merkje is het stukje lijn zelf: zo hoef je niet te raden welke lijn op
	   het bed bij deze zin hoort. */
	.spoor-merk {
		flex: none;
		width: 22px;
		height: 0;
		margin-top: 0.5em;
		border-top: 2px solid var(--accent);
		opacity: 0.9;
	}
	.spoor-uitleg .mono {
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	.hit {
		cursor: pointer;
	}
	/* Fijn gestippeld en op volle sterkte, zodat een hulplijn niet te verwarren
	   is met de kopmarkering (dezelfde accentkleur, maar doorgetrokken en
	   halfdoorzichtig) of met de gestreepte selectiecontour. */
	.guide {
		pointer-events: none;
	}
	.guide line {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 2 2;
		vector-effect: non-scaling-stroke;
	}
	.guide text {
		fill: var(--accent);
		font-variant-numeric: tabular-nums;
		/* Een randje in de bedkleur onder de letters: het woordje staat pal naast
		   het werkstuk en zou anders over een contour of een greep vallen. */
		paint-order: stroke;
		stroke: var(--bed);
		stroke-width: 3px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
		/* Geen font-size hier: die wordt per element uitgerekend, want deze tekst
		   staat in millimeters en zou anders met de zoom meegroeien. */
	}
	.hit.passive {
		pointer-events: none;
	}
	.pending {
		stroke: var(--accent);
		stroke-width: 1;
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.endpoint {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		pointer-events: none;
	}
	/* Onzichtbare trefzone om een greep heen; de greep zelf is te klein om te
	   raken zodra hij een vaste schermmaat heeft. */
	.grip {
		fill: transparent;
		stroke: none;
		cursor: grab;
		touch-action: none;
	}
	.grip:active {
		cursor: grabbing;
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
		font-variant-numeric: tabular-nums;
		/* Geen font-size hier: die wordt per element uitgerekend, omdat deze
		   tekst in millimeters staat en anders met de zoom meegroeit. */
		fill: var(--accent);
		font-family: var(--font-mono, monospace);
	}
	.knot {
		fill: var(--surface-1);
		stroke: var(--accent);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		pointer-events: none;
	}
	/* De trefzone ligt ná de greep in de boom; :has kijkt vooruit. */
	.knot:has(+ .grip:hover) { fill: var(--accent); }
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
	.zoom .fit {
		display: flex;
		align-items: center;
		gap: 4px;
		width: auto;
		padding: 0 var(--space-3);
		font-size: var(--text-xs);
	}
	.zoom button {
		min-width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.zoom button:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.zoom .snap.aan {
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
	}
	.zoom .scheiding {
		width: 1px;
		align-self: stretch;
		margin: 2px 2px;
		background: var(--line);
	}
	.zoom .val {
		font-size: 11px;
		padding: 0 8px;
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
		pointer-events: none;
	}
	.selection rect.handle-hit {
		fill: transparent;
		stroke: none;
		touch-action: none;
	}
	.selection rect.handle-hit.grabbable {
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
	}
	.empty {
		position: absolute;
		inset: auto 0 var(--space-6) 0;
		text-align: center;
		color: var(--text-2);
	}
</style>
