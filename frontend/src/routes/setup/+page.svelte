<script lang="ts">
	import { onMount } from 'svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { Machine } from '$lib/machines.svelte';

	const store = createStore();

	onMount(() => store.loadMachines());

	// De engine maakt bij het opstarten zelf een lhystudios-apparaat aan, zodat
	// de kernel altijd iets heeft om tegen te praten. Dat is geen machine van
	// de gebruiker, en hem in deze lijst zetten als "In gebruik" leest als een
	// apparaat dat je zelf hebt toegevoegd. We zetten hem apart met de reden
	// erbij, in plaats van hem te verbergen: hij is wél actief, en dat moet je
	// kunnen zien.
	let eigen = $derived(store.machines.filter((m) => m.configured !== false));
	let placeholder = $derived(store.machines.find((m) => m.configured === false) ?? null);

	async function useMachine(machine: Machine) {
		if (await store.activate(machine.path)) await store.loadMachines();
	}

	async function removeMachine(machine: Machine) {
		if (await store.remove(machine.path)) await store.loadMachines();
	}

	// ------------------------------- machineprofiel uitwisselen (gat E5)
	//
	// LightBurn heeft `.lbdev`: een fabrikant levert een kant-en-klaar profiel
	// mee, en wie een tweede computer inricht typt niets over. Zelfde vorm als
	// de bibliotheek van B7 — eerst kijken wat erin zit, dan pas aanmaken. Een
	// machineprofiel bepaalt waar de kop heen gaat; blind inladen wat iemand je
	// mailde is één stap van een kop tegen zijn eindaanslag.

	type Voorbeeld = {
		profile: string;
		label: string;
		info: string;
		known: boolean;
		friendly_name: string | null;
		family: string | null;
		settings: number;
		essential: Record<string, string | number | boolean>;
		local: Record<string, string | number | boolean>;
		exported_at: string | null;
	};

	/** De sleutels van de engine in woorden; "bedwidth" leest niemand als bed. */
	const VELDNAAM: Record<string, string> = {
		bedwidth: 'Bedbreedte',
		bedheight: 'Bedhoogte',
		interface: 'Verbinding',
		address: 'Adres',
		serial_port: 'Seriële poort',
		port: 'Poort'
	};

	let voorbeeld = $state<Voorbeeld | null>(null);
	let profielFout = $state<string | null>(null);
	let profielBezig = $state(false);
	let ingelezen = $state<string | null>(null);

	function token(): Record<string, string> {
		const t = typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		return t ? { Authorization: `Bearer ${t}` } : {};
	}

	function exporteer(machine: Machine) {
		const anker = document.createElement('a');
		anker.href = `/api/machines/${encodeURIComponent(machine.path)}/export.openkerf-machine`;
		anker.download = `${machine.label}.openkerf-machine`;
		anker.click();
	}

	async function kiesProfiel(bestand: File) {
		voorbeeld = null;
		ingelezen = null;
		profielFout = null;
		profielBezig = true;
		try {
			const form = new FormData();
			form.append('file', bestand);
			const response = await fetch('/api/machines/import/upload', {
				method: 'POST',
				headers: token(),
				body: form
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				profielFout =
					typeof data?.detail === 'string' ? data.detail : `Inlezen mislukte (${response.status}).`;
				return;
			}
			voorbeeld = data;
		} catch (e) {
			profielFout = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
		} finally {
			profielBezig = false;
		}
	}

	async function neemProfiel() {
		if (!voorbeeld) return;
		profielBezig = true;
		profielFout = null;
		try {
			const response = await fetch('/api/machines/import', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...token() },
				body: JSON.stringify({ profile: voorbeeld.profile })
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				profielFout =
					typeof data?.detail === 'string'
						? data.detail
						: `Aanmaken mislukte (${response.status}).`;
				return;
			}
			ingelezen = `${data.label ?? voorbeeld.label} staat erbij${
				data.skipped?.length
					? ` — ${data.skipped.length} instelling${data.skipped.length === 1 ? '' : 'en'} kende deze versie niet en ${data.skipped.length === 1 ? 'is' : 'zijn'} overgeslagen`
					: ''
			}. Controleer het adres en de bedmaat voor je iets brandt.`;
			voorbeeld = null;
			await store.loadMachines();
		} finally {
			profielBezig = false;
		}
	}
</script>

<svelte:head><title>OpenKerf — machines</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>Jouw machines</h1>
	{#if eigen.length === 0}
		<p class="leeg">
			<strong>Nog geen machine ingesteld.</strong>
			<span class="muted">
				Voeg de laser toe die in je werkplaats staat. Dat bepaalt het bed op het canvas,
				welke bediening je krijgt en hoe OpenKerf hem aanspreekt.
			</span>
		</p>
	{:else}
		<ul class="machines">
			{#each eigen as machine (machine.path)}
				<li class:active={machine.active}>
					<div>
						<div class="name" title={machine.label}>{machine.label}</div>
						<div class="muted mono">{machine.path}</div>
					</div>
					{#if machine.active}
						<span class="badge">In gebruik</span>
					{:else}
						<button class="btn" onclick={() => useMachine(machine)}>Gebruiken</button>
					{/if}
					<!-- Instellingen waren alleen tijdens het aanmaken te bereiken. -->
					<a class="btn" href="/setup/instellen?machine={encodeURIComponent(machine.path)}">
						Instellingen
					</a>
					<!-- Gat E5: deze machine als bestand, voor een tweede computer. -->
					<button class="btn subtle" onclick={() => exporteer(machine)}>Profiel exporteren</button>
					{#if !machine.active}
						<button class="btn subtle" onclick={() => removeMachine(machine)}>Verwijderen</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	<div class="actions">
		<a class="btn primary" href="/setup/soort">Machine toevoegen</a>
		<!-- Gat E5: dezelfde weg als "Machine toevoegen", maar dan met een
		     profiel dat iemand anders al heeft ingevuld. -->
		<label class="btn file">
			Profiel importeren…
			<input
				type="file"
				accept=".openkerf-machine,application/json"
				onchange={(e) => {
					const f = e.currentTarget.files?.[0];
					e.currentTarget.value = '';
					if (f) kiesProfiel(f);
				}}
			/>
		</label>
	</div>

	{#if profielFout}<p class="error" role="alert">{profielFout}</p>{/if}
	{#if ingelezen}<p class="gelukt" role="status">{ingelezen}</p>{/if}

	{#if voorbeeld}
		<!-- Eerst wat erin zit, dan pas aanmaken. Een profiel bepaalt de bedmaat,
		     de verbinding en de spiegeling; dat hoort je niet te overkomen. -->
		<aside class="voorbeeld">
			<h2>Dit profiel: {voorbeeld.label}</h2>
			{#if voorbeeld.known}
				<p class="muted">
					{voorbeeld.friendly_name}{voorbeeld.family ? ` · ${voorbeeld.family}` : ''} —
					{voorbeeld.settings} instellingen.
				</p>
			{:else}
				<p class="muted">
					Dit profiel is gemaakt voor machinetype <span class="mono">{voorbeeld.info}</span>, en
					dat type kent deze installatie niet. Aanmaken zal mislukken; werk eerst MeerK40t bij.
				</p>
			{/if}
			<dl class="feiten">
				{#each Object.entries(voorbeeld.essential) as [naam, waarde] (naam)}
					<div><dt>{VELDNAAM[naam] ?? naam}</dt><dd class="mono">{waarde}</dd></div>
				{/each}
			</dl>
			{#if Object.keys(voorbeeld.local).length}
				<p class="lokaal">
					Hoort bij de opstelling waar dit profiel vandaan komt — controleer het hier:
					{#each Object.entries(voorbeeld.local) as [naam, waarde], i (naam)}{i ? ', ' : ''}<span
							class="mono">{VELDNAAM[naam] ?? naam} {waarde}</span
						>{/each}.
				</p>
			{/if}
			<div class="uitknoppen">
				<button class="btn primary" disabled={profielBezig || !voorbeeld.known} onclick={neemProfiel}>
					{profielBezig ? 'Bezig…' : 'Machine aanmaken'}
				</button>
				<button class="btn subtle" onclick={() => (voorbeeld = null)}>Toch niet</button>
			</div>
		</aside>
	{/if}

	{#if placeholder}
		<aside class="placeholder">
			<h2>Standaardapparaat van de engine</h2>
			<p class="muted">
				MeerK40t maakt bij het opstarten zelf een apparaat aan
				(<span class="mono">{placeholder.label}</span>) zodat er altijd iets actief is.
				Niemand heeft het gekozen, en de bedmaten en verbinding zijn gokwerk — brand er niets
				op zonder ze te controleren.
			</p>
			<p class="muted">
				Heb je toevallig precies zo'n machine? Geef hem dan een naam en zijn echte bedmaat;
				vanaf dan telt hij als jouw machine.
			</p>
			<a class="btn" href="/setup/instellen?machine={encodeURIComponent(placeholder.path)}">
				Nakijken en overnemen
			</a>
		</aside>
	{/if}
</section>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.machines li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 8px 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		margin-bottom: var(--space-2);
	}
	.machines li.active {
		border-color: var(--accent);
	}
	.machines li > div:first-child {
		flex: 1;
		min-width: 0;
	}
	.machines .mono {
		font-size: var(--text-xs);
	}
	.name {
		font-weight: 500;
		/* Een naam die de engine geeft ("lhystudios1") heeft geen afbreekpunt: hij
		   duwde de badge weg of werd erdoor afgesneden. Afkappen met ellips is
		   eerlijk — je ziet dat er meer staat. De volledige naam blijft in de
		   title-tip. */
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* Onder ~420px is er naast de naam geen kolom meer over: op 390 hield de
	   naam 74px van de 308 en botste "Ruida 5030" tegen de badge. De naam krijgt
	   dan de hele regel, de acties de regel eronder — dat is ook de volgorde
	   waarin je ze leest. */
	@media (max-width: 420px) {
		.machines li {
			flex-wrap: wrap;
		}
		.machines li > div:first-child {
			flex: 1 0 100%;
		}
		/* De knoppen mogen dan de volle breedte delen; ze zijn hier het doel van
		   een duim, niet van een muis. */
		.machines li .btn,
		.machines li .badge {
			min-height: 44px;
			display: inline-flex;
			align-items: center;
		}
	}
	/* Accent op een tint van 14% accent haalt geen AA (gemeten: 4,10 in licht,
	   4,46 in donker). De tint blijft de accentkleur dragen, de tekst niet —
	   dezelfde uitweg als in ToolRail, en zonder de merkkleur te verschuiven. */
	.badge {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--text-1);
	}
	.leeg {
		display: grid;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-4);
		border: 1px dashed var(--line);
		border-radius: var(--radius-card);
	}
	.placeholder {
		margin-top: var(--space-8);
		padding: var(--space-4);
		border-radius: var(--radius-card);
		/* Een waarschuwingsvlak, geen fout: dit apparaat werkt, het is alleen
		   niet het jouwe. Zie DESIGN-SYSTEM, "zekerheid is een zin". */
		border-left: 3px solid var(--warn);
		background: var(--surface-2);
	}
	.placeholder h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: 0 0 var(--space-2);
	}
	.placeholder p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}

	/* ------------------------------- machineprofiel uitwisselen (gat E5) */

	/* Een bestandskiezer die eruitziet als de knop ernaast: de input zelf is
	   onzichtbaar maar blijft het raakvlak, dus toetsenbord en schermlezer
	   krijgen gewoon een invoerveld met een naam. */
	.btn.file {
		position: relative;
		overflow: hidden;
		cursor: pointer;
	}
	.btn.file input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.gelukt {
		margin: var(--space-4) 0 0;
		padding: var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--ok);
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		font-size: var(--text-xs);
	}
	.voorbeeld {
		margin-top: var(--space-4);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.voorbeeld h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: 0 0 var(--space-2);
	}
	.voorbeeld p { margin: 0 0 var(--space-2); font-size: var(--text-xs); }
	.feiten {
		display: grid;
		gap: var(--space-1);
		margin: 0 0 var(--space-3);
		font-size: var(--text-xs);
	}
	.feiten div { display: flex; justify-content: space-between; gap: var(--space-3); }
	.feiten dt { color: var(--text-2); }
	.feiten dd { margin: 0; }
	/* Het adres van de andere werkbank is het eerste dat hier niet klopt. Geen
	   fout, wel iets om te controleren voor je iets brandt. */
	.lokaal {
		padding: var(--space-2) var(--space-3);
		border-left: 3px solid var(--warn-solid, var(--warn));
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		color: var(--text-1);
	}
	.uitknoppen { display: flex; gap: var(--space-2); flex-wrap: wrap; }
</style>
