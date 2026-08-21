<script lang="ts">
	import { onMount } from 'svelte';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { Machine } from '$lib/machines.svelte';

	const store = createStore();

	onMount(() => store.loadMachines());

	// The engine creates an lhystudios device itself at startup, so the kernel
	// always has something to talk to. That is not a machine of the user's, and
	// putting it in this list as "In use" reads as a device you added yourself. We
	// set it apart with the reason, rather than hiding it: it *is* active, and that
	// has to be visible.
	let eigen = $derived(store.machines.filter((m) => m.configured !== false));
	let placeholder = $derived(store.machines.find((m) => m.configured === false) ?? null);

	async function useMachine(machine: Machine) {
		if (await store.activate(machine.path)) await store.loadMachines();
	}

	async function removeMachine(machine: Machine) {
		if (await store.remove(machine.path)) await store.loadMachines();
	}

	// ------------------------------- exchanging a machine profile (gap E5)
	//
	// LightBurn has `.lbdev`: a manufacturer ships a ready-made profile, and whoever
	// sets up a second computer types nothing over. Same shape as the library of B7 —
	// look at what is in it first, only then create. A machine profile decides where
	// the head goes; loading what someone mailed you blind is one step away from a
	// head against its end stop.

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

	/** The engine's keys in words; nobody reads "bedwidth" as a bed. */
	const VELDNAAM: Record<string, MessageKey> = {
		bedwidth: 'setup.field.bedwidth',
		bedheight: 'setup.field.bedheight',
		interface: 'setup.field.interface',
		address: 'setup.field.address',
		serial_port: 'setup.field.serialPort',
		port: 'setup.field.port'
	};

	/** The name of a setting, or the engine's own key when we have no word for it. */
	function veldnaam(key: string): string {
		return key in VELDNAAM ? t(VELDNAAM[key]) : key;
	}

	let preview = $state<Voorbeeld | null>(null);
	let profielFout = $state<string | null>(null);
	let profileBusy = $state(false);
	let ingelezen = $state<string | null>(null);

	function token(): Record<string, string> {
		const t = typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		return t ? { Authorization: `Bearer ${t}` } : {};
	}

	function exporteer(machine: Machine) {
		const anchor = document.createElement('a');
		anchor.href = `/api/machines/${encodeURIComponent(machine.path)}/export.openkerf-machine`;
		anchor.download = `${machine.label}.openkerf-machine`;
		anchor.click();
	}

	async function kiesProfiel(bestand: File) {
		preview = null;
		ingelezen = null;
		profielFout = null;
		profileBusy = true;
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
					typeof data?.detail === 'string'
						? data.detail
						: t('setup.import.failed', { status: response.status });
				return;
			}
			preview = data;
		} catch (e) {
			profielFout = t('error.network', { message: e instanceof Error ? e.message : e });
		} finally {
			profileBusy = false;
		}
	}

	async function neemProfiel() {
		if (!preview) return;
		profileBusy = true;
		profielFout = null;
		try {
			const response = await fetch('/api/machines/import', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', ...token() },
				body: JSON.stringify({ profile: preview.profile })
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				profielFout =
					typeof data?.detail === 'string'
						? data.detail
						: t('setup.create.failed', { status: response.status });
				return;
			}
			ingelezen = data.skipped?.length
				? t('setup.imported.skipped', {
						label: data.label ?? preview.label,
						n: data.skipped.length
					})
				: t('setup.imported', { label: data.label ?? preview.label });
			preview = null;
			await store.loadMachines();
		} finally {
			profileBusy = false;
		}
	}
</script>

<svelte:head><title>{t('setup.head.machines')}</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>{t('setup.yourMachines')}</h1>
	{#if eigen.length === 0}
		<p class="empty">
			<strong>{t('setup.none.title')}</strong>
			<span class="muted">{t('setup.none.body')}</span>
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
						<span class="badge">{t('setup.inUse')}</span>
					{:else}
						<button class="btn" onclick={() => useMachine(machine)}>{t('setup.use')}</button>
					{/if}
					<!-- Settings used to be reachable only while creating the machine. -->
					<a class="btn" href="/setup/settings?machine={encodeURIComponent(machine.path)}">
						{t('setup.settings')}
					</a>
					<!-- Gap E5: this machine as a file, for a second computer. -->
					<button class="btn subtle" onclick={() => exporteer(machine)}
						>{t('setup.exportProfile')}</button
					>
					{#if !machine.active}
						<button class="btn subtle" onclick={() => removeMachine(machine)}
							>{t('common.remove')}</button
						>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	<div class="actions">
		<a class="btn primary" href="/setup/kind">{t('setup.addMachine')}</a>
		<!-- Gap E5: the same route as "Add a machine", but with a profile someone else
		     has already filled in. -->
		<label class="btn file">
			{t('setup.importProfile')}
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
	{#if ingelezen}<p class="done" role="status">{ingelezen}</p>{/if}

	{#if preview}
		<!-- What is in it first, only then create. A profile decides the bed size, the
		     connection and the mirroring; that should not happen *to* you. -->
		<aside class="preview">
			<h2>{t('setup.profile.title', { label: preview.label })}</h2>
			{#if preview.known}
				<p class="muted">
					{t('setup.profile.known', {
						name: `${preview.friendly_name}${preview.family ? ` · ${preview.family}` : ''}`,
						n: preview.settings
					})}
				</p>
			{:else}
				<p class="muted">{t('setup.profile.unknown', { type: preview.info })}</p>
			{/if}
			<dl class="facts">
				{#each Object.entries(preview.essential) as [name, value] (name)}
					<div><dt>{veldnaam(name)}</dt><dd class="mono">{value}</dd></div>
				{/each}
			</dl>
			{#if Object.keys(preview.local).length}
				<p class="lokaal">
					{t('setup.profile.local', {
						values: Object.entries(preview.local)
							.map(([name, value]) => `${veldnaam(name)} ${value}`)
							.join(', ')
					})}
				</p>
			{/if}
			<div class="uitknoppen">
				<button class="btn primary" disabled={profileBusy || !preview.known} onclick={neemProfiel}>
					{profileBusy ? t('common.busy') : t('setup.profile.create')}
				</button>
				<button class="btn subtle" onclick={() => (preview = null)}
					>{t('setup.profile.cancel')}</button
				>
			</div>
		</aside>
	{/if}

	{#if placeholder}
		<aside class="placeholder">
			<h2>{t('setup.placeholder.title')}</h2>
			<p class="muted">{t('setup.placeholder.body', { label: placeholder.label })}</p>
			<p class="muted">{t('setup.placeholder.yours')}</p>
			<a class="btn" href="/setup/settings?machine={encodeURIComponent(placeholder.path)}">
				{t('setup.placeholder.adopt')}
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
		/* A name the engine gives ("lhystudios1") has no break point: it pushed the badge
		   away or was cut off by it. Truncating with an ellipsis is honest — you see that
		   there is more. The full name stays in the title tip. */
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* Below ~420px there is no column left beside the name: at 390 the name kept 74px of
	   the 308 and "Ruida 5030" collided with the badge. The name then gets the whole line,
	   the actions the line below — which is also the order in which you read them. */
	@media (max-width: 420px) {
		.machines li {
			flex-wrap: wrap;
		}
		.machines li > div:first-child {
			flex: 1 0 100%;
		}
		/* The buttons may then share the full width; here they are the target of a thumb,
		   not of a mouse. */
		.machines li .btn,
		.machines li .badge {
			min-height: 44px;
			display: inline-flex;
			align-items: center;
		}
	}
	/* Accent on a 14% accent tint does not make AA (measured: 4.10 in light, 4.46 in
	   dark). The tint keeps carrying the accent colour, the text does not — the same way
	   out as in ToolRail, and without shifting the brand colour. */
	.badge {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--text-1);
	}
	.empty {
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
		/* A warning surface, not an error: this device works, it is simply not yours. See
		   DESIGN-SYSTEM, "certainty is a sentence". */
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

	/* A file picker that looks like the button beside it: the input itself is invisible
	   but stays the touch surface, so keyboard and screen reader simply get an input with
	   a name. */
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
	.done {
		margin: var(--space-4) 0 0;
		padding: var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--ok);
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		font-size: var(--text-xs);
	}
	.preview {
		margin-top: var(--space-4);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.preview h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: 0 0 var(--space-2);
	}
	.preview p { margin: 0 0 var(--space-2); font-size: var(--text-xs); }
	.facts {
		display: grid;
		gap: var(--space-1);
		margin: 0 0 var(--space-3);
		font-size: var(--text-xs);
	}
	.facts div { display: flex; justify-content: space-between; gap: var(--space-3); }
	.facts dt { color: var(--text-2); }
	.facts dd { margin: 0; }
	/* The address of the other workbench is the first thing here that does not hold. Not
	   an error, but something to check before you burn anything. */
	.lokaal {
		padding: var(--space-2) var(--space-3);
		border-left: 3px solid var(--warn-solid, var(--warn));
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		color: var(--text-1);
	}
	.uitknoppen { display: flex; gap: var(--space-2); flex-wrap: wrap; }
</style>
