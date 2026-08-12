<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { createStore } from '$lib/setup.svelte';
	import type { CatalogMachine } from '$lib/machines.svelte';

	const store = createStore();

	let typeKey = $derived($page.url.searchParams.get('type') ?? '');
	let chosen = $state<CatalogMachine | null>(null);
	let label = $state('');
	let touched = $state(false);

	// Kwam dit type uit de zoekknop van stap 1, dan reizen de gevonden
	// verbindingsgegevens als parameter mee naar de instelstap. Ze worden pas
	// dáár toegepast, en pas als je daar opslaat: tot dan is er niets verbonden.
	let verbinding = $derived($page.url.searchParams.get('verbinding') ?? '');
	let gevonden = $derived($page.url.searchParams.get('gevonden') ?? '');

	onMount(async () => {
		// Ook de bestaande machines ophalen: een naam die al bestaat, is geen naam.
		await Promise.all([store.loadCatalog(), store.loadMachines()]);
		chosen =
			store.catalog
				.flatMap((family) => family.machines)
				.find((machine) => machine.key === typeKey) ?? null;
		// Alleen voorinvullen zolang de gebruiker zelf nog niets typte.
		if (chosen && !touched) label = uniek(String(chosen.defaults.label ?? chosen.friendly_name));
	});

	/**
	 * Een naam die nog niet vergeven is.
	 *
	 * Dezelfde regel als bij vellen (`sheets.py`, `add`): twee dingen die
	 * hetzelfde heten zijn niet uit elkaar te houden. Bij een machine weegt dat
	 * zwaarder dan bij een vel — in de bovenbalk staat alleen de naam, en die
	 * balk is het enige wat zegt waar je job straks naartoe gaat. Gemeten vóór
	 * deze regel: de wizard twee keer doorlopen gaf twee machines die allebei
	 * "Werkplaats 5030" heetten, zonder één woord erover.
	 */
	function uniek(wens: string): string {
		const bezet = new Set(store.machines.map((m) => m.label));
		if (!bezet.has(wens)) return wens;
		let n = 2;
		while (bezet.has(`${wens} (${n})`)) n += 1;
		return `${wens} (${n})`;
	}

	let botsing = $derived(
		label.trim() !== '' && store.machines.some((m) => m.label === label.trim())
	);

	async function create() {
		const result = await store.create(typeKey, label.trim());
		if (result) {
			const params = new URLSearchParams({ machine: result.path });
			if (verbinding) params.set('verbinding', verbinding);
			await goto(`/setup/instellen?${params}`);
		}
	}
</script>

<svelte:head><title>OpenKerf — naam</title></svelte:head>

<section class="setup narrow">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	{#if !typeKey}
		<h1>Geen machinetype gekozen</h1>
		<p class="muted">Kies eerst een type; dan weet ik wat ik moet aanmaken.</p>
		<div class="actions"><a class="btn primary" href="/setup/type">Naar de typekeuze</a></div>
	{:else}
		<h1>Geef de machine een naam</h1>
		<p class="muted">
			Zo herken je hem in de bovenbalk{chosen ? `: “${chosen.friendly_name}”` : ''}.
		</p>
		{#if gevonden}
			<p class="gevonden">
				Uit het zoeken: <strong>{gevonden}</strong>. De verbinding staat klaar voor de
				volgende stap; hij wordt pas gelegd als je een job start.
			</p>
		{/if}
		<label class="field">
			<span>Naam</span>
			<input
				type="text"
				bind:value={label}
				oninput={() => (touched = true)}
				placeholder="bijv. 5030 CO2"
			/>
		</label>
		{#if botsing}
			<!-- Waarschuwen, niet blokkeren: misschien staan er echt twee dezelfde
			     in de werkplaats. Maar dan moet je het wel weten, want de bovenbalk
			     toont niets anders dan deze naam. -->
			<p class="botsing" role="alert">
				Er staat al een machine die “{label.trim()}” heet. In de bovenbalk zijn
				ze dan niet uit elkaar te houden.
				<button class="link" type="button" onclick={() => { label = uniek(label.trim()); touched = true; }}>
					Maak er “{uniek(label.trim())}” van
				</button>
			</p>
		{/if}
		<div class="actions">
			<!-- Wie hier via de zoekknop kwam, koos geen model in stap 2; terug naar
			     de modellijst zou dan een stap tonen die hij nooit zag. -->
			<a class="btn" href={gevonden ? '/setup/soort' : '/setup/type'}>Terug</a>
			<button class="btn primary" onclick={create} disabled={store.busy || !label.trim()}>
				{store.busy ? 'Bezig…' : 'Aanmaken'}
			</button>
		</div>
	{/if}
</section>

<style>
	.field {
		display: grid;
		gap: var(--space-1);
		margin: var(--space-4) 0;
		font-weight: 500;
	}
	.botsing {
		margin: calc(-1 * var(--space-2)) 0 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--warn, var(--accent));
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.botsing .link {
		display: block;
		margin-top: 4px;
		padding: 0;
		font: inherit;
		color: var(--accent);
		background: none;
		border: 0;
		text-decoration: underline;
		cursor: pointer;
	}
	.gevonden {
		margin: var(--space-3) 0 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--ok);
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.field input {
		font: inherit;
		font-weight: 400;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
