<script lang="ts">
	import {
		formatDuration,
		formatMm,
		isStalled,
		remainingSeconds,
		totalSeconds,
		type Device,
		type Job,
		type MachineState
	} from '$lib/api';

	import type { Controller } from '$lib/control.svelte';
	import { verbinding } from '$lib/verbinding.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import Verbinding from './Verbinding.svelte';
	import Melding from './Melding.svelte';

	let {
		device,
		machineState,
		job,
		connected,
		control,
		pointerMm = null,
		acties = true
	}: {
		device: Device | null;
		machineState: MachineState;
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
	// Uit dezelfde bron als `remaining` — dat is de hele fix van gat B1. Stond
	// hier `job.estimate_seconds`, dan las de balk "nog 0:00 van 13:45:04":
	// een restant van de klok naast een totaal van het brandmodel.
	let totaal = $derived(totalSeconds(job));
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
	 * Er stond één zin: "Verbonden met de laser" of niet. Die was driemaal
	 * onwaar. Hij zei "verbonden" terwijl er geen kabel in zat, hij wees bij
	 * een weggevallen server naar de laser terwijl het probleem de server was —
	 * en dan sta je een USB-kabel te controleren die niets mankeert — en hij
	 * zei het ook als niemand het kón weten.
	 *
	 * Dat laatste was gat E3. Voor grbl, newly en het dummy-apparaat meldt de
	 * engine `connection.state === "unknown"`: er is domweg geen bron. Onze
	 * balk maakte daar "Verbonden met de laser" van, met een groene stip erbij,
	 * ook meteen na de wizard — terwijl de wizard zélf zegt dat de verbinding
	 * pas bij de eerste job gelegd wordt. Twee schermen die elkaar tegenspreken,
	 * op de plek waar je het meest vertrouwt.
	 *
	 * Nu zegt de balk alleen "verbonden" als de driver dat zelf meldt. Weet
	 * niemand het, dan staat dat er: "Verbinding onbekend". Dat is geen storing
	 * en geen belofte, en het is het enige wat waar is.
	 *
	 * Verleidelijk maar fout: een lopende job als bewijs nemen. Gemeten op deze
	 * eigen server — het Job-paneel toonde een job op 80 % terwijl de engine
	 * eronder "USB connection did not exist" meldde. De spooler draait vrolijk
	 * door zonder machine; hij is dus geen handshake.
	 */
	let onbekend = $derived(
		connected && machineState !== 'unplugged' && device?.connection?.state !== 'connected'
	);
	/**
	 * Twee indicatoren, twee onderwerpen.
	 *
	 * De balk zei het twee keer: hier stond "Machine niet verbonden" en helemaal
	 * rechts stond "Niet verbonden" — dezelfde mededeling, twee keer, 700 px van
	 * elkaar. En het énige dat er níet stond was of de pagina zelf nog aan de
	 * server hangt; dat zag je alleen doordat deze tekst rood werd.
	 *
	 * Dus: hier de machine (met de knop erbij, want dáár kun je iets aan doen),
	 * en rechts de lijn naar OpenKerf. Twee dingen die los kunnen stukgaan
	 * krijgen twee plekken die dat los kunnen zeggen.
	 */
	let verbindingstekst = $derived(
		!connected
			? t('status.machine.unknown')
			: machineState === 'unplugged'
				? t('status.machine.notConnected')
				: onbekend
					? t('status.machine.connectionUnknown')
					: t('status.machine.connected')
	);
	/**
	 * De knop naast de toestand.
	 *
	 * De balk kon lezen dat er geen machine aan de lijn hing en er niets aan
	 * doen — "niet verbonden" zonder knop. Alleen zichtbaar als de driver het
	 * kent: grbl opent zelf zodra er werk naartoe gaat, en dan hoort er geen
	 * knop te zijn die niets betekent.
	 *
	 * Verbreken vraagt om bevestiging, verbinden niet. Gemeten op de echte
	 * KH-5030 gaat opnieuw verbinden na een verbreken soms wél en soms niet: op
	 * een server waar alleen curl tegen praat faalde het drie op drie, met de
	 * app eraan stond de verbinding binnen ~6 s vanzelf weer open. Wat hem
	 * heropent is niet gevonden. Zolang dat zo is, mag verbreken geen knop van
	 * één klik zijn — en mag de tekst niet meer beloven dan we weten.
	 */
	let hangt = $derived(device?.connection?.state === 'connected');
	let kanVerbinden = $derived(
		connected &&
			Boolean(
				hangt
					? control.capabilities?.connection?.disconnect
					: control.capabilities?.connection?.connect
			)
	);
	let zekerVerbreken = $state(false);

	let verbindingsuitleg = $derived(
		onbekend
			? t('status.machine.connectionUnknown.hint')
			: undefined
	);
</script>

<Verbinding brandt={Boolean(job?.running)} />

<!-- Gat E2. De socket is terug, de balk is weer groen, maar het is een andere
     engine dan die deze pagina kent: de elementenboom aan de andere kant is
     leeg. Niet vanzelf herladen — dat gooit werk weg zonder dat iemand erom
     vroeg — maar het ook niet verzwijgen, want alles wat je hierna doet gaat
     over een document dat daar niet meer bestaat. -->
{#if verbinding.herstart}
	<div class="herstart" role="alert">
		<div class="tekst">
			<strong>{t('status.restart.title')}</strong>
			<p>
				{t('status.restart.body')}
			</p>
		</div>
		<button onclick={() => location.reload()}>{t('status.restart.reload')}</button>
	</div>
{/if}
<!-- Fouten uit schrijfacties zijn hier niet thuis, maar dit is de enige
     component die op elk tabblad meedraait. Zonder dit landde een mislukte
     import in een paneel dat je op dat moment niet openhad. -->
<Melding {control} />

<footer class="statusbar mono">
	<!-- Twee posities naast elkaar: waar de kop staat, en waar jouw muis staat.
	     Zonder onderscheid leest de een als de ander. -->
	<span class="wat">{t('status.head')}</span>
	<span class:oud={!vers}>X <b>{formatMm(mm?.[0])}</b></span>
	<span class:oud={!vers}>Y <b>{formatMm(mm?.[1])}</b> mm</span>
	{#if !vers}
		<!-- Eén woord, maar het is het verschil tussen "de kop staat daar" en
		     "de kop stond daar toen we hem voor het laatst zagen". -->
		<span class="wat">{t('status.lastSeen')}</span>
	{/if}
	<span class="sep muisdeel" aria-hidden="true"></span>
	<span class="wat muisdeel">{t('status.mouse')}</span>
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
			<!-- Two whole messages instead of one sentence with a styled tail: the
			     emphasis survives (how long is left is the number that counts) and
			     neither half is a fragment a translator cannot place. -->
			{t('status.remaining', { remaining: formatDuration(remaining) })}
			<span class="van">{t('status.total', { total: formatDuration(totaal) })}</span>
		{:else if job}
			{t('status.estimated', { total: formatDuration(totaal) })}
		{:else}
			{t('status.noJob')}
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<!-- Gebruikerstaal, geen protocoltaal: wie dit leest wil weten of de laser
	     luistert, niet of er een socket openstaat. -->
	<span
		class:offline={!connected}
		class:onthecht={connected && machineState === 'unplugged'}
		class:afwachtend={Boolean(verbindingsuitleg)}
		title={verbindingsuitleg}
	>
		{verbindingstekst}
	</span>
	{#if kanVerbinden}
		{#if zekerVerbreken}
			<span class="verbreek-vraag">
				{t('status.disconnect.ask')}
				<button
					class="verbind"
					disabled={control.busy === 'disconnect'}
					onclick={() => {
						zekerVerbreken = false;
						control.disconnect();
					}}
				>{t('status.disconnect')}</button>
				<button class="verbind" onclick={() => (zekerVerbreken = false)}>{t('status.disconnect.keep')}</button>
			</span>
		{:else}
			<button
				class="verbind"
				disabled={control.needsToken || control.busy === 'connect' || control.busy === 'disconnect'}
				title={control.needsToken
					? t('status.needsToken')
					: hangt
						? t('status.disconnect.title')
						: t('status.connect.title')}
				onclick={() => (hangt ? (zekerVerbreken = true) : control.connect())}
			>
				{control.busy === 'connect'
					? t('status.connect.busy')
					: control.busy === 'disconnect'
						? t('status.disconnect.busy')
						: hangt
							? t('status.disconnect')
							: t('status.connect')}
			</button>
		{/if}
	{/if}
	<!--
		Hier stonden pauze en stop. Ze zijn naar de bovenbalk gegaan, waar starten
		en stoppen al stonden: het transport hoort bij elkaar, en drie balken met
		elk een deel ervan is precies de verspreiding waar de klacht over ging. Wat
		de statusbalk houdt is de voortgang, en die hoort hier — hij geldt voor de
		hele app, op elk tabblad.
	-->
	<!-- De lijn naar OpenKerf zelf. Hier stond de machinetoestand, en die staat
	     al links in deze balk én in de bovenbalk. -->
	<span
		class="right"
		class:offline={!connected}
		title={connected ? t('status.openkerf.live.title') : t('status.openkerf.away.title')}
	>
		<span class="dot {connected ? 'ready' : 'offline'}" aria-hidden="true"></span>
		{connected ? t('status.openkerf.live') : t('status.openkerf.away')}
	</span>
</footer>

<style>
	/* Boven de statusbalk, over de volle breedte: dit gaat over de hele pagina
	   en niet over één paneel. Niet gecentreerd bovenin — daar staat al de
	   verbindingskaart, en twee kaarten over elkaar heen is geen bericht. */
	.herstart {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--statusbar-height);
		z-index: 70;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-2) var(--space-4);
		border-top: 1px solid var(--warn-solid);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.herstart .tekst { min-width: 0; }
	.herstart strong { display: block; font-size: var(--text-sm); }
	.herstart p { margin: 0; color: var(--text-2); }
	.herstart button {
		flex: none;
		margin-left: auto;
		/* 44px: dit wordt ook op een tablet naast de machine aangeraakt. */
		min-height: 44px;
		padding: 0 var(--space-4);
		font: inherit;
		font-weight: 600;
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		background: var(--accent);
		color: var(--accent-ink);
	}
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
	.verbind {
		margin-left: var(--space-1);
		padding: 1px var(--space-1);
		font: inherit;
		color: var(--text-1);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-1);
		cursor: pointer;
	}
	.verbind:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
	.verbind:disabled { opacity: 0.5; cursor: default; }
	.verbreek-vraag {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		margin-left: var(--space-1);
		color: var(--text-1);
	}

	/* Nog niet verbonden is geen storing en geen belofte. Dezelfde gedempte
	   tint als de rest van de balk, met een streepje eronder dat zegt dat er
	   uitleg achter zit. Geel zou hier alarm slaan over iets wat volkomen
	   normaal is vlak na de wizard. */
	.afwachtend {
		color: var(--text-2);
		text-decoration: underline dotted;
		text-underline-offset: 3px;
	}
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
</style>
