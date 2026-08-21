<script lang="ts">
	/**
	 * The wow moment: exactly one, when a job starts.
	 *
	 * At that one moment something happens in the real world — a laser comes on.
	 * That may be felt. Everywhere else motion is purely functional (see
	 * DESIGN-SYSTEM, "The wow moment"): once, ~900 ms, and never again in the
	 * same session unless something really starts again.
	 */
	import { t } from '$lib/i18n/index.svelte';

	let { label = null }: { label?: string | null } = $props();
</script>

<div class="flits" aria-hidden="true">
	<div class="veeg"></div>
	<div class="woord">
		<span class="groot">{t('jobStart.title')}</span>
		{#if label}<span class="klein">{label}</span>{/if}
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
		animation: verdwijn 900ms cubic-bezier(0.2, 0, 0, 1) forwards;
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
		animation: trek 900ms cubic-bezier(0.2, 0, 0, 1) forwards;
	}
	.woord {
		display: grid;
		justify-items: center;
		gap: 2px;
		padding: var(--space-3) var(--space-6);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		animation: op 900ms cubic-bezier(0.2, 0, 0, 1) forwards;
	}
	.groot { font-size: var(--text-lg); font-weight: 600; letter-spacing: -0.01em; }
	.klein { font-size: var(--text-xs); color: var(--text-2); }

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
		.flits, .woord { animation-duration: 900ms; animation-name: quiet; }
		@keyframes quiet {
			0%, 80% { opacity: 1; }
			100% { opacity: 0; }
		}
	}
</style>
