/**
 * One list of operations, three surfaces.
 *
 * This file is the reason the right-click menu, the action bar above the canvas
 * and the keyboard cannot drift apart. All three read from here: the same name,
 * the same shortcut, the same reason why something cannot be done right now.
 *
 * Before this existed, every operation lived in exactly one place — and so did
 * the reason it was greyed out, inside a single tooltip. Whoever looked for the
 * operation elsewhere did not find it; whoever found it did not know which key
 * belonged to it. The placement rule in DESIGN-SYSTEM.md ("a value belongs in the
 * panel, a verb in the menu") can only be carried through if one place knows
 * *which* verbs exist.
 *
 * What is deliberately *not* here: what an operation does. That stays in the page,
 * with the existing handlers. This file knows a name, a key, a state, and a
 * `run()` that points at such a handler.
 *
 * Names are English because the code is; the text a user reads comes from the
 * message catalogue (`$lib/i18n`).
 */
import { t } from './i18n/core.ts';

/** A single operation. */
export type Action = {
	id: string;
	label: string;
	/** How the shortcut is shown, e.g. "⌘C". Empty means there is none. */
	key?: string;
	/** Name of an icon in `ArrangeIcon.svelte`. */
	icon?: string;
	/** Why this cannot be done now. Set means disabled, and the reason goes in the
	 *  tooltip. A grey button without a reason is a riddle. */
	off?: string;
	/** For toggleable rows: is it on? */
	on?: boolean;
	/** Extra explanation in the tooltip when nothing is in the way. */
	explain?: string;
	/** Red, and never the first row: this throws something away. */
	danger?: boolean;
	run: () => void;
};

/** A row that opens a submenu. */
export type Submenu = {
	id: string;
	label: string;
	off?: string;
	explain?: string;
	/** Never set on a submenu; present so the menu can read one type. */
	on?: undefined;
	danger?: undefined;
	key?: undefined;
	icon?: string;
	/** Eight icons in two rows of four, like aligning. */
	grid?: boolean;
	items: Action[];
};

export type MenuItem = Action | Submenu;
export type Group = { title?: string; items: (MenuItem | 'separator')[] };
export type Menu = Group[];

export function isSubmenu(item: MenuItem): item is Submenu {
	return 'items' in item;
}

// ─── Shortcuts ───────────────────────────────────────────────────────────────
//
// Two things decide this table, and they fight each other.
//
// 1. **What a LightBurn user reaches for.** ⌘Z, ⌘X/C/V, ⌘D, ⌘A, ⌘G, ⌘⇧H/V, and
//    for zooming ⌘0 and ⌘⇧A.
// 2. **The browser.** ⌘0, ⌘+ and ⌘− are the browser's own zoom and cannot be
//    intercepted in Chrome — a `preventDefault` does nothing there. Binding them
//    anyway builds a shortcut that rescales the page instead of the bed. That is
//    worse than no shortcut.
//
// Hence the split: everything interceptable gets the key the user already knows.
// Zooming gets bare digits, which always work, plus ⌘⇧A for "to the selection"
// because that one *is* interceptable and is exactly LightBurn's key.
export const KEYS: Record<string, string> = {
	undo: 'mod+z',
	redo: 'mod+shift+z',
	cut: 'mod+x',
	copy: 'mod+c',
	paste: 'mod+v',
	duplicate: 'mod+d',
	delete: 'delete',
	selectAll: 'mod+a',
	// Locking a shape is the counterpart of selecting it, and ⌘L is free here.
	lock: 'mod+l',
	group: 'mod+g',
	// Two keys for one operation: ⌘⇧G comes from Illustrator and Figma, ⌘U from
	// LightBurn. Whoever comes from one of the three need not relearn.
	ungroup: 'mod+shift+g',
	ungroupAlt: 'mod+u',
	// Bridges (tabs) in a cut line. ⌘⇧B is Chrome's bookmarks-bar toggle, and unlike ⌘0
	// that one *is* interceptable — verified in the browser: with the canvas focused the
	// bookmarks bar stays as it was and the bridges land on the selection.
	bridges: 'mod+shift+b',
	mirrorH: 'mod+shift+h',
	mirrorV: 'mod+shift+v',
	rotateLeft: ',',
	rotateRight: '.',
	zoomHundred: '1',
	zoomSelection: '2',
	zoomAll: '3',
	zoomBed: '0',
	// The old keys keep working: they are in the tooltips of the zoom bar and by
	// now someone has them in their fingers.
	zoomAllOld: 'shift+1',
	zoomSelectionOld: 'shift+2',
	zoomSelectionLightburn: 'mod+shift+a',
	zoomIn: '+',
	zoomOut: '-',
	// Node editing (P1). Shift+L and Shift+U are Inkscape's own keys for "make this
	// segment straight" and "make it a curve", so whoever comes from there need not
	// relearn. Inkscape adds a node with Insert; a Mac keyboard has no Insert, so it is
	// Shift+I here. Delete removes the node and not the shape — while the node tool has a
	// node in hand, that is what "delete" means.
	// The cut path (gap S1). Alt+P is LightBurn's own key for its Preview, and
	// unlike ⌘0 the browser leaves Alt+P alone — verified in Chrome with the canvas
	// focused: the window opens and nothing else moves.
	cutPath: 'alt+p',
	nodeAdd: 'shift+i',
	nodeCorner: 'shift+l',
	nodeCurve: 'shift+u',
	nodeRemove: 'delete'
};

const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '');

/** "mod+shift+z" → "⌘⇧Z" on a Mac, "Ctrl+Shift+Z" elsewhere. */
export function keyLabel(combo: string | undefined): string | undefined {
	if (!combo) return undefined;
	const parts = combo.split('+');
	const last = parts.pop() ?? '';
	const names: Record<string, string> = {
		delete: MAC ? '⌫' : 'Del',
		arrowup: '↑',
		arrowdown: '↓',
		arrowleft: '←',
		arrowright: '→'
	};
	const core = names[last] ?? (last.length === 1 ? last.toUpperCase() : last);
	if (MAC) {
		const sign: Record<string, string> = { mod: '⌘', shift: '⇧', alt: '⌥' };
		return parts.map((p) => sign[p] ?? p).join('') + core;
	}
	const sign: Record<string, string> = { mod: 'Ctrl', shift: 'Shift', alt: 'Alt' };
	return [...parts.map((p) => sign[p] ?? p), core].join('+');
}

/** Reads a keystroke as combo text, so it can be matched against `KEYS`. */
export function comboOf(event: KeyboardEvent): string {
	const parts: string[] = [];
	if (event.metaKey || event.ctrlKey) parts.push('mod');
	if (event.shiftKey) parts.push('shift');
	if (event.altKey) parts.push('alt');
	let key = event.key.toLowerCase();
	if (key === 'backspace') key = 'delete';
	// Shift+1 yields "!" on a US layout and "1" on some others; both must give the
	// same combo, otherwise the shortcut works on one keyboard layout and not the
	// next.
	const shifted: Record<string, string> = {
		'!': '1',
		'@': '2',
		'#': '3',
		')': '0',
		'=': '+',
		_: '-'
	};
	if (shifted[key]) key = shifted[key];
	parts.push(key);
	return parts.join('+');
}

// ─── The state an operation depends on ───────────────────────────────────────

export type Context = {
	/** How many shapes are selected. */
	count: number;
	/** Is the selection inside a group? */
	inGroup: boolean;
	/** How many of the selected shapes are locked. Decides the row and its reason. */
	lockedCount: number;
	isImage: boolean;
	isText: boolean;
	isCropped: boolean;
	/** Does the selection already have a fill? Decides the wording of the fill row. */
	filled: boolean;
	/**
	 * Bridges (tabs) on the selection: can these shapes carry them at all, and do they
	 * have them now? The second decides whether the row offers them or takes them away —
	 * one row for both, like the fill row above.
	 */
	bridges: { carries: boolean; has: boolean };
	/** How many shapes are on the clipboard. */
	clipboard: number;
	/** Is a write action still in flight? */
	busy: boolean;
	/** May this session write (token)? */
	may: boolean;
	/** The layers the selection can be put into. */
	layers: { id: string; label: string; inside: boolean }[];
	/** The other sheets. */
	sheets: { id: string; name: string }[];
	/** Is snapping on? */
	snap: boolean;
	/** Are the layer numbers shown? */
	layerNumbers: boolean;
	/** Is the bed empty? */
	empty: boolean;
	/** What splitting would yield: how many shapes out of how many loose pieces.
	 *  The number goes on the menu row, because a promise without a number
	 *  ("split") does not say whether there is anything to split. */
	splittable: { shapes: number; pieces: number };
	/**
	 * The shapes under the pointer, topmost first — for the right-click that opened
	 * this menu.
	 *
	 * Alt+click walks down a pile, and that is quick once you know it. This is the
	 * way that needs no knowing and no keyboard: a list, by name, with the one you
	 * have now ticked. It is also the only way on a touch screen, where there is no
	 * Alt to hold.
	 */
	under: { id: string; label: string; selected: boolean }[];
};

/** What the page must be able to perform. One object, so a test can fake it. */
export type Handlers = {
	cut: () => void;
	copy: () => void;
	paste: (at?: { x: number; y: number }) => void;
	duplicate: () => void;
	remove: () => void;
	selectAll: () => void;
	clearSelection: () => void;
	arrange: (mode: string) => void;
	rotate: (degrees: number) => void;
	split: () => void;
	fill: (on: boolean) => void;
	corners: () => void;
	/** Bridges on the selection; `false` takes them away again. */
	bridges: (on: boolean) => void;
	onlyLayer: (kind: 'cut' | 'engrave' | 'raster') => void;
	/** Select exactly this one shape — from the list of what lies under the pointer. */
	selectOne: (id: string) => void;
	/** Lock the selection, or unlock it. */
	setLocked: (locked: boolean) => void;
	/** Look for shapes lying on top of each other, and offer to remove them. */
	duplicates: () => void;
	assignLayer: (id: string, inside: boolean) => void;
	toSheet: (id: string) => void;
	editText: () => void;
	crop: () => void;
	uncrop: () => void;
	vectorise: () => void;
	undo: () => void;
	redo: () => void;
	zoom: (what: 'all' | 'selection' | 'bed' | 'hundred') => void;
	snap: () => void;
	layerNumbers: () => void;
	rescue: () => void;
	/** Open the cut-path window: the order, the travel and the clock (gap S1). */
	cutPath: () => void;
};

const K = (id: string) => keyLabel(KEYS[id]);

/** Why an operation that needs more shapes cannot run now. */
function needsTwo(ctx: Context): string | undefined {
	if (!ctx.may) return t('reason.needsToken');
	if (ctx.count < 2) return t('reason.needsTwo');
	return undefined;
}

function needsThree(ctx: Context): string | undefined {
	if (!ctx.may) return t('reason.needsToken');
	if (ctx.count < 3) return t('reason.needsThree');
	return undefined;
}

function mayWrite(ctx: Context): string | undefined {
	if (!ctx.may) return t('reason.needsToken');
	if (ctx.busy) return t('reason.busy');
	return undefined;
}

/**
 * The eight align and distribute buttons.
 *
 * In the same order as the old panel grid — first row horizontal, second row
 * vertical — so whoever had them in their fingers finds them in the same place.
 */
export function alignActions(ctx: Context, h: Handlers): Action[] {
	const rows: [string, string, string, boolean][] = [
		['left', 'align-left', 'action.align.left', false],
		['centerh', 'align-centerh', 'action.align.centerH', false],
		['right', 'align-right', 'action.align.right', false],
		['spaceh', 'space-h', 'action.align.spaceH', true],
		['top', 'align-top', 'action.align.top', false],
		['centerv', 'align-centerv', 'action.align.centerV', false],
		['bottom', 'align-bottom', 'action.align.bottom', false],
		['spacev', 'space-v', 'action.align.spaceV', true]
	];
	return rows.map(([mode, icon, key, three]) => ({
		id: `align-${mode}`,
		label: t(key as never),
		icon,
		off: three ? needsThree(ctx) : needsTwo(ctx),
		run: () => h.arrange(mode)
	}));
}

/** Group, ungroup and mirror — the rest of the action bar. */
export function arrangeActions(ctx: Context, h: Handlers): Action[] {
	return [
		{
			id: 'group',
			label: t('action.group'),
			icon: 'group',
			key: K('group'),
			off: needsTwo(ctx),
			explain: t('explain.group'),
			run: () => h.arrange('group')
		},
		{
			id: 'ungroup',
			label: t('action.ungroup'),
			icon: 'ungroup',
			key: K('ungroup'),
			off: !ctx.may
				? t('reason.needsToken')
				: ctx.inGroup
					? undefined
					: t('reason.notInGroup'),
			run: () => h.arrange('ungroup')
		},
		{
			id: 'mirrorH',
			label: t('action.mirrorH'),
			icon: 'mirror-h',
			key: K('mirrorH'),
			off: mayWrite(ctx) ?? (ctx.count ? undefined : t('reason.pickShape')),
			explain: t('explain.mirrorH'),
			run: () => h.arrange('mirror-h')
		},
		{
			id: 'mirrorV',
			label: t('action.mirrorV'),
			icon: 'mirror-v',
			key: K('mirrorV'),
			off: mayWrite(ctx) ?? (ctx.count ? undefined : t('reason.pickShape')),
			explain: t('explain.mirrorV'),
			run: () => h.arrange('mirror-v')
		}
	];
}

/** Undo and redo — leftmost in the action bar, and in no menu. */
export function historyActions(ctx: Context, h: Handlers): Action[] {
	return [
		{
			id: 'undo',
			label: t('action.undo'),
			icon: 'undo',
			key: K('undo'),
			off: mayWrite(ctx),
			run: h.undo
		},
		{
			id: 'redo',
			label: t('action.redo'),
			icon: 'redo',
			key: K('redo'),
			off: mayWrite(ctx),
			run: h.redo
		}
	];
}

/**
 * The menu on a shape.
 *
 * The order is the order of every desktop app: clipboard first, then arranging,
 * then the shape itself, then where it belongs (layer, sheet), and only at the
 * bottom what throws it away. Whoever bad-clicks here hits "Copy" and not
 * "Delete".
 */
/** Is every shape in the selection locked? Decides which way the lock row points. */
function allLocked(ctx: Context): boolean {
	return ctx.count > 0 && ctx.lockedCount === ctx.count;
}

export function objectMenu(ctx: Context, h: Handlers): Menu {
	const cannot = mayWrite(ctx);
	// A locked shape refuses geometry in the API, so the row says why before you
	// press it. Without this the menu offers "Mirror" and the app answers 409 — the
	// reason arrives after the click instead of on it.
	const locked =
		ctx.lockedCount === 0
			? undefined
			: ctx.lockedCount === ctx.count && ctx.count === 1
				? t('reason.locked')
				: t('reason.someLocked', { n: ctx.lockedCount });
	const needsOne = cannot ?? locked ?? (ctx.count ? undefined : t('reason.pickShape'));

	const combine: Action[] = (
		[
			['union', 'action.union'],
			['difference', 'action.difference'],
			['intersection', 'action.intersection'],
			['xor', 'action.xor']
		] as const
	).map(([op, key]) => ({
		id: `bool-${op}`,
		label: t(key),
		off: needsTwo(ctx),
		explain: t('explain.combine'),
		run: () => h.arrange(op)
	}));

	const path: Action[] = [
		{ id: 'path-offset', label: t('action.offset'), off: needsOne, run: () => h.arrange('offset') },
		{
			id: 'path-simplify',
			label: t('action.simplify'),
			off: needsOne,
			run: () => h.arrange('simplify')
		},
		{
			id: 'path-nest',
			label: t('action.nest'),
			off: needsTwo(ctx),
			explain: t('explain.nest'),
			run: () => h.arrange('nest')
		},
		{
			id: 'path-split',
			label: ctx.splittable.shapes
				? t('action.splitInto', { n: ctx.splittable.pieces })
				: t('action.split'),
			off: needsOne ?? (ctx.splittable.shapes ? undefined : t('reason.onePiece')),
			run: h.split
		},
		{
			// On the selection here; the bed's own menu has the same verb for the whole
			// design. Two shapes are the fewest that can lie on top of each other.
			id: 'path-duplicates',
			label: t('action.duplicates'),
			off: cannot ?? (ctx.count > 1 ? undefined : t('reason.needsTwo')),
			explain: t('duplicates.why'),
			run: h.duplicates
		},
		{ id: 'path-hatch', label: t('action.hatch'), off: needsOne, run: () => h.arrange('hatch') },
		{ id: 'path-wobble', label: t('action.wobble'), off: needsOne, run: () => h.arrange('wobble') }
	];

	// Existing layers as checkable rows — a shape can sit in more than one layer,
	// so these are checkmarks and not radio buttons. Below them the three "only
	// in" rows: those also take it *out* of the other layers, which is a different
	// verb than ticking a box.
	const layers: Action[] = [
		...ctx.layers.map((layer) => ({
			id: `layer-${layer.id}`,
			label: layer.label,
			on: layer.inside,
			off: needsOne,
			run: () => h.assignLayer(layer.id, !layer.inside)
		})),
		{
			id: 'layer-only-cut',
			label: t('action.onlyCut'),
			off: needsOne,
			run: () => h.onlyLayer('cut')
		},
		{
			id: 'layer-only-engrave',
			label: t('action.onlyEngrave'),
			off: needsOne,
			run: () => h.onlyLayer('engrave')
		},
		{
			id: 'layer-only-raster',
			label: t('action.onlyRaster'),
			off: needsOne,
			run: () => h.onlyLayer('raster')
		}
	];

	// Only when there is really something to choose between: one shape under the
	// pointer is not a choice, and a row that says what you already have is noise.
	const under: Submenu[] =
		ctx.under.length > 1
			? [
					{
						id: 'under-pointer',
						label: t('canvas.under'),
						items: ctx.under.map((shape) => ({
							id: `under-${shape.id}`,
							label: shape.label,
							on: shape.selected,
							run: () => h.selectOne(shape.id)
						}))
					}
				]
			: [];

	const menu: Menu = [
		...(under.length ? [{ items: under }] : []),
		{
			items: [
				{ id: 'cut', label: t('action.cut'), key: K('cut'), off: needsOne, run: h.cut },
				{ id: 'copy', label: t('action.copy'), key: K('copy'), off: needsOne, run: h.copy },
				{
					id: 'duplicate',
					label: t('action.duplicate'),
					key: K('duplicate'),
					off: needsOne,
					run: h.duplicate
				}
			]
		},
		{
			items: [
				{
					id: 'align',
					label: t('action.align'),
					grid: true,
					off: needsTwo(ctx),
					items: alignActions(ctx, h)
				},
				...arrangeActions(ctx, h),
				{
					// One row, two directions: "Lock" while something is still unlocked,
					// "Unlock" when everything picked is locked. A mixed selection locks
					// the rest, because that is what somebody who picked all of it means.
					id: allLocked(ctx) ? 'unlock' : 'lock',
					label: allLocked(ctx) ? t('action.unlock') : t('action.lock'),
					key: K('lock'),
					// Deliberately not `needsOne`: that one carries the locked reason, and
					// this is the single row a lock may never refuse.
					off: cannot ?? (ctx.count ? undefined : t('reason.pickShape')),
					run: () => h.setLocked(!allLocked(ctx))
				},
				{
					id: 'rotate',
					label: t('action.rotate'),
					off: needsOne,
					// The rows *inside* a submenu carry their own reason too. Disabling
					// only the parent is enough for the mouse, but not for the keyboard
					// and not for a second surface reading the same list — which is
					// exactly what this list exists for.
					items: [
						{
							id: 'rotate-left',
							label: t('action.rotateLeft'),
							key: K('rotateLeft'),
							off: needsOne,
							run: () => h.rotate(-90)
						},
						{
							id: 'rotate-right',
							label: t('action.rotateRight'),
							key: K('rotateRight'),
							off: needsOne,
							run: () => h.rotate(90)
						},
						{
							id: 'rotate-180',
							label: t('action.rotate180'),
							off: needsOne,
							run: () => h.rotate(180)
						}
					]
				}
			]
		},
		{
			items: [
				{ id: 'combine', label: t('action.combine'), off: needsTwo(ctx), items: combine },
				{ id: 'path', label: t('action.path'), off: needsOne, items: path },
				{
					id: 'corners',
					label: t('action.corners'),
					explain: t('explain.corners'),
					off: needsOne,
					run: h.corners
				},
				{
					id: 'bridges',
					label: ctx.bridges.has ? t('action.bridgesOff') : t('action.bridges'),
					key: K('bridges'),
					explain: ctx.bridges.has ? t('explain.bridgesOff') : t('explain.bridges'),
					// The panel has the two numbers; this row is the one-click default, because a
					// field nobody finds is not a feature. Four of 2 mm: one per side of a
					// rectangle, so the part hangs on four corners instead of tipping on one.
					off:
						needsOne ??
						(ctx.bridges.carries ? undefined : t('reason.noBridges')),
					run: () => h.bridges(!ctx.bridges.has)
				},
				{
					id: 'fill',
					label: ctx.filled ? t('action.unfill') : t('action.fill'),
					off: needsOne,
					explain: ctx.filled ? t('explain.unfill') : t('explain.fill'),
					run: () => h.fill(!ctx.filled)
				}
			]
		},
		{
			items: [
				{ id: 'layer', label: t('action.layer'), off: needsOne, items: layers },
				...(ctx.sheets.length
					? [
							{
								id: 'sheet',
								label: t('action.toSheet'),
								off: needsOne,
								items: ctx.sheets.map((sheet) => ({
									id: `sheet-${sheet.id}`,
									label: sheet.name,
									off: needsOne,
									run: () => h.toSheet(sheet.id)
								}))
							} as Submenu
						]
					: [])
			]
		}
	];

	// Only what applies to *this* kind of shape. A menu that always offers "Crop"
	// on a rectangle teaches you that half of it is grey.
	const special: (MenuItem | 'separator')[] = [];
	if (ctx.isText)
		special.push({ id: 'text', label: t('action.editText'), off: needsOne, run: h.editText });
	if (ctx.isImage) {
		special.push({
			id: 'crop',
			label: t('action.crop'),
			off: needsOne,
			explain: t('explain.crop'),
			run: h.crop
		});
		if (ctx.isCropped)
			special.push({ id: 'uncrop', label: t('action.uncrop'), off: needsOne, run: h.uncrop });
		special.push({
			id: 'vectorise',
			label: t('action.vectorise'),
			off: needsOne,
			explain: t('explain.vectorise'),
			run: h.vectorise
		});
	}
	if (special.length) menu.push({ items: special });

	menu.push({
		items: [
			{
				id: 'delete',
				label: t('action.delete'),
				key: K('delete'),
				off: needsOne,
				danger: true,
				run: h.remove
			}
		]
	});
	return menu;
}

/**
 * The menu on the canvas itself.
 *
 * This is about the view and the whole design, not about one shape. "Paste here"
 * is at the top because it is the reason you right-click here: you copied
 * something and you are pointing at where it should go.
 */
export function canvasMenu(
	ctx: Context,
	h: Handlers,
	at: { x: number; y: number } | null
): Menu {
	const cannot = mayWrite(ctx);
	return [
		{
			items: [
				{
					id: 'paste',
					label: at ? t('action.pasteHere') : t('action.paste'),
					key: K('paste'),
					off: cannot ?? (ctx.clipboard ? undefined : t('reason.clipboardEmpty')),
					explain: at ? t('explain.pasteHere') : undefined,
					run: () => h.paste(at ?? undefined)
				},
				{
					id: 'selectAll',
					label: t('action.selectAll'),
					key: K('selectAll'),
					off: ctx.empty ? t('reason.bedEmpty') : undefined,
					run: h.selectAll
				},
				{
					id: 'clearSelection',
					label: t('action.clearSelection'),
					key: 'Esc',
					off: ctx.count ? undefined : t('reason.nothingSelected'),
					run: h.clearSelection
				}
			]
		},
		{
			title: t('action.view'),
			items: [
				{
					id: 'zoom-all',
					label: t('action.zoomAll'),
					key: K('zoomAll'),
					off: ctx.empty ? t('reason.bedEmpty') : undefined,
					run: () => h.zoom('all')
				},
				{
					id: 'zoom-selection',
					label: t('action.zoomSelection'),
					key: K('zoomSelection'),
					off: ctx.count ? undefined : t('reason.nothingSelected'),
					run: () => h.zoom('selection')
				},
				{ id: 'zoom-bed', label: t('action.zoomBed'), key: K('zoomBed'), run: () => h.zoom('bed') },
				{
					id: 'zoom-hundred',
					label: t('action.zoomHundred'),
					key: K('zoomHundred'),
					run: () => h.zoom('hundred')
				},
				{
					// A workspace, so it opens a window of its own (the placement rule). Here
					// as well as in the pre-flight: the pre-flight is where you *want* it,
					// this is where you look for it while still drawing.
					id: 'cut-path',
					label: t('cutpath.show'),
					key: K('cutPath'),
					explain: t('cutpath.show.title'),
					off: ctx.empty ? t('reason.bedEmpty') : undefined,
					run: h.cutPath
				}
			]
		},
		{
			items: [
				{
					id: 'snap',
					label: t('action.snap'),
					on: ctx.snap,
					explain: t('explain.snap'),
					run: h.snap
				},
				{
					id: 'layerNumbers',
					label: t('action.layerNumbers'),
					on: ctx.layerNumbers,
					run: h.layerNumbers
				}
			]
		},
		{
			items: [
				{
					// The same verb as in the shape menu, and here it means the whole bed —
					// which is how you meet the problem: an import landed on top of what was
					// already there and nothing looks wrong.
					id: 'canvas-duplicates',
					label: t('action.duplicates'),
					off: cannot ?? (ctx.empty ? t('reason.bedEmpty') : undefined),
					explain: t('duplicates.why'),
					run: h.duplicates
				},
				{
					id: 'rescue',
					label: t('action.rescue'),
					off: cannot ?? (ctx.empty ? t('reason.bedEmpty') : undefined),
					explain: t('explain.rescue'),
					run: h.rescue
				}
			]
		}
	];
}

// ─── The menu on a node ──────────────────────────────────────────────────────
//
// Its own context, like the layer row's, because a node is not a selection of shapes: a
// verb here works on one point of one shape and its reasons are different ones. The
// keyboard reads the same rows, so Delete on a node cannot come to mean something else
// than the row that says "Remove this node".

export type NodeContext = {
	/** Which node this is about; -1 when none is in hand. */
	index: number;
	/** How many nodes the shape has. */
	count: number;
	/** Does the shape come back to where it started? */
	closed: boolean;
	/** The kind of the segment leaving this node, or null when there is none (the last
	 *  node of an open path). */
	kind: 'line' | 'quad' | 'cubic' | 'arc' | null;
	busy: boolean;
	may: boolean;
};

export type NodeHandlers = {
	addNode: () => void;
	removeNode: () => void;
	setKind: (kind: 'line' | 'quad') => void;
};

export function nodeMenu(ctx: NodeContext, h: NodeHandlers): Menu {
	const cannot =
		!ctx.may
			? t('reason.needsToken')
			: ctx.busy
				? t('reason.busy')
				: ctx.index < 0
					? t('reason.pickNode')
					: undefined;
	// A segment is what carries the curve, so without one there is nothing to bend. That
	// is the last node of an open path.
	const needsSegment = cannot ?? (ctx.kind ? undefined : t('reason.nodeIsLast'));
	// What is refused is what would leave no shape behind.
	const tooFew = ctx.closed
		? ctx.count <= 3
			? t('reason.nodeClosedThree')
			: undefined
		: ctx.count <= 2
			? t('reason.nodeOpenTwo')
			: undefined;
	// With no piece at all the row is disabled anyway, and then the offer ("a curve") reads
	// better than its undo ("straight"): there is nothing there yet to straighten.
	const straight = ctx.kind === 'line' || ctx.kind === null;

	return [
		{
			items: [
				{
					id: 'node-add',
					label: t('action.nodeAdd'),
					key: K('nodeAdd'),
					off: needsSegment,
					explain: t('explain.nodeAdd'),
					run: h.addNode
				},
				{
					// One row for both directions, like the fill row: a segment is either
					// straight or curved and the row says which way it will go.
					id: 'node-kind',
					label: straight ? t('action.nodeCurve') : t('action.nodeCorner'),
					key: K(straight ? 'nodeCurve' : 'nodeCorner'),
					off: needsSegment,
					explain: straight ? t('explain.nodeCurve') : undefined,
					run: () => h.setKind(straight ? 'quad' : 'line')
				}
			]
		},
		{
			items: [
				{
					id: 'node-remove',
					label: t('action.nodeRemove'),
					key: K('nodeRemove'),
					off: cannot ?? tooFew,
					danger: true,
					run: h.removeNode
				}
			]
		}
	];
}

// ─── The menu on a row in a list ─────────────────────────────────────────────

export type LayerContext = {
	label: string;
	shapeCount: number;
	burns: boolean;
	visible: boolean;
	first: boolean;
	last: boolean;
	/** Are there shapes selected to put into this layer? */
	selection: number;
	/** Is the whole selection already in it? */
	inside: boolean;
	may: boolean;
	locked?: string;
};

export type LayerHandlers = {
	selectShapes: () => void;
	putSelection: (inside: boolean) => void;
	toggleBurns: () => void;
	toggleVisible: () => void;
	up: () => void;
	down: () => void;
	openSettings: () => void;
	remove: () => void;
};

/**
 * Right-click on a layer.
 *
 * LightBurn has this too, with almost the same rows: on/off, hide, and select the
 * shapes on that layer. That last one existed nowhere in our app, and it is
 * exactly what you want while sorting out an imported drawing: see *what* is in a
 * layer by selecting it.
 */
export function layerMenu(ctx: LayerContext, h: LayerHandlers): Menu {
	const cannot = ctx.may ? undefined : t('reason.needsToken');
	const locked = ctx.locked;
	return [
		{
			items: [
				{
					id: 'layer-select',
					label: t('layerMenu.selectShapes', { n: ctx.shapeCount }),
					off: ctx.shapeCount ? undefined : t('reason.layerEmpty'),
					run: h.selectShapes
				},
				{
					id: 'layer-put',
					label: ctx.inside ? t('layerMenu.takeOut') : t('layerMenu.putIn'),
					off: cannot ?? locked ?? (ctx.selection ? undefined : t('reason.nothingSelected')),
					run: () => h.putSelection(!ctx.inside)
				}
			]
		},
		{
			items: [
				{
					id: 'layer-burns',
					label: t('layerMenu.burns'),
					on: ctx.burns,
					off: cannot ?? locked,
					explain: t('explain.burns'),
					run: h.toggleBurns
				},
				{
					id: 'layer-visible',
					label: t('layerMenu.visible'),
					on: ctx.visible,
					explain: t('explain.visible'),
					run: h.toggleVisible
				}
			]
		},
		{
			items: [
				{
					id: 'layer-up',
					label: t('layerMenu.earlier'),
					off: cannot ?? (ctx.first ? t('reason.alreadyFirst') : undefined),
					run: h.up
				},
				{
					id: 'layer-down',
					label: t('layerMenu.later'),
					off: cannot ?? (ctx.last ? t('reason.alreadyLast') : undefined),
					run: h.down
				},
				{
					id: 'layer-settings',
					label: t('layerMenu.settings'),
					explain: t('explain.layerSettings'),
					run: h.openSettings
				}
			]
		},
		{
			items: [
				{
					id: 'layer-remove',
					label: t('layerMenu.remove'),
					off: cannot ?? locked,
					explain: t('explain.layerRemove'),
					danger: true,
					run: h.remove
				}
			]
		}
	];
}
