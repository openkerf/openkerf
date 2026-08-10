<script lang="ts">
	import Dialog from './Dialog.svelte';
	import { CONFIDENCE, PresetariatStore } from '$lib/presetariat.svelte';
	import { OPERATIONS, type LibraryStore } from '$lib/library.svelte';

	let {
		open = $bindable(),
		catalogue,
		library,
		canEdit = false,
		onImported
	}: {
		open: boolean;
		catalogue: PresetariatStore;
		library: LibraryStore;
		canEdit?: boolean;
		onImported?: () => void;
	} = $props();

	let machineId = $state<number | null>(null);
	let material = $state('');
	let operation = $state('');
	let loaded = false;
	let result = $state<{ imported: number; skipped: number } | null>(null);

	// Pas ophalen als het venster opengaat: de catalogus staat op internet.
	$effect(() => {
		if (!open || loaded) return;
		loaded = true;
		machineId = library.machines[0]?.id ?? null;
		catalogue.load({ machineId });
	});

	function refresh(hard = false) {
		result = null;
		catalogue.load({ machineId, material, operation, refresh: hard });
	}

	async function importChosen() {
		const outcome = await catalogue.importChosen(machineId);
		if (!outcome) return;
		result = { imported: outcome.imported.length, skipped: outcome.skipped.length };
		await library.load();
		await catalogue.load({ machineId, material, operation });
		onImported?.();
	}

	function label(value: string) {
		return OPERATIONS.find((o) => o.value === value)?.label ?? value;
	}
</script>

<Dialog title="Presetariat" bind:open width="720px">
	<p class="lead">
		Instellingen die anderen deelden. Ze komen van andermans machine: neem ze als
		startpunt, niet als waarheid. Wat met een testraster gemeten is, staat bovenaan.
	</p>

	<div class="filters">
		<label>
			<span>Machine</span>
			<select
				bind:value={machineId}
				onchange={() => refresh()}
			>
				<option value={null}>Alle machines</option>
				{#each library.machines as machine (machine.id)}
					<option value={machine.id}>{machine.name}</option>
				{/each}
			</select>
		</label>
		<label>
			<span>Bewerking</span>
			<select bind:value={operation} onchange={() => refresh()}>
				<option value="">Alle</option>
				{#each OPERATIONS as item (item.value)}
					<option value={item.value}>{item.label}</option>
				{/each}
			</select>
		</label>
		<label class="grow">
			<span>Materiaal</span>
			<input
				type="search"
				bind:value={material}
				placeholder="bijv. berken of acrylaat"
				oninput={() => refresh()}
			/>
		</label>
		<button class="btn" disabled={catalogue.busy} onclick={() => refresh(true)}>Verversen</button>
	</div>

	{#if catalogue.error}
		<p class="warn">{catalogue.error}</p>
	{/if}
	{#if catalogue.stale}
		<p class="warn">Uit de lokale kopie — de catalogus was niet bereikbaar.</p>
	{/if}
	{#if result}
		<p class="ok">
			{result.imported} geïmporteerd{result.skipped
				? `, ${result.skipped} overgeslagen (had je al)`
				: ''}.
		</p>
	{/if}

	<div class="list">
		{#each catalogue.presets as preset (preset.id)}
			{@const badge = CONFIDENCE[preset.source.kind] ?? CONFIDENCE.handmatig}
			<label class="row" class:done={preset.imported}>
				<input
					type="checkbox"
					disabled={!canEdit || preset.imported}
					checked={catalogue.chosen.has(preset.id)}
					onchange={() => catalogue.toggle(preset.id)}
				/>
				<div class="what">
					<strong>{preset.material}</strong>
					<span class="sub">
						{preset.thickness_mm ? `${preset.thickness_mm} mm · ` : ''}{label(preset.operation)}
						· {preset.machine.power_watt} W {preset.machine.laser_type}
					</span>
				</div>
				<div class="numbers mono">
					{preset.speed_mm_s} mm/s · {preset.power_percent}%{preset.passes && preset.passes > 1
						? ` · ${preset.passes}×`
						: ''}
				</div>
				<span class="badge {badge.tone}">{badge.text}</span>
				{#if preset.verified}
					<span class="badge ok" title="Door een tweede persoon nagebrand">Nagebrand</span>
				{/if}
				{#if preset.imported}
					<span class="badge neutral">In bibliotheek</span>
				{/if}
			</label>
		{:else}
			<p class="empty">
				{catalogue.busy ? 'Ophalen…' : 'Niets gevonden voor deze machine en filters.'}
			</p>
		{/each}
	</div>

	<div class="actions">
		<span class="meta mono">
			{catalogue.presets.length} van {catalogue.total}{catalogue.version
				? ` · versie ${catalogue.version}`
				: ''}
		</span>
		<button
			class="btn primary"
			disabled={!canEdit || !catalogue.chosen.size || catalogue.busy}
			onclick={importChosen}
		>
			{catalogue.chosen.size ? `${catalogue.chosen.size} importeren` : 'Importeren'}
		</button>
	</div>
</Dialog>

<style>
	.lead {
		margin: 0 0 var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
		line-height: 1.5;
	}
	.filters {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}
	.filters label {
		display: grid;
		gap: 2px;
		font-size: 10px;
		color: var(--text-2);
	}
	.filters .grow { flex: 1; min-width: 160px; }
	select,
	input[type='search'] {
		font: inherit;
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.list {
		display: grid;
		gap: 2px;
		max-height: 46vh;
		overflow-y: auto;
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 6px 8px;
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.row:hover { background: var(--surface-2); }
	.row.done { opacity: 0.55; }
	.what { display: grid; }
	.sub { color: var(--text-2); font-size: 10px; }
	.numbers { margin-left: auto; color: var(--text-1); }
	.badge {
		font-size: 9px;
		padding: 2px 6px;
		border-radius: 999px;
		border: 1px solid var(--line);
		color: var(--text-2);
		white-space: nowrap;
	}
	.badge.ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
	.badge.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
	.empty { font-size: var(--text-xs); color: var(--text-2); padding: var(--space-4) 0; }
	.warn { font-size: var(--text-xs); color: var(--warn); margin: 0 0 var(--space-2); }
	.ok { font-size: var(--text-xs); color: var(--ok); margin: 0 0 var(--space-2); }
	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-4);
	}
	.meta { font-size: 10px; color: var(--text-2); }
	.btn {
		margin-left: auto;
		padding: 7px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.filters .btn { margin-left: 0; }
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
</style>
