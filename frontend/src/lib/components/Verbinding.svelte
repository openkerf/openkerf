<script lang="ts">
	/**
	 * Wat je ziet als de server wegvalt.
	 *
	 * Tot nu toe verkleurde alleen een stipje en werden een paar knoppen grijs.
	 * Dat is geen bericht maar een symptoom: het scherm ziet er bevroren uit en
	 * niemand weet of hij moet wachten, verversen of naar de machine rennen.
	 * Drie dingen horen erin, in deze volgorde: wat er stuk is, wat dat voor je
	 * werk betekent, en wat de app er nú aan doet.
	 *
	 * De veiligheidsregel staat er niet voor de sier. Valt de server weg terwijl
	 * de machine brandt, dan brandt hij door en kan deze app hem niet meer
	 * stoppen. Dat mag je op zo'n moment niet zelf hoeven bedenken.
	 */
	import { verbinding } from '$lib/verbinding.svelte';

	let { brandt = false }: { brandt?: boolean } = $props();

	// Een halve seconde netwerkhik is geen mededeling; de herverbinding lukt
	// dan al voordat iemand het gelezen heeft. Pas na twee seconden praten.
	const GEDULD = 2000;
	let laat = $state(false);
	$effect(() => {
		if (verbinding.online) {
			laat = false;
			return;
		}
		const t = setTimeout(() => (laat = true), GEDULD);
		return () => clearTimeout(t);
	});

	let weg = $derived(
		verbinding.sinds ? Math.round((Date.now() - verbinding.sinds) / 1000) : 0
	);
	// Alleen noemen als het lang genoeg duurt om ongerust van te worden.
	let duur = $derived(weg >= 60 ? `${Math.floor(weg / 60)} min` : null);
</script>

{#if !verbinding.online && laat}
	<div class="verbroken" role="alert">
		<span class="stip" aria-hidden="true"></span>
		<div class="tekst">
			<strong>Geen verbinding met OpenKerf</strong>
			<p>
				De server reageert niet{duur ? ` — al ${duur}` : ''}. Wat je nu tekent of
				instelt komt niet aan, en de standen hieronder zijn de laatste die we
				gezien hebben.
			</p>
			{#if brandt}
				<p class="urgent">
					De machine loopt door. Stoppen kan nu alleen met de knop op de machine
					zelf.
				</p>
			{/if}
		</div>
		<div class="actie">
			<button onclick={() => verbinding.nuProberen()}>Nu opnieuw proberen</button>
			<span class="klok">
				{#if verbinding.overSeconden > 0}
					vanzelf over {verbinding.overSeconden} s
				{:else}
					bezig met verbinden…
				{/if}
			</span>
		</div>
	</div>
{/if}

<style>
	.verbroken {
		position: fixed;
		/* Onder de bovenbalk, tegen de gereedschapsrail aan: in de looprichting
		   van je blik, maar boven het canvas en niet boven het rechterpaneel.
		   Gecentreerd lag hij op tablet dwars over de paneeltabs — en juist daar
		   staat wat je op dat moment wilde bedienen. */
		top: calc(var(--topbar-height, 46px) + var(--space-3));
		left: calc(var(--rail-width) + var(--space-3));
		z-index: 60;
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		max-width: min(560px, calc(100vw - 2 * var(--space-4)));
		padding: var(--space-3) var(--space-4);
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
	.tekst { min-width: 0; }
	strong { display: block; font-size: var(--text-sm); margin-bottom: 2px; }
	p { margin: 0; color: var(--text-2); }
	.urgent { margin-top: var(--space-2); color: var(--danger); font-weight: 500; }
	.actie {
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 4px;
	}
	.actie button {
		/* 44px hoog: dit is precies een knop die iemand met handschoenen aan,
		   naast een machine, in één keer moet raken. */
		min-height: 44px;
		padding: 0 var(--space-3);
		white-space: nowrap;
		font: inherit;
		font-weight: 600;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.actie button:hover { background: var(--surface-2); }
	.klok {
		text-align: center;
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	/*
	 * Op de telefoon niet. Dit scherm zegt het al drie keer op eigen kracht —
	 * in de kop, onder het bed en boven de noodrem — en een zwevende kaart
	 * bovenop een vaste onderbalk van 390 px breed ging daar letterlijk
	 * overheen liggen. Het knopje "opnieuw proberen" staat daar in de
	 * onderbalk zelf.
	 */
	@media (max-width: 767px) {
		.verbroken { display: none; }
	}
</style>
