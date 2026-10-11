/**
 * What removing one layer means for the shapes in it.
 *
 * Plain functions, so the question under a layer row and its test read the same
 * rule. They came with the report "I cannot delete layers that have objects in them":
 * cleaning up after an import is moving a layer's shapes into the layer they belong
 * with, and only then letting the layer go.
 */
import type { DesignElement, DesignOperation } from './design.svelte.ts';

type Layer = Pick<DesignOperation, 'id' | 'type' | 'color' | 'element_ids'>;

/**
 * The layer a layer's shapes most likely belong in: the same kind and the same
 * colour first (what an import that split one colour over two layers leaves), then
 * the same kind, then the first other layer. `null` when there is no other layer.
 */
export function mergeTarget(layer: Layer, others: Layer[]): string | null {
	const candidates = others.filter((o) => o.id !== layer.id);
	const colour = (c: string | null) => (c ?? '').toLowerCase().slice(0, 7);
	return (
		candidates.find((o) => o.type === layer.type && colour(o.color) === colour(layer.color))?.id ??
		candidates.find((o) => o.type === layer.type)?.id ??
		candidates[0]?.id ??
		null
	);
}

/**
 * How many of the layer's shapes are in no other layer — the ones that would stop
 * burning if the layer went without moving them. A shape can sit in several layers;
 * those stay where they also are.
 */
export function shapesOnlyIn(
	layer: Pick<DesignOperation, 'id' | 'element_ids'>,
	elements: Pick<DesignElement, 'id' | 'operation_ids'>[]
): number {
	const inLayer = new Set(layer.element_ids);
	return elements.filter(
		(e) => inLayer.has(e.id) && e.operation_ids.every((id) => id === layer.id)
	).length;
}
