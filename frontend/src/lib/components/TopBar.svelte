<script lang="ts">
	import { machineStateLabel, STOP_KEY, type Device, type MachineState } from '$lib/api';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import LanguagePicker from './LanguagePicker.svelte';
	import { apparaat } from '$lib/apparaat.svelte';
	import { bewaarBestand } from '$lib/opslaan';
	import { verbinding } from '$lib/verbinding.svelte';
	import Logo from './Logo.svelte';

	let {
		device,
		state: machineState,
		canStart,
		canStop,
		stopArmed = false,
		canEdit = false,
		smal = false,
		canPause = false,
		canResume = false,
		paused = false,
		onPause,
		onResume,
		onStart,
		onStop,
		onFrame,
		canFrame = false,
		material = null,
		thicknessMm = null,
		onOpenMaterial,
		onOpenFile,
		onOpenProject,
		onNewProject,
		onSaved,
		onToggleTheme
	}: {
		device: Device | null;
		state: MachineState;
		canStart: boolean;
		canStop: boolean;
		/** Er is iets om te stoppen. De knop blijft altijd bruikbaar — als onze
		 *  statusdetectie ernaast zit mag je de noodrem niet kwijt zijn — maar hij
		 *  schreeuwt alleen wanneer het ertoe doet. */
		stopArmed?: boolean;
		canEdit?: boolean;
		/**
		 * @deprecated Wordt genegeerd; de afspraak staat in `$lib/apparaat.svelte`.
		 *
		 * Gat J9: deze prop en de `@media (max-width: 1199px)` in JobControls
		 * waren twee bronnen voor één regel. Beide componenten lezen nu
		 * `apparaat.bedieningInBalk`. De prop blijft geaccepteerd zodat de
		 * pagina niet in dezelfde stap mee hoeft; hij mag daar weg.
		 */
		tablet?: boolean;
		/** Onder ~950px passen de bestandsknoppen er niet meer bij; ze staan dan
		 *  in het menu van de gereedschapsrail. */
		smal?: boolean;
		canPause?: boolean;
		canResume?: boolean;
		paused?: boolean;
		onPause?: () => void;
		onResume?: () => void;
		onStart: () => void;
		onStop: () => void;
		onFrame?: () => void;
		/** Er ligt iets op het bed én deze machine kan bewegen. */
		canFrame?: boolean;
		/** Het materiaal van het huidige vel — waarín gebrand wordt. Hoort naast
		 *  de machine: die twee samen bepalen elke instelling stroomafwaarts.
		 *  Leeg is een geldige staat en zegt dat ook. */
		material?: string | null;
		thicknessMm?: number | null;
		onOpenMaterial?: () => void;
		onOpenFile?: (file: File) => void;
		onOpenProject?: (file: File) => void;
		/** Opnieuw beginnen. Vraagt zelf om bevestiging als er werk ligt. */
		onNewProject?: () => void;
		/** Na een geslaagde download: de pagina moet zijn "gewijzigd"-vlag opnieuw
		 *  ophalen, want de server heeft het ontwerp dan schoon verklaard. */
		onSaved?: () => void;
		onToggleTheme: () => void;
	} = $props();

	/**
	 * Opslaan gaat door `bewaarBestand` en niet door een kale `<a download>`.
	 *
	 * De link werkt op zichzelf prima, maar de app hoort erna te weten dat het
	 * ontwerp opgeslagen is — anders blijft `dirty` op de client staan en
	 * beweert het volgende venster dat er niet-opgeslagen werk is. Zie
	 * `$lib/opslaan`. De `href` blijft staan, zodat de knop ook zonder
	 * JavaScript een echte link is.
	 */
	async function bewaar(event: MouseEvent, url: string, naam: string) {
		event.preventDefault();
		projectOpen = false;
		if (await bewaarBestand(url, naam)) onSaved?.();
	}

	/**
	 * Het projectmenu.
	 *
	 * Vast gepositioneerd en met de knoppositie mee: de balk scrollt intern
	 * (`overflow-x: auto`), dus een absoluut geplaatst menu wordt afgeknipt op de
	 * balkhoogte en is dan onbruikbaar.
	 */
	let projectOpen = $state(false);
	let projectPos = $state({ x: 0, y: 0 });

	function openProjectMenu(knop: HTMLElement) {
		if (projectOpen) {
			projectOpen = false;
			return;
		}
		const doos = knop.getBoundingClientRect();
		// Uitlijnen op de rechterrand van de knop, maar nooit buiten het scherm.
		const breedte = 250;
		projectPos = {
			x: Math.max(8, Math.min(doos.right - breedte, window.innerWidth - breedte - 8)),
			y: doos.bottom + 6
		};
		projectOpen = true;
	}

	// De bovenbalk staat altijd; hier hangt het meeluisteren naar de
	// schermbreedte, zodat de rest van de app het niet nog eens hoeft te doen.
	$effect(() => apparaat.volg());
	let balkdraagt = $derived(apparaat.bedieningInBalk);

	/**
	 * Zonder server is dit geen bediening meer, en dat moet je zien.
	 *
	 * Dit was gat E1, en het was het gevaarlijkste dat de ronde vond. De Stop in
	 * deze balk bleef klikbaar nadat de server was weggevallen (gemeten op 1440
	 * én 1024: `disabled` bleef `false`), terwijl de Stop ín het Job-paneel wél
	 * uitging. Op tablet draagt deze balk als enige de bediening — daar was dit
	 * dus de énige stopknop, en die deed niets. Je drukt, er gebeurt niets
	 * zichtbaars, en je gelooft dat de machine stopt.
	 *
	 * Een knop die niet aankomt hoort niet te doen alsof. Hij gaat uit, en de
	 * tooltip zegt wat er aan de hand is én wat je dán moet doen: de knop op de
	 * machine. Dat laatste is het halve antwoord; zonder die zin heb je alleen
	 * een dode knop.
	 */
	let weg = $derived(!verbinding.online);
	let stopTitel = $derived(
		weg
			? `${t('transport.noServer')} ${t('transport.noServer.stop')}`
			: stopArmed
				? t('transport.stop.now', { key: STOP_KEY })
				: t('transport.stop.armed', { key: STOP_KEY })
	);
	let pauzeTitel = $derived(
		weg
			? `${t('transport.noServer')} ${t('transport.noServer.pause')}`
			: canPause
				? t('transport.pause.title')
				: t('transport.pause.unsupported')
	);
	let hervatTitel = $derived(
		weg
			? `${t('transport.noServer')} ${t('transport.noServer.resume')}`
			: t('transport.resume.title')
	);
	let startTitel = $derived(
		weg
			? `${t('transport.noServer')} ${t('transport.noServer.start')}`
			: stopArmed
				? t('transport.start.busy')
				: t('transport.start.preflight')
	);

	/**
	 * Sneltoetsen voor pauzeren en stoppen (gat J4).
	 *
	 * LightBurn heeft Pause en Ctrl+Break, en die werken daar zelfs als het
	 * venster niet vooraan staat. Dat laatste kunnen wij niet: een webpagina
	 * krijgt geen toetsaanslagen als hij geen focus heeft, en er is geen browser
	 * die daar een uitzondering voor maakt. Wat wél kan is dit — overal in de
	 * app, op elk tabblad, zonder eerst een paneel te moeten zoeken. Wie de
	 * machine wil kunnen stoppen zónder naar het scherm te kijken, gebruikt de
	 * knop op de machine; dat is ook waar de tooltip naartoe wijst zodra de
	 * server weg is.
	 *
	 * Pause staat niet op elk toetsenbord (Apple levert hem al jaren niet meer),
	 * daarom is er een tweede weg die overal bestaat.
	 */
	function sneltoets(e: KeyboardEvent) {
		// Een open menu sluit met Escape, ook midden in het typen van een naam.
		if (e.key === 'Escape' && projectOpen) {
			projectOpen = false;
			return;
		}
		// Niet ingrijpen terwijl iemand een maat of een naam intypt: daar is
		// Ctrl+. een teken en geen noodrem.
		const doel = e.target as HTMLElement | null;
		if (
			doel?.isContentEditable ||
			['INPUT', 'TEXTAREA', 'SELECT'].includes(doel?.tagName ?? '')
		) {
			return;
		}
		const meta = e.ctrlKey || e.metaKey;
		// Stop: Ctrl/⌘ + punt. Eén hand, geen modus, en vrij in elke browser.
		if (meta && (e.key === '.' || e.code === 'Period')) {
			e.preventDefault();
			if (canStop && !weg) onStop();
			return;
		}
		// Pauze/hervat: de Pause-toets, met of zonder Ctrl (Ctrl+Break stuurt
		// dezelfde `key`). Toggle, want je drukt hem twee keer.
		if (e.key === 'Pause') {
			e.preventDefault();
			if (weg) return;
			if (paused && canResume) onResume?.();
			else if (!paused && canPause && stopArmed) onPause?.();
		}
	}

	// Tijdens het slepen leest `box` de voorvertoning, dus de velden lopen mee.
	// Ze zijn dan niet te bewerken: je bent al aan het slepen.

	// "3 mm", niet "3.0 mm" — en 0,8 mm blijft 0,8 mm.
	// "3mm" aan elkaar: in de balk telt elke pixel, en het leest als één maat.
	// "3 mm", not "3.0 mm" — and in the reader's notation: 3,5 in Dutch, 3.5 in
	// English. Glued to the unit, because every pixel counts in the bar and it
	// reads as one measurement.
	let dikte = $derived(
		thicknessMm === null || thicknessMm === undefined
			? null
			: `${i18n.number(thicknessMm)}mm`
	);
	let materiaalTitel = $derived(
		material
			? dikte
				? t('topbar.material.isThickness', { material, thickness: dikte })
				: t('topbar.material.noThickness', { material })
			: t('topbar.material.none')
	);
</script>

<svelte:window onkeydown={sneltoets} />

<header class="topbar" class:smal class:weg>
	<div class="brand" title={t('app.name')}><Logo /><span class="woord">OpenKerf</span></div>

	<!-- Machine-eerst: de gebruiker weet altijd of de laser "er is". Klikken
	     leidt naar de setup — ook de route als er nog géén machine is. -->
	<!-- Gat B3: xTool toont het apparaat op een tablet als object, met een
	     modelafbeelding. Wij niet, en bewust — zie het rapport bij deze ronde:
	     wij hebben geen artwork per bordfamilie en een verkeerd plaatje boven een
	     Ruida is een bewering over welke machine je aanraakt. Wat de vraag eronder
	     wél verdient — "wélke machine en hoe groot" — staat hier in de tooltip en
	     bij het bed op het canvas, zonder de balk breder te maken (B6 mat dat de
	     ruimte op is). -->
	<a
		class="machine"
		href="/setup"
		title="{device?.label ?? t('topbar.machine.setup')} — {machineStateLabel(machineState)}{device
			?.bed?.width_mm && device?.bed?.height_mm
			? ` · bed ${Math.round(device.bed.width_mm)} × ${Math.round(device.bed.height_mm)} mm`
			: ''}"
	>
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="naam">{device?.label ?? t('topbar.machine.setup')}</span>
		<!-- Het woord bij de toestand stond hier een derde keer: de statusbalk
		     rechtsonder zegt het voluit, en de gekleurde stip zegt het hier al.
		     Die 55px zijn de ruimte waarin het materiaal past — en zonder die
		     ruimte schuift de startknop van het scherm af. Op tablet was dit om
		     dezelfde reden al verborgen. -->
		<span class="muted toestand">{machineStateLabel(machineState)}</span>
	</a>

	<!-- Waarmee (machine) en waarín (materiaal) horen naast elkaar: samen
	     bepalen ze elke instelling die hierna volgt. Het materiaal hing tot nu
	     toe in een filter in een venster dat je weer sluit — zie besluit B1. -->
	<button
		class="machine materiaal"
		class:leeg={!material}
		disabled={!canEdit}
		title={materiaalTitel}
		onclick={onOpenMaterial}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5 12 4l9 4.5-9 4.5z"/><path d="M3 8.5V15l9 4.5 9-4.5V8.5"/></svg>
		<!-- Op een smalle tablet is "Materiaal kiezen" 49px die de startknop van
		     het scherm duwen. Eén woord naast een streepjesrand en een plankje
		     nodigt net zo goed uit, en de hele zin staat in de tooltip. -->
		<span class="naam">{material ?? (smal ? t('topbar.material.short') : t('topbar.material.choose'))}</span>
		{#if dikte}<span class="dikte mono">{dikte}</span>{/if}
	</button>

	<div class="spacer"></div>

	<!-- Openen en opslaan van het project: één knop, op elke breedte.
	     Twee losse knoppen mét woord kostten 310px, en die waren er onder 1600
	     niet — dan stonden ze alleen nog in het menu van de gereedschapsrail, en
	     daar vond de gebruiker ze twee ronden lang niet ("ik zie alleen
	     exporteren en importeren"). Besluit "project is leidend" staat; alleen de
	     uitvoering deugde niet.
	     Deze knop kost 106px met woord en 44px zonder, dus hij past ook op 768
	     naast de noodrem (gemeten met c7-balk). Het woord "Project" staat er in
	     beeld bij: dát is wat er ontbrak — niet de handeling, maar het bestaan
	     van het begrip in de balk. -->
	<button
		class="btn project-knop"
		aria-haspopup="menu"
		aria-expanded={projectOpen}
		aria-label={t('topbar.project.aria')}
		title={t('topbar.project.title')}
		onclick={(e) => openProjectMenu(e.currentTarget as HTMLElement)}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/></svg>
		<!-- Zonder `blijft`: onder 1200px valt het woord weg, net als bij de andere
		     bestandsknoppen. Gemeten met c7-balk: mét woord loopt de balk op 768
		     44px over de rand en dan schuift de startknop van het scherm. Een map
		     met een pijltje omlaag is op die breedte het menu-idioom, en de
		     tooltip en het aria-label dragen het woord. -->
		<span class="btn-label">{t('topbar.project')}</span>
		<svg class="pijl" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
	</button>

	{#if projectOpen}
		<!-- `position: fixed`, want de balk zelf scrollt intern (`overflow-x`) en
		     zou een absoluut menu afknippen. -->
		<div class="afdek" role="presentation" onclick={() => (projectOpen = false)}></div>
		<div class="projectmenu" role="menu" style="left: {projectPos.x}px; top: {projectPos.y}px">
			<!-- Opslaan en openen stonden hier al, opnieuw beginnen niet: je kon
			     alleen aan iets nieuws beginnen door alles met de hand weg te
			     halen. Boven het paar, want het is de eerste handeling van een
			     sessie — en het vraagt eerst, net als openen. -->
			<button
				class="regel"
				role="menuitem"
				type="button"
				onclick={() => {
					projectOpen = false;
					onNewProject?.();
				}}
			>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M12 11v6m-3-3h6"/></svg>
				<span>{t('topbar.project.new')}</span>
			</button>
			<span class="menuscheiding" role="separator"></span>
			<!-- Een label met een verborgen bestandsveld erin: geen `menuitem`-rol,
			     want het invoerveld is al het bedienbare element. -->
			<label class="regel">
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 18v-5m0 0-2 2m2-2 2 2"/></svg>
				<span>{t('topbar.project.open')}</span>
				<input
					type="file"
					aria-label={t('topbar.project.pick')}
					accept=".openkerf,.zip"
					onchange={(e) => {
						const input = e.currentTarget as HTMLInputElement;
						const file = input.files?.[0];
						input.value = '';
						projectOpen = false;
						if (file) onOpenProject?.(file);
					}}
				/>
			</label>
			<a
				class="regel"
				role="menuitem"
				href="/api/project/export.openkerf"
				download="project.openkerf"
				onclick={(e) => bewaar(e, '/api/project/export.openkerf', 'project.openkerf')}
			>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 13v5m0 0-2-2m2 2 2-2"/></svg>
				<span>{t('topbar.project.save')}</span>
			</a>
			<p class="uitleg">{t('topbar.project.hint')}</p>
		</div>
	{/if}

	<span class="scheiding docs" aria-hidden="true"></span>
	<label class="btn file docs" title={t('topbar.import.title')}>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 17v-5m0 0-2 2m2-2 2 2"/></svg>
		<span class="btn-label">{t('topbar.import')}</span>
		<input
			type="file"
			aria-label={t('topbar.import.aria')}
			accept=".svg,.dxf,.rd,.egv,.gcode,.nc,.lbrn,.lbrn2,.ezd,.xcs,.png,.jpg,.jpeg,.gif,.bmp"
			onchange={(e) => {
				const input = e.currentTarget as HTMLInputElement;
				const file = input.files?.[0];
				input.value = '';
				if (file) onOpenFile?.(file);
			}}
		/>
	</label>

	<!-- Opslaan als SVG: MeerK40t's eigen schrijver, dus operaties komen bij
	     terugladen weer mee. -->
	<a
		class="btn docs"
		href="/api/design/export.svg"
		download="ontwerp.svg"
		title={t('topbar.export.title')}
		onclick={(e) => bewaar(e, '/api/design/export.svg', 'ontwerp.svg')}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11l3 3v13H5z"/><path d="M12 9v6m0 0-2.5-2.5M12 15l2.5-2.5"/></svg>
		<span class="btn-label">{t('topbar.export')}</span>
	</a>

	<!-- De laatste controle vóór je brandt: past het, ligt het recht, zit de
	     klem in de weg. De laser blijft uit. -->
	<button
		class="btn kader"
		disabled={!canFrame || weg}
		title={weg
			? `${t('transport.noServer')} ${t('topbar.frame.noServer')}`
			: canFrame
				? t('topbar.frame.title')
				: t('topbar.frame.off')}
		onclick={onFrame}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="4 3"/></svg>
		<!-- The word stays even on a tablet, because there this is a first-class
		     action and a thin dashed square says nothing. On a narrow bar only the
		     short form is left. Two whole labels rather than a word plus a
		     fragment: "show" on its own is not translatable, and in some languages
		     it does not even come second. -->
		<span class="btn-label blijft lang">{t('topbar.frame')}</span>
		<span class="btn-label blijft kort">{t('topbar.frame.short')}</span>
	</button>
	<!--
		Pauzeren hoort naast starten en stoppen, op elke breedte.

		Dit stond achter `balkdraagt`, dus op de desktop droeg de bovenbalk wél
		start en stop maar níet pauze — die stond in de statusbalk, onderaan het
		scherm. Twee van de drie transportknoppen bij elkaar en de derde ergens
		anders is de soort inconsistentie waar je pas achter komt op het moment dat
		je hem nodig hebt. De statusbalk houdt de voortgang (die hoort daar: hij
		geldt voor de hele app) en is zijn knoppen kwijt.

		Hij houdt zijn plek ook als er niets loopt: een knop die verspringt zodra de
		job start is precies op dat moment onvindbaar.
	-->
		{#if paused}
			<button
				class="btn hervat"
				disabled={!canResume || weg}
				title={hervatTitel}
				onclick={onResume}
			>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
				<span class="btn-label blijft">{t('transport.resume')}</span>
			</button>
		{:else}
			<button
				class="btn pauze"
				disabled={!canPause || !stopArmed || weg}
				title={pauzeTitel}
				onclick={onPause}
			>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="5.5" width="3.5" height="13" rx="1"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1"/></svg>
				<span class="btn-label blijft">{t('transport.pause')}</span>
			</button>
		{/if}
	<!-- Stoppen kan altijd, overal, in één tik. Vol rood alleen als er ook echt
	     iets loopt: een knop die uren per dag alarm staat te slaan zonder reden
	     leert de gebruiker hem te negeren, en dan mist hij hem als het telt. -->
	<!-- Weggevallen server: geen rood, geen vulling, en het woord zegt waar de
	     stop dán zit. Een tooltip is hier geen antwoord — op de tablet, waar dit
	     de enige stopknop is, bestaat hover niet. -->
	<button
		class="btn danger"
		class:sluimer={!stopArmed && !weg}
		class:dood={weg}
		disabled={!canStop || weg}
		onclick={onStop}
		title={stopTitel}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
		<span class="btn-label blijft"
			>{weg ? t('transport.stop.onMachine') : t('transport.stop')}</span
		>
	</button>
	<!-- Opent geen dialoog maar de pre-flight in het rechterpaneel. -->
	<button
		class="btn primary"
		disabled={!canStart || weg}
		title={startTitel}
		onclick={onStart}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
		<!-- Two whole labels: on a narrow bar the short one, otherwise the long
		     one. Gluing "job" onto "Start" made the button read "Startjob" the
		     moment Svelte trimmed the leading space, and it is not a fragment a
		     translator can do anything with. -->
		<span class="btn-label blijft lang">{t('transport.start')}</span>
		<span class="btn-label blijft kort">{t('transport.start.short')}</span>
	</button>
	<LanguagePicker />
	<button class="iconbtn" onclick={onToggleTheme} title={t('topbar.theme')} aria-label={t('topbar.theme')}>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
	</button>
</header>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		/* Zonder deze twee duwt de knoppenrij de héle pagina breder dan het
		   scherm — op een tablet scroll je dan horizontaal langs je eigen app. */
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.topbar::-webkit-scrollbar { display: none; }
	/* Een knop die je weg kunt scrollen is geen knop. De balk mag daarom niets
	   uitdelen wat er niet in past: alles krijgt `flex: none`, en wat er op 768
	   niet bij kan verhuist naar het menu van de rail (klasse `docs`). */
	.topbar > :global(*) { flex: none; }

	/* Smal scherm: knoppen tonen alleen hun icoon. De titel staat in de
	   tooltip en het aria-label, dus er gaat geen betekenis verloren.
	   De grens ligt op 1200px, niet op 900: op een tablet van 1024 breken de
	   labels anders over twee regels en groeit de balk mee. */
	@media (max-width: 1199px) {
		.kader .kort { display: inline; }
		/* De knoppen die de machine aansturen houden hun woord: een rood
		   vierkantje zonder tekst is geen noodstop. */
		.topbar :global(.btn-label:not(.blijft)) { display: none; }
		/* The frame keeps its word — on a tablet this is a first-class action and a
		   thin dashed square says nothing — but only the short form: "Frame" next to
		   that square is unambiguous. */
		.kader .lang { display: none; }
		/* Het hele merk gaat weg, woord én beeld.
		   Het woordmerk kostte al 100px; het beeldmerk kost er nog 108 met zijn
		   gap (gemeten), en die zijn hier meer waard dan een logo. Op een tablet
		   weet je welke app je open hebt — je hebt hem net aangetikt — en de
		   gereedschapsrail links draagt de identiteit al. Deze balk draagt op
		   tablet als enige de noodrem én het kader; dat weegt zwaarder dan een
		   merkteken. Dít is de ruimte waaruit het kader terugkomt. */
		.topbar .brand { display: none; }
		/* 44px: dit is de route naar de setup en was met 38px het enige doel in
		   de balk dat de handschoenmaat niet haalde. Alleen op tablet: op de
		   desktop staat hij naast knoppen van 37px en zou hij uitsteken. */
		.machine {
			min-height: 44px;
			padding: 0 var(--space-2);
		}
		/* Een machinenaam kan willekeurig lang zijn en duwde op 768 de startknop
		   van het scherm. Alleen de machinelink: `a.machine`, niet `.machine` —
		   de materiaalchip draagt dezelfde klasse en heeft zijn eigen maat. */
		a.machine .naam {
			max-width: 10ch;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
		/* De dikte blijft staan — 3 mm berken snijdt anders dan 6 mm — en de naam
		   krijgt de ruimte die overblijft. Het icoontje levert die ruimte in: de
		   naam van je materiaal zegt meer dan een plankje van 16px. */
		.materiaal svg { display: none; }
	}
	/* Onder 850px verliest het kader zijn woord alsnog.
	   Gemeten met de langste namen die deze balk kan krijgen ("Thunder Nova 51
	   werkplaats" en "Multiplex berken transparant 18,5mm"): die 40px persen de
	   materiaalnaam op 768 samen tot 15px — één letter en een puntje. Dat is de
	   verkeerde ruil. Waarín je brandt bepaalt samen met de machine élke
	   instelling die daarna volgt (besluit B1) en heeft geen vervanging; het
	   kader heeft zijn gestippelde vierkantje, zijn vaste plek naast de
	   bediening en zijn tooltip. Zonder dat woord houdt de naam 64px. */
	@media (max-width: 849px) {
		.topbar .kader .btn-label { display: none; }
		/* En zonder server valt op 768 ook de materiaalnaam weg.
		   "Stop op de machine" is 60px breder dan "Stop", en het materiaal is het
		   enige buigzame ding in deze balk, dus het betaalde die 60px met zijn
		   naam: er stond "B  3mm" en dat is geen chip maar een restant.
		   Dan liever expliciet weg. Op het moment dat de server eruit ligt is het
		   materiaal onveranderlijk en niet waar je naar kijkt; de enige vraag is
		   waar de stop zit, en dat antwoord mag de hele breedte hebben. Boven
		   850px blijft de chip staan — daar is de ruimte er (gemeten). */
		.topbar.weg .materiaal { display: none; }
	}
	/* Daar houdt de projectknop op.
	   Hij is de enige knop in deze balk die geen machinehandeling is, en het
	   materiaal is het enige buigzame ding ernaast: gemeten kromp de
	   materiaalnaam van 63px naar 40px op 850 en naar 7px op 768 zodra deze knop
	   erbij stond — "M…", en dat is geen chip meer. Vanaf 880 is er ruimte voor
	   allebei (gemeten: 63px, geen krimp). Waarín je brandt weegt zwaarder
	   (besluit B1) dan iets wat je aan het begin en eind van een sessie doet.
	   Onder deze breedte staat het project in het menu van de gereedschapsrail,
	   mét zijn woord — zie `projectInRail` in +page.svelte. Daarboven staat het
	   in de balk, en dát is de verbetering: de grens lag op 1600, en daar vond de
	   gebruiker het twee ronden lang niet. */
	@media (max-width: 879px) {
		.topbar .project-knop { display: none; }
	}
	/* Onder ~950px verdwijnen de bestandsknoppen; het materiaal blijft, want het
	   hoort bij wat er straks gebeurt. Alleen krapper. */
	/* Was 8ch op de hele tabletbreedte, toen het merk nog 120px kostte. Dat merk
	   is weg, en die ruimte gaat naar de twee chips die samen elke instelling
	   bepalen (besluit B1): achter "Multiple…" kun je niet zien of je in
	   multiplex brandt of in multiplex met een folie erop.
	   Gemeten met "Thunder Nova 51 werkplaats" én "Multiplex berken transparant
	   18,5mm", de langste namen die deze balk kan krijgen: op 850 en hoger past
	   het met 56px over, en op 768 vangt het `flex: 0 1 auto` hieronder het
	   verschil op — de chip krimpt naar 137px en de naam naar 64px, interne
	   overloop 0, laatste knop op 756 van 768. Een extra mediaquery voor het
	   smalste geval was daarmee overbodig: het vangnet dóet zijn werk. */
	.topbar.smal .materiaal .naam { max-width: 10ch; }
	/* Kaderen blíjft op tablet in beeld.
	   Hij stond hier op `display: none` onder 950px, met het argument dat hij ook
	   in de pre-flight woont. Dat argument klopt niet voor dít apparaat: de tablet
	   is het scherm dat naast de machine ligt, en kaderen is de laatste controle
	   die je dáár uitvoert — met je hand op het werkstuk, niet vanaf een
	   bureaustoel. Een actie die je uitsluitend naast de machine doet hoort op het
	   apparaat dat daar ligt, niet in een paneel dat dichtgeklapt kan zijn.
	   De ruimte komt van het merk (zie de tabletregel hierboven). */
	/* Vangnet voor wat hierna nog in deze balk komt: de machinebediening staat
	   vast (`flex: none` hierboven), maar het materiaal mag als laatste redmiddel
	   krimpen in plaats van de startknop van het scherm te duwen. */
	/* Vangnet voor wat hierna nog in deze balk komt: de machinebediening staat
	   vast (`flex: none` hierboven), maar het materiaal mag als laatste redmiddel
	   krimpen in plaats van de startknop van het scherm te duwen. Gemeten op 768
	   met de langste namen die mogelijk zijn: de chip zakt naar 137px en de naam
	   naar 64px — afgekapt maar leesbaar, en de balk loopt niet over.
	   Ik heb hier een ondergrens van 9rem geprobeerd en weer weggehaald: hij deed
	   niets, want tokens.css zet in zijn coarse-pointerblok `min-width: 44px` op
	   elke knop met een selector die deze verslaat. Een regel die niets doet maar
	   wel iets belooft, is erger dan geen regel. */
	.materiaal { flex: 0 1 auto; min-width: 0; }
	.materiaal .naam { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* Een afgekapte materiaalnaam is jammer maar leesbaar via de tooltip; een
	   afgekapte uitnodiging ("Materiaa…") is onbegrijpelijk. Deze selector moet
	   de regel hierboven verslaan, dus staat de hele keten erin. */
	.topbar.smal .materiaal.leeg .naam { max-width: none; }
	/* Het projectpaar is één knop met een menu geworden.
	   Vier bestandsknoppen mét label kosten 560px en pasten op 1440 niet naast
	   machine, materiaal en bediening; het projectpaar week toen uit naar het
	   railmenu. Dat was te ver weg — de gebruiker vond ze twee ronden lang niet.
	   Eén knop "Project" kost 106px, past overal, en houdt het woord in beeld.
	   Importeren en exporteren blijven losse knoppen: dát is wat je tijdens het
	   werken doet. */
	.project-knop .pijl { color: var(--text-2); margin-left: -2px; }
	.afdek {
		position: fixed;
		inset: 0;
		z-index: 39;
	}
	.projectmenu {
		position: fixed;
		width: 250px;
		padding: var(--space-2);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		z-index: 40;
	}
	.projectmenu .regel {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		/* Ook met een handschoen aan te raken. */
		min-height: 44px;
		padding: 0 var(--space-2);
		border-radius: var(--radius-field);
		color: var(--text-1);
		text-align: left;
		text-decoration: none;
		cursor: pointer;
		transition: background var(--transition);
		/* De rij is een label, een link én een knop; die laatste brengt zijn
		   eigen achtergrond, rand en lettertype mee. */
		background: none;
		border: 0;
		font: inherit;
	}
	.projectmenu .regel svg { flex: none; color: var(--text-2); }
	.projectmenu .menuscheiding {
		display: block;
		height: 1px;
		margin: var(--space-2) var(--space-2);
		background: var(--line);
	}
	.projectmenu .regel:hover,
	.projectmenu .regel:focus-within { background: var(--surface-2); }
	.projectmenu input[type='file'] {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
	}
	/* Wat er in dat bestand zit, één keer, hier — niet in een tooltip die op een
	   aanraakscherm niet bestaat. */
	.projectmenu .uitleg {
		margin: var(--space-2) 0 0;
		padding: 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Onder ~950px is er geen ruimte meer voor bestandsacties náást de
	   machinebediening. De machine wint; de bestanden staan dan in het menu van
	   de gereedschapsrail, één tik verderop. */
	.topbar.smal .docs { display: none; }
	/* Narrow bar: the short label, wide bar: the long one. Two whole labels, so a
	   translation is never half a sentence. */
	.btn-label.kort { display: none; }
	.topbar.smal .btn.primary .lang { display: none; }
	.topbar.smal .btn.primary .kort { display: inline; }
	/* Het project en de losse bestanden zijn twee soorten handelingen; een
	   haarlijn zegt dat zonder woorden. */
	.scheiding {
		width: 1px;
		align-self: stretch;
		margin: 8px 4px;
		background: var(--line);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
		letter-spacing: -0.01em;
	}
	.machine {
		white-space: nowrap;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 8px var(--space-2);
		border-radius: var(--radius-field);
		/* Onzichtbaar, maar aanwezig: de lege materiaalknop krijgt een streepjes-
		   rand, en zonder deze regel verspringt de balk 2px zodra je er een
		   materiaal in zet. */
		border: 1px solid transparent;
		background: var(--surface-2);
		color: inherit;
		text-decoration: none;
		transition: background var(--transition);
	}
	/* --line is een randkleur, afgestemd op oppervlakken die tegen elkaar aan
	   liggen; als vulling onder tekst haalt --text-2 erop 4,05 in licht en 3,49
	   in donker. --hover is een doorschijnende sluier en werkt op élk oppervlak.
	   Gat D9, gemeld door de thema-agent. */
	.machine:hover {
		background: var(--hover);
	}
	.muted {
		color: var(--text-2);
	}
	/* Nog niets gekozen is geen fout, dus geen rood en geen uitroepteken. Een
	   onderbroken rand zegt "hier hoort nog iets in te vullen" en verder niets;
	   zodra er een materiaal staat, wordt het een gewone chip. */
	.materiaal.leeg {
		background: transparent;
		/* --line is afgestemd op vlakken die tegen elkaar aan liggen; als losse
		   streepjesrand op de balk verdwijnt hij. Dezelfde secundaire tekstkleur,
		   verdund, houdt hem zichtbaar zonder alarm te slaan. */
		border: 1px dashed color-mix(in srgb, var(--text-2) 45%, transparent);
		color: var(--text-2);
	}
	/* "Materiaal kiezen" is korter dan een materiaalnaam en mag heel blijven:
	   afgekapt tot "Materiaal…" is het geen uitnodiging meer. */
	.materiaal.leeg .naam { max-width: none; }
	.materiaal.leeg:hover:not(:disabled) { color: var(--text-1); }
	.materiaal:disabled { cursor: not-allowed; }
	.materiaal svg { color: var(--text-2); flex: none; }
	.materiaal .naam {
		max-width: 14ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* De dikte is het halve antwoord en mag niet wegvallen, maar hij hoeft ook
	   niet even zwaar te wegen als de naam. */
	.dikte { color: var(--text-2); font-size: var(--text-xs); }
	.toestand { display: none; }
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		flex: none;
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }
	.spacer { flex: 1; }
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		transition: background var(--transition);
	}
	.btn { text-decoration: none; color: inherit; }
	.btn.file { cursor: pointer; }
	.btn.file input { display: none; }
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.primary:hover:not(:disabled) { background: var(--accent); filter: brightness(1.06); }
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
		/* Stop en Start job zijn de twee tegengestelde acties van deze balk en
		   stonden 12px uit elkaar. De balk-gap is 12, dus deze marge maakt er 24
		   van — het minimum uit DESIGN-SYSTEM v2 voor doelen met tegengestelde
		   gevolgen. */
		margin-right: var(--space-3);
	}
	.btn.danger:hover:not(:disabled) { background: var(--danger-solid); filter: brightness(1.06); }
	/* Pauze en stop hebben tegengestelde gevolgen — de een bewaart je werkstuk,
	   de ander gooit het weg. Dus ook hier 24px, net als in de statusbalk. */
	.btn.hervat,
	.btn.pauze { margin-right: var(--space-3); }
	.btn.hervat {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	/* Sluimerend: herkenbaar als de stopknop (rode rand, rood vierkant), maar
	   niet als alarm. Bij een lopende job wint de gevulde variant hierboven. */
	.btn.danger.sluimer {
		background: var(--surface-1);
		border-color: var(--danger-solid);
		/* Het woord in gewone tekstkleur, het icoon in rood: --danger op
		   --surface-1 haalt in het donkere thema 4,4:1 en dat is te weinig voor
		   tekst. De rode rand plus het rode vierkantje dragen de betekenis. */
		color: var(--text-1);
	}
	.btn.danger.sluimer svg { color: var(--danger); }
	.btn.danger.sluimer:hover:not(:disabled) {
		background: var(--danger-solid);
		color: var(--on-color);
		filter: none;
	}
	.btn.danger.sluimer:hover:not(:disabled) svg { color: inherit; }
	/* De knop die niet aankomt.
	   Niet "rood maar vaag": een vervaagde noodstop leest nog steeds als een
	   noodstop, en dat is precies de belofte die hier niet waargemaakt kan
	   worden. Dus geen rood meer, een onderbroken rand — hetzelfde teken dat de
	   lege materiaalknop draagt voor "hier staat nog niets" — en het woord dat
	   zegt waar de stop wél zit. `opacity` blijft weg: de tekst moet leesbaar
	   zijn, want hij is nu het bericht. */
	.btn.danger.dood {
		background: transparent;
		border: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		color: var(--text-2);
		opacity: 1;
	}
	.btn.danger.dood svg { color: var(--text-2); }

	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	/* Deze knop dráágt zijn eigen uitleg; de standaard-vervaging maakt hem
	   onleesbaar en die uitleg is nu het enige wat de knop nog doet. */
	.btn.danger.dood:disabled { opacity: 1; }

	.iconbtn {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		transition: background var(--transition);
	}
	.iconbtn:hover { background: var(--surface-2); color: var(--text-1); }
</style>
