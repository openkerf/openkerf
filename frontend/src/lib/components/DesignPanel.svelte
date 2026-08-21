<script lang="ts">
	import {
		LAYER_COLORS,
		elementName,
		inkOn,
		type DesignOperation,
		type DesignStore
	} from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';
	import ArrangeIcon from './ArrangeIcon.svelte';
	import Menu from './Menu.svelte';
	import { en } from '$lib/i18n/en';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import { layerMenu, type Menu as MenuList } from '$lib/actions';
	import { untrack } from 'svelte';

	let {
		design,
		edits,
		canEdit = false,
		onRotate,
		onAssign,
		onLayerChange,
		onArrange,
		cornerNote = null,
		onPrune,
		tidyNote = null,
		onImage,
		onImageDpi,
		box = null,
		onSetPosition,
		onSetSize,
		image = null,
		onImageSet,
		onImageClear,
		show = 'selection',
		bed = null
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onRotate?: (angleDeg: number) => void;
		onAssign?: (operationId: string, assigned: boolean) => void;
		onLayerChange?: () => void;
		/** Alleen nog voor "alles op het bed leggen": de rest van het schikken
		 *  woont since v4 in de actiebalk en het rechterklikmenu. */
		onArrange?: (action: string) => void;
		/** Wat er van de last hoekbewerking te melden valt (overgeslagen
		 *  hoeken). Op een vaste plek in het paneel, niet in een browserpopup. */
		cornerNote?: string | null;
		/** Lege lagen weg. */
		onPrune?: () => void;
		/** Wat er van de last indeel-handeling te melden valt. */
		tidyNote?: string | null;
		onImage?: (adjustment: string) => void;
		onImageDpi?: (dpi: number) => void;
		/** Live maten tijdens het slepen; valt terug op de selectie zelf. */
		box?: { x: number; y: number; width: number; height: number } | null;
		onSetPosition?: (x: number, y: number) => void;
		onSetSize?: (width: number, height: number) => void;
		/** Wat er op de gekozen afbeelding aanstaat; komt van de API. */
		image?: {
			dpi: number | null;
			dither_types: string[];
			adjustments: {
				name: string;
				label: string;
				enabled: boolean;
				ranges: Record<string, number[]>;
				values: Record<string, string | number | boolean>;
			}[];
		} | null;
		onImageSet?: (
			name: string,
			enabled: boolean,
			values: Record<string, unknown> | null
		) => void;
		onImageClear?: () => void;
		/** Welk deel getoond wordt. Selectie en lagen naast elkaar in één
		 *  paneel werd te druk om iets in terug te vinden. */
		show?: 'selection' | 'layers';
		/** Bedmaat in mm, om te zien of er iets buiten valt. */
		bed?: { width: number; height: number } | null;
	} = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);
	let selected = $derived(design.selected);
	let size = $derived(design.selectedSize);

	// Wat buiten het bed ligt, brandt niet mee en is lastig te pakken. Beter
	// melden met een uitweg dan de gebruiker laten ontdekken dat er iets mist.
	let strays = $derived.by(() => {
		const perMm = design.design?.units_per_mm;
		if (!bed || !perMm) return [];
		return design.elements.filter((element) => {
			if (!element.bounds) return false;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			return x0 < -0.5 || y0 < -0.5 || x1 > bed.width + 0.5 || y1 > bed.height + 0.5;
		});
	});
	// Tijdens het slepen laat de canvaslaag een voorbeeldkader zien; die maten
	// horen hier dan ook te staan, anders lopen paneel en canvas uit elkaar.
	let live = $derived(box ?? size);

	// Verhouding vasthouden. Zonder dit vervormt een logo zodra je één maat
	// intikt, en dat merk je pas als het gebrand is.
	let linked = $state(true);

	function commitPosition(axis: 'x' | 'y', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value)) return;
		onSetPosition?.(axis === 'x' ? value : live.x, axis === 'y' ? value : live.y);
	}

	function commitSize(axis: 'width' | 'height', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value) || value <= 0) return;
		if (linked && live.width > 0 && live.height > 0) {
			const factor = value / (axis === 'width' ? live.width : live.height);
			onSetSize?.(live.width * factor, live.height * factor);
			return;
		}
		onSetSize?.(
			axis === 'width' ? value : live.width,
			axis === 'height' ? value : live.height
		);
	}
	let chosen = $derived(design.selectedElements);

	/** De lagen waar de selectie in zit, met hun kleur en brandnummer. */
	let inLagen = $derived.by(() => {
		const ids = new Set(chosen.flatMap((e) => e.operation_ids ?? []));
		const gewoon = design.operations.filter((op) => !op.grid);
		return gewoon
			.map((op, index) => ({ ...op, nummer: index + 1 }))
			.filter((op) => ids.has(op.id));
	});
	let selectedIds = $derived(design.selectedIds);

	// ------------------------------------------------------------- de stand
	//
	// Draaien en spiegelen waren tot nu toe blinde handelingen: je kon klikken
	// maar niet zien waar je stond, dus elke klik stapelde op de vorige en de
	// enige weg terug was ongedaan maken. De engine wéét de stand — hij bewaart
	// hem in de matrix van elke node — dus die staat nu in de snapshot en het
	// paneel toont hem. Daarmee wordt elke handeling een waarde in plaats van
	// een stap: hetzelfde getal intikken geeft hetzelfde beeld, hoe vaak je ook
	// geklikt hebt.

	/** De hoek van de selectie, of null als de vormen het oneens zijn. */
	let pose = $derived.by(() => {
		const poses = chosen.map((e) => e.pose).filter(Boolean) as {
			angle_deg: number;
			mirrored: boolean;
		}[];
		if (!poses.length) return { angle: null as number | null, mirrored: false, mixed: false };
		const first = poses[0];
		const mixed = poses.some((p) => Math.abs(p.angle_deg - first.angle_deg) > 0.05);
		return {
			angle: mixed ? null : first.angle_deg,
			// Eén gespiegelde vorm in de selectie is genoeg om het te melden;
			// zwijgen zou betekenen dat je het pas op het werkstuk ziet.
			mirrored: poses.some((p) => p.mirrored),
			mixed
		};
	});

	/**
	 * Waar de selectie stond toen je hem pakte.
	 *
	 * Dit is het anker voor "Terugzetten": zolang een selectie active is, kun
	 * je in één tik terug naar precies de stand van vóór het schikken — niet
	 * naar de vorige klik, maar naar het origineel. Bewust géén schaduwkopie
	 * van het document: elke tik blijft een gewone, ongedaan te maken bewerking
	 * in de engine, en niets stroomafwaarts (job, pre-flight, autosave) kijkt
	 * naar geometrie die er niet echt is.
	 */
	let anchor = $state<{
		key: string;
		angle: number | null;
		mirrored: boolean;
		box: { x: number; y: number; width: number; height: number };
	} | null>(null);

	$effect(() => {
		const key = selectedIds.join(',');
		const start = design.selectedSize;
		const stand = pose;
		untrack(() => {
			if (!key || !start) {
				anchor = null;
				return;
			}
			// Alleen bij een níeuwe selectie opnieuw ankeren. Zou het anker
			// meelopen met elke bewerking, dan was het geen anker maar een
			// spiegel van de last klik.
			if (anchor?.key === key) return;
			anchor = { key, angle: stand.angle, mirrored: stand.mirrored, box: { ...start } };
		});
	});

	function near(a: number, b: number, slack = 0.05) {
		return Math.abs(a - b) < slack;
	}

	/** Is the selection somewhere other than where you grabbed it? */
	let moved = $derived.by(() => {
		if (!anchor || !size) return false;
		if (pose.mirrored !== anchor.mirrored) return true;
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			return true;
		return (
			!near(size.x, anchor.box.x) ||
			!near(size.y, anchor.box.y) ||
			!near(size.width, anchor.box.width) ||
			!near(size.height, anchor.box.height)
		);
	});

	/**
	 * In words, what has changed since it was clicked.
	 *
	 * Only what the button beside it undoes, and not what is there now: the sizes
	 * are already in the fields above, and saying that twice makes the line longer
	 * without making it clearer.
	 */
	let movedSummary = $derived.by(() => {
		if (!anchor || !size) return '';
		const parts: string[] = [];
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			parts.push(t('panel.moved.rotated', { angle: format(pose.angle) }));
		if (pose.mirrored !== anchor.mirrored) parts.push(t('panel.moved.mirrored'));
		// Rotating about the centre changes the bounding box, so size and place are
		// only reported when nothing else changed — otherwise it says "moved" on
		// every rotation and the word stops meaning anything.
		if (!parts.length) {
			const otherSize =
				!near(size.width, anchor.box.width) || !near(size.height, anchor.box.height);
			const otherPlace = !near(size.x, anchor.box.x) || !near(size.y, anchor.box.y);
			// With one shape a different box really is a different size. With more
			// shapes the box is the hull of the whole selection, and that changes as
			// well when the shapes only move relative to *each other* — aligning, for
			// instance. Saying "scaled" then is untrue: nothing got bigger or smaller.
			// Measured after one click on "Align top" with three shapes: the box got
			// shorter and the line said "scaled".
			if (otherSize) parts.push(t(chosen.length > 1 ? 'panel.moved.arranged' : 'panel.moved.scaled'));
			else if (otherPlace) parts.push(t('panel.moved.moved'));
		}
		return parts.join(' · ') || t('panel.moved.changed');
	});

	// One decimal, but not a bare ".0": an angle of 45 is 45°, not 45.0°. The
	// decimal separator comes from the reader's locale.
	function format(value: number) {
		return i18n.number(Math.round(value * 10) / 10);
	}

	async function setAngle(raw: string) {
		const value = Number(raw.replace(',', '.'));
		if (!Number.isFinite(value) || !selectedIds.length) return;
		if ((await edits.rotate(selectedIds, ((value % 360) + 360) % 360, true)).ok)
			await design.load();
	}

	/** Terug naar de stand van vóór het schikken, in één tik. */
	async function restore() {
		if (!anchor || !selectedIds.length) return;
		const ids = selectedIds;
		// Volgorde telt: spiegelen kantelt het teken van de hoek, dus de hoek
		// gaat er daarna overheen, en het kader als last — dat set ook de
		// verschuiving terug die draaien om het midden achterlaat.
		if (pose.mirrored !== anchor.mirrored) await edits.mirror(ids, 'horizontal');
		if (anchor.angle !== null) await edits.rotate(ids, anchor.angle, true);
		const { x, y, width, height } = anchor.box;
		await edits.resize(ids, x, y, width, height);
		await design.load();
	}

	// Wat er open staat van de zelden gebruikte groepen. Onthouden per paneel,
	// niet per selectie: wie booleans gebruikt, gebruikt ze de hele middag.
	let openGroups = $state<Record<string, boolean>>({});

	// Hoekbewerking: de stijl en de maat blijven staan tussen twee bewerkingen,
	// want wie één hoek afrondt, rondt er meestal meer af met dezelfde maat.
	let hoekstijl = $state<'round' | 'chamfer'>('round');
	let hoekmaat = $state('3');

	const hoekLabel = $derived.by(() => {
		const maat = Number(hoekmaat);
		const wat = hoekstijl === 'round' ? 'afronden' : 'afschuinen';
		if (!chosen.length) return `CornersDialog ${wat}`;
		const aantal = chosen.length === 1 ? '1 vorm' : `${chosen.length} vormen`;
		if (!Number.isFinite(maat) || maat <= 0) return `${aantal} ${wat}`;
		// De primaire knop zegt wát er komt, niet dát er iets komt (DESIGN-SYSTEM).
		return `${aantal} ${wat} — ${maat} mm`;
	});

	/** Eén hoek van 30 mm met de gekozen maat eraf, als voorbeeldtekening. */
	const hoekVoorbeeld = $derived.by(() => {
		const zijde = 30;
		const maat = Math.min(Math.max(Number(hoekmaat) || 0, 0), zijde / 2);
		const p = 2; // marge in de viewBox
		if (maat <= 0) return `M ${p} ${p + zijde} L ${p} ${p} L ${p + zijde} ${p}`;
		const start = `M ${p} ${p + zijde} L ${p} ${p + maat}`;
		const eind = `L ${p + zijde} ${p}`;
		if (hoekstijl === 'chamfer') return `${start} L ${p + maat} ${p} ${eind}`;
		return `${start} A ${maat} ${maat} 0 0 1 ${p + maat} ${p} ${eind}`;
	});

	let editingLayer = $state<string | null>(null);
	/** Het rechterklikmenu op een laagrij. */
	/**
	 * Het menu op een laagrij, uit één plek.
	 *
	 * De rechterklik en de ⋯-knop openen hetzelfde menu op dezelfde manier. Ze
	 * stonden als twee aanroepen in de opmaak, en dan is het een kwestie van tijd
	 * tot de een een regel heeft die de ander mist.
	 */
	function opendLaagMenu(op: DesignOperation, index: number, x: number, y: number) {
		rijMenu = {
			x,
			y,
			lijst: layerMenu(
				{
					label: op.label,
					shapeCount: op.element_ids.length,
					burns: op.output,
					visible: !design.isLayerHidden(op.id),
					first: index === 0,
					last: index === plainLayers.length - 1,
					selection: selectedIds.length,
					inside: selectedIds.length > 0 && membership(op.id) === 'all',
					may: canEdit,
					locked: op.grid ? t('reason.testGridLayer') : undefined
				},
				{
					selectShapes: () => design.selectMany(op.element_ids),
					putSelection: (inside) => onAssign?.(op.id, inside),
					toggleBurns: () => patchLayer(op.id, { output: !op.output }),
					toggleVisible: () => design.toggleLayer(op.id),
					up: () => moveLayer(op.id, 'up'),
					down: () => moveLayer(op.id, 'down'),
					openSettings: () => (editingLayer = op.id),
					remove: () => (confirmDrop = op.id)
				}
			)
		};
	}

	let rijMenu = $state<{
		lijst: MenuList;
		x: number;
		y: number;
		/** Voor een menu dat aan een knop onderaan het paneel hangt. */
		upward?: boolean;
	} | null>(null);
	let openGrid = $state<number | null>(null);

	// Rasterlagen zijn geen gewone lagen: ze horen bij één testraster en hun
	// snelheid en vermogen zíjn de test. Eén regel per raster dus.
	/**
	 * Wat splitsen zou opleveren. Een geïmporteerd pad houdt al zijn panelen in
	 * één vorm; het getal hier is het aantal vormen dat de knop belooft.
	 */
	const teSplitsen = $derived.by(() => {
		const samengesteld = chosen.filter((e) => (e.subpaths ?? 1) > 1);
		return {
			vormen: samengesteld.length,
			stukken: samengesteld.reduce((n, e) => n + (e.subpaths ?? 1), 0)
		};
	});

	/**
	 * Kan deze selectie een vlak dragen, en heeft ze dat al?
	 *
	 * Een lijn en een punt hebben geen binnenkant; de knop hoort er dan niet te
	 * staan. Zonder vulling rastert een vorm alleen zijn omtrek, en dat is de
	 * hele reden dat deze knop bestaat.
	 */
	const VULBAAR = ['elem rect', 'elem ellipse', 'elem path', 'elem polyline'];
	const vulbaar = $derived(chosen.filter((e) => VULBAAR.includes(e.type)));
	const alGevuld = $derived(
		vulbaar.length > 0 && vulbaar.every((e) => Boolean(e.fill))
	);

	/** In hoeveel lagen de selectie nu zit — het getal dat 'alleen in' opheft. */
	const nuInLagen = $derived(
		new Set(chosen.flatMap((e) => e.operation_ids ?? [])).size
	);

	let plainLayers = $derived(operations.filter((o) => !o.grid));
	/** Lagen zonder werk: wat 'lege lagen opruimen' weghaalt. */
	const legeLagen = $derived(plainLayers.filter((op) => !op.element_ids.length));

	let gridGroups = $derived.by(() => {
		const byGrid = new Map<number, typeof operations>();
		for (const op of operations) {
			if (!op.grid) continue;
			const list = byGrid.get(op.grid.grid_id) ?? [];
			list.push(op);
			byGrid.set(op.grid.grid_id, list);
		}
		return [...byGrid.entries()].map(([id, ops]) => ({ id, ops }));
	});

	async function removeGrid(gridId: number) {
		const token =
			typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		await fetch(`/api/library/testgrids/${gridId}/remove-from-design`, {
			method: 'POST',
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		});
		onLayerChange?.();
	}
	let newLayerType = $state('cut');
	// Een laag weggooien neemt zijn toewijzingen mee. Dat mag niet op één tik
	// naast de snelheidsvelden gebeuren, dus er komt een bevestiging tussen.
	let confirmDrop = $state<string | null>(null);
	// Alles tegelijk weggooien is dezelfde handeling maal tien, dus dezelfde
	// bevestiging — maar wel eentje die zegt hóéveel er weggaat en wat blijft.
	let confirmDropAll = $state(false);

	const LAYER_TYPES = [
		{ value: 'cut', label: t('panel.kind.cut'), noun: t('panel.kind.cutNoun') },
		{ value: 'engrave', label: t('panel.kind.engrave'), noun: t('panel.kind.engraveNoun') },
		{ value: 'raster', label: t('panel.kind.raster'), noun: t('panel.kind.rasterNoun') },
		{ value: 'dots', label: t('panel.kind.dots'), noun: t('panel.kind.dotsNoun') }
	];
	let newLayerNoun = $derived(
		LAYER_TYPES.find((type) => type.value === newLayerType)?.noun ?? t('panel.kind.layerNoun')
	);

	async function addLayer() {
		if (await edits.addLayer(newLayerType)) onLayerChange?.();
	}

	async function patchLayer(id: string, fields: Record<string, unknown>) {
		if (await edits.updateLayer(id, fields)) onLayerChange?.();
	}

	async function moveLayer(id: string, direction: 'up' | 'down') {
		if (await edits.moveLayer(id, direction)) onLayerChange?.();
	}

	/** Graveren vóór snijden, in één klik (gat L2). */
	async function sorteerLagen() {
		const uit = await edits.sortLayers();
		if (uit.ok) onLayerChange?.();
	}

	/**
	 * Het soort bewerking van een bestaande laag wijzigen (gat L3).
	 *
	 * De laag krijgt een nieuw id — de engine kan het type van een knoop niet
	 * wisselen — dus de uitklap sluit: hij zou anders naar een laag wijzen die
	 * niet meer bestaat.
	 */
	async function retypeLayer(id: string, type: string) {
		const uit = await edits.retypeLayer(id, type);
		if (!uit.ok) return;
		editingLayer = null;
		onLayerChange?.();
	}

	// ── Slepen om te herordenen (gat L1) ──────────────────────────────────────
	//
	// Niet de HTML5-sleep-API: die werkt niet op een aanraakscherm, en naast een
	// laser is een tablet het gebruikelijke device. Pointer-events werken op
	// alle drie de apparaten met dezelfde code.
	//
	// De knoppen ↑/↓ in de uitklap blijven staan, en de greep zelf doet met de
	// pijltjestoetsen hetzelfde — slepen is een extra weg, geen vervanging.
	let slepen = $state<{ id: string; van: number; naar: number } | null>(null);
	let rijElementen: (HTMLElement | null)[] = [];
	let rijGrenzen: { top: number; midden: number }[] = [];

	function startSleep(event: PointerEvent, id: string, index: number) {
		if (!canEdit || edits.busy) return;
		event.preventDefault();
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		// De maten één keer opmeten, aan het begin: tijdens het slepen verschuift
		// de lijst zelf niet, en opnieuw meten per beweging kost een layout per
		// muisbeweging.
		rijGrenzen = rijElementen
			.filter((el): el is HTMLElement => !!el)
			.map((el) => {
				const doos = el.getBoundingClientRect();
				return { top: doos.top, midden: doos.top + doos.height / 2 };
			});
		slepen = { id, van: index, naar: index };
	}

	function beweegSleep(event: PointerEvent) {
		if (!slepen) return;
		let naar = 0;
		for (let i = 0; i < rijGrenzen.length; i++) {
			if (event.clientY > rijGrenzen[i].midden) naar = i + 1;
		}
		// Boven de eigen rij landen betekent: op die plek. Onder de eigen rij
		// schuift alles ertussen één op, dus is de bestemming er één lager.
		if (naar > slepen.van) naar -= 1;
		naar = Math.min(Math.max(naar, 0), rijGrenzen.length - 1);
		if (naar !== slepen.naar) slepen = { ...slepen, naar };
	}

	async function eindSleep() {
		const beweging = slepen;
		slepen = null;
		if (!beweging || beweging.naar === beweging.van) return;
		const uit = await edits.dropLayerAt(beweging.id, beweging.naar);
		if (uit.ok) onLayerChange?.();
	}

	/**
	 * Compacte lijst (gat L5).
	 *
	 * Gemeten: onze rij is 76 px op de desktop en 111 px op een aanraakscherm;
	 * LightBurn doet 23–26 px. Boven de acht lagen is onze lijst daarmee een
	 * scrollpartij. Compact set identiteit en waarden op één regel in plaats van
	 * twee — de velden blijven staan, want bijstellen naast een draaiende machine
	 * mag geen submenu kosten. Dat is precies waarom dit paneel bestaat.
	 *
	 * De stand blijft bewaard: wie met vijftien lagen werkt, doet dat de hele
	 * middag.
	 */
	let compact = $state(
		typeof window !== 'undefined' && localStorage.getItem('openkerf.lagen-compact') === 'aan'
	);

	// Dezelfde volgorde als de server (`Drawing.BURN_ORDER`): eerst wat het
	// oppervlak raakt, snijden als last. Hier alleen om te weten of de knop
	// nog iets te doen heeft — sorteren zelf gebeurt in de engine.
	const BRAND_ORDER: Record<string, number> = {
		'op image': 0,
		'op raster': 1,
		'op engrave': 2,
		'op dots': 3,
		'op cut': 4
	};

	let gesorteerd = $derived.by(() => {
		const rangen = plainLayers.map((o) => BRAND_ORDER[o.type] ?? 99);
		return {
			kanSorteren: rangen.some((rang, i) => i > 0 && rang < rangen[i - 1])
		};
	});

	function compactSchakel() {
		compact = !compact;
		if (typeof window !== 'undefined') {
			localStorage.setItem('openkerf.lagen-compact', compact ? 'aan' : 'uit');
		}
	}

	async function dropLayer(id: string) {
		confirmDrop = null;
		if (await edits.removeLayer(id)) onLayerChange?.();
	}

	async function dropAllLayers() {
		confirmDropAll = false;
		if (await edits.removeAllLayers()) onLayerChange?.();
	}

	/** The kind of operation in the reader's language; the engine calls it "op cut". */
	function typeName(type: string): string {
		const kind = type.replace(/^(op|effect) /, '');
		const key = `panel.type.${kind}` as MessageKey;
		return key in en ? t(key) : kind;
	}

	/**
	 * The layer type as the segmented control knows it.
	 *
	 * The engine calls them `op cut`; our four choices are called `cut`. An image
	 * layer (`op image`) has no choice of its own — the engine makes that itself
	 * when an image is placed — and falls under raster, because that is what it
	 * does.
	 */
	function kindOf(type: string): string {
		const kind = String(type).replace(/^op /, '');
		return kind === 'image' ? 'raster' : kind;
	}

	/** Power sits at 0–1000 in the engine; the user reckons in per cent. */
	function powerPercent(op: { power: number | null }): number | null {
		return op.power === null ? null : Math.round(op.power / 10);
	}

	/**
	 * A number from a field that sits right in the row.
	 *
	 * Empty or nonsense is left as it was rather than turned into zero: zero mm/s
	 * is a machine standing still with the laser on.
	 */
	function commitNumber(
		event: Event & { currentTarget: HTMLInputElement },
		id: string,
		field: string,
		was: number | null
	) {
		const value = Number(event.currentTarget.value);
		if (!Number.isFinite(value) || value <= 0) {
			event.currentTarget.value = was === null ? '' : String(was);
			return;
		}
		if (value === was) return;
		patchLayer(id, { [field]: value });
	}

	// An operation is "on" for the selection when *every* chosen element is in it.
	function membership(operationId: string): 'all' | 'some' | 'none' {
		if (chosen.length === 0) return 'none';
		const inside = chosen.filter((e) => e.operation_ids.includes(operationId)).length;
		if (inside === 0) return 'none';
		return inside === chosen.length ? 'all' : 'some';
	}

	/**
	 * The three values of a layer as one line, for the compact mode.
	 *
	 * With units, because "35 · 100 · 1" is a row of numbers without meaning.
	 * Passes only when there is more than one: that is the case for a couple of
	 * layers at most, and "1×" on all the others is noise.
	 */
	function short(op: { speed: number | null; power: number | null; passes: number | null }) {
		const parts: string[] = [];
		parts.push(op.speed === null ? '—' : `${op.speed}`);
		const percent = powerPercent(op);
		parts.push(percent === null ? '—' : `${percent}%`);
		if ((op.passes ?? 1) > 1) parts.push(`${op.passes}×`);
		return parts.join(' · ');
	}

	function describe(op: { speed: number | null; power: number | null }) {
		const parts: string[] = [];
		if (op.speed !== null) parts.push(`${op.speed} mm/s`);
		if (op.power !== null) parts.push(`${Math.round((op.power / 1000) * 100)}%`);
		return parts;
	}
</script>

{#if show === 'selection' && strays.length}
	<div class="section stray">
		<!-- The same words as the strip under the canvas (gap C2): there says what is
		     going on, here says the way out. Two places naming the same problem
		     differently makes the reader think there are two problems. -->
		<p>{t('canvas.outsideBed', { n: strays.length })}</p>
		{#if canEdit}
			<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('rescue')}>
				{t('action.rescue')}
			</button>
		{/if}
	</div>
{/if}

<div class="section">
	<!-- Heading, count and history on one line. They used to be on three, and
	     three lines above the selection are three lines pushing the selection
	     down. -->
	<div class="section-head">
		<h2 class="section-title">{t('panel.design')}</h2>
		{#if elements.length}
			<span class="muted mono tally">{t('panel.elements', { n: elements.length })}</span>
		{/if}
		<!-- Undo and redo used to be here. They moved to the action bar above the
		     canvas: they were the only two buttons in the app that disappeared the
		     moment you were on the Job tab, while that is precisely where you
		     sometimes want to take something back. Since the move they have ⌘Z and
		     ⌘⇧Z as well. -->
	</div>
	{#if edits.error}
		<p class="edit-error" role="alert">{edits.error}</p>
	{/if}
	{#if elements.length === 0}
		<!-- This used to say "Use 'Load design…' in the Job tab". That button does
		     not exist and never has (repo-wide grep: this line was the only place
		     that name appeared). An empty state pointing at an invented button is
		     worse than one that keeps quiet: you go looking. -->
		<p class="empty">{t('panel.empty')}</p>
	{/if}
</div>

{#if show === 'selection' && selected && size}
	<div class="section">
		<h2 class="section-title">{t('panel.selection')}</h2>
		<div class="selected">
			<div class="head">
				<span class="name" title={chosen.length > 1 ? undefined : selected.label}>
					{chosen.length > 1 ? t('panel.shapes', { n: chosen.length }) : elementName(selected)}
				</span>
				<!-- How many layers the selection is in used to be a paragraph of its own
				     at the bottom of the panel, out of sight. It belongs to the identity
				     of what you are holding, so it sits next to the name. -->
				<!-- *Which* layer, not how many. "in 1 layer" was true and useless: that
				     the shape is in something is not the question, the question is what.
				     And this is exactly what you check before starting — with the layer
				     colour, so it matches what you see on the canvas. -->
				<span class="in-layers">
					{#if inLagen.length === 0}
						<span class="geenlaag" title={t('panel.noLayer.title')}>{t('panel.noLayer')}</span>
					{:else}
						{#each inLagen as laag (laag.id)}
							<span class="laagchip" title={t('panel.layerChip', { n: laag.nummer, label: laag.label })}>
								<span class="stip" style="background: {laag.color}"></span>
								{laag.label}
							</span>
						{/each}
					{/if}
				</span>
				<button class="clear" onclick={() => design.select(null)}>{t('panel.clear')}</button>
			</div>
			<!-- Sizes, position and angle as one grid of three lines: two columns of
			     numbers with the unit once on the right. They used to be freely
			     wrapping pills beside each other, so X ended up on the first line and Y
			     on its own on the second — and then two pairs no longer read as two
			     pairs. -->
			<div class="figures mono">
				<!-- The one-letter labels are translated too: "B" is Breedte in Dutch and
				     means nothing in English, where the same column reads "W". -->
				{#each [
					[t('panel.widthShort'), 'width', t('panel.width')],
					[t('panel.heightShort'), 'height', t('panel.height')]
				] as [label, key, naam] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							min="0.1"
							aria-label={t('panel.inMillimetres', { what: naam })}
							disabled={!canEdit}
							value={(live ?? size)[key as 'width' | 'height'].toFixed(1)}
							onchange={(e) => commitSize(key as 'width' | 'height', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<button
					class="link"
					aria-pressed={linked}
					disabled={!canEdit}
					title={linked ? t('panel.ratio.locked') : t('panel.ratio.free')}
					aria-label={linked ? t('panel.ratio.lockedShort') : t('panel.ratio.freeShort')}
					onclick={() => (linked = !linked)}
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if linked}
							<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
							<path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
						{:else}
							<path d="M9 12H5a3 3 0 0 1 0-6h4M15 12h4a3 3 0 0 1 0 6h-4" />
						{/if}
					</svg>
				</button>
				{#each [['X', 'x', t('panel.positionX')], ['Y', 'y', t('panel.positionY')]] as [label, key, naam] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							aria-label={t('panel.inMillimetres', { what: naam })}
							disabled={!canEdit}
							value={(live ?? size)[key as 'x' | 'y'].toFixed(1)}
							onchange={(e) => commitPosition(key as 'x' | 'y', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<span class="unit">mm</span>
			</div>

			{#if canEdit}
				<!-- De hoek stond nergens. Je kon draaien per 1° en per 90° maar
				     niet zien waar je stond, dus elke klik was een gok bovenop de
				     vorige. Nu is de hoek een waarde uit de engine: intikbaar,
				     en de stapjes verplaatsen hem in plaats van iets op te
				     stapelen. -->
				<div class="figures mono rotrow">
					<label class="f angle" class:mixed={pose.mixed}>
						<span aria-hidden="true">∠</span>
						<input
							type="number"
							step="1"
							inputmode="decimal"
							aria-label={t('panel.angle')}
							title={pose.mixed ? t('panel.angle.mixed') : t('panel.angle.title')}
							disabled={edits.busy || pose.mixed || pose.angle === null}
							value={pose.angle === null
								? ''
								: Number.isInteger(pose.angle)
									? pose.angle
									: pose.angle.toFixed(1)}
							placeholder={pose.mixed ? '—' : ''}
							onchange={(e) => setAngle(e.currentTarget.value)}
						/>
						<!-- The degree sign belongs *in* the field. As a column of its own it
						     sat three columns away on a tablet, apart from the number it
						     belongs to. -->
						<span class="suffix" aria-hidden="true">°</span>
					</label>
					<!-- Only the one-degree steps are left: that is the spinner belonging to
					     this field. Rotating by 90° is an operation and lives in the
					     right-click menu under "Rotate" (with , and . as shortcuts). -->
					{#each [[-1, ''], [1, '']] as [angle, icon] (angle)}
						<button
							class="icon step"
							disabled={edits.busy}
							title={t('panel.rotate.step', {
								angle: `${Number(angle) > 0 ? '+' : ''}${angle}`
							})}
							aria-label={t('panel.rotate.stepAria', {
								angle: `${Number(angle) > 0 ? '+' : ''}${angle}`
							})}
							onclick={() => onRotate?.(Number(angle))}
						>
							{#if icon}
								<ArrangeIcon name={String(icon)} size={18} />
							{:else}
								<span class="stepnum">{Number(angle) > 0 ? '+' : '−'}1</span>
							{/if}
						</button>
					{/each}
				</div>
				{#if pose.mixed}
					<p class="tip">{t('panel.angle.mixedNote')}</p>
				{/if}
			{/if}

			{#if selected.text}
				<!-- The content of the text is a value and belongs here; editing it is an
				     operation and lives in the right-click menu. This used to be one
				     button doing both, and then the text is only readable once you have
				     already clicked it. -->
				<p class="tekstwaarde" title={selected.text.text}>“{selected.text.text}”</p>
			{/if}

			<!-- Twelve icons — align, distribute, mirror, group — used to be here. They
			     moved to the action bar above the canvas: there they are visible on
			     every tab and do not scroll away. See DESIGN-SYSTEM v4, "Where an
			     operation belongs". -->

			{#if canEdit && (moved || pose.mirrored)}
				<!-- The anchor. As long as this selection is active, every rotation and
				     every mirroring can be taken back to how it was before the arranging
				     — not to the previous click. Clicking away makes it final; there is
				     nothing to commit, because every tap was already in the document and
				     can simply be undone. -->
				<div class="anchor" class:idle={!moved}>
					<span class="anchor-what">
						{#if moved}
							{t('panel.anchor.since', { what: movedSummary })}
						{:else}
							{t('panel.anchor.mirrored')}
						{/if}
					</span>
					{#if moved}
						<button
							class="anchor-back"
							disabled={edits.busy}
							title={t('panel.anchor.backTitle')}
							onclick={restore}
						><ArrangeIcon name="restore" size={16} /> {t('panel.anchor.back')}</button>
					{/if}
				</div>
			{/if}

			{#if selected.effect}
				<p class="hint">{t('panel.inEffect', { label: selected.effect.label })}</p>
			{/if}

			{#if teSplitsen.vormen}
				<!-- This is a diagnosis, not an operation: it says what you are holding.
				     The button that went with it ("Split into n shapes") moved to the
				     right-click menu, under "Edit path", with the same number. Without
				     this line the menu would promise a count you could not check
				     anywhere. -->
				<p class="tip">
					{t('panel.splittable', { n: teSplitsen.vormen, pieces: teSplitsen.stukken })}
				</p>
			{/if}
			{#if tidyNote}
				<p class="tip" role="status">{tidyNote}</p>
			{/if}
			{#if cornerNote}
				<p class="tip" role="status">{cornerNote}</p>
			{/if}

			<!-- Three collapsed folds used to be here: Combine (unite, difference,
			     intersect, exclude), Edit path (nest, offset, simplify, hatch, wobble)
			     and Corners. Fifteen operations behind three clicks, in a column you had
			     to scroll anyway. All fifteen are in the right-click menu on the shape
			     now, in submenus with the same names; Corners opens a window of its own
			     with the preview in it. -->

			{#if canEdit && selected.image}
				<!-- The edits are not destructive: the recipe runs over the original again
				     every time. Hence switches with their values, and not a row of
				     buttons where you have to remember what you pressed.

				     Collapsed, though: eight switches with sliders are on their own
				     longer than the rest of the panel put together, and you set them once
				     rather than over and over. -->
				<details
					class="fold"
					open={openGroups.image}
					ontoggle={(e) => (openGroups.image = e.currentTarget.open)}
				>
					<summary>
						{t('panel.image')}
						{#if image?.adjustments.some((a) => a.enabled)}
							<span class="fold-note on">
								{t('panel.image.on', { n: image.adjustments.filter((a) => a.enabled).length })}
							</span>
						{/if}
					</summary>
				<div class="imagefx">
					<div class="fx-head">
						<button
							class="rot"
							disabled={edits.busy || !image?.adjustments.some((a) => a.enabled)}
							onclick={() => onImageClear?.()}
						>{t('panel.image.clearAll')}</button>
					</div>

					{#each image?.adjustments ?? [] as item (item.name)}
						<div class="fx" class:on={item.enabled}>
							<label class="fx-toggle">
								<input
									type="checkbox"
									checked={item.enabled}
									disabled={edits.busy}
									onchange={(e) => onImageSet?.(item.name, e.currentTarget.checked, null)}
								/>
								<span>{item.label}</span>
							</label>
							{#if item.enabled}
								{#each Object.entries(item.values) as [key, value] (key)}
									{#if item.ranges[key]}
										<label class="fx-value">
											<span>{key}</span>
											<input
												type="range"
												min={item.ranges[key][0]}
												max={item.ranges[key][1]}
												step={key === 'radius' || key === 'factor' ? 0.1 : 1}
												{value}
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, {
														[key]: Number(e.currentTarget.value)
													})}
											/>
											<span class="mono fx-num">{value}</span>
										</label>
									{:else if key === 'type' && item.name === 'dither'}
										<label class="fx-value">
											<span>{t('panel.image.kind')}</span>
											<select
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, { type: e.currentTarget.value })}
											>
												{#each image?.dither_types ?? [] as option (option)}
													<option value={option} selected={option === value}>{option}</option>
												{/each}
											</select>
										</label>
									{/if}
								{/each}
							{/if}
						</div>
					{/each}

					<div class="fx-actions">
						<!-- Vectoriseren, bijsnijden en de snede terugnemen stonden hier.
						     Het zijn handelingen, dus staan ze in het rechterklikmenu op de
						     afbeelding. Wat blijft is DPI: dat is een eigenschap van deze
						     afbeelding en hoort bij de rest van het recept. -->
						<label class="dpi mono">
							DPI
							<input
								type="number"
								min="10"
								max="2000"
								step="10"
								value={selected.image.dpi ?? 96}
								onchange={(e) => onImageDpi?.(Number(e.currentTarget.value))}
							/>
						</label>
					</div>
				</div>
				</details>
			{/if}

			<!-- "Naar ander vel" stond hier als dichtgeklapte vouw met een knop per
			     vel. Het is een handeling en staat nu in het rechterklikmenu onder
			     "Naar een ander vel" — met dezelfde velnamen, zonder eerst uit te
			     klappen. -->

			<p class="hint">
				{#if canEdit}
					{t('panel.dragHint')}
				{:else}
					{t('panel.needsToken')}
				{/if}
			</p>
		</div>
	</div>
{/if}

{#if show === 'selection' && !selected}
	<div class="section">
		<p class="muted">{t('panel.nothingSelected')}</p>
	</div>
{/if}

{#if show === 'layers'}
	<div class="section">
		<div class="section-head">
			<h2 class="section-title">{t('panel.layers')}</h2>
			{#if plainLayers.length}
				<!-- What the number on the chip means is said once. Without it the list
				     reads as an arbitrary stack instead of as the order the machine works
				     in. -->
				<span class="order-note mono">{t('panel.burnOrder', { n: plainLayers.length })}</span>
			{/if}
		</div>

		{#if plainLayers.length > 1}
			<!--
				The bar above the list: one menu and one switch.

				There used to be four buttons on three lines here — sort, remove all,
				clear out empty layers, and the density. Three of those are verbs about
				the whole list, and by the placement rule those belong in a menu
				(DESIGN-SYSTEM v4). What stays is the density, because that is a way of
				looking, and the tidy-up line — which reports a *state* ("there are empty
				layers") and offers the way out in the same line.
			-->
			<div class="lijst-balk">
				{#if canEdit}
					<button
						class="lijstmeer"
						aria-haspopup="menu"
						title={t('panel.list.title')}
						onclick={(e) => {
							const doos = (e.currentTarget as HTMLElement).getBoundingClientRect();
							rijMenu = {
								x: doos.left,
								y: doos.bottom + 4,
								lijst: [
									{
										items: [
											{
												id: 'sorteer',
												label: t('panel.list.sort'),
												explain: t('panel.list.sort.explain'),
												off: gesorteerd.kanSorteren ? undefined : t('panel.list.sort.already'),
												run: sorteerLagen
											},
											{
												id: 'ruim',
												label: legeLagen.length
													? t('panel.list.pruneCount', { n: legeLagen.length })
													: t('panel.list.prune'),
												explain: t('panel.list.prune.explain'),
												off: legeLagen.length ? undefined : t('panel.list.prune.none'),
												run: () => onPrune?.()
											}
										]
									},
									{
										items: [
											{
												id: 'alles-weg',
												label: t('panel.list.dropAll'),
												explain: t('explain.layerRemove'),
												danger: true,
												run: () => (confirmDropAll = true)
											}
										]
									}
								]
							};
						}}
					>
						{t('panel.list')}
						<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
					</button>
				{/if}
				<span class="lijst-rek"></span>
				<button
					class="dichtheid"
					aria-pressed={compact}
					title={compact ? t('panel.density.compact') : t('panel.density.roomy')}
					onclick={compactSchakel}
				>
					<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if compact}
							<path d="M4 7h16M4 12h16M4 17h16" />
						{:else}
							<path d="M4 8h16M4 16h16" />
						{/if}
					</svg>
					{compact ? t('panel.density.compactLabel') : t('panel.density.roomyLabel')}
				</button>
			</div>
			{#if canEdit && legeLagen.length}
				<!-- A state with its way out in the same line. As a button in the bar it
				     was there even when there was nothing to clear out; as a line it is
				     only there when it means something, and then it says how many. -->
				<p class="opruimregel">
					{t('panel.empties', { n: legeLagen.length })}
					<button class="alsLink" disabled={edits.busy} onclick={() => onPrune?.()}
						>{t('panel.tidyUp')}</button
					>
				</p>
			{/if}
		{/if}
		{#if confirmDropAll}
			<!-- Say what goes and what stays. Throwing away a layer must not throw away
			     work, and that has to be readable here before you click — the same rule
			     as when removing a sheet. -->
			<div class="confirm">
				<span>
					{t('panel.dropAll.ask', { n: plainLayers.length })}
					{#if design.elements.length === 1}
						{t('panel.dropAll.oneShape')}
					{:else if design.elements.length}
						{t('panel.dropAll.shapes', { n: design.elements.length })}
					{:else}
						{t('panel.dropAll.noShapes')}
					{/if}
					{#if gridGroups.length}
						{t('panel.dropAll.gridsStay')}
					{/if}
				</span>
				<button class="rot" onclick={() => (confirmDropAll = false)}>{t('common.cancel')}</button>
				<button class="rot drop" disabled={edits.busy} onclick={dropAllLayers}>
					{t('panel.dropAll.confirm')}
				</button>
			</div>
		{/if}
		{#if !operations.length}
			<p class="muted">{t('panel.noLayers')}</p>
		{/if}
		{#each plainLayers as op, index (op.id)}
			{@const open = editingLayer === op.id}
			{@const percent = powerPercent(op)}
			<div
				class="layer"
				class:compact
				class:off={!op.output}
				class:onzichtbaar={design.isLayerHidden(op.id)}
				class:open
				class:sleept={slepen?.id === op.id}
				class:sleep-modus={slepen != null}
				class:doel-boven={slepen != null && slepen.id !== op.id && slepen.naar === index && index < slepen.van}
				class:doel-onder={slepen != null && slepen.id !== op.id && slepen.naar === index && index > slepen.van}
				bind:this={rijElementen[index]}
				role="presentation"
				oncontextmenu={(e) => {
					e.preventDefault();
					opendLaagMenu(op, index, e.clientX, e.clientY);
				}}
			>
				<div class="ident">
					{#if canEdit && plainLayers.length > 1}
					<!--
						Eén greep voor de volgorde, niet drie.

						Hier stond een kolom van drie: een pijl omhoog, de sleepgreep, een
						pijl omlaag. Die pijlen kwamen er voor gat L9 — slepen en de
						pijltjestoetsen waren onzichtbare grepen, en er moest iets zijn dat
						zichzelf uitlegt. Dat argument is vervallen: since de vorige ronde
						heeft elke laagrij een rechterklikmenu met de woorden "Eerder
						branden" en "Later branden" erin, en dát legt zichzelf uit beter dan
						een pijl van 11 px. Wat overblijft is de greep, met dezelfde
						pijltjestoetsen erop.

						Winst: twee knoppen minder per rij (tien in een lijst van vijf), en
						de rij hoeft niet meer drie knoppen hoog te zijn.
					-->
					<button
						class="greep"
						aria-label={t('panel.layer.dragAria', { label: op.label })}
						title={t('panel.layer.dragTitle')}
						disabled={edits.busy}
						onpointerdown={(e) => startSleep(e, op.id, index)}
						onpointermove={beweegSleep}
						onpointerup={eindSleep}
						onpointercancel={() => (slepen = null)}
						onkeydown={(e) => {
							if (e.key === 'ArrowUp' && index > 0) {
								e.preventDefault();
								moveLayer(op.id, 'up');
							} else if (e.key === 'ArrowDown' && index < plainLayers.length - 1) {
								e.preventDefault();
								moveLayer(op.id, 'down');
							}
						}}
					>
						<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
							<circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" />
							<circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" />
							<circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" />
						</svg>
					</button>
					{/if}
					<!-- The number on the chip *is* the burn order. Clicking opens the
					     layer, so the colour is also the way to its settings. -->
					<button
						class="chip mono"
						style="background: {design.colorFor(op.id)}; color: {inkOn(
							design.colorFor(op.id)
						)}"
						disabled={!canEdit}
						title={t('panel.layer.chipTitle', { n: index + 1, total: plainLayers.length })}
						aria-expanded={open}
						aria-label={t('panel.layer.openAria', { label: op.label })}
						onclick={() => (editingLayer = open ? null : op.id)}
					>{index + 1}</button>
					<!-- One line for the identity. The element count went to the value line:
					     with name and count stacked, a row is 186 px tall on a tablet and
					     three layers fit on a screen. -->
					<div class="layer-name">{op.label}</div>
					<!-- Only the number, next to the name. Put on the value line the row
					     became 96 px: that line is genuinely full with three fields (215 of
					     218 px, as the note there already said). What the number means is in
					     the tooltip; zero stands out because the column aligns. -->
					<span class="count" title={t('panel.layer.count', { n: op.element_ids.length })}
						>{op.element_ids.length}</span
					>
					{#if canEdit}
						<!-- Burn-along belongs in the row: it is the switch you touch most
						     often while working, and hidden in a submenu you cannot see which
						     layers are off. -->
						<button
							class="out"
							class:on={op.output}
							role="switch"
							aria-checked={op.output}
							title={op.output ? t('panel.layer.burnsOn') : t('panel.layer.burnsOff')}
							aria-label={t('panel.layer.burnsAria', { label: op.label })}
							disabled={edits.busy}
							onclick={() => patchLayer(op.id, { output: !op.output })}
						>
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
								<path d="M12 3v9" />
								<path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
							</svg>
						</button>
						<!-- Decision B4: visible and burn-along are two things. Keeping an
						     alignment box on the canvas without burning it is a standard
						     trick, and with one switch that is impossible. Visibility is a way
						     of looking: it does not go to the engine and so changes nothing
						     about what gets burned.

						     In compact mode this one moves into the fold. Measured on a
						     tablet: with both 44 px switches side by side the layer name has
						     30 px left and reads "Cu…" — and a list in which you cannot tell
						     the layers apart is not a compact list but an unreadable one.
						     Burn-along stays in the row, because that is the switch you touch
						     while working; hiding you do once. *That* a layer is hidden stays
						     in the row as a word.

						     The eye used to be here, next to the on/off switch and the ⋯.
						     Three 28 px touch targets plus the chip, the grip and the count
						     left the layer name 37 of 215 px — measured, and that is why it
						     read "Out-si-…". Hiding you do once per layer and it is in the row
						     menu.

						     The ⋯ did the same as the chip beside it: open the fold. Two
						     buttons for one operation, while the row menu could only be found
						     with the right mouse button. Now the chip opens the settings and
						     the ⋯ the menu — two different things, and the way to the menu has
						     become visible. -->
						<button
							class="more"
							aria-haspopup="menu"
							title={t('panel.layer.moreTitle', { label: op.label })}
							aria-label={t('panel.layer.moreAria', { label: op.label })}
							onclick={(e) => {
								const doos = (e.currentTarget as HTMLElement).getBoundingClientRect();
								opendLaagMenu(op, index, doos.right - 200, doos.bottom + 4);
							}}
						>⋯</button>
					{/if}
				</div>

				<!-- Speed, power and passes are fields in the row itself. That is the whole
				     reason this panel exists: adjusting next to a running machine must not
				     cost a submenu.

				     Compact (gap L5) is the exception: there the values are one readable
				     line and the fields move into the fold. Three fields beside a name and
				     three switches do not fit in a 280 px panel without wrapping, and then
				     the row is two lines tall again and nothing has been gained. -->
				<div class="vals">
					{#if canEdit && compact}
						<button
							class="kort mono"
							title={t('panel.layer.valuesTitle')}
							aria-expanded={open}
							aria-label={t('panel.layer.valuesAria', { label: op.label, values: short(op) })}
							onclick={() => (editingLayer = open ? null : op.id)}
						>{short(op)}</button>
					{:else if canEdit}
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="0.1"
								inputmode="decimal"
								aria-label={t('panel.layer.speedAria', { label: op.label })}
								value={op.speed ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'speed', op.speed)}
							/><span>mm/s</span>
						</label>
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								max="100"
								inputmode="numeric"
								aria-label={t('panel.layer.powerAria', { label: op.label })}
								value={percent ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'power_percent', percent)}
							/><span>%</span>
						</label>
						<label class="val narrow">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								inputmode="numeric"
								aria-label={t('panel.layer.passesAria', { label: op.label })}
								value={op.passes ?? 1}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'passes', op.passes ?? 1)}
							/><span>×</span>
						</label>
					{:else}
						{#each describe(op) as value (value)}
							<span class="pill mono">{value}</span>
						{/each}
					{/if}
					{#if !op.output}
						<!-- Colour alone is not enough: this is here in words too, because it
						     is the difference between "it has been cut" and "I forgot
						     it". -->
						<span class="tag">{t('panel.tag.doesNotBurn')}</span>
					{/if}
					{#if design.isLayerHidden(op.id)}
						<!-- And this is the other half of B4: hidden says nothing about
						     burning. Two separate words, because two separate states. -->
						<span class="tag zicht">{t('panel.tag.hidden')}</span>
					{/if}
					{#if design.layerCapabilities.air_assist && (compact || op.air_assist)}
						<!-- Air assist in the row (decision B11, gap L10).
						     It used to sit here as a dead word once it was on; now it is a
						     switch, because whether the blower joins in is the difference
						     between a clean cut and a scorched edge, and you flip that per
						     material. Switching it off cost a tap into the fold and a tap
						     back until now.

						     Why it only appears in roomy mode when it is *on*, and always in
						     compact: measured with four layers at 1440 and 1024. In compact
						     mode the pill fits beside the value line and the row stays 36 px
						     (desktop) and 54 px (tablet) — exactly the sizes from L5. In roomy
						     mode the value line is already full (215 of 218 px on desktop) and
						     the pill drops to a third line: 76 → 101 px, and on a tablet
						     111 → 159 px. That is half the list gone for a switch you rarely
						     touch. LightBurn does fit it on one line, but their panel is
						     480–512 px; ours has 280.

						     So in roomy mode switching on happens in the fold, switching off
						     can be done from the row — that is the side with the hurry in it.

						     The pill only appears when the driver has a command that really
						     switches the blower; on a Ruida there is none (L8). -->
						<button
							class="tag lucht"
							class:uit={!op.air_assist}
							role="switch"
							aria-checked={op.air_assist}
							aria-label={t('panel.air.aria', { label: op.label })}
							title={op.air_assist ? t('panel.air.on') : t('panel.air.off')}
							disabled={edits.busy}
							onclick={() => patchLayer(op.id, { air_assist: !op.air_assist })}
						>{t('panel.tag.air')}</button>
					{/if}
					{#if canEdit && selectedIds.length}
						<!-- Assigning is at the end and not before the name: otherwise the
						     whole row shifts the moment you select something. -->
						<button
							class="assign"
							class:in={membership(op.id) === 'all'}
							class:partly={membership(op.id) === 'some'}
							aria-pressed={membership(op.id) === 'all'}
							title={t('panel.assign.title', { label: op.label })}
							disabled={edits.busy}
							onclick={() => onAssign?.(op.id, membership(op.id) !== 'all')}
						>{membership(op.id) === 'all' ? '✓' : membership(op.id) === 'some' ? '–' : '+'}
							{t('panel.assign.label')}</button>
					{/if}
				</div>
			</div>

			{#if canEdit && open}
				{@const onthouden = design.memoryFor(design.colorFor(op.id))}
				<div class="layer-edit">
					{#if compact}
						<!-- In compact mode the fields are here, because there is no room in
						     the row. Same fields, same behaviour — just one line lower. -->
						<div class="vals wide">
							<label class="val">
								<input
									class="mono"
									type="number"
									step="1"
									min="0.1"
									inputmode="decimal"
									aria-label={t('panel.layer.speedAria', { label: op.label })}
									value={op.speed ?? ''}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'speed', op.speed)}
								/><span>mm/s</span>
							</label>
							<label class="val">
								<input
									class="mono"
									type="number"
									step="1"
									min="1"
									max="100"
									inputmode="numeric"
									aria-label={t('panel.layer.powerAria', { label: op.label })}
									value={percent ?? ''}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'power_percent', percent)}
								/><span>%</span>
							</label>
							<label class="val narrow">
								<input
									class="mono"
									type="number"
									step="1"
									min="1"
									inputmode="numeric"
									aria-label={t('panel.layer.passesAria', { label: op.label })}
									value={op.passes ?? 1}
									disabled={edits.busy}
									onchange={(e) => commitNumber(e, op.id, 'passes', op.passes ?? 1)}
								/><span>×</span>
							</label>
						</div>
					{/if}
					<div class="swatches" role="group" aria-label={t('panel.colourAria', { label: op.label })}>
						{#each LAYER_COLORS as swatch (swatch)}
							<button
								class="swatch"
								class:picked={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								style="background: {swatch}"
								title={t('panel.swatch', { colour: swatch })}
								aria-label={t('panel.swatch', { colour: swatch })}
								aria-pressed={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								disabled={edits.busy}
								onclick={() => patchLayer(op.id, { color: swatch })}
							></button>
						{/each}
					</div>

					<!-- What this colour has remembered on this machine (decision B2). It
					     says in so many words that it is not a preset: a preset belongs to a
					     material and a thickness and says something has been burned. This
					     only says what you last did here, and that must never pass for
					     evidence. -->
					<p class="geheugen wide">
						{#if onthouden?.speed_mm_s}
							{t('panel.memory.remembered', {
								values: `${onthouden.speed_mm_s} mm/s${
									onthouden.power_percent == null
										? ''
										: ` · ${Math.round(onthouden.power_percent)}%`
								}`,
								machine: onthouden.machine_name ?? t('panel.memory.thisMachine')
							})}
						{:else}
							{t('panel.memory.none')}
						{/if}
					</p>

					<label class="wide">
						<span>{t('panel.name')}</span>
						<input
							type="text"
							value={op.label}
							onchange={(e) => patchLayer(op.id, { label: e.currentTarget.value })}
						/>
					</label>

					<!-- What this layer does, changeable after creating it (gap L3). Making a
					     cut layer into an engrave layer could only be done by throwing it away
					     and redoing every assignment; LightBurn has a dropdown for it in the
					     row. The shapes and the settings come along. -->
					<div class="soort wide">
						<span class="rot-label">{t('panel.kind')}</span>
						<Segmented
							label={t('panel.kindOf', { label: op.label })}
							options={LAYER_TYPES.map(({ value, label }) => ({ value, label }))}
							disabled={edits.busy}
							bind:value={() => kindOf(op.type), (waarde) => retypeLayer(op.id, waarde)}
						/>
						<p class="hint">{t('panel.kind.hint')}</p>
					</div>

					{#if compact}
						<!-- The way-of-looking switch from the row, here as a checkbox (see the
						     note about the eye in the row). Same behaviour, same explanation:
						     this changes nothing about what gets burned. -->
						<label class="check wide">
							<input
								type="checkbox"
								checked={!design.isLayerHidden(op.id)}
								onchange={() => design.toggleLayer(op.id)}
							/>
							<span>{t('panel.visibleOnCanvas')}</span>
						</label>
					{/if}

					{#if design.layerCapabilities.air_assist}
						<!-- Decision B11: only visible when the driver has a command for it. The
						     same rule as with the Z axis — what the machine *can* do decides
						     what you see. If the switch is not there, this machine has no
						     method set up to drive the blower. -->
						<label class="check wide">
							<input
								type="checkbox"
								checked={op.air_assist}
								disabled={edits.busy}
								onchange={(e) => patchLayer(op.id, { air_assist: e.currentTarget.checked })}
							/>
							<span>{t('panel.airDuring')}</span>
						</label>
					{/if}

					{#if design.layerCapabilities.z_step}
						<!-- Zakken per pass, dezelfde regel als bij air assist (B11): alleen
						     te zien als de driver een Z-as heeft die hij ook echt beweegt.
						     Op een Ruida staat dit veld er dus niet, want daar zou het niets
						     doen. De engine kent dit niet uit zichzelf — een pass is bij haar
						     een teller op één cutcode-object — dus wij bouwen het op in het
						     plan, met een `z_move` tussen de passes en een beweging terug
						     naar de begin­hoogte na de last. -->
						<div class="zstep wide">
							<NumberField
								label={t('panel.zStep')}
								unit="mm"
								value={String(op.z_step_mm ?? 0)}
								step={0.1}
								min={-20}
								max={20}
								disabled={edits.busy}
								onchange={(v) => patchLayer(op.id, { z_step_mm: Number(v) })}
							/>
							<p class="hint">
								{#if !op.z_step_mm}
									{t('panel.zStep.off')}
								{:else if (op.passes ?? 1) < 2}
									{t('panel.zStep.onePass')}
								{:else}
									{t('panel.zStep.explain', {
										passes: op.passes,
										step: i18n.number(Math.abs(op.z_step_mm)),
										direction: t(op.z_step_mm > 0 ? 'panel.zStep.lower' : 'panel.zStep.higher')
									})}
								{/if}
							</p>
						</div>
					{/if}

					{#if op.type === 'op raster' || op.type === 'op image'}
						<!-- Only rastering uses these; on a cut they are meaningless. -->
						<!-- Each over the full width: a stepper is two 38 px buttons plus a
						     field, and in a half column of 112 px there is nothing left for
						     "2000". -->
						<div class="steppers wide">
						<NumberField
							label="DPI"
							value={String(op.dpi ?? 500)}
							step={10}
							min={10}
							max={2000}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { dpi: Number(v) })}
						/>
						<NumberField
							label={t('panel.overscan')}
							unit="mm"
							value={String(parseFloat(op.overscan ?? '0.5') || 0)}
							step={0.5}
							min={0}
							max={50}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { overscan_mm: Number(v) })}
						/>
						</div>
						<label class="check wide">
							<input
								type="checkbox"
								checked={op.bidirectional}
								onchange={(e) =>
									patchLayer(op.id, { bidirectional: e.currentTarget.checked })}
							/>
							<span>{t('panel.bidirectional')}</span>
						</label>
					{/if}

					<!-- Order is burn order: engrave first, only then cut, otherwise the
					     workpiece falls out of the sheet before the lettering is on it. -->
					<div class="order wide">
						<span class="rot-label">{t('panel.order', { kind: typeName(op.type) })}</span>
						<button
							class="rot"
							disabled={edits.busy || index === 0}
							title={index === 0 ? t('reason.alreadyFirst') : t('panel.order.burnEarlier')}
							onclick={() => moveLayer(op.id, 'up')}
						>↑ {t('panel.order.earlier')}</button>
						<button
							class="rot"
							disabled={edits.busy || index === plainLayers.length - 1}
							title={index === plainLayers.length - 1
								? t('reason.alreadyLast')
								: t('panel.order.burnLater')}
							onclick={() => moveLayer(op.id, 'down')}
						>↓ {t('panel.order.later')}</button>
					</div>

					{#if confirmDrop === op.id}
						<div class="confirm wide">
							<span>{t('panel.drop.ask', { label: op.label })}</span>
							<button class="rot" onclick={() => (confirmDrop = null)}>{t('common.cancel')}</button>
							<button class="rot drop" onclick={() => dropLayer(op.id)}
								>{t('panel.drop.confirm')}</button
							>
						</div>
					{:else}
						<button class="weg wide" onclick={() => (confirmDrop = op.id)}>
							{t('panel.drop.layer')}
						</button>
					{/if}
				</div>
			{/if}
		{/each}

		{#each gridGroups as group (group.id)}
			<div class="layer grid-row">
				<div class="ident">
					<span class="chip mono grid-chip">R</span>
					<div class="layer-name">
						<div class="op">{t('panel.grid.title', { id: group.id })}</div>
						<div class="obj">{t('panel.grid.cells', { n: group.ops.length })}</div>
					</div>
					<button
						class="more"
						aria-expanded={openGrid === group.id}
						aria-label={t('panel.grid.showCells', { id: group.id })}
						onclick={() => (openGrid = openGrid === group.id ? null : group.id)}
					>{openGrid === group.id ? '−' : '+'}</button>
				</div>
			</div>

			{#if openGrid === group.id}
				<div class="cells">
					{#each group.ops as op (op.id)}
						<label class="cell" title={t('panel.grid.cell', { row: op.grid?.row, column: op.grid?.column })}>
							<input
								type="checkbox"
								checked={op.output}
								disabled={!canEdit || edits.busy}
								onchange={(e) => patchLayer(op.id, { output: e.currentTarget.checked })}
							/>
							<span class="mono">{op.grid?.speed_mm_s}·{op.grid?.power_percent}%</span>
						</label>
					{/each}
					{#if canEdit}
						<button class="weg cells-remove" onclick={() => removeGrid(group.id)}>
							{t('panel.grid.remove')}
						</button>
					{/if}
				</div>
			{/if}
		{/each}
		{#if canEdit}
			<!-- Vier vaste soorten: als één balk, zodat je in één blik ziet wat er
			     te kiezen valt en wat er nu staat. De knop noemt wat er komt —
			     anders leest de balk als een filter over de lijst erboven. Onder
			     de lijst, want de lagen die er al zijn kijk je vaker aan dan dat
			     je er een maakt. -->
			<!--
				Eén knop met een menu, in plaats van een label, vier keuzerondjes en
				een knop.

				Het kostte vijf bedieningsorganen en drie regels om iets te doen wat
				je een paar keer per project doet: kies een soort, druk op toevoegen.
				Nu is het één knop die de vier soorten uitklapt — evenveel tikken,
				een vijfde van de ruimte, en het soort staat in het menu bij zijn
				naam in plaats van als afgekorte pil.
			-->
			<button
				class="add"
				aria-haspopup="menu"
				disabled={edits.busy}
				onclick={(e) => {
					const doos = (e.currentTarget as HTMLElement).getBoundingClientRect();
					rijMenu = {
						x: doos.left,
						y: doos.top - 8,
						upward: true,
						lijst: [
							{
								title: t('panel.addLayer'),
								items: LAYER_TYPES.map(({ value, label }) => ({
									id: `nieuw-${value}`,
									label,
									run: () => {
										newLayerType = value;
										addLayer();
									}
								}))
							}
						]
					};
				}}
			>
				+ {t('panel.addLayer')}
			</button>
		{/if}
		<p class="hint">
			{#if selected}
				{t('panel.assign.hint', { into: t('panel.assign.label') })}
			{:else}
				{t('panel.assign.hintNone')}
			{/if}
		</p>
	</div>
{/if}

{#if rijMenu}
	<Menu
		menu={rijMenu.lijst}
		x={rijMenu.x}
		y={rijMenu.y}
		upward={rijMenu.upward ?? false}
		onClose={() => (rijMenu = null)}
	/>
{/if}

<style>
	.section + .section {
		margin-top: var(--space-6);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.empty,
	.muted {
		color: var(--text-2);
		margin: 0;
	}
	/* Twee regels per laag: wie hij is, en wat hij doet. Meer regels en de
	   lijst wordt een stapel kaarten waarin je niets meer terugvindt; minder
	   en de waarden zijn niet meer aan te tikken. */
	.layer {
		/* Anker voor de sleepgreep, die in de linkermarge hangt. */
		position: relative;
		display: grid;
		/* minmax(0, 1fr) en niet de impliciete auto-kolom: die groeit mee met
		   de langste laagnaam en duwt dan de hele lijst het paneel uit. */
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-1);
		/* Links iets meer lucht: daar hangt de sleepgreep in. Hem in de rij zetten
		   kostte de laagnaam 20 px en dan brak "Graveren" af als "Gra-veren" —
		   precies de leesbaarheid die de vorige ronde had gewonnen. In de marge
		   kost hij tien pixels en niets van de naam. */
		padding: var(--space-2) var(--space-2) var(--space-2) calc(var(--space-2) + 14px);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.layer .ident {
		display: flex;
		align-items: center;
		/* 6 px en niet 8: met de sleepgreep erbij (L1) hield de laagnaam 53 px
		   over en brak "Graveren" af als "Gra-veren". Zes keer twee pixels terug
		   geeft de naam er achttien bij, en dat is precies wat hij nodig had. */
		gap: var(--space-1h);
	}
	.layer + .layer {
		margin-top: var(--space-1);
	}
	/* Een uitgezette laag dimmen we niet weg: je moet hem nog kunnen lezen en
	   aanzetten. Alleen de waarden vervagen, want die doen even niets. */
	.layer.off .vals .val,
	.layer.off .vals .pill {
		opacity: 0.5;
	}
	.layer.off {
		border-style: dashed;
	}
	.layer.open {
		border-color: var(--accent);
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
	}
	/* ── Compacte lijst (L5) ──────────────────────────────────────────────────
	   Identiteit en waarden op één regel. De velden blijven staan: dit paneel
	   bestaat omdat bijstellen naast een draaiende machine geen submenu mag
	   kosten. Wat wijkt is de naam — die mag afkappen, want hij staat er in de
	   ruime stand voluit en in de tooltip altijd. */
	.layer.compact {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2) var(--space-1) calc(var(--space-2) + 10px);
	}
	/* De twee schakelaars mogen in de compacte stand krap: ze zitten naast
	   elkaar en je mikt op een icoon van 16 px, niet op de rand van het vlak.
	   Op een aanraakscherm blijven ze 44 px — dat regelt de mediaquery onderaan,
	   die zwaarder weegt dan deze regel. */
	.layer.compact .out,
	.layer.compact .ident {
		flex: 1 1 12ch;
		min-width: 0;
		/* Vier raakdoelen en een naam in 247 px: elke pixel gaat naar de naam,
		   want dat is het enige in de rij dat nergens anders staat. Gemeten:
		   met de ruime tussenruimte hield de naam 10 px over en las "G". */
		gap: var(--space-1);
	}
	.layer.compact .vals {
		flex: 0 1 auto;
	}
	.layer.compact .layer-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.layer.compact .count {
		display: none;
	}
	/* De drie waarden als één regel. Een knop en geen tekst: hij opent dezelfde
	   uitklap als de chip, zodat je vanaf het getal dat je wilt wijzigen bij het
	   veld komt. */
	.kort {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		/* Kaal, zonder kader: een pil kost hier 14 px die de laagnaam nodig heeft.
		   Dat het te openen is, blijkt uit de onderstreping bij aanwijzen en uit
		   `aria-expanded` — en de chip ernaast doet hetzelfde. */
		padding: 0;
		white-space: nowrap;
	}
	.kort:hover {
		color: var(--text-1);
		text-decoration: underline;
	}
	/* Tijdens het slepen mag er nergens tekst geselecteerd worden: de aanslag
	   begint op de greep, maar de browser zoekt vandaar het eerstvolgende stukje
	   selecteerbare tekst en trok een blauwe baan tot in de statusbalk. */
	.layer.sleep-modus,
	.layer.sleep-modus * {
		user-select: none;
	}
	/* ── De ordekolom in de marge: ▲ / greep / ▼ (L1 en L9) ─────────────────
	   Drie wegen naar dezelfde handeling, en dat is geen luxe: slepen is het
	   snelst met een muis, de pijltjestoetsen op de greep werken zonder muis, en
	   de knoppen zijn de enige van de drie die zichzelf uitleggen. LightBurn
	   heeft die derde altijd zichtbaar; wij hadden hem in de uitklap. */
	/* Uit én weg te klikken: een laag die al bovenaan staat, kan niet hoger.
	   Onzichtbaar maken zou de kolom laten verspringen, dus hij blijft staan en
	   wordt alleen stil. */
	/* Onder 1200 px verdwijnen ze. Dat is niet willekeurig: dezelfde grens waar
	   tokens.css elke knop 44×44 maakt omdat je daar met een vinger werkt. Drie
	   raakdoelen van 44 px boven elkaar in een rij van 111 px kan niet, en 14 px
	   brede pijlen naast een greep van 26 px is een raakdoel dat je alleen per
	   ongeluk raakt — gemeten: de globale regel blies ze op tot 44×44 in een
	   kolom van 14 px, dwars over de kaartrand heen.
	   Daar blijft de greep over: slepen is op een aanraakscherm het gebaar dat
	   je verwacht, de pijltjestoetsen erop doen hetzelfde, en de knoppen
	   ↑ Eerder / ↓ Later staan nog in de uitklap. */
	@media (max-width: 1199px), (pointer: coarse) {
	}
	/* ── Slepen om te herordenen (L1) ──────────────────────────────────────── */
	.greep {
		flex: none;
		width: 14px;
		height: 22px;
		/* Slepen mag geen tekst selecteren: de eerste versie trok bij elke
		   sleepbeweging een blauwe selectie over het halve scherm. */
		user-select: none;
		display: grid;
		place-items: center;
		border-radius: var(--radius-field);
		color: var(--text-2);
		cursor: grab;
		touch-action: none;
	}
	.greep:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Wat je vasthebt, ligt los van de lijst: opgetild en iets doorzichtig, zodat
	   je de rij eronder ziet waar hij terechtkomt. */
	.layer.sleept {
		opacity: 0.65;
		border-color: var(--accent);
		box-shadow: var(--shadow-float);
		cursor: grabbing;
	}
	/* De bestemming, als lijn tegen de rij aan. Een lijn en geen opengeschoven
	   gat: de lijst mag onder je vinger niet gaan schuiven, dan mik je mis. */
	.layer.doel-boven {
		box-shadow: inset 0 3px 0 0 var(--accent);
	}
	.layer.doel-onder {
		box-shadow: inset 0 -3px 0 0 var(--accent);
	}
	.lijst-balk {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.lijst-rek { flex: 1; }
	/* Het lijstmenu: dezelfde vorm als de dichtheidsschakelaar ernaast, want ze
	   staan in dezelfde balk en horen niet om de aandacht te vechten. */
	.lijstmeer {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		padding: var(--space-1) var(--space-2);
		font: inherit;
		font-size: var(--text-xs);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.lijstmeer:hover { background: var(--surface-2); color: var(--text-1); }
	/* Een toestand met zijn uitweg in dezelfde regel. */
	.opruimregel {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.alsLink {
		padding: 0;
		border: none;
		background: none;
		font: inherit;
		font-weight: 500;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.alsLink:disabled { opacity: 0.5; text-decoration: none; }
	.dichtheid {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		margin-left: auto;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		color: var(--text-2);
		background: var(--surface-1);
	}
	.dichtheid:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.soort {
		display: grid;
		gap: var(--space-1);
	}
	.soort :global(.segmented) {
		width: 100%;
	}
	/* Het veld met zijn uitleg als één blok: de zin eronder zegt wat er gebeurt
	   bij dit aantal passes, en die hoort bij het getal te staan. */
	.zstep {
		display: grid;
		gap: var(--space-1);
	}
	/* Vier woorden in 222 px: met de standaard tussenruimte van 12 px per zijde
	   liep "Graveren" over zijn eigen segment heen en las er "Gravere". De
	   letters blijven op de typeschaal; alleen de lucht eromheen krimpt. */
	.soort :global(.segmented button) {
		padding-left: var(--space-1);
		padding-right: var(--space-1);
	}
	.chip {
		width: 26px;
		height: 26px;
		flex: none;
		border-radius: var(--radius-field);
		display: grid;
		place-items: center;
		font-size: var(--text-xs);
		font-weight: 600;
		/* De inkt komt van inkOn() als inline stijl; dit is alleen de val voor
		   een kleur die niet te ontleden is. */
		color: var(--on-color);
		border: 0;
		padding: 0;
	}
	.chip:not(:disabled):hover {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px currentColor;
	}
	/* Meebranden: een knop met een aan-stand, geen vinkje dat je moet raken. */
	.out {
		flex: none;
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.out.on {
		border-color: color-mix(in srgb, var(--ok) 55%, var(--line));
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		color: var(--ok);
	}
	.out:hover:not(:disabled) {
		background: var(--surface-2);
	}
	/* Zichtbaarheid staat naast meebranden en ziet er bewust ánders off: dit is
	   een kijkstand, geen machinestand. Daarom neutraal grijs waar meebranden
	   groen kleurt — kleur is hier gereserveerd voor wat de laser gaat doen. */
	/* Een verborgen laag mag je nog wél lezen — hij is niet uitgezet, hij staat
	   alleen even niet op het bed. De naam vervaagt, de knoppen niet. */
	.layer.onzichtbaar .layer-name,
	.layer.onzichtbaar .count {
		opacity: 0.55;
	}
	.tag.zicht {
		color: var(--text-2);
		font-weight: 400;
	}
	/* Air assist on: geen waarschuwing, dus niet in amber. Een stand die je moet
	   kunnen zien, in de gewone tekstkleur met een randje eromheen. */
	.tag.lucht {
		color: var(--text-1);
		font-weight: 400;
		border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line));
		border-radius: var(--radius-dot);
		padding: 0 var(--space-2);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
	}
	/* Uit is geen lege plek maar een doorgehaald woord: dubbel gecodeerd, zodat
	   het ook zonder kleurverschil te lezen is — en zodat "deze machine kan het
	   niet" (geen pil) iets anders blijft dan "hij staat uit". */
	.tag.lucht.uit {
		color: var(--text-2);
		border-color: var(--line);
		background: transparent;
		text-decoration: line-through;
	}
	.tag.lucht:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--text-1);
	}
	.geheugen {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: var(--space-2);
	}
	.more {
		flex: none;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		line-height: 1;
	}
	.more:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.vals {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}
	/*
	   Een waarde met zijn eenheid als één ding: het veld hoort bij "mm/s", dus
	   ze delen een rand en de eenheid is niet aan te klikken.

	   Kaal tot je hem aanwijst. Drie omkaderde pillen per rij maakten van een
	   lijst van vijf lagen vijftien vakjes — 44 knoppen in het paneel, en de
	   getallen die je juist met elkaar wil vergelijken verdwenen tussen de
	   randen. Ze zijn nog steeds ter plekke te wijzigen (dat is de reden dat dit
	   paneel bestaat), maar de rand komt pas als je er iets mee gaat doen. Bij
	   aanwijzen én bij focus, dus met het toetsenbord is hij er ook.
	*/
	.val {
		display: inline-flex;
		align-items: center;
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		background: transparent;
		overflow: hidden;
		transition: background var(--transition), border-color var(--transition);
	}
	.val:hover {
		border-color: var(--line);
		background: var(--surface-2);
	}
	.val:focus-within {
		border-color: var(--accent);
		background: var(--surface-2);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	.val input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		width: 4.2em;
		min-width: 0;
		text-align: right;
		padding: var(--space-1) 2px var(--space-1) var(--space-2);
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.val.narrow input {
		width: 2.4em;
	}
	/* De eigen spinner van de browser is twee pixels hoog; met handschoenen aan
	   raak je hem niet en hij vreet de breedte die het getal nodig heeft. */
	.val input::-webkit-outer-spin-button,
	.val input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.val input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.val span {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 0 var(--space-2) 0 2px;
		white-space: nowrap;
	}
	.tag {
		color: var(--warn);
		font-weight: 500;
	}

	/* De naam mag over twee regels: "Buitensnede 3…" en "Contour grave…" zijn
	   niet uit elkaar te houden, en juist het staartje is wat de gebruiker zelf
	   getypt heeft. Een rij die groeit om een naam is eerlijk; een rij die een
	   naam wegknipt om even hoog te blijven, niet. */
	.layer-name {
		flex: 1;
		min-width: 0;
		font-weight: 500;
		line-height: 1.25;
		overflow: hidden;
		/* break-word en niet anywhere: anywhere hakt "Binnensneden" in
		   "Binnensned / en", ook als het net wél past. */
		overflow-wrap: break-word;
		/* Breekt een te lang woord liever op een lettergreep dan middenin. */
		hyphens: auto;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
	}
	.layer-name .op {
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.layer-name .obj {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.count {
		flex: none;
		min-width: 1.6em;
		text-align: center;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.pill {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.hint {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.section-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.section-head .section-title { margin-bottom: 0; }
	.tally {
		flex: 1;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Geen nowrap: op een tablet is deze regel breder dan het paneel, en dan
	   duwt hij de hele lijst zijwaarts uit beeld in plaats van af te breken. */
	.order-note {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Naast de machine bedien je dit met een vinger, soms met een handschoen.
	   De globale regel maakt knoppen 44 px hoog maar niet breed genoeg, en de
	   invoervelden vallen er helemaal buiten. */
	@media (max-width: 1199px), (pointer: coarse) {
		.chip,
		.out,
		.more {
			width: 44px;
			height: 44px;
			min-height: 44px;
		}
		/* De greep is smaller dan de rest maar even hoog: hij moet met een vinger
		   te pakken zijn zonder de naam uit de rij te duwen. */
		.greep {
			width: 26px;
			height: 44px;
			min-height: 44px;
		}
		/* Met een vinger is de greep breder, dus is de marge waar hij in hangt
		   dat ook. */
		.layer {
			padding-left: calc(var(--space-2) + 20px);
		}
		.layer.compact {
			padding-left: calc(var(--space-2) + 20px);
		}
		.dichtheid {
			min-height: 44px;
		}
		.val input {
			/* 44 px hoog, ook al is dit geen <button> en pakt de globale regel
			   hem niet. Met een handschoen aan mik je hier anders naast. */
			padding: var(--space-3) 2px var(--space-3) var(--space-2);
			width: 3.6em;
		}
		.val.narrow input {
			width: 2.2em;
		}
		.assign {
			min-height: 44px;
		}
		/* Drie raakdoelen van 44 px naast een naam passen niet in 290 px. Het
		   aantal vormen sneuvelt als eerste: dat staat ook in de tooltip van de
		   chip en in het paneel eronder, de naam staat nergens anders. */
		.count {
			display: none;
		}
		.layer .ident {
			gap: var(--space-1);
		}
		/* Op een vinger moet elk staal de 44 px halen die de rest ook heeft. */
		.swatch {
			height: 44px;
			min-height: 44px;
		}
		/* Volgorde en verwijderen mogen elkaar niet raken: één misgetikte tik
		   verderop kost je een laag met al zijn toewijzingen. */
		.layer-edit .weg,
		.confirm .drop {
			margin-left: var(--space-6);
		}
		.layer-edit .weg {
			margin-top: var(--space-6);
		}
	}
	.edit-error {
		margin: 0 0 var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
	.imagefx { display: grid; gap: 4px; }
	.fx-head { display: flex; align-items: center; gap: var(--space-2); }
	.fx {
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: 4px 8px;
	}
	.fx.on { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
	.fx-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.fx-value {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.fx-value input[type='range'] { flex: 1; }
	.fx-value select {
		flex: 1;
		font: inherit;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.fx-num { min-width: 3em; text-align: right; }
	.fx-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 4px; }
	.dpi { display: flex; align-items: center; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.dpi input {
		width: 4.5em;
		font: inherit;
		padding: 2px 4px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stray {
		border: 1px solid color-mix(in srgb, var(--warn) 50%, var(--line));
		border-radius: var(--radius-card);
		background: color-mix(in srgb, var(--warn) 8%, transparent);
		display: grid;
		gap: 8px;
	}
	.stray p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	.tip {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	/* Geen eigen margin meer: de selectiekaart is een grid met één gap, en een
	   groep die daar zijn eigen afstand bovenop zette maakte het ritme grillig
	   én het paneel langer. */

	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
		margin-right: var(--space-1);
	}
	.rot {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.rot:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.rot:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.grid-row .grid-chip { background: var(--text-2); }
	.cells {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-top: none;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
		margin-bottom: 8px;
	}
	.cell {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 2px 4px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.cell input { width: 12px; height: 12px; accent-color: var(--accent); }
	.cells-remove {
		flex-basis: 100%;
		text-align: left;
		font-size: var(--text-xs);
		color: var(--danger);
		margin-top: var(--space-1);
	}
	/* De knop noemt de uitkomst, niet de handeling — zie DESIGN-SYSTEM, "de
	   primaire knop zegt wát er komt". */
	.add {
		width: 100%;
		padding: 8px;
		font: inherit;
		font-size: var(--text-xs);
		font-weight: 500;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--accent);
	}
	.add:hover:not(:disabled) { background: var(--surface-2); }
	.add:disabled { opacity: 0.45; cursor: not-allowed; }
	.layer-edit {
		display: grid;
		/* minmax(0, 1fr): een 1fr-kolom krimpt niet onder de min-content van
		   wat erin staat, en een stepper met twee knoppen van 38 px duwt de
		   kolom dan breder dan het paneel. */
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
		padding: var(--space-3);
		margin: -1px 0 var(--space-1);
		border: 1px solid var(--accent);
		border-top: 0;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
	}
	.layer-edit label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.layer-edit .wide { grid-column: 1 / -1; }
	.steppers { display: grid; gap: var(--space-2); }
	.layer-edit label.check {
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
	}
	.layer-edit input[type='text'] {
		font: inherit;
		width: 100%;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Tien vaste kleuren, want een vrije kleurkiezer levert tinten op die op
	   het canvas niet meer uit elkaar te houden zijn. */
	/* Vijf per regel, ook op de desktop: tien op een rij past net niet in een
	   paneel van 280 px en de last valt er dan buiten. */
	.swatches {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 4px;
	}
	.swatch {
		width: auto;
		height: 24px;
		padding: 0;
		border: 1px solid var(--edge-on-color);
		border-radius: var(--radius-field);
	}
	.swatch.picked {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px var(--accent);
	}
	/* Label op zijn eigen regel, de twee knoppen naast elkaar: laat je ze
	   wrappen dan staat er op een tablet één knop per regel. */
	.order {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		align-items: center;
		gap: var(--space-1);
	}
	.order .rot-label {
		grid-column: 1 / -1;
		margin: 0;
	}
	.order .rot {
		text-align: center;
	}
	/* Weggooien staat los van de rest en vraagt door: het neemt de
	   toewijzingen van de laag mee en dat is niet terug te tikken. */
	.confirm {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-2);
		border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--line));
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.confirm span { flex-basis: 100%; }
	.rot.drop { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
	/* Een rode tekstlink, geen gevulde knop: de klasse heet daarom niet
	   `danger` — het vangnet in tokens.css vult elke `button.danger` bij hover
	   solide rood, en dat hoort bij een knop die meteen wist. Deze opent een
	   bevestiging. */
	.layer-edit .weg {
		font-size: var(--text-xs);
		color: var(--danger);
		text-align: left;
		margin-top: var(--space-2);
	}
	/* Toewijzen staat op de waarderegel, niet vóór de naam: anders verschuift
	   de hele rij zodra je iets selecteert. */
	.assign {
		font: inherit;
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.assign:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.assign.in {
		border-style: solid;
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}
	.assign.partly {
		border-style: solid;
		border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
		color: var(--text-1);
	}
	.selected {
		border: 1px solid var(--accent);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		display: grid;
		/* Eén ritme voor het hele blok. Elke groep zette eerder zijn eigen
		   margin-top, waardoor de afstanden per rij verschilden en het paneel
		   langer werd dan de inhoud rechtvaardigt. */
		gap: var(--space-3);
	}
	/* Een grid-item krimpt standaard niet onder zijn inhoud. Zonder deze regel
	   duwt een lange elementnaam — de engine plakt id en streekkleur achter
	   "Path", en dat is zo dertig tekens — de hele kopregel de kaart uit, en
	   dan valt "Wis" van het paneel af. Dat stond zo op de screenshot en is
	   niet met het blote oog te zien aankomen. */
	.selected > * {
		min-width: 0;
	}
	.selected .head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	/* De naam mag wijken vóór de rest: hij is het langste en het minst kritiek
	   — wat je vast hebt zie je ook op het canvas, "Wis" nergens anders. */
	/* The name keeps its width and the layer chips give way. "3 shapes" is short
	   and is what you are holding; "3 sha…" beside two full layer names is the
	   wrong half to lose. Measured in English, where the same header truncated and
	   the Dutch one did not — a language should not decide which half survives. */
	.selected .head .name { flex: 0 0 auto; }
	.selected .head .in-layers { flex: 1 1 auto; min-width: 0; overflow: hidden; }
	.selected .name {
		font-weight: 600;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.laagchip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 11ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.laagchip + .laagchip::before {
		content: ',';
		margin-right: 2px;
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		border: 1px solid color-mix(in srgb, currentColor 25%, transparent);
	}
	/* Geen laag betekent: deze vorm gaat de machine niet in. Dat is geen failure,
	   maar het is wel het enige geval hier waar je iets moet doen. */
	.geenlaag { color: var(--warn); }
	.in-layers {
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.clear {
		font-size: var(--text-xs);
		color: var(--accent);
		flex: none;
		margin-left: auto;
	}

	/* Twee kolommen getallen met de eenheid één keer rechts. Een vast raster in
	   plaats van wrappende pillen: alleen zo staan B boven X en H boven Y, en
	   dat is wat de vier velden als twee paren laat lezen. */
	.figures {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
		align-items: end;
		gap: var(--space-1) var(--space-2);
	}
	.figures .f {
		display: flex;
		align-items: stretch;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		overflow: hidden;
		min-width: 0;
	}
	.figures .f:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	/* Het label zit ín het veld en niet erboven: een aparte labelregel boven
	   vier velden kost twee regels hoogte voor twee tekens informatie. */
	.figures .f > span {
		display: grid;
		place-items: center;
		padding: 0 var(--space-1) 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		flex: none;
	}
	.figures input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		/* min-width: 0 en flex: 1 — zonder dat houdt een number-input zijn
		   eigen minimumbreedte aan en werd "145.0" tot "145." afgekapt. Dat
		   stond zo op de tablet in beeld. */
		flex: 1;
		width: 100%;
		min-width: 0;
		text-align: right;
		padding: var(--space-1h) var(--space-2) var(--space-1h) 0;
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.figures input::-webkit-outer-spin-button,
	.figures input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.figures input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.figures input:disabled { opacity: 0.6; }
	.figures .unit {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding-bottom: var(--space-1h);
		text-align: center;
		min-width: 1.6em;
	}
	.figures .link {
		display: grid;
		place-items: center;
		width: 100%;
		min-width: 1.6em;
		height: 30px;
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.figures .link[aria-pressed='true'] {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.figures .link:hover:not(:disabled) { background: var(--surface-2); }

	/* Hoek plus vier stapjes op één regel. Het hoekveld krijgt bewust meer
	   ruimte dan een knop: er moet "337,5" in passen, en een afgekapt getal is
	   erger dan geen getal — dan geloof je wat er staat. */
	.rotrow {
		grid-template-columns: minmax(4.6em, 1.6fr) repeat(4, minmax(0, 1fr));
		align-items: center;
	}
	.rotrow .f.angle > span:first-child {
		padding-right: 0;
		font-size: var(--text-sm);
	}
	.rotrow .f.angle input { padding-right: 0; }
	.figures .suffix {
		display: grid;
		place-items: center;
		flex: none;
		padding: 0 var(--space-2) 0 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.figures .f.mixed input { color: var(--text-2); }
	.icon.step {
		width: 100%;
		height: 30px;
	}
	.stepnum {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}

	/* De pictogramrijen. Vier per rij, want vier van 44 px passen met tussenruimte
	   in een paneel van 279 px en zes niet — en vier laat de indeling bovendien
	   samenvallen met de betekenis: rij één horizontaal, rij twee verticaal. */
	/* Knoppen zonder rand voor geschiedenis en draaistapjes: die horen bij het
	   veld ernaast, niet bij het raster eronder. */
	.icon {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.icon:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.icon:disabled { opacity: 0.4; cursor: not-allowed; }

	/* Het anker: waar je vandaan kwam, en de weg terug. Neutraal van kleur —
	   dit is geen waarschuwing maar een aantekening. */
	.anchor {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* The whole line carries the emphasis now: the change used to be bold inside
	   the sentence, and a message is one string — splitting it to keep the tag
	   would make the halves untranslatable. */
	.anchor-what { min-width: 0; color: var(--text-1); }
	.anchor-back {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		flex: none;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-size: var(--text-xs);
		color: var(--accent-text);
	}
	.anchor-back:hover:not(:disabled) { border-color: var(--accent); }

	/* Ingeklapte groepen. De samenvatting blijft een gewone leesbare regel met
	   een driehoekje — je kunt hem vinden zonder te weten dat hij er is. */
	.fold {
		border-top: 1px solid var(--line);
		padding-top: var(--space-2);
		margin-top: calc(var(--space-1) * -1);
	}
	.fold summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-1);
		min-height: 24px;
	}
	/* Eigen driehoekje. `display: flex` op een summary laat de standaardmarker
	   van de browser vallen, en dan is een dichtgeklapte groep niet van een kop
	   te onderscheiden — precies de reden waarom je zo'n groep niet mag
	   verstoppen. */
	.fold summary::-webkit-details-marker { display: none; }
	.fold summary::marker { content: ''; }
	.fold summary::before {
		content: '';
		flex: none;
		width: 0;
		height: 0;
		border-left: 5px solid currentColor;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
		transition: transform 120ms ease;
	}
	.fold[open] summary::before { transform: rotate(90deg); }
	.fold summary:hover { color: var(--accent); }
	.fold-note {
		font-weight: 400;
		color: var(--text-2);
	}
	.fold-note.on {
		color: var(--accent-text);
		font-variant-numeric: tabular-nums;
	}
	.fold > :not(summary) { margin-top: var(--space-2); }

	/* Naast de machine met een vinger. Deze blok staat bewust hélemaal
	   onderaan: de regels hierboven hebben dezelfde specificiteit, dus wie
	   eerder staat verliest — en toen dit blok halverwege stond, hield de
	   draairij zijn zes kolommen van de desktop en liep de kaart aan de
	   rechterkant het paneel uit. */
	@media (max-width: 1199px), (pointer: coarse) {
		/* Dikke vingers: elk doel in de selectiekaart haalt 44 px, met minstens
		   12 px ertussen. Sinds de pictogramrasters naar de actiebalk en het
		   rechterklikmenu verhuisd zijn, gaat dit alleen nog over de velden en
		   hun stapjes. */
		.icon,
		.icon.step,
		.figures .link {
			height: 44px;
			min-height: 44px;
		}
		.icon { width: 44px; }
		.figures { gap: var(--space-2) var(--space-3); }
		.figures input {
			/* 44 en niet 43: het veld haalde het net niet omdat de rand van de
			   omhullende twee pixels opsnoept. */
			min-height: 44px;
			padding-top: var(--space-3);
			padding-bottom: var(--space-3);
		}
		.rotrow {
			/* Het hoekveld en vier knoppen van 44 px passen niet naast elkaar op
			   een tablet. Het veld krijgt daarom de volle breedte; de stapjes
			   houden hun volle raakvlak op de regel eronder. */
			grid-template-columns: repeat(4, minmax(0, 1fr));
		}
		.rotrow .f.angle { grid-column: 1 / -1; }
		.fold summary { min-height: 44px; }
		.anchor-back { min-height: 44px; }
	}
</style>
