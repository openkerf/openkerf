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
	import { t } from '$lib/i18n/index.svelte';
	import { connection } from '$lib/connection.svelte';

	let { brandt = false }: { brandt?: boolean } = $props();

	// Een halve seconde netwerkhik is geen mededeling; de herverbinding lukt
	// dan al voordat iemand het gelezen heeft. Pas na twee seconden praten.
	const GEDULD = 2000;
	let laat = $state(false);
	$effect(() => {
		if (connection.online) {
			laat = false;
			return;
		}
		const t = setTimeout(() => (laat = true), GEDULD);
		return () => clearTimeout(t);
	});

	let weg = $derived(
		connection.since ? Math.round((Date.now() - connection.since) / 1000) : 0
	);
	// Only mentioned when it lasts long enough to worry about.
	let duur = $derived(weg >= 60 ? t('connection.minutes', { n: Math.floor(weg / 60) }) : null);

	/**
	 * Deze kaart en het machine-alarm vormen één kolom, en dit is de maat ervan.
	 *
	 * Ze hingen aan hetzelfde anker en lagen over elkaar heen — niet volledig,
	 * wat erger is: het alarm begon halverwege deze kaart en kapte twee zinnen
	 * middenin af ("Wat je nu tekent of instelt k…"). Een afgebroken zin ziet
	 * eruit als een hele zin, dus je weet niet dát je iets mist, en je handelt op
	 * de helft van een instructie.
	 *
	 * Twee vaste elementen kunnen alleen stapelen als ze van elkaar weten hoe
	 * hoog ze zijn. Geen wrapper-element (dat zou `+page.svelte` raken, en deze
	 * kaart en het alarm worden daar op twee verschillende plekken gerenderd),
	 * dus geeft deze kaart zijn hoogte door in een variabele op `:root` en rekent
	 * het alarm daarmee zijn eigen `top` uit. Nul zodra deze kaart weg is.
	 *
	 * De volgorde is niet willekeurig: zonder onze server is elke melding over de
	 * machine per definitie oud nieuws — de engine die het meldde is dezelfde die
	 * niet meer antwoordt. Deze kaart hoort dus boven.
	 */
	let kaart = $state<HTMLElement | null>(null);
	$effect(() => {
		const wortel = document.documentElement;
		if (!kaart) {
			wortel.style.removeProperty('--notice-column');
			return;
		}
		// Hoogte plus de tussenruimte in één getal: dan hoeft het alarm er niets
		// bij te rekenen en kan er ook geen halve variabele overblijven.
		const meet = () =>
			wortel.style.setProperty(
				'--notice-column',
				`calc(${Math.ceil(kaart!.offsetHeight)}px + var(--space-2))`
			);
		meet();
		// De hoogte verandert met de tekst ("al 3 min") en met de vensterbreedte.
		const wacht = new ResizeObserver(meet);
		wacht.observe(kaart);
		return () => {
			wacht.disconnect();
			wortel.style.removeProperty('--notice-column');
		};
	});
</script>

{#if !connection.online && laat}
	<div class="verbroken" role="alert" bind:this={kaart}>
		<span class="stip" aria-hidden="true"></span>
		<div class="tekst">
			<strong>{t('connection.lost')}</strong>
			<p>
				{duur ? t('connection.lost.bodyFor', { duration: duur }) : t('connection.lost.body')}
			</p>
			{#if brandt}
				<p class="urgent">{t('connection.stillBurning')}</p>
			{/if}
		</div>
		<div class="actie">
			<button onclick={() => connection.retryNow()}>{t('connection.retryNow')}</button>
			<span class="klok">
				{#if connection.inSeconds > 0}
					{t('connection.autoIn', { seconds: connection.inSeconds })}
				{:else}
					{t('connection.connecting')}
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
		/* Zelfde breedte als het alarm eronder, want samen zijn ze één kolom.
		   Stond op 560 tegenover 720 van het alarm, en dan lezen twee kaarten met
		   dezelfde linkerrand als een failure in plaats van als een stapel. */
		width: min(620px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
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
	/* Tablet: zelfde 560 als het alarm eronder — op 1024 begint het rechterpaneel
	   op x≈700 en zou 620 px de paneeltabs afdekken. Deze maat hoort gelijk te
	   blijven met die in `AlarmCard.svelte`; zie de toelichting daar. */
	@media (min-width: 768px) and (max-width: 1199px) {
		.verbroken {
			width: min(560px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		}
	}
	@media (max-width: 767px) {
		.verbroken { display: none; }
	}
</style>
