/**
 * Vastklikken op raster, vormen en randen.
 *
 * Alles hier rekent in millimeters, want dat is de eenheid van het bed. De
 * *trefafstand* is de enige uitzondering: die komt binnen als millimeters die
 * het canvas heeft teruggerekend uit schermpixels. Zo werkt het bij LightBurn
 * (Snap Distance staat in pixels, Edit → Settings → Units and Grids) en bij
 * Inkscape ("The snap distance is in units of screen pixels"). Dat is ook de
 * enige juiste maat: bij 400% inzoomen wil je preciezer kunnen mikken, niet
 * grover, en een vaste marge in mm doet precies het omgekeerde.
 *
 * De module is bewust vrij van Svelte en van de DOM: de rekenkern is te
 * controleren met losse waarden, en het canvas doet alleen de omrekening en het
 * tekenen.
 */

/**
 * Het woordje dat bij de hulplijn komt te staan.
 *
 * Specifieker dan alleen de herkomst: "rand" en "midden" zijn twee heel
 * verschillende uitlijningen, en juist bij het midden is het antwoord op
 * "waarom springt hij daarheen?" anders niet te geven.
 */
export type SnapKind =
	| 'raster'
	| 'rand'
	| 'midden'
	| 'bedrand'
	| 'bedmidden'
	| 'velrand'
	| 'velmidden';

export type SnapTarget = {
	/** De coördinaat op de as waarop wordt vastgeklikt, in mm. */
	pos: number;
	kind: SnapKind;
	/**
	 * Waar de hulplijn zich loodrecht op deze as toe uitstrekt, in mm. Bij een
	 * vorm loopt de lijn van de vorm naar wat eraan vastklikt, zoals in Inkscape;
	 * bij raster- en bedlijnen is er niets om tussen te spannen en trekt het
	 * canvas hem over het hele bed door.
	 */
	span?: [number, number];
};

export type SnapGuide = {
	axis: 'x' | 'y';
	pos: number;
	kind: SnapKind;
	span?: [number, number];
};

export type SnapHit = { delta: number; guide: SnapGuide };

export type Box = { x: number; y: number; width: number; height: number };

/** Een doos genormaliseerd naar min/max, ook als hij negatief geschaald is. */
function grenzen(box: Box) {
	return {
		x0: Math.min(box.x, box.x + box.width),
		x1: Math.max(box.x, box.x + box.width),
		y0: Math.min(box.y, box.y + box.height),
		y1: Math.max(box.y, box.y + box.height)
	};
}

/**
 * Trefpunten van de omgeving: bed, vel en de dozen van alle andere vormen.
 *
 * Van een vorm tellen de randen én het midden, net als bij Inkscape (hoeken,
 * zijmiddens, middelpunt). Alleen randen is te weinig: twee vormen op één
 * hartlijn zetten is precies wat je met de hand niet voor elkaar krijgt.
 */
export function omgevingstrefpunten(opties: {
	bed: { width: number; height: number };
	vel?: { width: number; height: number } | null;
	anderen: Box[];
}): { x: SnapTarget[]; y: SnapTarget[] } {
	const { bed, vel, anderen } = opties;
	const x: SnapTarget[] = [
		{ pos: 0, kind: 'bedrand' },
		{ pos: bed.width / 2, kind: 'bedmidden' },
		{ pos: bed.width, kind: 'bedrand' }
	];
	const y: SnapTarget[] = [
		{ pos: 0, kind: 'bedrand' },
		{ pos: bed.height / 2, kind: 'bedmidden' },
		{ pos: bed.height, kind: 'bedrand' }
	];

	// Het vel ligt in de linkerbovenhoek van het bed; zijn linkerrand valt dus
	// samen met die van het bed en voegt niets toe.
	if (vel) {
		if (vel.width < bed.width - 0.01) {
			x.push({ pos: vel.width / 2, kind: 'velmidden' }, { pos: vel.width, kind: 'velrand' });
		}
		if (vel.height < bed.height - 0.01) {
			y.push({ pos: vel.height / 2, kind: 'velmidden' }, { pos: vel.height, kind: 'velrand' });
		}
	}

	for (const doos of anderen) {
		const g = grenzen(doos);
		const langsY: [number, number] = [g.y0, g.y1];
		const langsX: [number, number] = [g.x0, g.x1];
		x.push(
			{ pos: g.x0, kind: 'rand', span: langsY },
			{ pos: (g.x0 + g.x1) / 2, kind: 'midden', span: langsY },
			{ pos: g.x1, kind: 'rand', span: langsY }
		);
		y.push(
			{ pos: g.y0, kind: 'rand', span: langsX },
			{ pos: (g.y0 + g.y1) / 2, kind: 'midden', span: langsX },
			{ pos: g.y1, kind: 'rand', span: langsX }
		);
	}
	return { x, y };
}

/**
 * De beste treffer voor één as.
 *
 * `kandidaten` zijn de punten van het bewegende ding die mogen vastklikken —
 * bij een verplaatsing de linkerrand, het midden en de rechterrand; bij een
 * hoekgreep alleen die hoek. De teruggegeven `delta` telt op bij de beweging.
 *
 * Een vorm-, vel- of bedrand wint van een rasterlijn op gelijke afstand: het
 * raster ligt overal, dus zonder die voorkeur klik je nooit op een vorm vast
 * zodra die toevallig naast een rasterlijn ligt.
 */
export function klikVast(
	as: 'x' | 'y',
	kandidaten: number[],
	trefpunten: SnapTarget[],
	rasterstap: number,
	trefafstand: number
): SnapHit | null {
	let beste: SnapHit | null = null;
	const beter = (afstand: number) => !beste || afstand < Math.abs(beste.delta) - 1e-9;

	for (const kandidaat of kandidaten) {
		for (const punt of trefpunten) {
			const delta = punt.pos - kandidaat;
			if (Math.abs(delta) > trefafstand) continue;
			if (!beter(Math.abs(delta))) continue;
			beste = { delta, guide: { axis: as, pos: punt.pos, kind: punt.kind, span: punt.span } };
		}
	}

	if (rasterstap > 0) {
		for (const kandidaat of kandidaten) {
			const lijn = Math.round(kandidaat / rasterstap) * rasterstap;
			const delta = lijn - kandidaat;
			if (Math.abs(delta) > trefafstand) continue;
			if (!beter(Math.abs(delta))) continue;
			beste = { delta, guide: { axis: as, pos: lijn, kind: 'raster' } };
		}
	}
	return beste;
}

/**
 * Een hele doos verplaatsen: rand, midden en rand mogen elk vastklikken, per
 * as onafhankelijk. Zo kan een vorm links uitlijnen op de ene buur en boven op
 * de andere — dat is het gedrag dat je van een tekenprogramma verwacht.
 */
export function klikDoosVast(
	doos: Box,
	verplaatsing: { dx: number; dy: number },
	trefpunten: { x: SnapTarget[]; y: SnapTarget[] },
	rasterstap: number,
	trefafstand: number
): { dx: number; dy: number; guides: SnapGuide[] } {
	const g = grenzen(doos);
	const x = klikVast(
		'x',
		[g.x0 + verplaatsing.dx, (g.x0 + g.x1) / 2 + verplaatsing.dx, g.x1 + verplaatsing.dx],
		trefpunten.x,
		rasterstap,
		trefafstand
	);
	const y = klikVast(
		'y',
		[g.y0 + verplaatsing.dy, (g.y0 + g.y1) / 2 + verplaatsing.dy, g.y1 + verplaatsing.dy],
		trefpunten.y,
		rasterstap,
		trefafstand
	);
	const guides: SnapGuide[] = [];
	if (x) guides.push(x.guide);
	if (y) guides.push(y.guide);
	return {
		dx: verplaatsing.dx + (x?.delta ?? 0),
		dy: verplaatsing.dy + (y?.delta ?? 0),
		guides
	};
}

/**
 * Eén punt vastklikken: een hoekgreep tijdens het schalen, een knooppunt, een
 * eindpunt van een lijn, of de plek waar een nieuwe vorm komt.
 */
export function klikPuntVast(
	punt: { x: number; y: number },
	trefpunten: { x: SnapTarget[]; y: SnapTarget[] },
	rasterstap: number,
	trefafstand: number
): { x: number; y: number; guides: SnapGuide[] } {
	const x = klikVast('x', [punt.x], trefpunten.x, rasterstap, trefafstand);
	const y = klikVast('y', [punt.y], trefpunten.y, rasterstap, trefafstand);
	const guides: SnapGuide[] = [];
	if (x) guides.push(x.guide);
	if (y) guides.push(y.guide);
	return { x: punt.x + (x?.delta ?? 0), y: punt.y + (y?.delta ?? 0), guides };
}

/** Het woordje bij een hulplijn. Kort, want het staat op het werkstuk. */
export const SNAP_LABEL: Record<SnapKind, string> = {
	raster: 'raster',
	rand: 'rand',
	midden: 'midden',
	bedrand: 'bedrand',
	bedmidden: 'bedmidden',
	velrand: 'velrand',
	velmidden: 'velmidden'
};
