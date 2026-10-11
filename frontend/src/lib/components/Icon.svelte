<script lang="ts" module>
	/**
	 * The icons the app draws in more than one place, in one stroke (1.75) on one grid
	 * (24). They replace the glyphs that stood in for icons — ×, ⋯, ↑, ↓, ›, −, + —
	 * which changed shape with the typeface and sat on the baseline instead of the
	 * middle of a button.
	 *
	 * Components with an icon of their own (the tool rail, the action bar) keep drawing
	 * it inline; what they share is the `.icon-svg` stroke in `tokens.css`.
	 */
	const PATHS = {
		close: 'M6 6l12 12M18 6L6 18',
		more: 'M5 12h.01M12 12h.01M19 12h.01',
		'chevron-down': 'M6 9l6 6 6-6',
		'chevron-up': 'M6 15l6-6 6 6',
		'chevron-right': 'M9 6l6 6-6 6',
		'arrow-up': 'M12 19V5M6 11l6-6 6 6',
		'arrow-down': 'M12 5v14M6 13l6 6 6-6',
		plus: 'M12 5v14M5 12h14',
		minus: 'M5 12h14',
		check: 'M5 12.5l4.5 4.5L19 7.5',
		info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01',
		warn: 'M12 3.5l9.5 16.5h-19L12 3.5zM12 10v4.5M12 17.5h.01',
		danger: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5v5.5M12 16.5h.01',
		ok: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12.5l2.8 2.8L16.5 9.5',
		empty: 'M4 8l8-4 8 4v8l-8 4-8-4V8zM4 8l8 4 8-4M12 12v8',
		search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4'
	} as const;

	export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
	let {
		name,
		size = 16,
		label
	}: {
		name: IconName;
		/** 16 inside text and small buttons, 20 in a toolbar or beside a title. */
		size?: 16 | 20;
		/** Only when the icon is the whole message; otherwise it is decoration. */
		label?: string;
	} = $props();
</script>

<svg
	class="icon-svg"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	aria-hidden={label ? undefined : 'true'}
	role={label ? 'img' : undefined}
	aria-label={label}
	focusable="false"><path d={PATHS[name]} /></svg
>
