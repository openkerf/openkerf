<script lang="ts" generics="T">
	/**
	 * Eén keuze uit een korte, vaste rij — als één blok, niet als losse knopjes.
	 *
	 * Losse knoppen laten open of er ook twee aan kunnen staan, en welke groep
	 * bij elkaar hoort. Een aaneengesloten balk zegt allebei zonder woorden. Voor
	 * meer dan vijf opties hoort een `<select>` (zie DESIGN-SYSTEM, Patroonkeuzewijzer).
	 */
	let {
		options,
		value = $bindable(),
		label,
		mono = false,
		disabled = false
	}: {
		options: { value: T; label: string; title?: string }[];
		value: T;
		label: string;
		mono?: boolean;
		disabled?: boolean;
	} = $props();
</script>

<div class="segmented" class:mono role="radiogroup" aria-label={label}>
	{#each options as option (option.label)}
		<button
			role="radio"
			aria-checked={value === option.value}
			class:on={value === option.value}
			title={option.title}
			{disabled}
			onclick={() => (value = option.value)}
		>{option.label}</button>
	{/each}
</div>

<style>
	.segmented {
		display: inline-flex;
		/* Eén rand om het geheel, haarlijnen ertussen: het is één ding. */
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
	/* De gekozen stand is gevuld, niet omrand: dan verspringt er niets en is
	   hij ook op een meter afstand te zien. */
	button.on {
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	button.on:hover { background: var(--accent); color: var(--accent-ink); }
</style>
