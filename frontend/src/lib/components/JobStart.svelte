<script lang="ts">
	/**
	 * The wow moment: exactly one, when a job starts.
	 *
	 * At that one moment something happens in the real world — a laser comes on.
	 * That may be felt. Everywhere else motion is purely functional (see
	 * DESIGN-SYSTEM, "The wow moment"): once, `--duration-slow`, and never again in the
	 * same session unless something really starts again.
	 */
	import { t } from '$lib/i18n/index.svelte';

	let { label = null }: { label?: string | null } = $props();
</script>

<div class="flits" aria-hidden="true">
	<div class="veeg"></div>
	<div class="woord">
		<span class="big">{t('jobStart.title')}</span>
		{#if label}<span class="small">{label}</span>{/if}
	</div>
</div>

<style>
	.flits {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		pointer-events: none;
		z-index: 4;
		animation: verdwijn var(--duration-slow) var(--ease-panel) forwards;
	}
	/* A streak of light crossing the bed once — the head setting off. */
	.veeg {
		position: absolute;
		inset: 0;
		background: linear-gradient(
			105deg,
			transparent 35%,
			color-mix(in srgb, var(--accent) 26%, transparent) 50%,
			transparent 65%
		);
		transform: translateX(-60%);
		animation: trek var(--duration-slow) var(--ease-panel) forwards;
	}
	.woord {
		display: grid;
		justify-items: center;
		gap: var(--space-1);
		padding: var(--space-3) var(--space-6);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		animation: op var(--duration-slow) var(--ease-panel) forwards;
	}
	.big { font-size: var(--text-lg); font-weight: 600; letter-spacing: -0.01em; }
	.small { font-size: var(--text-xs); color: var(--text-2); }

	@keyframes trek {
		from { transform: translateX(-60%); }
		to { transform: translateX(60%); }
	}
	@keyframes op {
		0% { opacity: 0; transform: scale(0.96); }
		25% { opacity: 1; transform: scale(1); }
		75% { opacity: 1; transform: scale(1); }
		100% { opacity: 0; transform: scale(1); }
	}
	@keyframes verdwijn {
		0%, 99% { opacity: 1; }
		100% { opacity: 0; }
	}

	/* Anybody who has switched motion off gets the message without the show. */
	@media (prefers-reduced-motion: reduce) {
		.veeg { display: none; }
		.flits, .woord { animation-duration: var(--duration-slow); animation-name: quiet; }
		@keyframes quiet {
			0%, 80% { opacity: 1; }
			100% { opacity: 0; }
		}
	}
</style>
