<script lang="ts">
	/**
	 * Eén plek waar een mislukte opdracht zichtbaar wordt.
	 *
	 * De foutmelding van een import stond in het Job-tabblad, en importeren doe
	 * je vanuit de bovenbalk terwijl je in Bewerken staat. Gevolg: een kapot
	 * bestand leverde een keurig geformuleerde melding op die niemand ooit zag —
	 * je zag alleen een bed dat leeg bleef. Een failure hoort te verschijnen waar je
	 * kijkt, niet waar hij vandaan komt.
	 *
	 * Blijft staan tot je hem wegklikt. Een melding die vanzelf verdwijnt, mis je
	 * precies wanneer je even naar de machine keek.
	 */
	import { t } from '$lib/i18n/index.svelte';
	import type { Controller } from '$lib/control.svelte';

	let { control }: { control: Controller } = $props();
</script>

{#if control.error}
	<div class="melding" role="alert">
		<span class="stip" aria-hidden="true"></span>
		<p>{control.error}</p>
		<button aria-label={t('message.close')} onclick={() => (control.error = null)}>×</button>
	</div>
{/if}

<style>
	.melding {
		position: fixed;
		/* Rechtsboven, onder de bovenbalk. Eerst stond hij rechtsonder en dekte
		   hij de zoomknoppen af; bovendien komen de meeste van deze fouten uit de
		   bovenbalk (openen, importeren, exporteren) en daar hoort het antwoord
		   dan ook te verschijnen. */
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
