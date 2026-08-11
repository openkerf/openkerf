<script lang="ts">
	import {
		formatDuration,
		formatMm,
		isStalled,
		remainingSeconds,
		STATE_LABEL,
		type Device,
		type Job,
		type MachineState
	} from '$lib/api';

	import type { Controller } from '$lib/control.svelte';
	import Verbinding from './Verbinding.svelte';
	import Melding from './Melding.svelte';

	let {
		device,
		state,
		job,
		connected,
		control,
		pointerMm = null,
		acties = true
	}: {
		device: Device | null;
		state: MachineState;
		job: Job | null;
		connected: boolean;
		control: Controller;
		/** Muispositie op het bed; staat naast de machinepositie. */
		pointerMm?: { x: number; y: number } | null;
		/** Draagt deze balk de pauze- en stopknop? Op tablet niet: daar staat de
		 *  machinebediening in de bovenbalk, en twee plekken voor dezelfde stop
		 *  maakt op het beslissende moment onduidelijk welke de echte is. Op 768
		 *  liep de balk bovendien over en viel de stopknop van het scherm. */
		acties?: boolean;
	} = $props();

	// Stoppen hoorde alleen in het Job-tabblad. Wie tijdens het branden aan het
	// ontwerpen was, had geen stop in beeld — en dat is precies het moment
	// waarop je hem nodig hebt. Vandaar hier, altijd zichtbaar zodra er iets
	// loopt of in de wachtrij staat.
	// Ook een gepauzeerde job telt: die heeft bij Lihuiyu `running === false` en
	// verdween daardoor uit deze balk — precies wanneer je de hervatknop zoekt.
	let busy = $derived(Boolean(job) || (device?.spooler.queue_length ?? 0) > 0);

	let mm = $derived(device?.position.mm ?? null);

	// Pauzeren moest lukken vanaf élk tabblad. Stond hij alleen in het
	// Job-paneel, dan kostte het een tabwissel plus een klik — precies op het
	// moment dat je geen tweede handeling wil doen. Dus hier, naast de stop.
	let paused = $derived(isStalled(job));
	let canPause = $derived(control.capabilities?.actions.pause ?? false);
	let canResume = $derived(control.capabilities?.actions.resume ?? false);
	let remaining = $derived(remainingSeconds(job));
	let percent = $derived(job?.progress !== null && job?.progress !== undefined
		? Math.round(job.progress * 100)
		: null);

	// Zonder verbinding is elk getal hieronder een herinnering, geen meting. Ze
	// blijven staan — ze zeggen nog steeds waar de kop stond — maar ze mogen
	// zich niet voordoen als actueel.
	let vers = $derived(connected);

	/**
	 * Wat er over de verbinding staat, in de juiste volgorde van slecht nieuws.
	 *
	 * Er stond één zin: "Verbonden met de laser" of niet. Die was tweemaal
	 * onwaar. Hij zei "verbonden" terwijl er geen kabel in zat, en hij wees bij
	 * een weggevallen server naar de laser terwijl het probleem de server was —
	 * en dan sta je een USB-kabel te controleren die niets mankeert.
	 */
	let verbindingstekst = $derived(
		!connected
			? 'Geen verbinding met OpenKerf'
			: state === 'unplugged'
				? 'Machine niet verbonden'
				: 'Verbonden met de laser'
	);
</script>

<Verbinding brandt={Boolean(job?.running)} />
<!-- Fouten uit schrijfacties zijn hier niet thuis, maar dit is de enige
     component die op elk tabblad meedraait. Zonder dit landde een mislukte
     import in een paneel dat je op dat moment niet openhad. -->
<Melding {control} />

<footer class="statusbar mono">
	<!-- Twee posities naast elkaar: waar de kop staat, en waar jouw muis staat.
	     Zonder onderscheid leest de een als de ander. -->
	<span class="wat">kop</span>
	<span class:oud={!vers}>X <b>{formatMm(mm?.[0])}</b></span>
	<span class:oud={!vers}>Y <b>{formatMm(mm?.[1])}</b> mm</span>
	{#if !vers}
		<!-- Eén woord, maar het is het verschil tussen "de kop staat daar" en
		     "de kop stond daar toen we hem voor het laatst zagen". -->
		<span class="wat">laatst gezien</span>
	{/if}
	<span class="sep muisdeel" aria-hidden="true"></span>
	<span class="wat muisdeel">muis</span>
	<span class="muis muisdeel">
		{#if pointerMm}
			<b>{pointerMm.x.toFixed(1)}</b>, <b>{pointerMm.y.toFixed(1)}</b> mm
		{:else}
			—
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<!-- Tijdens een job is "hoe lang nog" het enige getal dat telt; de totale
	     schatting stond er, maar die moest je zelf van de klok aftrekken. -->
	<span class="tijd">
		{#if job && remaining !== null}
			{#if percent !== null}<b class="pct">{percent}%</b>{/if}
			nog <b>{formatDuration(remaining)}</b>
			<span class="van">van {formatDuration(job.estimate_seconds)}</span>
		{:else if job}
			~ {formatDuration(job.estimate_seconds)} geschat
		{:else}
			geen job
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<!-- Gebruikerstaal, geen protocoltaal: wie dit leest wil weten of de laser
	     luistert, niet of er een socket openstaat. -->
	<span class:offline={!connected} class:onthecht={connected && state === 'unplugged'}>
		{verbindingstekst}
	</span>
	{#if busy && acties}
		<span class="acties">
			{#if paused}
				<button
					class="hervat"
					disabled={control.needsToken || !canResume || !connected}
					title={!connected
						? 'Geen verbinding met OpenKerf'
						: control.needsToken
							? 'Eerst een token invullen'
							: 'Verder waar hij gebleven was'}
					onclick={() => control.resume()}
				>
					Hervatten
				</button>
			{:else}
				<button
					class="pauze"
					disabled={control.needsToken || !canPause || !job?.running || !connected}
					title={!connected
						? 'Geen verbinding met OpenKerf'
						: control.needsToken
							? 'Eerst een token invullen'
						: !canPause
							? 'Deze machine kent geen pauze — gebruik de knop op de machine'
							: 'Job pauzeren'}
					onclick={() => control.pause()}
				>
					Pauze
				</button>
			{/if}
			<!-- 24px ertussen: pauze en stop hebben tegengestelde gevolgen, en een
			     mistik kost je het werkstuk. Zie DESIGN-SYSTEM v2, "Touch". -->
			<!-- Uitgeschakeld zodra de server weg is. Een stopknop die er levend
			     uitziet en niets doet, is gevaarlijker dan geen stopknop: je drukt
			     hem in, loopt weg, en denkt dat het geregeld is. -->
			<button
				class="stop"
				disabled={control.needsToken || !connected}
				title={!connected
					? 'Geen verbinding met OpenKerf — stoppen kan alleen met de knop op de machine'
					: control.needsToken
						? 'Zonder token kan de app niet stoppen — gebruik de stopknop op de machine'
						: 'Job afbreken'}
				onclick={() => control.stop()}
			>
				Stop
			</button>
		</span>
	{/if}
	<span class="right">
		<span class="dot {state}" aria-hidden="true"></span>{STATE_LABEL[state]}
	</span>
</footer>

<style>
	.wat {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Vaste breedte: anders springt de hele balk mee met elke muisbeweging. */
	.muis { display: inline-block; min-width: 13ch; }
	/* Op tablet teken je niet, dus is de muispositie geen informatie — en de
	   ruimte hebben de bedieningsknoppen wél nodig: zonder dit brak de balk
	   over twee regels zodra er een job liep. */
	@media (max-width: 1199px) {
		.muisdeel { display: none; }
	}
	.statusbar > span { white-space: nowrap; }

	.statusbar {
		/* Vaste hoogte op desktop; op touch groeien de knoppen naar 44px en dan
		   moet de balk meegeven in plaats van ze eruit te laten steken. */
		min-height: var(--statusbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.offline { color: var(--danger); }
	/* Niet rood: de server doet het, er hangt alleen geen machine aan. Rood zou
	   dit gelijkstellen aan een storing, en dan gelooft niemand het rood meer
	   dat er wél toe doet. */
	.onthecht { color: var(--warn); }
	/* Standen van vóór de stilte: leesbaar, maar niet meer als feit. */
	.oud { opacity: 0.55; }
	b {
		color: var(--text-1);
		font-weight: 400;
	}
	.sep {
		width: 1px;
		height: 14px;
		background: var(--line);
	}
	/* De voortgang in cijfers: percentage vet, resterend vet, totaal gedempt —
	   drie getallen naast elkaar lezen anders als één brij. */
	.tijd { white-space: nowrap; }
	.pct { margin-right: var(--space-2); }
	.van { color: var(--text-2); }

	.acties {
		margin-left: auto;
		display: flex;
		align-items: center;
		/* 24px: tegengestelde gevolgen horen niet naast elkaar te plakken. */
		gap: var(--space-6);
	}
	.pauze,
	.hervat,
	.stop {
		padding: 4px 12px;
		font: inherit;
		font-weight: 600;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.hervat {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--accent-ink);
	}
	.stop {
		border-color: var(--danger-solid);
		background: var(--danger-solid);
		color: var(--on-color);
	}
	.pauze:disabled,
	.hervat:disabled,
	.stop:disabled { opacity: 0.5; cursor: not-allowed; }
	.acties + .right { margin-left: var(--space-3); }
	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-1);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
	.dot.unplugged { background: var(--warn-solid); }
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }
</style>
