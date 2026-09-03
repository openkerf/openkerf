<script lang="ts" generics="T">
	/**
	 * One choice from a short, fixed row — as one block, not as separate buttons.
	 *
	 * Separate buttons leave open whether two can be on at once, and which group belongs
	 * together. A continuous bar says both without words. For more than five options a
	 * `<select>` is right (see DESIGN-SYSTEM, pattern guide).
	 */
	let {
		options,
		value = $bindable(),
		label,
		mono = false,
		disabled = false,
		why = undefined
	}: {
		options: { value: T; label: string; title?: string }[];
		value: T;
		label: string;
		mono?: boolean;
		disabled?: boolean;
		/** Why the whole row is off. The options keep their own titles; this is the one
		 *  the reader needs when none of them can be pressed. */
		why?: string;
	} = $props();
</script>

<div class="segmented" class:mono role="radiogroup" aria-label={label}>
	{#each options as option (option.label)}
		<button
			role="radio"
			aria-checked={value === option.value}
			class:on={value === option.value}
			title={disabled ? why : option.title}
			{disabled}
			onclick={() => (value = option.value)}
		>{option.label}</button>
	{/each}
</div>

<style>
	.segmented {
		display: inline-flex;
		/* One border around the whole, hairlines in between: it is one thing. */
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		overflow: hidden;
	}
	.segmented.mono button { font-family: var(--font-mono); }
	button {
		flex: 1;
		min-width: 0;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		font-size: var(--text-xs);
		color: var(--text-2);
		background: transparent;
		border: 0;
		border-left: 1px solid var(--line);
		white-space: nowrap;
	}
	button:first-child { border-left: 0; }
	button:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	button:disabled { opacity: 0.5; }
	/* The chosen state is filled, not outlined: then nothing jumps and it can be seen
	   from a metre away too. */
	button.on {
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	button.on:hover { background: var(--accent); color: var(--accent-ink); }
</style>
