<script lang="ts">
	import { STATE_LABEL, type Device, type MachineState } from '$lib/api';
	import Logo from './Logo.svelte';

	let {
		device,
		state: machineState,
		canStart,
		canStop,
		stopArmed = false,
		canEdit = false,
		tablet = false,
		smal = false,
		krap = false,
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
		/** Tablet 768–1199: hier hoort de machinebediening, want het paneel kan
		 *  ingeklapt zijn en de statusbalk past niet op 768. */
		tablet?: boolean;
		/** Onder ~950px passen de bestandsknoppen er niet meer bij; ze staan dan
		 *  in het menu van de gereedschapsrail. */
		smal?: boolean;
		/** Onder ~1500px is er geen ruimte voor vier bestandsknoppen mét woord
		 *  náást machine, materiaal en de bediening. Ze houden hun icoon, hun
		 *  tooltip en hun plek; alleen het woord gaat weg. */
		krap?: boolean;
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
		onToggleTheme: () => void;
	} = $props();

	// Tijdens het slepen leest `box` de voorvertoning, dus de velden lopen mee.
	// Ze zijn dan niet te bewerken: je bent al aan het slepen.

	// "3 mm", niet "3.0 mm" — en 0,8 mm blijft 0,8 mm.
	// "3mm" aan elkaar: in de balk telt elke pixel, en het leest als één maat.
	let dikte = $derived(
		thicknessMm === null || thicknessMm === undefined
			? null
			: `${String(thicknessMm).replace('.', ',')}mm`
	);
	let materiaalTitel = $derived(
		material
			? `Dit vel is ${material}${dikte ? `, ${dikte}` : ' (dikte niet ingevuld)'} — klik om te wijzigen`
			: 'Nog geen materiaal gekozen voor dit vel — klik om het in te vullen'
	);
</script>

<header class="topbar" class:smal class:krap>
	<div class="brand" title="OpenKerf"><Logo /><span class="woord">OpenKerf</span></div>

	<!-- Machine-eerst: de gebruiker weet altijd of de laser "er is". Klikken
	     leidt naar de setup — ook de route als er nog géén machine is. -->
	<a class="machine" href="/setup" title="{device?.label ?? 'Machine instellen'} — {STATE_LABEL[machineState]}">
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="naam">{device?.label ?? 'Machine instellen'}</span>
		<!-- Het woord bij de toestand stond hier een derde keer: de statusbalk
		     rechtsonder zegt het voluit, en de gekleurde stip zegt het hier al.
		     Die 55px zijn de ruimte waarin het materiaal past — en zonder die
		     ruimte schuift de startknop van het scherm af. Op tablet was dit om
		     dezelfde reden al verborgen. -->
		<span class="muted toestand">{STATE_LABEL[machineState]}</span>
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
		<span class="naam">{material ?? 'Materiaal kiezen'}</span>
		{#if dikte}<span class="dikte mono">{dikte}</span>{/if}
	</button>

	<div class="spacer"></div>

	<!-- Openen hoort naast opslaan: in de Job-tab vindt niemand het. -->
	<label class="btn file docs project" title="Project openen (ontwerp + bibliotheek)">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 18v-5m0 0-2 2m2-2 2 2"/></svg>
		<span class="btn-label">Project openen</span>
		<input
			type="file"
			aria-label="Bestand kiezen"
			accept=".openkerf,.zip"
			onchange={(e) => {
				const input = e.currentTarget as HTMLInputElement;
				const file = input.files?.[0];
				input.value = '';
				if (file) onOpenProject?.(file);
			}}
		/>
	</label>
	<a class="btn docs project" href="/api/project/export.openkerf" download="project.openkerf" title="Project opslaan">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 13v5m0 0-2-2m2 2 2-2"/></svg>
		<span class="btn-label">Project opslaan</span>
	</a>

	<span class="scheiding docs project" aria-hidden="true"></span>
	<label class="btn file docs" title="Bestand in dit vel importeren — SVG, DXF, RD, G-code of een afbeelding">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 17v-5m0 0-2 2m2-2 2 2"/></svg>
		<span class="btn-label">Importeren</span>
		<input
			type="file"
			aria-label="Bestand kiezen"
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
	<a class="btn docs" href="/api/design/export.svg" download="ontwerp.svg" title="Dit vel opslaan als SVG">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11l3 3v13H5z"/><path d="M12 9v6m0 0-2.5-2.5M12 15l2.5-2.5"/></svg>
		<span class="btn-label">Exporteren</span>
	</a>

	<!-- De laatste controle vóór je brandt: past het, ligt het recht, zit de
	     klem in de weg. De laser blijft uit. -->
	<button
		class="btn"
		disabled={!canFrame}
		title={canFrame ? 'De kop langs de omtrek van je werk sturen, zonder te branden' : 'Er ligt niets op het bed, of deze machine kan niet bewegen'}
		onclick={onFrame}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="4 3"/></svg>
		<span class="btn-label">Kader tonen</span>
	</button>
	{#if tablet}
		<!-- Op de tablet kan het paneel dicht zijn en past de statusbalk op 768
		     niet; dan stond de pauzeknop nergens. Hij houdt zijn plek ook als er
		     niets loopt: een knop die verspringt zodra de job start is precies op
		     dat moment onvindbaar. -->
		{#if paused}
			<button
				class="btn hervat"
				disabled={!canResume}
				title="Verder waar hij gebleven was"
				onclick={onResume}
			>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
				<span class="btn-label blijft">Hervat</span>
			</button>
		{:else}
			<button
				class="btn pauze"
				disabled={!canPause || !stopArmed}
				title={canPause
					? 'Job pauzeren — de kop stopt, de job blijft staan'
					: 'Deze machine kent geen pauze — gebruik de knop op de machine'}
				onclick={onPause}
			>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="5.5" width="3.5" height="13" rx="1"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1"/></svg>
				<span class="btn-label blijft">Pauze</span>
			</button>
		{/if}
	{/if}
	<!-- Stoppen kan altijd, overal, in één tik. Vol rood alleen als er ook echt
	     iets loopt: een knop die uren per dag alarm staat te slaan zonder reden
	     leert de gebruiker hem te negeren, en dan mist hij hem als het telt. -->
	<button
		class="btn danger"
		class:sluimer={!stopArmed}
		disabled={!canStop}
		onclick={onStop}
		title={stopArmed ? 'Job direct afbreken' : 'Er loopt nu niets — dit breekt een job af zodra er een loopt'}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
		<span class="btn-label blijft">Stop</span>
	</button>
	<!-- Opent geen dialoog maar de pre-flight in het rechterpaneel. -->
	<button
		class="btn primary"
		disabled={!canStart}
		title={stopArmed ? 'Er loopt al een job' : 'De pre-flight openen'}
		onclick={onStart}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
		<!-- De spatie staat als entity in de span: Svelte knipt leidende witruimte
		     binnen een element weg, en dan las de knop "Startjob". -->
		<span class="btn-label blijft">Start<span class="job">&nbsp;job</span></span>
	</button>
	<button class="iconbtn" onclick={onToggleTheme} title="Thema wisselen" aria-label="Thema wisselen">
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
		/* De knoppen die de machine aansturen houden hun woord: een rood
		   vierkantje zonder tekst is geen noodstop. */
		.topbar :global(.btn-label:not(.blijft)) { display: none; }
		/* Het woordmerk kost 100px die de machineknoppen nodig hebben; het
		   beeldmerk blijft en zegt hetzelfde. */
		.brand .woord { display: none; }
		/* Een machinenaam kan willekeurig lang zijn en duwde op 768 de startknop
		   van het scherm. */
		/* 44px: dit is de route naar de setup en was met 38px het enige doel in
		   de balk dat de handschoenmaat niet haalde. Alleen op tablet: op de
		   desktop staat hij naast knoppen van 37px en zou hij uitsteken. */
		.machine {
			min-height: 44px;
			padding: 0 var(--space-2);
		}
		.machine .naam {
			max-width: 15ch;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
		/* De dikte blijft staan — 3 mm berken snijdt anders dan 6 mm — en de naam
		   krijgt de ruimte die overblijft. Het icoontje levert die ruimte in: de
		   naam van je materiaal zegt meer dan een plankje van 16px. */
		.materiaal svg { display: none; }
		.materiaal .naam { max-width: 13ch; }
	}
	/* Onder ~950px verdwijnen de bestandsknoppen; het materiaal blijft, want het
	   hoort bij wat er straks gebeurt. Alleen krapper. */
	.topbar.smal .materiaal .naam { max-width: 8ch; }
	/* Een afgekapte materiaalnaam is jammer maar leesbaar via de tooltip; een
	   afgekapte uitnodiging ("Materiaa…") is onbegrijpelijk. Deze selector moet
	   de regel hierboven verslaan, dus staat de hele keten erin. */
	.topbar.smal .materiaal.leeg .naam { max-width: none; }
	/* Vier bestandsknoppen mét label kosten 560px; dat paste zolang de balk
	   verder alleen de machine droeg. Met het materiaal erbij (besluit B1) liep
	   hij op 1440 — onze eigen maat — over de rand, en dan staat de startknop
	   buiten beeld.

	   Niet de woorden weghalen maar het projectpaar: vier naamloze icoontjes
	   waarvan er twee een doos met een pijltje zijn, is geen balk maar een
	   raadsel. Openen en opslaan van het hele project staan in het menu van de
	   gereedschapsrail, met hun woord erbij; importeren en exporteren — wat je
	   tijdens het werken doet — houden hier hun naam. */
	.topbar.krap .project { display: none; }
	/* Onder ~950px is er geen ruimte meer voor bestandsacties náást de
	   machinebediening. De machine wint; de bestanden staan dan in het menu van
	   de gereedschapsrail, één tik verderop. */
	.topbar.smal .docs { display: none; }
	.topbar.smal .btn.primary .job { display: none; }
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
	.machine:hover {
		background: var(--line);
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
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
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
