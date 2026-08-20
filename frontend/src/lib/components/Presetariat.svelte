<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
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

	/**
	 * Wat de hele lijst gemeen heeft, zeggen we één keer.
	 *
	 * Twenty-six rows with exactly the same amber "Starting value" pill inform
	 * nobody; they turn a warning into wallpaper. If there is variation in it, every
	 * row deserves its own pill.
	 */
	let soorten = $derived(new Set(catalogue.presets.map((p) => p.source.kind)));
	let eenSoort = $derived(soorten.size === 1 ? [...soorten][0] : null);
</script>

<Dialog title={t('presetariat.title')} bind:open width="720px">
	<p class="lead">{t('presetariat.lead')}</p>

	<div class="filters">
		<label>
			<span>{t('library.machine')}</span>
			<select
				bind:value={machineId}
				onchange={() => refresh()}
			>
				<option value={null}>{t('presetariat.allMachines')}</option>
				{#each library.machines as machine (machine.id)}
					<option value={machine.id}>{machine.name}</option>
				{/each}
			</select>
		</label>
		<label>
			<span>{t('library.operation')}</span>
			<select bind:value={operation} onchange={() => refresh()}>
				<option value="">{t('presetariat.allOperations')}</option>
				{#each OPERATIONS as item (item.value)}
					<option value={item.value}>{item.label}</option>
				{/each}
			</select>
		</label>
		<label class="grow">
			<span>{t('library.material')}</span>
			<input
				type="search"
				bind:value={material}
				placeholder={t('presetariat.materialPlaceholder')}
				oninput={() => refresh()}
			/>
		</label>
		<button class="btn" disabled={catalogue.busy} onclick={() => refresh(true)}
			>{t('presetariat.refresh')}</button
		>
	</div>

	{#if catalogue.error}
		<p class="warn">{catalogue.error}</p>
	{/if}
	{#if catalogue.stale}
		<p class="warn">{t('presetariat.stale')}</p>
	{/if}
	{#if result}
		<p class="ok">
			{result.skipped
				? t('presetariat.imported.skipped', { n: result.imported, skipped: result.skipped })
				: t('presetariat.imported', { n: result.imported })}
		</p>
	{/if}

	{#if eenSoort}
		{@const gedeeld = CONFIDENCE[eenSoort] ?? CONFIDENCE.handmatig}
		<p class="gedeeld {gedeeld.tone}">
			{t(
				eenSoort === 'handmatig'
					? 'presetariat.allOf.manual'
					: eenSoort === 'testraster'
						? 'presetariat.allOf.grid'
						: 'presetariat.allOf.maker',
				{ kind: gedeeld.text.toLowerCase() }
			)}
		</p>
	{/if}

	<div class="list">
		{#each catalogue.presets as preset (preset.id)}
			{@const badge = CONFIDENCE[preset.source.kind] ?? CONFIDENCE.handmatig}
			<label class="row" class:done={preset.imported} title={preset.note ?? undefined}>
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
				{#if !eenSoort}
					<span class="badge {badge.tone}">{badge.text}</span>
				{/if}
				{#if preset.verified}
					<span class="badge ok" title={t('presetariat.verified.title')}>{t('presetariat.verified')}</span>
				{/if}
				{#if preset.imported}
					<span class="badge neutral">{t('presetariat.inLibrary')}</span>
				{/if}
			</label>
		{:else}
			<p class="empty">
				{catalogue.busy ? t('presetariat.fetching') : t('presetariat.nothing')}
			</p>
		{/each}
	</div>

	<div class="actions">
		<span class="meta mono">
			{catalogue.version
				? t('presetariat.count.version', {
						shown: catalogue.presets.length,
						total: catalogue.total,
						version: catalogue.version
					})
				: t('presetariat.count', { shown: catalogue.presets.length, total: catalogue.total })}
		</span>
		<button
			class="btn primary"
			disabled={!canEdit || !catalogue.chosen.size || catalogue.busy}
			onclick={importChosen}
		>
			{catalogue.chosen.size
				? t('presetariat.importN', { n: catalogue.chosen.size })
				: t('presetariat.import')}
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
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.filters .grow { flex: 1; min-width: 160px; }
	select,
	input[type='search'] {
		font: inherit;
		width: 100%;
		padding: 8px 8px;
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
		padding: 8px 8px;
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.row:hover { background: var(--surface-2); }
	.row.done { opacity: 0.55; }
	.what { display: grid; }
	.sub { color: var(--text-2); font-size: var(--text-xs); }
	.numbers { margin-left: auto; color: var(--text-1); }
	.badge {
		font-size: var(--text-xs);
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		color: var(--text-2);
		white-space: nowrap;
	}
	.badge.ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
	.badge.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
	.gedeeld {
		margin: 0 0 var(--space-2);
		padding: var(--space-1h) 8px;
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.gedeeld.warn {
		color: var(--warn);
		background: color-mix(in srgb, var(--warn) 12%, transparent);
	}
	.gedeeld.ok {
		color: var(--ok);
		background: color-mix(in srgb, var(--ok) 10%, transparent);
	}
	.gedeeld.neutral { color: var(--text-2); background: var(--surface-2); }
	.empty { font-size: var(--text-xs); color: var(--text-2); padding: var(--space-4) 0; }
	.warn { font-size: var(--text-xs); color: var(--warn); margin: 0 0 var(--space-2); }
	.ok { font-size: var(--text-xs); color: var(--ok); margin: 0 0 var(--space-2); }
	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-4);
	}
	.meta { font-size: var(--text-xs); color: var(--text-2); }
	.btn {
		margin-left: auto;
		padding: 8px 12px;
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
