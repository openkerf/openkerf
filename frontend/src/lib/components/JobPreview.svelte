<script lang="ts">
	/**
	 * Wat er gebrand wordt, vlak voordat je op starten drukt (besluit B8).
	 *
	 * Het canvas staat er op tablet en telefoon niet naast, en op de desktop
	 * kijk je er vlak vóór het starten toch niet meer naar. Dit is het laatste
	 * moment waarop een verkeerde laag, een vergeten vorm of iets dat over de
	 * rand van het vel hangt nog niets kost.
	 *
	 * Bewust géén snijvolgorde: die vraagt het volledige snijplan, en juist dat
	 * plan bouwen was de reden dat de pre-flight minuten stilstond (gat J1).
	 * Zie BESLISSINGEN.md, B8.
	 */
	import type { Design } from '$lib/design.svelte';
	import Dialog from './Dialog.svelte';

	/** De tekening op ware grootte, in een eigen venster. */
	let groot = $state(false);

	// Een SVG-pattern heeft een id, en twee weergaven op één pagina mogen niet
	// dezelfde dragen — dan pakt de tweede het patroon van de eerste.
	const eigenId = $props.id();

	/**
	 * Wat de server over de grenzen meldt (gat C2).
	 *
	 * De meting komt uit `/api/job/layers`, dezelfde die het canvas en de
	 * telefoon gebruiken. Hem hier overdoen zou betekenen dat twee plekken
	 * kunnen gaan verschillen over de vraag of iets nog net past — en dan is
	 * geen van beide te vertrouwen.
	 */
	type BoundsReport = {
		bed: { width_mm: number; height_mm: number } | null;
		sheet: { width_mm: number; height_mm: number } | null;
		work: { x_mm: number; y_mm: number; width_mm: number; height_mm: number } | null;
		outside_bed: number;
		outside_sheet: number;
		outside_bed_ids: string[];
		outside_sheet_ids: string[];
	};

	let {
		design,
		sheet,
		bounds = null,
		colorFor
	}: {
		design: Design | null;
		/** Het vel waarop gebrand wordt; zonder vel valt hij terug op het werk zelf. */
		sheet: { name: string; width_mm: number; height_mm: number } | null;
		bounds?: BoundsReport | null;
		colorFor?: (operationId: string | null) => string;
	} = $props();

	const GRIJS = 'var(--text-2)';

	/** Lagen die meebranden. Een laag met "meebranden" uit hoort hier niet in:
	 *  dat is precies het verschil dat deze weergave zichtbaar moet maken. */
	let brandende = $derived(
		new Set((design?.operations ?? []).filter((o) => o.output).map((o) => o.id))
	);

	type Vorm = {
		id: string;
		path: string;
		image: { x: number; y: number; w: number; h: number } | null;
		kleur: string;
		/** Zit in geen enkele meebrandende laag: wordt niet gebrand. */
		stil: boolean;
		/** Steekt buiten het vel uit: daar ligt geen materiaal. */
		buiten: boolean;
		/** Ligt buiten het bed: daar komt de kop niet eens. */
		buitenBed: boolean;
	};

	let perMm = $derived(design?.units_per_mm ?? 1);

	// De meting van de server, als hij er is. Zonder `bounds` (bijvoorbeeld
	// terwijl het overzicht nog laadt) valt hij terug op de velrand die hij zelf
	// kan zien; het bed kent hij dan niet en dat meldt hij dus ook niet.
	let bedIds = $derived(new Set(bounds?.outside_bed_ids ?? []));
	let velIds = $derived(new Set(bounds?.outside_sheet_ids ?? []));

	let vormen = $derived.by<Vorm[]>(() => {
		if (!design) return [];
		return design.elements
			.filter((element) => !element.hidden)
			.map((element) => {
				const lagen = (element.operation_ids ?? []).filter((id) => brandende.has(id));
				const box = element.bounds;
				const zelfBuiten = Boolean(
					sheet &&
						box &&
						(box[0] / perMm < -0.05 ||
							box[1] / perMm < -0.05 ||
							box[2] / perMm > sheet.width_mm + 0.05 ||
							box[3] / perMm > sheet.height_mm + 0.05)
				);
				const buitenBed = bounds ? bedIds.has(element.id) : false;
				return {
					id: element.id,
					path: element.path,
					image: element.image
						? {
								x: element.image.x_mm * perMm,
								y: element.image.y_mm * perMm,
								w: element.image.width_mm * perMm,
								h: element.image.height_mm * perMm
							}
						: null,
					kleur: lagen.length ? (colorFor?.(lagen[0]) ?? GRIJS) : GRIJS,
					stil: lagen.length === 0,
					// Buiten het bed is de zwaarste van de twee, dus die wint: een
					// vorm die er allebei buiten valt, is er één die de machine niet
					// kan bereiken. Twee merktekens over één vorm zeggen niets extra.
					buiten: (bounds ? velIds.has(element.id) : zelfBuiten) && !buitenBed,
					buitenBed
				};
			});
	});

	let buitenVel = $derived(vormen.filter((v) => v.buiten).length);
	let buitenBed = $derived(vormen.filter((v) => v.buitenBed).length);
	let stille = $derived(vormen.filter((v) => v.stil).length);
	let brandt = $derived(vormen.filter((v) => !v.stil).length);

	/**
	 * Het kader waar de weergave in kijkt, in millimeters.
	 *
	 * Het vel plus alles wat erbuiten valt: wie een vorm over de rand heeft
	 * hangen, moet die vorm zien liggen en niet alleen zijn afwezigheid.
	 */
	let kader = $derived.by(() => {
		let x0 = 0;
		let y0 = 0;
		let x1 = sheet?.width_mm ?? 0;
		let y1 = sheet?.height_mm ?? 0;
		for (const element of design?.elements ?? []) {
			if (element.hidden || !element.bounds) continue;
			const [a, b, c, d] = element.bounds;
			x0 = Math.min(x0, a / perMm);
			y0 = Math.min(y0, b / perMm);
			x1 = Math.max(x1, c / perMm);
			y1 = Math.max(y1, d / perMm);
		}
		if (x1 <= x0 || y1 <= y0) return null;
		// Iets lucht eromheen, zodat een vorm die precies op de rand ligt niet
		// tegen de zijkant van het kader geplakt zit.
		const marge = Math.max(x1 - x0, y1 - y0) * 0.04;
		return {
			x: x0 - marge,
			y: y0 - marge,
			w: x1 - x0 + 2 * marge,
			h: y1 - y0 + 2 * marge
		};
	});

	/**
	 * Hoe groot het werk zelf is, in millimeters.
	 *
	 * Zonder maat is de weergave een plaatje: je ziet dát iets krap ligt, maar
	 * niet of het past. Dit is het getal waarmee je het naast je restje legt.
	 */
	let werk = $derived.by(() => {
		let x0 = Infinity;
		let y0 = Infinity;
		let x1 = -Infinity;
		let y1 = -Infinity;
		for (const element of design?.elements ?? []) {
			if (element.hidden || !element.bounds) continue;
			const [a, b, c, d] = element.bounds;
			x0 = Math.min(x0, a);
			y0 = Math.min(y0, b);
			x1 = Math.max(x1, c);
			y1 = Math.max(y1, d);
		}
		if (!Number.isFinite(x0)) return null;
		return { w: (x1 - x0) / perMm, h: (y1 - y0) / perMm };
	});

	/** Eén zin die zegt wat je ziet, voor wie het beeld niet krijgt. */
	let beschrijving = $derived.by(() => {
		if (!kader) return 'Niets op het vel.';
		const delen = [`${brandt} ${brandt === 1 ? 'vorm brandt' : 'vormen branden'}`];
		if (sheet) delen.push(`op ${sheet.name}, ${maat(sheet.width_mm)} bij ${maat(sheet.height_mm)} millimeter`);
		if (buitenBed) delen.push(`${buitenBed} liggen buiten het bed`);
		if (buitenVel) delen.push(`${buitenVel} vallen buiten het vel`);
		if (stille) delen.push(`${stille} zitten in geen laag`);
		return delen.join('; ') + '.';
	});

	function maat(value: number) {
		return String(Math.round(value)).replace('.', ',');
	}

	/**
	 * Buiten het vel is gearceerd, niet anders gekleurd.
	 *
	 * Gemeten: `--bed` en `--surface-2` zijn in het donkere thema exact dezelfde
	 * kleur (1,00:1) en in het lichte thema 1,14:1. Geen enkel bestaand token
	 * haalt tegenover `--bed` meer dan 1,23:1, dus met een vlakkleur is "hier
	 * ligt geen materiaal" in het donker domweg onzichtbaar. Arcering is ook de
	 * gangbare taal ervoor in CAM-software, en werkt bij kleurenblindheid.
	 */
	const arceringId = `ok-arcering-${eigenId}`;
	// De arcering staat in millimeters, net als de rest van de weergave; de
	// stap schaalt mee met het kader zodat hij op elk formaat even fijn oogt.
	let stap = $derived(kader ? Math.max(kader.w, kader.h) / 45 : 1);
</script>

<!-- Tweemaal dezelfde tekening: klein in het paneel, groot in het venster. Het
     patroon-id moet per exemplaar verschillen, anders wijst de tweede naar het
     patroon van de eerste en verdwijnt de arcering zodra de eerste weg is. -->
{#snippet tekening(sleutel: string)}
	{@const patroon = `${arceringId}-${sleutel}`}
	{#if kader}
		<svg
			viewBox="{kader.x} {kader.y} {kader.w} {kader.h}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-label={beschrijving}
		>
			<!-- Het vel. De weergave meet in millimeters, dus elke lengte hier is
			     er één; randen krijgen non-scaling-stroke, anders schaalt de lijn
			     mee met het vel en is hij op een groot vel onzichtbaar. -->
			{#if sheet}
				<defs>
					<pattern
						id={patroon}
						patternUnits="userSpaceOnUse"
						width={stap}
						height={stap}
						patternTransform="rotate(45)"
					>
						<line class="arcering" x1={stap / 2} y1="0" x2={stap / 2} y2={stap} />
					</pattern>
				</defs>
				<!-- Alles buiten het vel: gearceerd, want daar ligt geen materiaal. -->
				<rect
					x={kader.x}
					y={kader.y}
					width={kader.w}
					height={kader.h}
					fill="url(#{patroon})"
				/>
				<rect
					class="vel"
					class:overhang={buitenVel > 0}
					x="0"
					y="0"
					width={sheet.width_mm}
					height={sheet.height_mm}
				/>
			{/if}

			<!-- De bedrand, alleen als er iets buiten valt. Anders is het een grote
			     doos om een klein vel: ruis. Ligt er wél iets buiten, dan is een
			     rode vorm zonder zichtbare grens een raadsel — je ziet dát er iets
			     mis is, niet waarmee. -->
			{#if buitenBed && bounds?.bed}
				<rect
					class="bedrand"
					x="0"
					y="0"
					width={bounds.bed.width_mm}
					height={bounds.bed.height_mm}
				/>
			{/if}

			<!-- Het werk zelf. Eén schaaltransform rekent Tats om naar mm, precies
			     zoals het canvas het doet; de paddata blijft zoals de engine hem gaf. -->
			<g transform="scale({1 / perMm})">
				{#each vormen as vorm (vorm.id)}
					{#if vorm.image}
						<image
							href="/api/design/elements/{encodeURIComponent(vorm.id)}/image.png"
							x={vorm.image.x}
							y={vorm.image.y}
							width={vorm.image.w}
							height={vorm.image.h}
							preserveAspectRatio="none"
							opacity={vorm.stil ? 0.35 : 1}
						/>
					{:else if vorm.path}
						<path
							d={vorm.path}
							class="vorm"
							class:stil={vorm.stil}
							class:buiten={vorm.buiten}
							class:buitenbed={vorm.buitenBed}
							style:stroke={vorm.buitenBed
								? 'var(--danger-solid)'
								: vorm.buiten
									? 'var(--warn-solid)'
									: vorm.kleur}
						/>
					{/if}
				{/each}
			</g>
		</svg>
	{/if}
{/snippet}

{#if kader}
	<div class="pf-beeld">
		<!-- Klein in het paneel, groot op verzoek. LightBurn geeft zijn preview een
		     heel venster; een strook van 220 px is te weinig voor een fout die je
		     alleen hier nog kunt zien. -->
		<button
			class="vergroot"
			onclick={() => (groot = true)}
			aria-label="{beschrijving} Groter bekijken."
			title="Groter bekijken"
		>
			{@render tekening('klein')}
		</button>

		<!-- De maten eronder, want de weergave zelf heeft geen schaal: je ziet dat
		     iets krap ligt, niet of het past. Dit is ook het getal waarmee je het
		     naast een restje legt. -->
		<p class="maten">
			{#if sheet}<span
					>{sheet.name}
					<span class="mono">{maat(sheet.width_mm)} × {maat(sheet.height_mm)} mm</span></span
				>{/if}
			{#if werk}<span>werk <span class="mono">{maat(werk.w)} × {maat(werk.h)} mm</span></span>{/if}
		</p>

		<!-- Wat het beeld zegt, in woorden. Een rode lijn die je over het hoofd
		     ziet is geen waarschuwing; en wie op de telefoon in de zon staat,
		     ziet kleurverschil als eerste niet meer. -->
		<!-- Buiten het bed staat bovenaan en is rood; buiten het vel eronder en
		     oranje. Dat is geen smaakkwestie maar de volgorde waarin het
		     misgaat: buiten het vel kost je materiaal, buiten het bed komt de
		     kop er niet eens — daar staat de machine stil of loopt hij tegen
		     zijn eindaanslag. Twee even rode kaarten op rij (zoals het was)
		     maken die twee even erg, en dan weegt geen van beide nog. -->
		{#if buitenBed}
			<p class="melding buitenbed" role="alert">
				<strong>Buiten het bed.</strong>
				{buitenBed === 1 ? 'Eén vorm ligt' : `${buitenBed} vormen liggen`} buiten
				het bereik van de machine{bounds?.bed
					? `, die tot ${maat(bounds.bed.width_mm)} × ${maat(bounds.bed.height_mm)} mm reikt`
					: ''}. Daar komt de kop niet: verplaats het of maak het kleiner.
			</p>
		{/if}
		{#if buitenVel}
			<p class="melding buiten">
				{buitenVel === 1 ? 'Eén vorm valt' : `${buitenVel} vormen vallen`} buiten
				{sheet ? sheet.name : 'het vel'}. Daar ligt geen materiaal — wat er
				overheen steekt, brandt in je rooster of je werkblad.
			</p>
		{/if}
		{#if stille}
			<p class="melding stil">
				{stille === 1 ? 'Eén vorm zit' : `${stille} vormen zitten`} in geen enkele
				laag die meebrandt — grijs gestippeld hierboven. De machine slaat ze over.
			</p>
		{/if}
	</div>

	<Dialog title="Wat er gebrand wordt" bind:open={groot} width="960px">
		<div class="groot">
			{@render tekening('groot')}
			<p class="maten">
				{#if sheet}<span
						>{sheet.name}
						<span class="mono">{maat(sheet.width_mm)} × {maat(sheet.height_mm)} mm</span></span
					>{/if}
				{#if werk}<span>werk <span class="mono">{maat(werk.w)} × {maat(werk.h)} mm</span></span
					>{/if}
			</p>
		</div>
	</Dialog>
{/if}

<style>
	.pf-beeld {
		margin: 0 0 var(--space-3);
	}
	/* De knop is de tekening zelf; hij mag er niet als knop uitzien, maar moet
	   wel te focussen zijn en zeggen dat er iets gebeurt als je hem aanraakt. */
	.vergroot {
		display: block;
		width: 100%;
		padding: 0;
		border: none;
		background: none;
		border-radius: var(--radius-field);
		cursor: zoom-in;
	}
	.vergroot:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.groot :global(svg) {
		max-height: 66vh;
	}
	svg {
		display: block;
		width: 100%;
		/* Zonder plafond wordt een staand vel in een smal paneel een toren en
		   valt de tijdschatting eronder van het scherm. `meet` zorgt dat het
		   beeld daarbij nooit vervormt; er komt hooguit lucht naast. */
		max-height: 30vh;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	/* Fijn genoeg om achtergrond te blijven, sterk genoeg om op een weergave van
	   221 px nog als arcering te lezen. Op `--line` haalde hij 1,41:1 (licht) en
	   1,44:1 (donker) tegenover het vel — gemeten, en dat is te weinig. */
	.arcering {
		stroke: color-mix(in srgb, var(--text-2) 45%, transparent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
	}
	/* De rand van het vel is waar je materiaal ophoudt; dat is een grens en geen
	   scheidingslijntje. `--line` haalde er 1,41:1 (licht) / 1,44:1 (donker),
	   ruim onder de 3:1 die WCAG 1.4.11 voor een grafisch object vraagt;
	   `--text-2` haalt 6,00:1 en 5,65:1. */
	.vel {
		fill: var(--bed);
		stroke: var(--text-2);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
	}
	/* Steekt er iets over de rand, dan is de rand het onderwerp. Oranje en niet
	   rood: het vel is een stuk materiaal dat op is, niet een grens die de
	   machine niet haalt. Dat laatste is de bedrand hieronder. */
	.vel.overhang {
		stroke: var(--warn-solid);
		stroke-width: 2;
	}
	/* Waar de machine ophoudt. Rood en gestreept: twee codes voor één grens,
	   want op een klein beeld is hue alleen te weinig — en bij deuteranopie
	   liggen rood en amber tegen elkaar aan. */
	.bedrand {
		fill: none;
		stroke: var(--danger-solid);
		stroke-width: 2;
		stroke-dasharray: 10 6;
		vector-effect: non-scaling-stroke;
	}
	.vorm {
		fill: none;
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	/* Zit in geen laag: wordt niet gebrand. Gestippeld grijs, dezelfde taal als
	   op het canvas — daar betekent het al "deze vorm doet niet mee". */
	.vorm.stil {
		stroke: var(--text-2);
		stroke-dasharray: 4 3;
		stroke-width: 1;
	}
	/* Buiten het vel: oranje én onderbroken. Een langere streep dan die van
	   `stil` (4 3), zodat "doet niet mee" en "ligt naast je materiaal" op één
	   beeld niet hetzelfde patroon dragen. */
	.vorm.buiten {
		stroke-width: 2.5;
		stroke-dasharray: 9 4;
	}
	/* Buiten het bed: rood en dicht. De zwaarste van de drie krijgt de rustigste
	   lijn — die hoeft niets te suggereren, hij is gewoon fout. */
	.vorm.buitenbed {
		stroke-width: 3;
	}
	/* Twee maten naast elkaar als het past, onder elkaar als het niet past — in
	   een paneel van 220px past het niet, en dan is links uitlijnen rustiger dan
	   een tweede regel die tegen de rechterrand geplakt staat. */
	.maten {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-1) var(--space-3);
		margin-top: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.maten .mono {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.melding {
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		line-height: 1.45;
	}
	.melding.buiten,
	.melding.buitenbed {
		color: var(--text-1);
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
	}
	.melding.buitenbed {
		border-left: 4px solid var(--danger-solid);
		background: color-mix(in srgb, var(--danger) 18%, transparent);
	}
	.melding.buiten {
		border-left: 4px solid var(--warn-solid);
		background: color-mix(in srgb, var(--warn) 18%, transparent);
	}
	.melding.stil {
		color: var(--text-2);
	}
</style>
