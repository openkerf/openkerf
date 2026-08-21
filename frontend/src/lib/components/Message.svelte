<script lang="ts">
	/**
	 * One place where a failed command becomes visible.
	 *
	 * An import's error message lived in the Job tab, and you import from the top bar
	 * while you are in Design. Consequence: a broken file produced a neatly worded message
	 * nobody ever saw — all you saw was a bed that stayed empty. An error should appear
	 * where you are looking, not where it came from.
	 *
	 * It stays up until you click it away. A message that disappears by itself is one you
	 * miss precisely when you glanced at the machine.
	 */
	import { t } from '$lib/i18n/index.svelte';
	import type { Controller } from '$lib/control.svelte';

	let { control }: { control: Controller } = $props();
</script>

{#if control.error}
	<div class="notice" role="alert">
		<span class="stip" aria-hidden="true"></span>
		<p>{control.error}</p>
		<button aria-label={t('message.close')} onclick={() => (control.error = null)}>×</button>
	</div>
{/if}

<style>
	.notice {
		position: fixed;
		/* Top right, below the top bar. At first it was in the bottom right and covered
		   the zoom buttons; besides, most of these errors come from the top bar (open,
		   import, export) and that is where the answer should appear. */
		right: var(--space-4);
		top: calc(var(--topbar-height) + var(--space-3));
		z-index: 60;
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		max-width: min(420px, calc(100vw - 2 * var(--space-4)));
		padding: var(--space-3);
		border: 1px solid var(--danger-solid);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		margin-top: var(--space-1h);
		border-radius: var(--radius-dot);
		background: var(--danger-solid);
	}
	p { margin: 0; }
	button {
		flex: none;
		width: 24px;
		height: 24px;
		margin: -4px -4px 0 0;
		border-radius: var(--radius-field);
		font-size: var(--text-md);
		line-height: 1;
		color: var(--text-2);
	}
	button:hover { background: var(--surface-2); color: var(--text-1); }
</style>
