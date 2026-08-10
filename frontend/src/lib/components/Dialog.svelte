<script lang="ts">
	/**
	 * Overlayvenster voor bibliotheken en gereedschappen.
	 *
	 * Volgens DESIGN-SYSTEM.md: het rechterpaneel is voor het hier-en-nu
	 * (selectie, lagen, machine, job); dingen waarin je zoekt en vergelijkt
	 * krijgen de ruimte van een eigen venster.
	 */
	let {
		title,
		open = $bindable(),
		width = '560px',
		children
	}: {
		title: string;
		open: boolean;
		width?: string;
		children: import('svelte').Snippet;
	} = $props();

	let panel = $state<HTMLElement | null>(null);

	$effect(() => {
		if (open) panel?.focus();
	});
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="backdrop"
		onclick={(e) => {
			if (e.target === e.currentTarget) open = false;
		}}
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
		<section
			class="panel"
			style="width: min({width}, calc(100vw - 2 * var(--space-6)))"
			role="dialog"
			aria-modal="true"
			aria-label={title}
			tabindex="-1"
			bind:this={panel}
			onkeydown={(e) => {
				if (e.key === 'Escape') {
					e.stopPropagation();
					open = false;
				}
			}}
		>
			<header>
				<h2>{title}</h2>
				<button class="close" aria-label="Sluiten" onclick={() => (open = false)}>×</button>
			</header>
			<div class="body">
				{@render children()}
			</div>
		</section>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 20;
		display: grid;
		place-items: center;
		padding: var(--space-6);
		background: rgb(0 0 0 / 0.35);
	}
	.panel {
		display: flex;
		flex-direction: column;
		max-height: min(80vh, 760px);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		outline: none;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--line);
	}
	h2 {
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.close {
		font-size: 20px;
		line-height: 1;
		color: var(--text-2);
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
	}
	.close:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.body {
		overflow-y: auto;
		padding: var(--space-4);
	}
</style>
