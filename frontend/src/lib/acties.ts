/**
 * Eén lijst van handelingen, drie oppervlakken.
 *
 * Dit bestand is de reden dat het rechterklikmenu, de actiebalk boven het canvas
 * en het toetsenbord niet uit elkaar kunnen lopen. Ze lezen alle drie hiervan:
 * dezelfde naam, dezelfde sneltoets, dezelfde reden waarom iets nu niet kan.
 *
 * Vóór deze ronde stond elke handeling één keer in `DesignPanel.svelte` en
 * nergens anders — en dus stond de reden waarom hij niet kon ook maar op één
 * plek, in een tooltip. Wie de handeling elders zocht, vond hem niet; wie hem
 * vond, wist niet welke toets erbij hoorde. De plaatsingsregel uit
 * DESIGN-SYSTEM.md ("een waarde hoort in het paneel, een werkwoord in het
 * menu") is alleen door te voeren als er één plek is die weet wélke werkwoorden
 * er zijn.
 *
 * Wat hier *niet* in staat: wat een handeling dóet. Dat blijft in de pagina, bij
 * de bestaande afhandelaars. Dit bestand kent alleen naam, toets, toestand en
 * een `doen()` dat naar zo'n afhandelaar wijst.
 */

/** Losse handeling. */
export type Actie = {
	id: string;
	label: string;
	/** Weergave van de sneltoets, bijv. "⌘C". Leeg = geen. */
	toets?: string;
	/** Naam van een pictogram uit `ArrangeIcon.svelte`. */
	icoon?: string;
	/** Reden waarom dit nu niet kan. Gevuld = uitgeschakeld, en de reden staat
	 *  in de tooltip. Een grijze knop zonder reden is een raadsel. */
	uit?: string;
	/** Voor schakelbare regels: staat hij aan? */
	aan?: boolean;
	/** Extra uitleg in de tooltip als er niets in de weg staat. */
	uitleg?: string;
	/** Rood, en nooit de eerste regel: dit gooit iets weg. */
	gevaar?: boolean;
	doen: () => void;
};

/** Regel die een submenu opent. */
export type Submenu = {
	id: string;
	label: string;
	uit?: string;
	uitleg?: string;
	/** Nooit gezet op een submenu; staat er zodat het menu één type kan lezen. */
	aan?: undefined;
	gevaar?: undefined;
	toets?: undefined;
	icoon?: string;
	/** Acht pictogrammen in twee rijen van vier, zoals uitlijnen. */
	raster?: boolean;
	items: Actie[];
};

export type MenuItem = Actie | Submenu;
export type Groep = { titel?: string; items: (MenuItem | 'scheiding')[] };
export type Menu = Groep[];

/** Toont het menu deze regel als aanvinkbaar? */
export function isSubmenu(item: MenuItem): item is Submenu {
	return 'items' in item;
}

// ─── Sneltoetsen ─────────────────────────────────────────────────────────────
//
// Twee dingen bepalen deze tabel, en ze vechten met elkaar.
//
// 1. **De reflex van een LightBurn-gebruiker.** Die verwacht ⌘Z, ⌘X/C/V, ⌘D,
//    ⌘A, ⌘G, ⌘⇧H/V, en voor het zoomen ⌘0 en ⌘⇧A.
// 2. **De browser.** ⌘0, ⌘+ en ⌘− zijn de zoom van de browser zelf en zijn in
//    Chrome níet af te vangen — een `preventDefault` doet daar niets. Wie ze
//    toch koppelt, bouwt een sneltoets die de pagina laat verschalen in plaats
//    van het bed. Dat is erger dan geen sneltoets.
//
// Vandaar de verdeling: alles wat af te vangen is, krijgt de toets die de
// gebruiker al kent. Het zoomen krijgt kale cijfers (die werken altijd), plus
// ⌘⇧A voor "naar de selectie" omdat dát wél af te vangen is en precies de
// LightBurn-toets is.
export const TOETSEN: Record<string, string> = {
	undo: 'mod+z',
	redo: 'mod+shift+z',
	knippen: 'mod+x',
	kopieren: 'mod+c',
	plakken: 'mod+v',
	dupliceren: 'mod+d',
	verwijderen: 'delete',
	allesSelecteren: 'mod+a',
	groeperen: 'mod+g',
	// Twee toetsen voor één handeling: ⌘⇧G komt uit Illustrator en Figma, ⌘U uit
	// LightBurn. Wie uit een van de drie komt, hoeft niet om te leren.
	groepOpheffen: 'mod+shift+g',
	groepOpheffen2: 'mod+u',
	spiegelH: 'mod+shift+h',
	spiegelV: 'mod+shift+v',
	draaiLinks: ',',
	draaiRechts: '.',
	zoom100: '1',
	zoomSelectie: '2',
	zoomAlles: '3',
	zoomBed: '0',
	// De oude toetsen blijven werken: ze staan in de tooltips van de zoombalk en
	// iemand heeft ze inmiddels in zijn vingers.
	zoomAllesOud: 'shift+1',
	zoomSelectieOud: 'shift+2',
	zoomSelectieLightburn: 'mod+shift+a',
	zoomIn: '+',
	zoomUit: '-'
};

const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '');

/** "mod+shift+z" → "⌘⇧Z" op een Mac, "Ctrl+Shift+Z" elders. */
export function toetsLabel(combo: string | undefined): string | undefined {
	if (!combo) return undefined;
	const delen = combo.split('+');
	const laatste = delen.pop() ?? '';
	const namen: Record<string, string> = {
		delete: MAC ? '⌫' : 'Del',
		arrowup: '↑',
		arrowdown: '↓',
		arrowleft: '←',
		arrowright: '→'
	};
	const kern = namen[laatste] ?? (laatste.length === 1 ? laatste.toUpperCase() : laatste);
	if (MAC) {
		const teken: Record<string, string> = { mod: '⌘', shift: '⇧', alt: '⌥' };
		return delen.map((d) => teken[d] ?? d).join('') + kern;
	}
	const teken: Record<string, string> = { mod: 'Ctrl', shift: 'Shift', alt: 'Alt' };
	return [...delen.map((d) => teken[d] ?? d), kern].join('+');
}

/** Leest een toetsaanslag als combo-tekst, zodat hij tegen `TOETSEN` te leggen is. */
export function comboVan(event: KeyboardEvent): string {
	const delen: string[] = [];
	if (event.metaKey || event.ctrlKey) delen.push('mod');
	if (event.shiftKey) delen.push('shift');
	if (event.altKey) delen.push('alt');
	let sleutel = event.key.toLowerCase();
	if (sleutel === 'backspace') sleutel = 'delete';
	// Shift+1 levert "!" op een US-indeling en "1" op sommige andere; beide
	// moeten dezelfde combo geven, anders werkt de sneltoets op de ene toetsen-
	// indeling en op de andere niet.
	const shiftCijfers: Record<string, string> = {
		'!': '1',
		'@': '2',
		'#': '3',
		')': '0',
		'=': '+',
		_: '-'
	};
	if (shiftCijfers[sleutel]) sleutel = shiftCijfers[sleutel];
	delen.push(sleutel);
	return delen.join('+');
}

// ─── De handelingen op een selectie ──────────────────────────────────────────

export type Context = {
	/** Aantal geselecteerde vormen. */
	aantal: number;
	/** Zit de selectie in een groep? */
	inGroep: boolean;
	isAfbeelding: boolean;
	isTekst: boolean;
	isBijgesneden: boolean;
	/** Heeft de selectie al een vulling? Bepaalt het woord op de vulknop. */
	gevuld: boolean;
	/** Aantal vormen op het klembord. */
	klembord: number;
	/** Staat er een schrijfactie te wachten? */
	bezig: boolean;
	/** Mag deze sessie schrijven (token)? */
	mag: boolean;
	/** De lagen waarin de selectie gezet kan worden. */
	lagen: { id: string; label: string; erin: boolean }[];
	/** De andere vellen. */
	vellen: { id: string; name: string }[];
	/** Staat vastklikken aan? */
	vastklikken: boolean;
	/** Staan de laagnummers aan? */
	laagnummers: boolean;
	/** Is er iets op het bed? */
	leeg: boolean;
	/** Wat splitsen zou opleveren: hoeveel vormen uit hoeveel losse stukken. Het
	 *  getal staat op de menuregel, want een belofte zonder getal ("splitsen")
	 *  zegt niet of er iets te splitsen valt. */
	teSplitsen: { vormen: number; stukken: number };
};

/** Wat de pagina moet kunnen uitvoeren. Eén object, zodat een test het kan namaken. */
export type Handelingen = {
	knippen: () => void;
	kopieren: () => void;
	plakken: (opPunt?: { x: number; y: number }) => void;
	dupliceren: () => void;
	verwijderen: () => void;
	allesSelecteren: () => void;
	selectieWissen: () => void;
	schikken: (modus: string) => void;
	draaien: (graden: number) => void;
	splitsen: () => void;
	vullen: (aan: boolean) => void;
	hoeken: () => void;
	naarLaag: (soort: 'cut' | 'engrave' | 'raster') => void;
	laagToekennen: (id: string, erin: boolean) => void;
	naarVel: (id: string) => void;
	tekstBewerken: () => void;
	bijsnijden: () => void;
	bijsnijdenTerug: () => void;
	vectoriseren: () => void;
	undo: () => void;
	redo: () => void;
	zoom: (wat: 'alles' | 'selectie' | 'bed' | 'honderd') => void;
	vastklikken: () => void;
	laagnummers: () => void;
	redden: () => void;
};

const T = (id: string) => toetsLabel(TOETSEN[id]);

/** Waarom een handeling die meer vormen nodig heeft, nu niet kan. */
function tweeNodig(ctx: Context): string | undefined {
	if (!ctx.mag) return 'Vereist een token';
	if (ctx.aantal < 2) return 'Selecteer minstens twee vormen';
	return undefined;
}

function drieNodig(ctx: Context): string | undefined {
	if (!ctx.mag) return 'Vereist een token';
	if (ctx.aantal < 3) return 'Verdelen heeft minstens drie vormen nodig';
	return undefined;
}

function moetMogen(ctx: Context): string | undefined {
	if (!ctx.mag) return 'Vereist een token';
	if (ctx.bezig) return 'Er loopt nog een bewerking';
	return undefined;
}

/**
 * De acht uitlijn- en verdeelknoppen.
 *
 * Ze staan in dezelfde volgorde als in het oude paneel — eerste rij
 * horizontaal, tweede verticaal — zodat wie ze daar in zijn vingers had, ze
 * hier op dezelfde plek terugvindt.
 */
export function uitlijnActies(ctx: Context, h: Handelingen): Actie[] {
	const rijen: [string, string, string, boolean][] = [
		['left', 'align-left', 'Links uitlijnen', false],
		['centerh', 'align-centerh', 'Horizontaal centreren', false],
		['right', 'align-right', 'Rechts uitlijnen', false],
		['spaceh', 'space-h', 'Horizontaal verdelen', true],
		['top', 'align-top', 'Boven uitlijnen', false],
		['centerv', 'align-centerv', 'Verticaal centreren', false],
		['bottom', 'align-bottom', 'Onder uitlijnen', false],
		['spacev', 'space-v', 'Verticaal verdelen', true]
	];
	return rijen.map(([modus, icoon, label, drie]) => ({
		id: `uitlijn-${modus}`,
		label,
		icoon,
		uit: drie ? drieNodig(ctx) : tweeNodig(ctx),
		doen: () => h.schikken(modus)
	}));
}

/** Groeperen, opheffen en spiegelen — de rest van de actiebalk. */
export function schikActies(ctx: Context, h: Handelingen): Actie[] {
	return [
		{
			id: 'groeperen',
			label: 'Groeperen',
			icoon: 'group',
			toets: T('groeperen'),
			uit: tweeNodig(ctx),
			uitleg: 'De vormen bewegen voortaan samen',
			doen: () => h.schikken('group')
		},
		{
			id: 'groepOpheffen',
			label: 'Groep opheffen',
			icoon: 'ungroup',
			toets: T('groepOpheffen'),
			uit: !ctx.mag
				? 'Vereist een token'
				: ctx.inGroep
					? undefined
					: 'Deze selectie zit niet in een groep',
			doen: () => h.schikken('ungroup')
		},
		{
			id: 'spiegelH',
			label: 'Horizontaal spiegelen',
			icoon: 'mirror-h',
			toets: T('spiegelH'),
			uit: moetMogen(ctx) ?? (ctx.aantal ? undefined : 'Kies eerst een vorm'),
			uitleg: 'Om de verticale as. Nog een keer zet het terug.',
			doen: () => h.schikken('mirror-h')
		},
		{
			id: 'spiegelV',
			label: 'Verticaal spiegelen',
			icoon: 'mirror-v',
			toets: T('spiegelV'),
			uit: moetMogen(ctx) ?? (ctx.aantal ? undefined : 'Kies eerst een vorm'),
			uitleg: 'Om de horizontale as. Nog een keer zet het terug.',
			doen: () => h.schikken('mirror-v')
		}
	];
}

/** Ongedaan maken en opnieuw — links in de actiebalk, en in geen enkel menu. */
export function geschiedenisActies(ctx: Context, h: Handelingen): Actie[] {
	return [
		{
			id: 'undo',
			label: 'Ongedaan maken',
			icoon: 'undo',
			toets: T('undo'),
			uit: moetMogen(ctx),
			doen: h.undo
		},
		{
			id: 'redo',
			label: 'Opnieuw',
			icoon: 'redo',
			toets: T('redo'),
			uit: moetMogen(ctx),
			doen: h.redo
		}
	];
}

/**
 * Het menu op een vorm.
 *
 * De volgorde is de volgorde van elke desktop-app: eerst het klembord, dan
 * schikken, dan de vorm zelf, dan waar hij hoort (laag, vel), en pas onderaan
 * wat hem weggooit. Wie hier per ongeluk klikt, klikt op "Kopiëren" en niet op
 * "Verwijderen".
 */
export function objectMenu(ctx: Context, h: Handelingen): Menu {
	const magNiet = moetMogen(ctx);
	const eenNodig = magNiet ?? (ctx.aantal ? undefined : 'Kies eerst een vorm');

	const combineren: Actie[] = [
		['union', 'Verenigen'],
		['difference', 'Verschil'],
		['intersection', 'Doorsnede'],
		['xor', 'Uitsluiten']
	].map(([op, label]) => ({
		id: `bool-${op}`,
		label,
		uit: tweeNodig(ctx),
		uitleg: 'Het resultaat is één pad; de vormen verdwijnen',
		doen: () => h.schikken(op)
	}));

	const pad: Actie[] = [
		{
			id: 'pad-offset',
			label: 'Offset…',
			uit: eenNodig,
			doen: () => h.schikken('offset')
		},
		{
			id: 'pad-simplify',
			label: 'Vereenvoudigen',
			uit: eenNodig,
			doen: () => h.schikken('simplify')
		},
		{
			id: 'pad-nest',
			label: 'Nesten',
			uit: tweeNodig(ctx),
			uitleg: 'Leg de selectie dicht op elkaar om materiaal te sparen',
			doen: () => h.schikken('nest')
		},
		{
			id: 'pad-split',
			label: ctx.teSplitsen.vormen
				? `Splitsen in ${ctx.teSplitsen.stukken} vormen`
				: 'Splitsen in losse vormen',
			uit:
				eenNodig ??
				(ctx.teSplitsen.vormen ? undefined : 'Deze vorm bestaat uit één stuk'),
			doen: h.splitsen
		},
		{
			id: 'pad-hatch',
			label: 'Arcering (hatch)',
			uit: eenNodig,
			doen: () => h.schikken('hatch')
		},
		{ id: 'pad-wobble', label: 'Wobble', uit: eenNodig, doen: () => h.schikken('wobble') }
	];

	// Bestaande lagen als aanvinkbare regels — een vorm kan in meer dan één laag
	// zitten, dus dit zijn vinkjes en geen keuzerondjes. Daaronder de drie
	// "alleen in"-regels: die hálen hem ook uit de andere lagen, en dat is een
	// ander werkwoord dan aanvinken.
	const lagen: Actie[] = [
		...ctx.lagen.map((laag) => ({
			id: `laag-${laag.id}`,
			label: laag.label,
			aan: laag.erin,
			uit: eenNodig,
			doen: () => h.laagToekennen(laag.id, !laag.erin)
		})),
		{
			id: 'laag-alleen-cut',
			label: 'Alleen in de snijlaag',
			uit: eenNodig,
			doen: () => h.naarLaag('cut')
		},
		{
			id: 'laag-alleen-engrave',
			label: 'Alleen in de graveerlaag',
			uit: eenNodig,
			doen: () => h.naarLaag('engrave')
		},
		{
			id: 'laag-alleen-raster',
			label: 'Alleen in de rasterlaag',
			uit: eenNodig,
			doen: () => h.naarLaag('raster')
		}
	];

	const menu: Menu = [
		{
			items: [
				{
					id: 'knippen',
					label: 'Knippen',
					toets: T('knippen'),
					uit: eenNodig,
					doen: h.knippen
				},
				{
					id: 'kopieren',
					label: 'Kopiëren',
					toets: T('kopieren'),
					uit: eenNodig,
					doen: h.kopieren
				},
				{
					id: 'dupliceren',
					label: 'Dupliceren',
					toets: T('dupliceren'),
					uit: eenNodig,
					doen: h.dupliceren
				}
			]
		},
		{
			items: [
				{
					id: 'uitlijnen',
					label: 'Uitlijnen en verdelen',
					raster: true,
					uit: tweeNodig(ctx),
					items: uitlijnActies(ctx, h)
				},
				...schikActies(ctx, h),
				{
					id: 'draaien',
					label: 'Draaien',
					uit: eenNodig,
					// Ook de regels ín een submenu dragen hun eigen reden. Alleen de
					// ouder uitschakelen is genoeg voor de muis, maar niet voor het
					// toetsenbord en niet voor een tweede oppervlak dat dezelfde lijst
					// leest — en dat is precies waar deze lijst voor bestaat.
					items: [
						{
							id: 'draai-links',
							label: '90° linksom',
							toets: T('draaiLinks'),
							uit: eenNodig,
							doen: () => h.draaien(-90)
						},
						{
							id: 'draai-rechts',
							label: '90° rechtsom',
							toets: T('draaiRechts'),
							uit: eenNodig,
							doen: () => h.draaien(90)
						},
						{ id: 'draai-180', label: '180°', uit: eenNodig, doen: () => h.draaien(180) }
					]
				}
			]
		},
		{
			items: [
				{ id: 'combineren', label: 'Combineren', uit: tweeNodig(ctx), items: combineren },
				{ id: 'pad', label: 'Pad bewerken', uit: eenNodig, items: pad },
				{
					id: 'hoeken',
					label: 'Hoeken…',
					uitleg: 'Afronden of afschuinen, met het voorbeeld erbij',
					uit: eenNodig,
					doen: h.hoeken
				},
				{
					id: 'vullen',
					label: ctx.gevuld ? 'Vulling weghalen' : 'Vullen — voor rasteren',
					uit: eenNodig,
					uitleg: ctx.gevuld
						? 'Zonder vulling rastert een vorm alleen zijn omtrek'
						: 'Een rasterlaag brandt dan het vlak in plaats van alleen de omtrek',
					doen: () => h.vullen(!ctx.gevuld)
				}
			]
		},
		{
			items: [
				{
					id: 'laag',
					label: 'Laag',
					uit: eenNodig,
					items: lagen
				},
				...(ctx.vellen.length
					? [
							{
								id: 'vel',
								label: 'Naar een ander vel',
								uit: eenNodig,
								items: ctx.vellen.map((vel) => ({
									id: `vel-${vel.id}`,
									label: vel.name,
									uit: eenNodig,
									doen: () => h.naarVel(vel.id)
								}))
							} as Submenu
						]
					: [])
			]
		}
	];

	// Alleen wat op dít soort vorm van toepassing is. Een menu dat altijd
	// "Bijsnijden" toont bij een rechthoek leert je dat de helft grijs is.
	const bijzonder: (MenuItem | 'scheiding')[] = [];
	if (ctx.isTekst)
		bijzonder.push({
			id: 'tekst',
			label: 'Tekst bewerken…',
			uit: eenNodig,
			doen: h.tekstBewerken
		});
	if (ctx.isAfbeelding) {
		bijzonder.push({
			id: 'bijsnijden',
			label: 'Bijsnijden',
			uit: eenNodig,
			uitleg: 'Sleep daarna een kader over de afbeelding',
			doen: h.bijsnijden
		});
		if (ctx.isBijgesneden)
			bijzonder.push({
				id: 'bijsnijden-terug',
				label: 'Bijsnijden ongedaan maken',
				uit: eenNodig,
				doen: h.bijsnijdenTerug
			});
		bijzonder.push({
			id: 'vectoriseren',
			label: 'Vectoriseren',
			uit: eenNodig,
			uitleg: 'Maakt paden van de afbeelding',
			doen: h.vectoriseren
		});
	}
	if (bijzonder.length) menu.push({ items: bijzonder });

	menu.push({
		items: [
			{
				id: 'verwijderen',
				label: 'Verwijderen',
				toets: T('verwijderen'),
				uit: eenNodig,
				gevaar: true,
				doen: h.verwijderen
			}
		]
	});
	return menu;
}

/**
 * Het menu op het canvas zelf.
 *
 * Hier staat wat over het beeld en het hele ontwerp gaat, niet over één vorm.
 * "Plakken hier" staat bovenaan omdat het de reden is dat je hier rechtsklikt:
 * je hebt iets gekopieerd en je wijst aan waar het moet komen.
 */
export function canvasMenu(
	ctx: Context,
	h: Handelingen,
	punt: { x: number; y: number } | null
): Menu {
	const magNiet = moetMogen(ctx);
	return [
		{
			items: [
				{
					id: 'plakken-hier',
					label: punt ? 'Plakken hier' : 'Plakken',
					toets: T('plakken'),
					uit: magNiet ?? (ctx.klembord ? undefined : 'Er staat niets op het klembord'),
					uitleg: punt
						? 'De linkerbovenhoek komt op de plek waar je klikte'
						: undefined,
					doen: () => h.plakken(punt ?? undefined)
				},
				{
					id: 'allesSelecteren',
					label: 'Alles selecteren',
					toets: T('allesSelecteren'),
					uit: ctx.leeg ? 'Er staat niets op het bed' : undefined,
					doen: h.allesSelecteren
				},
				{
					id: 'selectieWissen',
					label: 'Selectie wissen',
					toets: 'Esc',
					uit: ctx.aantal ? undefined : 'Er is niets geselecteerd',
					doen: h.selectieWissen
				}
			]
		},
		{
			titel: 'Beeld',
			items: [
				{
					id: 'zoom-alles',
					label: 'Alles passend in beeld',
					toets: T('zoomAlles'),
					uit: ctx.leeg ? 'Er staat niets op het bed' : undefined,
					doen: () => h.zoom('alles')
				},
				{
					id: 'zoom-selectie',
					label: 'Naar de selectie',
					toets: T('zoomSelectie'),
					uit: ctx.aantal ? undefined : 'Er is niets geselecteerd',
					doen: () => h.zoom('selectie')
				},
				{
					id: 'zoom-bed',
					label: 'Het hele bed',
					toets: T('zoomBed'),
					doen: () => h.zoom('bed')
				},
				{
					id: 'zoom-honderd',
					label: '100 % — 1 mm op ware grootte',
					toets: T('zoom100'),
					doen: () => h.zoom('honderd')
				}
			]
		},
		{
			items: [
				{
					id: 'vastklikken',
					label: 'Vastklikken op raster en vormen',
					aan: ctx.vastklikken,
					uitleg: 'Alt ingedrukt houden slaat het even over',
					doen: h.vastklikken
				},
				{
					id: 'laagnummers',
					label: 'Laagnummers bij de vormen',
					aan: ctx.laagnummers,
					doen: h.laagnummers
				}
			]
		},
		{
			items: [
				{
					id: 'redden',
					label: 'Alles op het bed leggen',
					uit: magNiet ?? (ctx.leeg ? 'Er staat niets op het bed' : undefined),
					uitleg: 'Ook wat buiten beeld ligt en niet aan te klikken is',
					doen: h.redden
				}
			]
		}
	];
}


// ─── Het menu op een rij in een lijst ────────────────────────────────────────

export type LaagContext = {
	label: string;
	aantalVormen: number;
	meebranden: boolean;
	zichtbaar: boolean;
	eerste: boolean;
	laatste: boolean;
	/** Zijn er vormen geselecteerd om in deze laag te zetten? */
	selectie: number;
	/** Zit de hele selectie er al in? */
	erin: boolean;
	mag: boolean;
	opSlot?: string;
};

export type LaagHandelingen = {
	selecteerVormen: () => void;
	selectieErin: (erin: boolean) => void;
	meebranden: () => void;
	zichtbaar: () => void;
	omhoog: () => void;
	omlaag: () => void;
	openen: () => void;
	verwijderen: () => void;
};

/**
 * Rechterklik op een laag.
 *
 * LightBurn heeft dit ook, en met bijna dezelfde regels: aan/uit, verbergen, en
 * de vormen van die laag selecteren. Dat laatste bestond bij ons nergens, en
 * het is precies wat je wil zodra je een geïmporteerde tekening indeelt: zien
 * wát er in een laag zit door het te selecteren.
 */
export function laagMenu(ctx: LaagContext, h: LaagHandelingen): Menu {
	const magNiet = ctx.mag ? undefined : 'Vereist een token';
	const opSlot = ctx.opSlot;
	return [
		{
			items: [
				{
					id: 'laag-selecteer',
					label:
						ctx.aantalVormen === 1
							? 'De vorm in deze laag selecteren'
							: `De ${ctx.aantalVormen} vormen in deze laag selecteren`,
					uit: ctx.aantalVormen ? undefined : 'Deze laag is leeg',
					doen: h.selecteerVormen
				},
				{
					id: 'laag-erin',
					label: ctx.erin ? 'Selectie uit deze laag halen' : 'Selectie in deze laag zetten',
					uit: magNiet ?? opSlot ?? (ctx.selectie ? undefined : 'Er is niets geselecteerd'),
					doen: () => h.selectieErin(!ctx.erin)
				}
			]
		},
		{
			items: [
				{
					id: 'laag-meebranden',
					label: 'Brandt mee',
					aan: ctx.meebranden,
					uit: magNiet ?? opSlot,
					uitleg: 'Uit betekent: deze laag gaat de machine niet in',
					doen: h.meebranden
				},
				{
					id: 'laag-zichtbaar',
					label: 'Zichtbaar op het canvas',
					aan: ctx.zichtbaar,
					uitleg: 'Verandert niets aan de job',
					doen: h.zichtbaar
				}
			]
		},
		{
			items: [
				{
					id: 'laag-omhoog',
					label: 'Eerder branden',
					uit: magNiet ?? (ctx.eerste ? 'Deze laag brandt al als eerste' : undefined),
					doen: h.omhoog
				},
				{
					id: 'laag-omlaag',
					label: 'Later branden',
					uit: magNiet ?? (ctx.laatste ? 'Deze laag brandt al als laatste' : undefined),
					doen: h.omlaag
				},
				{
					id: 'laag-openen',
					label: 'Instellingen…',
					uitleg: 'Naam, snelheid, vermogen, passes, kleur',
					doen: h.openen
				}
			]
		},
		{
			items: [
				{
					id: 'laag-weg',
					label: 'Laag verwijderen',
					uit: magNiet ?? opSlot,
					uitleg: 'De vormen blijven op het bed staan',
					gevaar: true,
					doen: h.verwijderen
				}
			]
		}
	];
}
