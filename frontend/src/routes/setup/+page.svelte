<script lang="ts">
	import { onMount } from 'svelte';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import Notice from '$components/Notice.svelte';
	import EmptyState from '$components/EmptyState.svelte';
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
	{#if store.error}<Notice tone="danger" live>{store.error}</Notice>{/if}

	<h1 class="title">{t('setup.yourMachines')}</h1>
	{#if eigen.length === 0}
		<!-- The action that fills it is "Add a machine" in the row below, not a second
		     primary here. -->
		<EmptyState title={t('setup.none.title')} text={t('setup.none.body')} />
	{:else}
		<ul class="machines">
			{#each eigen as machine (machine.path)}
				<li>
					<div class="who">
						<div class="name" title={machine.label}>{machine.label}</div>
						<div class="help mono">{machine.path}</div>
					</div>
					<div class="verbs">
						<!-- "In use" is a state, so a badge and never the accent. -->
						{#if machine.active}
							<span class="badge ok">{t('setup.inUse')}</span>
						{:else}
							<button class="btn" onclick={() => useMachine(machine)}>{t('setup.use')}</button>
						{/if}
						<!-- Settings used to be reachable only while creating the machine. -->
						<a class="btn" href="/setup/settings?machine={encodeURIComponent(machine.path)}">
							{t('setup.settings')}
						</a>
						<!-- The rotary is bolted into *this* bed, so it belongs with this machine
						     and not with the design. -->
						<a class="btn" href="/setup/rotary?machine={encodeURIComponent(machine.path)}">
							{t('setup.rotary')}
						</a>
						<!-- Gap E5: this machine as a file, for a second computer. A quiet verb,
						     not a faded one: it is available, just not the point of the row. -->
						<button class="btn ghost" onclick={() => exporteer(machine)}
							>{t('setup.exportProfile')}</button
						>
						{#if !machine.active}
							<button class="btn ghost" onclick={() => removeMachine(machine)}
								>{t('common.remove')}</button
							>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}

	<div class="ask-actions">
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
		<a class="btn primary" href="/setup/kind">{t('setup.addMachine')}</a>
	</div>

	{#if profielFout}<div class="after"><Notice tone="danger" live>{profielFout}</Notice></div>{/if}
	{#if ingelezen}<div class="after"><Notice tone="ok" live>{ingelezen}</Notice></div>{/if}

	{#if preview}
		<!-- What is in it first, only then create. A profile decides the bed size, the
		     connection and the mirroring; that should not happen *to* you. -->
		<aside class="card inset preview">
			<h2 class="title">{t('setup.profile.title', { label: preview.label })}</h2>
			{#if preview.known}
				<p class="help">
					{t('setup.profile.known', {
						name: `${preview.friendly_name}${preview.family ? ` · ${preview.family}` : ''}`,
						n: preview.settings
					})}
				</p>
			{:else}
				<p class="help">{t('setup.profile.unknown', { type: preview.info })}</p>
			{/if}
			<dl class="facts">
				{#each Object.entries(preview.essential) as [name, value] (name)}
					<div><dt>{veldnaam(name)}</dt><dd class="mono">{value}</dd></div>
				{/each}
			</dl>
			{#if Object.keys(preview.local).length}
				<!-- The address of the other workbench is the first thing here that does not
				     hold. Not an error, but something to check before you burn anything. -->
				<Notice tone="warn">
					{t('setup.profile.local', {
						values: Object.entries(preview.local)
							.map(([name, value]) => `${veldnaam(name)} ${value}`)
							.join(', ')
					})}
				</Notice>
			{/if}
			<div class="ask-actions">
				<button class="btn" onclick={() => (preview = null)}>{t('setup.profile.cancel')}</button>
				<button
					class="btn primary"
					disabled={profileBusy || !preview.known}
					title={profileBusy ? t('common.busy') : t('reason.notLoaded')}
					onclick={neemProfiel}
				>
					{profileBusy ? t('common.busy') : t('setup.profile.create')}
				</button>
			</div>
		</aside>
	{/if}

	{#if placeholder}
		<!-- A warning, not an error: this device works, it is simply not yours. -->
		<div class="after placeholder">
			<Notice tone="warn">
				<strong>{t('setup.placeholder.title')}</strong>
				<span>{t('setup.placeholder.body', { label: placeholder.label })}</span>
				<span>{t('setup.placeholder.yours')}</span>
				<span>
					<a class="btn mini" href="/setup/settings?machine={encodeURIComponent(placeholder.path)}">
						{t('setup.placeholder.adopt')}
					</a>
				</span>
			</Notice>
		</div>
	{/if}
</section>

<style>
	.machines {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	/* Rows on a hairline, not a card each: they already sit inside the step's card. */
	.machines li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-3) 0;
	}
	.machines li + li {
		border-top: 1px solid var(--line);
	}
	/* The name keeps at least a readable column; when the verbs do not fit beside it they
	   go to the line below — the order in which you read them anyway. */
	.who {
		flex: 1 1 200px;
		min-width: 0;
	}
	.verbs {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
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
	.after {
		margin-top: var(--space-4);
	}
	.placeholder {
		margin-top: var(--space-8);
	}

	/* A file picker that looks like the button beside it: the input itself is invisible
	   but stays the touch surface, so keyboard and screen reader simply get an input with
	   a name. */
	.btn.file {
		position: relative;
		overflow: hidden;
	}
	.btn.file input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.preview {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.preview .ask-actions {
		margin-top: var(--space-2);
	}
	.facts {
		display: grid;
		gap: var(--space-1);
		margin: 0;
		font-size: var(--text-xs);
	}
	.facts div { display: flex; justify-content: space-between; gap: var(--space-3); }
	.facts dt { color: var(--text-2); }
	.facts dd { margin: 0; }
</style>
