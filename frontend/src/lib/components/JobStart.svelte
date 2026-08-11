<script lang="ts">
	/**
	 * Het wauw-moment: precies één, bij het starten van een job.
	 *
	 * Op dat ene moment gebeurt er iets in de echte wereld — een laser gaat aan.
	 * Dat mag je voelen. Overal elders is beweging alleen functioneel (zie
	 * DESIGN-SYSTEM, "Het wauw-moment"): één keer, ~900 ms, en daarna nooit meer
	 * in dezelfde sessie zonder dat er weer echt iets begint.
	 */
	let { label = null }: { label?: string | null } = $props();
</script>

<div class="flits" aria-hidden="true">
	<div class="veeg"></div>
	<div class="woord">
		<span class="groot">Job gestart</span>
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
	/* Een lichtstreep die één keer over het bed trekt — de kop die vertrekt. */
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

	/* Wie beweging heeft uitgezet, krijgt de mededeling zonder de show. */
	@media (prefers-reduced-motion: reduce) {
		.veeg { display: none; }
		.flits, .woord { animation-duration: 900ms; animation-name: stil; }
		@keyframes stil {
			0%, 80% { opacity: 1; }
			100% { opacity: 0; }
		}
	}
</style>
