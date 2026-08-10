<script lang="ts">
	import { OPERATIONS, SOURCE_LABEL, type LibraryStore, type Preset } from '$lib/library.svelte';
	import type { DesignOperation } from '$lib/design.svelte';

	let {
		library,
		operations,
		canEdit = false,
		onApplied
	}: {
		library: LibraryStore;
		operations: DesignOperation[];
		canEdit?: boolean;
		onApplied?: () => void;
	} = $props();

	let materialId = $state<number | null>(null);
	let adding = $state(false);
	let newMaterial = $state('');
	let draft = $state({ operation: 'snijden', thickness_mm: '3', speed_mm_s: '', power_percent: '' });
	let targetOperation = $state<string>('');

	let visible = $derived(library.presetsFor(materialId));
	let chosenOperation = $derived(
		operations.find((o) => o.id === targetOperation) ?? operations[0] ?? null
	);

	async function createMaterial() {
		if (!newMaterial.trim()) return;
		const created = await library.addMaterial(newMaterial.trim());
		if (created) {
			materialId = created.id;
			newMaterial = '';
			adding = false;
		}
	}

	async function createPreset() {
		if (materialId === null) return;
		const created = await library.addPreset({
			material_id: materialId,
			operation: draft.operation,
			thickness_mm: draft.thickness_mm === '' ? null : Number(draft.thickness_mm),
			speed_mm_s: Number(draft.speed_mm_s),
			power_percent: Number(draft.power_percent)
		});
		if (created) draft = { ...draft, speed_mm_s: '', power_percent: '' };
	}

	async function apply(preset: Preset) {
		const target = chosenOperation;
		if (!target) return;
		if (await library.applyTo(preset.id, target.id)) onApplied?.();
	}
</script>

<div class="section">
	<div class="section-head">
		<h2 class="section-title">Materiaal</h2>
		{#if canEdit}
			<button class="mini" onclick={() => (adding = !adding)}>
				{adding ? 'Annuleren' : 'Nieuw materiaal'}
			</button>
		{/if}
	</div>

	{#if library.error}
		<p class="error" role="alert">{library.error}</p>
	{/if}

	{#if adding}
		<div class="row">
			<input type="text" bind:value={newMaterial} placeholder="bijv. Multiplex berken" />
			<button class="btn" disabled={library.busy || !newMaterial.trim()} onclick={createMaterial}>
				Opslaan
			</button>
		</div>
	{/if}

	{#if library.materials.length === 0}
		<p class="muted">
			Nog geen materialen. Voeg er een toe en leg de instellingen vast die bij jouw machine werken.
		</p>
	{:else}
		<select class="picker" bind:value={materialId}>
			<option value={null}>Alle materialen</option>
			{#each library.materials as material (material.id)}
				<option value={material.id}>{material.name}</option>
			{/each}
		</select>
	{/if}
</div>

{#if library.materials.length}
	<div class="section">
		<div class="section-head">
			<h2 class="section-title">Presets</h2>
			{#if operations.length > 1}
				<select class="target" bind:value={targetOperation} title="Toepassen op welke laag">
					{#each operations as op, index (op.id)}
						<option value={op.id}>Laag {index + 1} · {op.label}</option>
					{/each}
				</select>
			{/if}
		</div>

		{#if visible.length === 0}
			<p class="muted">Geen presets voor dit materiaal.</p>
		{:else}
			{#each visible as preset (preset.id)}
				<article class="preset">
					<div class="head">
						<div class="what">
							<span class="name">{preset.material_name}</span>
							<span class="sub mono">
								{preset.thickness_mm !== null ? `${preset.thickness_mm} mm · ` : ''}{preset.operation}
							</span>
						</div>
						<span class="badge {SOURCE_LABEL[preset.source].tone}">
							{SOURCE_LABEL[preset.source].text}
						</span>
					</div>
					<div class="params">
						<div class="param">
							<div class="k">Snelheid</div>
							<div class="v mono">{preset.speed_mm_s} <small>mm/s</small></div>
						</div>
						<div class="param">
							<div class="k">Vermogen</div>
							<div class="v mono">{preset.power_percent} <small>%</small></div>
						</div>
						<div class="param">
							<div class="k">Passes</div>
							<div class="v mono">{preset.passes}</div>
						</div>
					</div>
					{#if canEdit}
						<div class="foot">
							<button
								class="btn primary"
								disabled={library.busy || !chosenOperation}
								onclick={() => apply(preset)}
							>
								Toepassen{chosenOperation ? ` op ${chosenOperation.label}` : ''}
							</button>
							<button class="mini" onclick={() => library.removePreset(preset.id)}>
								Verwijderen
							</button>
						</div>
					{/if}
				</article>
			{/each}
		{/if}

		{#if canEdit && materialId !== null}
			<div class="new-preset">
				<h3>Preset toevoegen</h3>
				<div class="grid">
					<label>
						<span>Bewerking</span>
						<select bind:value={draft.operation}>
							{#each OPERATIONS as op (op.value)}
								<option value={op.value}>{op.label}</option>
							{/each}
						</select>
					</label>
					<label><span>Dikte (mm)</span><input class="mono" bind:value={draft.thickness_mm} /></label>
					<label><span>Snelheid (mm/s)</span><input class="mono" bind:value={draft.speed_mm_s} /></label>
					<label><span>Vermogen (%)</span><input class="mono" bind:value={draft.power_percent} /></label>
				</div>
				<button
					class="btn"
					disabled={library.busy || !draft.speed_mm_s || !draft.power_percent}
					onclick={createPreset}
				>
					Opslaan
				</button>
			</div>
		{/if}
	</div>
{/if}

<style>
	.section + .section { margin-top: var(--space-6); }
	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.muted { color: var(--text-2); margin: 0; }
	.mini { font-size: var(--text-xs); color: var(--accent); }
	.row { display: flex; gap: var(--space-2); margin-bottom: var(--space-2); }
	.row input { flex: 1; min-width: 0; }
	input,
	select {
		font: inherit;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.picker, .target { width: 100%; }
	.target { width: auto; font-size: var(--text-xs); }
	.btn {
		padding: 7px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.preset {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		overflow: hidden;
		margin-top: var(--space-2);
	}
	.preset .head {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		padding: 10px;
	}
	.what { flex: 1; min-width: 0; }
	.name { font-weight: 600; }
	.sub { display: block; color: var(--text-2); font-size: 12px; }
	.badge {
		flex: none;
		font-size: var(--text-xs);
		font-weight: 500;
		padding: 2px 8px;
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-2);
	}
	.badge.ok {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		color: var(--ok);
	}
	.badge.warn {
		background: color-mix(in srgb, var(--warn) 16%, transparent);
		color: var(--warn);
	}
	.params {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		border-top: 1px solid var(--line);
	}
	.param { padding: 8px 10px; }
	.param + .param { border-left: 1px solid var(--line); }
	.param .k {
		font-size: 10px;
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.param .v { font-size: 14px; margin-top: 1px; }
	.param .v small { font-size: 10px; color: var(--text-2); }
	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: 8px 10px;
		border-top: 1px solid var(--line);
	}
	.new-preset {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px dashed var(--line);
	}
	.new-preset h3 {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.grid label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.grid input, .grid select { width: 100%; }
	.error {
		margin: 0 0 var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
</style>
