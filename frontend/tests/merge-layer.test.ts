/**
 * Removing a layer that still holds shapes: where they go, and how many would stop
 * burning.
 *
 * Run: `node --test frontend/tests/merge-layer.test.ts`.
 *
 * The report: "I cannot delete layers that have objects in them — no message, it simply
 * doesn't do it." The API removed the layer fine (200); the panel drew its question
 * inside the layer's settings fold, so *Remove layer* from the row menu showed nothing.
 * The question now stands under the row, and for a layer with shapes it offers to move
 * them first. These are the two rules that question reads; the source check at the end
 * holds the question out of the fold.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mergeTarget, shapesOnlyIn } from '../src/lib/layers.ts';

const layer = (id: string, type: string, color: string | null, element_ids: string[] = []) => ({
	id,
	type,
	color,
	element_ids
});

test('the shapes go to the other layer of the same kind and colour first', () => {
	const dup = layer('C2', 'op cut', '#ff0000');
	const list = [
		layer('E1', 'op engrave', '#ff0000'),
		layer('C1', 'op cut', '#0000ff'),
		layer('C3', 'op cut', '#FF0000ff'),
		dup
	];
	assert.equal(mergeTarget(dup, list), 'C3');
});

test('then the same kind, then any other layer, then none', () => {
	const dup = layer('C2', 'op cut', '#ff0000');
	assert.equal(mergeTarget(dup, [layer('E1', 'op engrave', '#ff0000'), layer('C1', 'op cut', '#00ff00'), dup]), 'C1');
	assert.equal(mergeTarget(dup, [layer('E1', 'op engrave', '#ff0000'), dup]), 'E1');
	assert.equal(mergeTarget(dup, [dup]), null);
});

test('only the shapes in no other layer would stop burning', () => {
	const op = layer('C2', 'op cut', null, ['a', 'b', 'c']);
	const elements = [
		{ id: 'a', operation_ids: ['C2'] },
		{ id: 'b', operation_ids: ['C2', 'E1'] },
		{ id: 'c', operation_ids: ['C2'] },
		{ id: 'd', operation_ids: [] }
	];
	assert.equal(shapesOnlyIn(op, elements), 2);
});

test('the removal question is not drawn inside the settings fold', () => {
	const source = readFileSync(
		new URL('../src/lib/components/DesignPanel.svelte', import.meta.url),
		'utf8'
	);
	const question = source.indexOf('{#if canEdit && confirmDrop === op.id}');
	assert.ok(question > 0, 'the question has its own block');
	// The fold is `{#if open}` inside `{#if canEdit && (open || colourOpen)}`; the
	// question must come after that block has closed, still inside the row loop.
	const fold = source.lastIndexOf('{#if canEdit && (open || colourOpen)}', question);
	const between = source.slice(fold, question);
	const opened = (between.match(/\{#if /g) ?? []).length;
	const closed = (between.match(/\{\/if\}/g) ?? []).length;
	assert.equal(opened, closed, 'the question sits inside an {#if} of the fold');
	// And the row menu opens the same question.
	assert.match(source, /remove: \(\) => askDrop\(op\.id\)/);
});
