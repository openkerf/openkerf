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
	KEYS,
	alignActions,
	arrangeActions,
	canvasMenu,
	comboOf,
	keyLabel,
	layerMenu,
	objectMenu,
	type Context,
	type Handlers,
	type LayerContext,
	type LayerHandlers,
	type Menu
} from '../src/lib/actions.ts';

const NOTHING = () => {};
const HANDLERS = new Proxy({}, { get: () => NOTHING }) as Handlers & LayerHandlers;

function context(over: Partial<Context> = {}): Context {
	return {
		count: 1,
		inGroup: false,
		isImage: false,
		isText: false,
		isCropped: false,
		filled: false,
		clipboard: 0,
		busy: false,
		may: true,
		layers: [],
		sheets: [],
		snap: true,
		layerNumbers: true,
		empty: false,
		splittable: { shapes: 0, pieces: 0 },
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
	const allowed = new Set([
		'ungroupAlt',
		'zoomAllOld',
		'zoomSelectionOld',
		'zoomSelectionLightburn'
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

test('a disabled row always says why', () => {
	for (const ctx of [
		context({ count: 0 }),
		context({ count: 1 }),
		context({ may: false }),
		context({ busy: true }),
		context({ count: 3, inGroup: true })
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
