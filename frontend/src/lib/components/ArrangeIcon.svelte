<script lang="ts">
	/**
	 * De pictogrammen voor schikken: aligning, verdelen, spiegelen, groeperen
	 * en combineren.
	 *
	 * They are all deliberately drawn to the same grammar, because that is what makes an
	 * icon quicker to read than a word: a **thick line** is the axis something arranges
	 * itself to, **open rectangles** are the shapes that move, and a **dotted line** is a
	 * mirror axis — an axis nothing comes to rest against, but that is looked through.
	 * Anybody who sees the grammar once reads the rest without a tooltip.
	 *
	 * Inkscape, Illustrator and LightBurn use the same grammar (see
	 * `Icon-Align-All.png` in their documentation). Deviating would mean a user coming
	 * from one of those three has to learn to look again.
	 */
	let { name, size = 20 }: { name: string; size?: number } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.6"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#if name === 'align-left'}
		<path d="M3 3v18" stroke-width="2.4" />
		<rect x="6" y="5" width="15" height="5.5" rx="1" />
		<rect x="6" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-centerh'}
		<path d="M12 2v20" stroke-width="2.4" stroke-dasharray="0 0" />
		<rect x="3.5" y="5" width="17" height="5.5" rx="1" />
		<rect x="7.5" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-right'}
		<path d="M21 3v18" stroke-width="2.4" />
		<rect x="3" y="5" width="15" height="5.5" rx="1" />
		<rect x="9" y="13.5" width="9" height="5.5" rx="1" />
	{:else if name === 'align-top'}
		<path d="M3 3h18" stroke-width="2.4" />
		<rect x="5" y="6" width="5.5" height="15" rx="1" />
		<rect x="13.5" y="6" width="5.5" height="9" rx="1" />
	{:else if name === 'align-centerv'}
		<path d="M2 12h20" stroke-width="2.4" />
		<rect x="5" y="3.5" width="5.5" height="17" rx="1" />
		<rect x="13.5" y="7.5" width="5.5" height="9" rx="1" />
	{:else if name === 'align-bottom'}
		<path d="M3 21h18" stroke-width="2.4" />
		<rect x="5" y="3" width="5.5" height="15" rx="1" />
		<rect x="13.5" y="9" width="5.5" height="9" rx="1" />
	{:else if name === 'space-h'}
		<!-- Distribute: the outer two are fixed (thick edges), the middle one moves until
		     the gaps are equal. The shapes are wider than in the first version — three
		     narrow bars read as dots. -->
		<path d="M2 5v14M22 5v14" stroke-width="2.4" />
		<rect x="4.5" y="7.5" width="4.5" height="9" rx="1" />
		<rect x="12" y="7.5" width="4.5" height="9" rx="1" />
	{:else if name === 'space-v'}
		<path d="M5 2h14M5 22h14" stroke-width="2.4" />
		<rect x="7.5" y="4.5" width="9" height="4.5" rx="1" />
		<rect x="7.5" y="12" width="9" height="4.5" rx="1" />
	{:else if name === 'mirror-h'}
		<!-- Mirror: the dotted line is the axis and deliberately sticks out above and
		     below the shapes, so that it reads as an axis and not as an edge. The left
		     half is filled: then you see *which* side flips over. Drawn smaller than the
		     first version, because two triangles against each other read as one dark
		     diamond. -->
		<path d="M12 2v20" stroke-dasharray="3 3" />
		<path d="M9 6.5 4 12l5 5.5Z" fill="currentColor" stroke="none" />
		<path d="M15 6.5 20 12l-5 5.5Z" />
	{:else if name === 'mirror-v'}
		<path d="M2 12h20" stroke-dasharray="3 3" />
		<path d="M6.5 9 12 4l5.5 5Z" fill="currentColor" stroke="none" />
		<path d="M6.5 15 12 20l5.5-5Z" />
	{:else if name === 'group'}
		<!-- Group versus ungroup: the difference has to be in the *shape*, not in a
		     little dash. Group = two shapes touching each other, with one frame around
		     them. Ungroup = the same two shapes apart, without a frame, with arrows
		     pointing away from each other. -->
		<rect x="2.5" y="2.5" width="19" height="19" rx="2.5" stroke-dasharray="4 3" />
		<rect x="6" y="6" width="7.5" height="7.5" rx="1" />
		<rect x="11" y="11" width="7" height="7" rx="1" />
	{:else if name === 'ungroup'}
		<rect x="2" y="2" width="8.5" height="8.5" rx="1" />
		<rect x="13.5" y="13.5" width="8.5" height="8.5" rx="1" />
		<path d="M13.5 10.5 21 3" />
		<path d="M15.5 3H21v5.5" />
		<!-- Boolean: two squares overlapping each other, with the result hatched. The hole
		     is cut out of the shape with `fill-rule="evenodd"` and not painted over with a
		     patch in the background colour — that last approach only holds as long as the
		     button does not change colour, and on hover it does. -->
	{:else if name === 'union'}
		<path
			d="M3 3h12v6h6v12H9v-6H3Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M3 3h12v12H3Z" opacity="0.45" />
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M3 3h12v6h6v12H9v-6H3Z" />
	{:else if name === 'difference'}
		<path
			fill-rule="evenodd"
			d="M3 3h12v12H3Zm6 6h6v6H9Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M3 3h12v12H3Z" />
	{:else if name === 'intersection'}
		<path d="M9 9h6v6H9Z" fill="currentColor" opacity="0.45" stroke="none" />
		<path d="M3 3h12v12H3Z" opacity="0.45" />
		<path d="M9 9h12v12H9Z" opacity="0.45" />
		<path d="M9 9h6v6H9Z" />
	{:else if name === 'xor'}
		<path
			fill-rule="evenodd"
			d="M3 3h12v6h6v12H9v-6H3Zm6 6h6v6H9Z"
			fill="currentColor"
			opacity="0.3"
			stroke="none"
		/>
		<path d="M3 3h12v6h6v12H9v-6H3Z" />
		<path d="M9 9h6v6H9Z" />
	{:else if name === 'rotate-ccw'}
		<path d="M4 9a8 8 0 1 1 .6 6" />
		<path d="M3.5 4v5h5" />
	{:else if name === 'rotate-cw'}
		<path d="M20 9a8 8 0 1 0-.6 6" />
		<path d="M20.5 4v5h-5" />
	{:else if name === 'undo'}
		<path d="M4 8h11a5 5 0 0 1 0 10H8" />
		<path d="M8 4 4 8l4 4" />
	{:else if name === 'redo'}
		<path d="M20 8H9a5 5 0 0 0 0 10h7" />
		<path d="m16 4 4 4-4 4" />
	{:else if name === 'restore'}
		<path d="M3 12a9 9 0 1 0 3-6.7" />
		<path d="M3 3v5h5" />
		<path d="M12 8v4.5l3 1.8" />
	{/if}
</svg>
