/**
 * The action registry: one source for the menu, the action bar and the keyboard.
 *
 * Run: `node --test frontend/tests/actions.test.ts`
 *
 * What is pinned here is not the wording but the promise the file makes: that the
 * three surfaces cannot drift apart, that a disabled row always *says* why, and
 * that the shortcuts the browser takes for itself are not in it. That last one is
 * the trap: ⌘0 and ⌘− cannot be intercepted in Chrome, so a shortcut pointing at
 * them rescales the page instead of the bed.
 *
 * The labels are English because English is the source language and no reactive
 * module is loaded here — the same path the static build takes.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
	barMenu,
	writeRefusal,
	bridgesRefusal,
	KEYS,
	alignActions,
	arrangeActions,
	canvasMenu,
	comboOf,
	keyLabel,
	layerMenu,
	nodeMenu,
	objectMenu,
	type Context,
	type Handlers,
	type LayerContext,
	type LayerHandlers,
	type NodeContext,
	type NodeHandlers,
	type Menu
} from '../src/lib/actions.ts';

const NOTHING = () => {};
const HANDLERS = new Proxy({}, { get: () => NOTHING }) as Handlers &
	LayerHandlers &
	NodeHandlers;

function nodeCtx(over: Partial<NodeContext> = {}): NodeContext {
	return { index: 0, count: 5, closed: true, kind: 'line', busy: false, may: true, ...over };
}

function context(over: Partial<Context> = {}): Context {
	return {
		count: 1,
		inGroup: false,
		lockedCount: 0,
		isImage: false,
		isText: false,
		isCropped: false,
		filled: false,
		bridges: { carries: true, has: false },
		clipboard: 0,
		busy: false,
		may: true,
		offline: false,
		layers: [],
		sheets: [],
		snap: true,
		layerNumbers: true,
		empty: false,
		splittable: { shapes: 0, pieces: 0 },
		under: [],
		columns: [],
		once: false,
		...over
	};
}

/** Every row of a menu, submenus included. */
function rows(menu: Menu): any[] {
	const out: any[] = [];
	for (const group of menu)
		for (const item of group.items) {
			if (item === 'separator') continue;
			out.push(item);
			if ('items' in item) out.push(...item.items);
		}
	return out;
}

test('the shortcuts leave the browser zoom alone', () => {
	// ⌘0, ⌘+ and ⌘− cannot be intercepted in Chrome. A shortcut pointing at them
	// rescales the page instead of the bed.
	const uninterceptable = ['mod+0', 'mod+=', 'mod+-', 'mod+shift+0'];
	for (const combo of Object.values(KEYS))
		assert.ok(
			!uninterceptable.includes(combo),
			`${combo} is a shortcut of the browser itself and does not belong here`
		);
});

test('every shortcut is unique, except where that is on purpose', () => {
	const seen = new Map<string, string>();
	// Two keys for one operation is allowed: ⌘⇧G and ⌘U both ungroup, and the zoom
	// keys keep their older variant.
	// And Delete deliberately means two things: with a node in hand the node tool takes it
	// (`nodeRemove`), otherwise it throws the shape away. The page decides in that order,
	// so the two can never both fire.
	const allowed = new Set([
		'ungroupAlt',
		'zoomAllOld',
		'zoomSelectionOld',
		'zoomSelectionLightburn',
		'nodeRemove'
	]);
	for (const [name, combo] of Object.entries(KEYS)) {
		if (allowed.has(name)) continue;
		assert.ok(!seen.has(combo), `${combo} sits on both ${seen.get(combo)} and ${name}`);
		seen.set(combo, name);
	}
});

test('a keystroke reads as the combo that is in the table', () => {
	const read = (over: Record<string, unknown>) =>
		comboOf({
			metaKey: false,
			ctrlKey: false,
			shiftKey: false,
			altKey: false,
			key: 'a',
			...over
		} as KeyboardEvent);
	assert.equal(read({ metaKey: true, key: 'c' }), 'mod+c');
	assert.equal(read({ ctrlKey: true, key: 'C' }), 'mod+c');
	assert.equal(read({ metaKey: true, shiftKey: true, key: 'z' }), 'mod+shift+z');
	assert.equal(read({ key: 'Backspace' }), 'delete');
	// Shift+1 gives "!" on a US layout; both must yield the same combo, otherwise
	// the shortcut works on one keyboard layout and not on the next.
	assert.equal(read({ shiftKey: true, key: '!' }), 'shift+1');
	assert.equal(read({ shiftKey: true, key: '1' }), 'shift+1');
});

test('what lies under the pointer is offered as a list, in order', () => {
	// The pile as the canvas hands it over: topmost first.
	const under = [
		{ id: 'a', label: 'Rectangle', selected: true },
		{ id: 'b', label: 'Circle', selected: false },
		{ id: 'c', label: 'Text “Openkerf”', selected: false }
	];
	const group = rows(objectMenu(context({ under }), HANDLERS)).find(
		(row) => row.id === 'under-pointer'
	);

	assert.ok(group, 'no list of what is under the pointer');
	assert.deepEqual(
		group.items.map((row: { label: string }) => row.label),
		['Rectangle', 'Circle', 'Text “Openkerf”']
	);
	// The one you have now is ticked; without that the list says nothing about
	// where you are in the pile.
	assert.deepEqual(
		group.items.map((row: { on?: boolean }) => Boolean(row.on)),
		[true, false, false]
	);
});

test('one shape under the pointer is not a choice', () => {
	for (const under of [[], [{ id: 'a', label: 'Rectangle', selected: true }]]) {
		const rows_ = rows(objectMenu(context({ under }), HANDLERS));
		assert.equal(
			rows_.find((row) => row.id === 'under-pointer'),
			undefined,
			`a list appeared for ${under.length} shape(s) under the pointer`
		);
	}
});

test('picking from that list selects exactly that shape', () => {
	const picked: string[] = [];
	const handlers = { ...HANDLERS, selectOne: (id: string) => picked.push(id) } as Handlers;
	const under = [
		{ id: 'top', label: 'Rectangle', selected: true },
		{ id: 'below', label: 'Circle', selected: false }
	];

	const group = rows(objectMenu(context({ under }), handlers)).find(
		(row) => row.id === 'under-pointer'
	);
	group.items[1].run();

	assert.deepEqual(picked, ['below']);
});

test('a disabled row always says why', () => {
	for (const ctx of [
		context({ count: 0 }),
		context({ count: 1 }),
		context({ may: false }),
		context({ busy: true }),
		context({ count: 3, inGroup: true }),
		// The rows a text brings with it, in all three of their states: no list to read
		// from, one column, and a submenu of several.
		context({ count: 0, isText: true }),
		context({ count: 1, isText: true, columns: ['name'] }),
		context({ count: 1, isText: true, columns: ['name', 'city'], may: false })
	])
		for (const row of [
			...rows(objectMenu(ctx, HANDLERS)),
			...rows(canvasMenu(ctx, HANDLERS, null))
		])
			if ('off' in row && row.off !== undefined)
				assert.ok(
					typeof row.off === 'string' && row.off.length > 3,
					`"${row.label}" is disabled without a reason`
				);
});

test('without a selection nothing can happen to a shape', () => {
	for (const row of rows(objectMenu(context({ count: 0 }), HANDLERS)))
		assert.ok(row.off, `"${row.label}" is usable without anything being selected`);
});

test('grouping asks for two shapes, distributing for three', () => {
	const one = objectMenu(context({ count: 1 }), HANDLERS);
	const two = objectMenu(context({ count: 2 }), HANDLERS);
	const three = objectMenu(context({ count: 3 }), HANDLERS);
	const find = (menu: Menu, id: string) => rows(menu).find((r) => r.id === id);

	assert.ok(find(one, 'group').off, 'grouping works with one shape');
	assert.ok(!find(two, 'group').off, 'grouping does not work with two shapes');
	assert.ok(find(two, 'align-spaceh').off, 'distributing already works with two shapes');
	assert.ok(!find(three, 'align-spaceh').off, 'distributing does not work with three shapes');
	assert.ok(!find(two, 'align-left').off, 'aligning does not work with two shapes');
});

test('ungrouping only works when the selection is in a group', () => {
	const find = (ctx: Context) => rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'ungroup');
	assert.ok(find(context({ count: 2 })).off);
	assert.ok(!find(context({ count: 2, inGroup: true })).off);
});

test('pasting is impossible with an empty clipboard, and says so', () => {
	const empty = rows(canvasMenu(context(), HANDLERS, null)).find((r) => r.id === 'paste');
	assert.match(empty.off, /clipboard/i);
	const full = rows(canvasMenu(context({ clipboard: 2 }), HANDLERS, null)).find(
		(r) => r.id === 'paste'
	);
	assert.equal(full.off, undefined);
});

test('"paste here" is only called that when a place comes with it', () => {
	const ctx = context({ clipboard: 1 });
	const withPoint = rows(canvasMenu(ctx, HANDLERS, { x: 10, y: 10 })).find((r) => r.id === 'paste');
	const without = rows(canvasMenu(ctx, HANDLERS, null)).find((r) => r.id === 'paste');
	assert.equal(withPoint.label, 'Paste here');
	assert.equal(without.label, 'Paste');
});

test('splitting promises the number that really comes out', () => {
	const find = (ctx: Context) => rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'path-split');
	const nothing = find(context({ splittable: { shapes: 0, pieces: 0 } }));
	assert.ok(nothing.off, 'splitting is enabled while there is nothing to split');
	const some = find(context({ splittable: { shapes: 1, pieces: 7 } }));
	assert.equal(some.off, undefined);
	assert.match(some.label, /7/);
});

test('the fill row says what it is going to do, not what it is', () => {
	const find = (ctx: Context) => rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'fill');
	assert.match(find(context({ filled: false })).label, /^Fill/);
	assert.match(find(context({ filled: true })).label, /remove/i);
});

test('only what applies to this kind of shape is in the menu', () => {
	const plain = rows(objectMenu(context(), HANDLERS)).map((r) => r.id);
	assert.ok(!plain.includes('crop'), 'a rectangle offers cropping');
	assert.ok(!plain.includes('text'), 'a rectangle offers editing text');

	const image = rows(objectMenu(context({ isImage: true }), HANDLERS)).map((r) => r.id);
	assert.ok(image.includes('crop'));
	assert.ok(image.includes('vectorise'));
	assert.ok(!image.includes('uncrop'), 'undoing the crop is possible without a crop');

	const cropped = rows(objectMenu(context({ isImage: true, isCropped: true }), HANDLERS)).map(
		(r) => r.id
	);
	assert.ok(cropped.includes('uncrop'));

	const text = rows(objectMenu(context({ isText: true }), HANDLERS)).map((r) => r.id);
	assert.ok(text.includes('text'));
});

test('delete is at the bottom, and is the only red row', () => {
	const menu = objectMenu(context(), HANDLERS);
	const last = menu[menu.length - 1].items;
	assert.equal(last.length, 1);
	assert.equal((last[0] as any).id, 'delete');
	assert.deepEqual(
		rows(menu)
			.filter((r) => r.danger)
			.map((r) => r.id),
		['delete']
	);
});

test('the action bar and the menu share the same operations', () => {
	const ctx = context({ count: 3 });
	const bar = [...alignActions(ctx, HANDLERS), ...arrangeActions(ctx, HANDLERS)].map((a) => a.id);
	const menu = rows(objectMenu(ctx, HANDLERS)).map((r) => r.id);
	for (const id of bar)
		assert.ok(menu.includes(id), `${id} is in the action bar but not in the menu`);
});

test('an existing layer can be ticked, and "only in" sits below it', () => {
	const ctx = context({
		layers: [
			{ id: 'op1', label: 'Cut', inside: true },
			{ id: 'op2', label: 'Engrave', inside: false }
		]
	});
	const layer = rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'layer');
	const names = layer.items.map((i: any) => i.label);
	assert.deepEqual(names.slice(0, 2), ['Cut', 'Engrave']);
	assert.equal(layer.items[0].on, true);
	assert.equal(layer.items[1].on, false);
	assert.ok(names.some((n: string) => /Only in the cut layer/.test(n)));
});

test('a layer menu refuses what a test-grid layer does not allow', () => {
	const ctx: LayerContext = {
		label: 'Speed 12',
		shapeCount: 4,
		burns: true,
		visible: true,
		first: true,
		last: false,
		selection: 2,
		inside: false,
		may: true,
		locked: 'This layer belongs to a test grid'
	};
	const menu = layerMenu(ctx, HANDLERS);
	const find = (id: string) => rows(menu).find((r) => r.id === id);
	assert.match(find('layer-remove').off, /test grid/);
	assert.match(find('layer-burns').off, /test grid/);
	// Selecting the shapes is always allowed: it changes nothing about the job.
	assert.equal(find('layer-select').off, undefined);
	// The first layer cannot burn any earlier, and it says so.
	assert.match(find('layer-up').off, /first/);
});

test('the shortcut on a row is the same as the one in the table', () => {
	const menu = objectMenu(context({ count: 2, clipboard: 1 }), HANDLERS);
	const find = (id: string) => rows(menu).find((r) => r.id === id);
	assert.equal(find('copy').key, keyLabel(KEYS.copy));
	assert.equal(find('group').key, keyLabel(KEYS.group));
	assert.equal(find('delete').key, keyLabel(KEYS.delete));
});

test('the bridges row offers them, and takes them away once they are there', () => {
	// One row for both directions, like the fill row: what it says is what the selection
	// is not yet. A separate "remove" row would be grey nine times out of ten.
	const off = rows(objectMenu(context(), HANDLERS)).find((r) => r.id === 'bridges');
	assert.equal(off.label, 'Add bridges (4 × 2 mm)');
	assert.equal(off.off, undefined);
	assert.equal(off.key, keyLabel(KEYS.bridges));

	const on = rows(
		objectMenu(context({ bridges: { carries: true, has: true } }), HANDLERS)
	).find((r) => r.id === 'bridges');
	assert.equal(on.label, 'Remove bridges');
});

test('a shape that carries no bridges says so instead of going quietly grey', () => {
	const row = rows(
		objectMenu(context({ bridges: { carries: false, has: false } }), HANDLERS)
	).find((r) => r.id === 'bridges');

	assert.equal(row.off, 'A line, text or an image carries no bridges');
});

// ─── A series: putting a column into a text, and the jig frame ───────────────

test('one column in the list is a row of its own, not a submenu of one', () => {
	const ctx = context({ isText: true, columns: ['name'] });
	const found = rows(objectMenu(ctx, HANDLERS));
	// The parent-and-submenu form is what more than one column earns; with one there is
	// nothing to choose between, so the row is the action and names the column.
	assert.equal(found.find((row) => row.id === 'insert-column'), undefined);
	const row = found.find((r) => r.id === 'column-name');
	assert.equal(row.label, 'Insert name');
	assert.equal(row.off, undefined);
	assert.ok(!('items' in row), 'a single column still opened a submenu');
});

test('more than one column becomes a submenu, and every row in it carries its own reason', () => {
	const ctx = context({ isText: true, columns: ['name', 'city'], count: 0 });
	const parent = rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'insert-column');

	assert.equal(parent.label, 'Insert a column');
	assert.deepEqual(
		parent.items.map((row: { id: string; label: string }) => [row.id, row.label]),
		[
			['column-name', 'name'],
			['column-city', 'city']
		]
	);
	// Disabling only the parent is enough for the mouse and not for the keyboard or for
	// any second surface reading this list — which is the reason this list exists.
	assert.ok(parent.off, 'the parent row is usable with nothing selected');
	for (const row of parent.items)
		assert.ok(row.off, `"${row.label}" is usable with nothing selected`);
});

test('with no list attached the row still stands there and says why', () => {
	const row = rows(objectMenu(context({ isText: true, columns: [] }), HANDLERS)).find(
		(r) => r.id === 'insert-column'
	);

	assert.equal(row.label, 'Insert a column');
	assert.equal(row.off, 'No list is attached in the Series window');
});

test('a column only goes into a text, and never into a rectangle', () => {
	const plain = rows(objectMenu(context({ columns: ['name', 'city'] }), HANDLERS)).map(
		(r) => r.id
	);
	assert.ok(!plain.includes('insert-column'), 'a rectangle offers to insert a column');
	assert.ok(!plain.includes('column-name'), 'a rectangle offers a column of the list');
});

test('picking a column asks for that column and no other', () => {
	const asked: string[] = [];
	const handlers = { ...HANDLERS, insertColumn: (c: string) => asked.push(c) } as Handlers;
	const ctx = context({ isText: true, columns: ['name', 'city'] });
	const parent = rows(objectMenu(ctx, handlers)).find((r) => r.id === 'insert-column');

	parent.items[1].run();
	// And the one-column form runs the same handler with the same argument, so the two
	// wordings cannot come to mean two different things.
	rows(objectMenu(context({ isText: true, columns: ['city'] }), handlers))
		.find((r) => r.id === 'column-city')
		.run();

	assert.deepEqual(asked, ['city', 'city']);
});

test('"burn only once" is one row that says which way it is going', () => {
	const find = (ctx: Context) => rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'burn-once');
	assert.equal(find(context()).label, 'Burn only once');
	assert.equal(find(context({ once: true })).label, 'Burn on every plate');

	// A lock stops an accident with the geometry, and this changes none — the API leaves
	// it unguarded for that reason, so the row may not refuse where the API does not.
	assert.equal(find(context({ count: 1, lockedCount: 1 })).off, undefined);
	assert.equal(find(context({ count: 0 })).off, 'Pick a shape first');
});

test('the flag flips to the other side of what the selection already is', () => {
	const asked: boolean[] = [];
	const handlers = { ...HANDLERS, burnOnce: (on: boolean) => asked.push(on) } as Handlers;
	rows(objectMenu(context(), handlers)).find((r) => r.id === 'burn-once').run();
	rows(objectMenu(context({ once: true }), handlers)).find((r) => r.id === 'burn-once').run();
	assert.deepEqual(asked, [true, false]);
});

test('the bed itself has a door to the series, and no key on it', () => {
	const row = rows(canvasMenu(context(), HANDLERS, null)).find((r) => r.id === 'series');

	assert.equal(row.label, 'Set up a series');
	assert.equal(row.key, undefined);
	assert.equal(row.off, undefined);
	// The tool rail greys its own button on the same condition. Two doors to one room
	// that disagree about whether it is open is worse than either.
	assert.equal(
		rows(canvasMenu(context({ may: false }), HANDLERS, null)).find((r) => r.id === 'series').off,
		'Requires a token'
	);
});

// ─── The menu on a node (P1) ─────────────────────────────────────────────────

test('a node with no piece after it cannot be bent or split', () => {
	// The last node of an open path: there is no segment leaving it, so there is nothing
	// to add a node to and nothing to curve.
	const menu = nodeMenu(nodeCtx({ closed: false, kind: null }), HANDLERS);
	const find = (id: string) => rows(menu).find((r) => r.id === id);

	assert.match(find('node-add').off, /no piece after it/);
	assert.match(find('node-kind').off, /no piece after it/);
	// Removing it is exactly what you do want with a node like that.
	assert.equal(find('node-remove').off, undefined);
});

test('the one row says which way the piece will go', () => {
	const straight = nodeMenu(nodeCtx({ kind: 'line' }), HANDLERS);
	const curved = nodeMenu(nodeCtx({ kind: 'quad' }), HANDLERS);
	const label = (menu: Menu) => rows(menu).find((r) => r.id === 'node-kind').label;

	assert.match(label(straight), /curve/);
	assert.match(label(curved), /straight/);
	// And the key follows the direction, so what the row does and what it says stay
	// together.
	assert.equal(rows(straight).find((r) => r.id === 'node-kind').key, keyLabel(KEYS.nodeCurve));
	assert.equal(rows(curved).find((r) => r.id === 'node-kind').key, keyLabel(KEYS.nodeCorner));
});

test('what would leave no shape behind says so instead of failing', () => {
	const closed = nodeMenu(nodeCtx({ closed: true, count: 3 }), HANDLERS);
	const open = nodeMenu(nodeCtx({ closed: false, count: 2 }), HANDLERS);
	const off = (menu: Menu) => rows(menu).find((r) => r.id === 'node-remove').off;

	assert.match(off(closed), /three nodes/);
	assert.match(off(open), /two nodes/);
	// One more and it is allowed again.
	assert.equal(rows(nodeMenu(nodeCtx({ count: 4 }), HANDLERS)).find((r) => r.id === 'node-remove').off, undefined);
});

test('without a node in hand every row says to pick one', () => {
	const menu = nodeMenu(nodeCtx({ index: -1 }), HANDLERS);
	for (const row of rows(menu)) assert.match(row.off, /Click a node/);
});

test('a read-only session cannot edit nodes either', () => {
	const menu = nodeMenu(nodeCtx({ may: false }), HANDLERS);
	for (const row of rows(menu)) assert.match(row.off, /token/);
});

test('the bridge control in the panel refuses in the same words as the menu row', () => {
	// `actions.ts` says it itself: "A grey button without a reason is a riddle", and
	// `a disabled row always says why` above enforces it — but only for rows that come
	// out of `actions.ts`. The panel has its own control for this same verb, and it
	// switched off on three conditions (`!canEdit || !bridges.carries || edits.busy`)
	// without one word. Measured in the panel: a checkbox that goes pale and says
	// nothing, six pixels from a menu that explains itself.
	//
	// So the reason is a function now, and this pins that both readers get the same
	// sentence. Whoever adds a third reader adds it here.
	for (const over of [
		{},
		{ may: false },
		{ busy: true },
		{ count: 0 },
		{ lockedCount: 1 },
		{ bridges: { carries: false, has: false } }
	] as Partial<Context>[]) {
		const ctx = context(over);
		const row = rows(objectMenu(ctx, HANDLERS)).find((r) => r.id === 'bridges');
		assert.equal(
			bridgesRefusal(ctx),
			row.off,
			`the panel and the menu disagree about ${JSON.stringify(over)}`
		);
	}
	// And it really does say something in the case the panel used to keep quiet about.
	assert.equal(
		bridgesRefusal(context({ bridges: { carries: false, has: false } })),
		'A line, text or an image carries no bridges'
	);
	assert.equal(bridgesRefusal(context()), undefined, 'nothing in the way, nothing to say');
});

test('"More" opens what a right-click would open in the same situation', () => {
	// The button's tooltip promises "All operations — or right-click a shape", and it
	// opened `objectMenu` whatever the state. Measured with nothing selected: 19 rows,
	// 19 of them grey. Right-clicking the bed at that same moment gave 13 rows of which
	// 10 worked — Select all, the four zoom rows, Show cut path, Series, Snap, Remove
	// duplicates, Put everything on the bed. None of those ten was reachable from the
	// bar, from a button that says it has them all.
	//
	// So the bar asks the same question the canvas asks: is anything selected?
	const nothing = rows(barMenu(context({ count: 0 }), HANDLERS));
	assert.ok(
		nothing.some((r) => !r.off),
		'with nothing selected the bar still offers nothing that can be done'
	);
	assert.ok(
		nothing.some((r) => r.id === 'selectAll'),
		'the rows about the whole design are missing'
	);

	// With a selection it is the menu for that selection, exactly as before.
	const chosen = rows(barMenu(context({ count: 2 }), HANDLERS)).map((r) => r.id);
	const direct = rows(objectMenu(context({ count: 2 }), HANDLERS)).map((r) => r.id);
	assert.deepEqual(chosen, direct);
});

test('every workspace has a door in the menu, not only two of the five', () => {
	// `actions.ts` is where a handling is described once, and the menu, the bar and the
	// keyboard read from it. Two of the five workspaces were in there — the cut path and
	// the series — and the material library, the test grid, the generators and the
	// clipart were reachable from the tool rail alone. So the same kind of door was in
	// two places for two of them and in one place for four.
	const ids = rows(canvasMenu(context({ count: 0 }), HANDLERS, null)).map((r) => r.id);
	for (const id of ['cut-path', 'series', 'library', 'test-grid', 'generators', 'clipart']) {
		assert.ok(ids.includes(id), `no row for ${id}`);
	}
});

test('a workspace that writes says so when this session may not', () => {
	// The same rule the series row already had: everything worth opening those windows
	// for is a write, and the rail greys its button on the same condition. Two doors to
	// one room that disagree about whether it is open is worse than either.
	const off = rows(canvasMenu(context({ count: 0, may: false }), HANDLERS, null));
	for (const id of ['library', 'test-grid', 'generators', 'clipart', 'series']) {
		assert.equal(off.find((r) => r.id === id).off, 'Requires a token', `${id} stayed open`);
	}
});

test('with no server behind it, a write says so before you press it', () => {
	// Measured with the engine killed under a running page: the tool rail stayed 0 of 14
	// disabled and the action bar stayed 12 of 15 — and those twelve were grey because
	// nothing was selected, not because the server had gone. So every drawing control
	// stayed live while nothing it did could arrive; the only sign was a card in the
	// corner.
	//
	// The top bar has had the sentence for this since gap E1, about its own stop button:
	// "No connection to OpenKerf — this button will not arrive." One text, one key, and
	// now every write reads it.
	//
	// The order matters. No server outranks no token: with the engine gone, "requires a
	// token" is true and useless — there is nothing to send the token to.
	assert.equal(writeRefusal({ may: true, busy: false, offline: true }), 'No connection to OpenKerf — this button will not arrive.');
	assert.equal(writeRefusal({ may: false, busy: false, offline: true }), 'No connection to OpenKerf — this button will not arrive.');
	assert.equal(writeRefusal({ may: false, busy: false, offline: false }), 'Requires a token');
	assert.equal(writeRefusal({ may: true, busy: true, offline: false }), 'Another operation is still running');
	assert.equal(writeRefusal({ may: true, busy: false, offline: false }), undefined);

	// And the menu rows carry it, because they read the same function.
	const row = rows(objectMenu(context({ offline: true }), HANDLERS)).find((r) => r.id === 'bridges');
	assert.equal(row.off, 'No connection to OpenKerf — this button will not arrive.');
});
