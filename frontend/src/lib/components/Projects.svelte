<script lang="ts">
	/**
	 * The Projects window: what is on the server, and — in `saveAs` mode — the name to
	 * save the work under.
	 *
	 * One window for both because they show the same list: choosing a row while saving
	 * fills the field, and an existing name asks before it is replaced. The name rule is
	 * applied while you type, as the machine-name field does it, so what is in the box
	 * is what the folder gets.
	 *
	 * Rename and Delete ask in the window itself, the same way the overwrite question
	 * does — never through `window.prompt`/`window.confirm`. `Offset.svelte` carries the
	 * reasoning: a browser dialog sits outside the theme, validates nothing, cannot be
	 * translated, and can be switched off by the user, at which point the button does
	 * nothing and says so to nobody.
	 */
	import Dialog from './Dialog.svelte';
	import Menu from './Menu.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { cleanName, MAX_NAME, type ProjectEntry, type ProjectsStore } from '$lib/projects.svelte';
	import type { Menu as MenuList } from '$lib/actions';

	let {
		projects,
		open = $bindable(),
		mode = 'open',
		onOpen,
		onSaved
	}: {
		projects: ProjectsStore;
		open: boolean;
		mode?: 'open' | 'saveAs';
		/** The user chose a row to open; the page asks about unsaved work first. */
		onOpen?: (name: string) => void;
		onSaved?: (entry: ProjectEntry) => void;
	} = $props();

	let typed = $state('');
	/** The one question the window can be asking right now — never more than one. */
	type Ask =
		| { kind: 'overwrite'; name: string }
		| { kind: 'rename'; from: string; typed: string }
		| { kind: 'delete'; name: string };
	let ask = $state<Ask | null>(null);
	let rowMenu = $state<{ list: MenuList; x: number; y: number } | null>(null);

	$effect(() => {
		if (open) {
			projects.load();
			typed = projects.current?.name ?? '';
			ask = null;
		}
	});

	const saveOff = $derived(
		projects.busy ? t('reason.busy') : cleanName(typed) === '' ? t('reason.needsProjectName') : undefined
	);
	const when = (iso: string) =>
		new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));

	function nameTyped(event: Event & { currentTarget: HTMLInputElement }) {
		const field = event.currentTarget;
		const kept = cleanName(field.value);
		if (kept !== field.value.trim()) {
			const at = field.selectionStart ?? kept.length;
			field.value = kept;
			field.setSelectionRange(Math.min(at, kept.length), Math.min(at, kept.length));
		}
		typed = kept;
	}

	function renameTyped(event: Event & { currentTarget: HTMLInputElement }) {
		if (ask?.kind !== 'rename') return;
		const field = event.currentTarget;
		const kept = cleanName(field.value);
		if (kept !== field.value.trim()) {
			const at = field.selectionStart ?? kept.length;
			field.value = kept;
			field.setSelectionRange(Math.min(at, kept.length), Math.min(at, kept.length));
		}
		ask = { ...ask, typed: kept };
	}

	async function save(overwrite = false) {
		const name = cleanName(typed);
		if (!name) return;
		if (!overwrite && projects.taken(name)) {
			ask = { kind: 'overwrite', name };
			return;
		}
		const entry = await projects.save(name, overwrite);
		if (entry) {
			ask = null;
			open = false;
			onSaved?.(entry);
		}
	}

	async function applyRename() {
		if (ask?.kind !== 'rename') return;
		const { from, typed: to } = ask;
		if (!to || to === from) {
			ask = null;
			return;
		}
		if (await projects.rename(from, to)) ask = null;
	}

	async function applyDelete() {
		if (ask?.kind !== 'delete') return;
		if (await projects.remove(ask.name)) ask = null;
	}

	function menuFor(entry: ProjectEntry, at: HTMLElement) {
		const box = at.getBoundingClientRect();
		rowMenu = {
			x: box.right,
			y: box.bottom,
			list: [
				{
					items: [
						{
							id: 'project.rename',
							label: t('projects.rename'),
							run: () => (ask = { kind: 'rename', from: entry.name, typed: entry.name })
						},
						{
							id: 'project.delete',
							label: t('projects.delete'),
							danger: true,
							run: () => (ask = { kind: 'delete', name: entry.name })
						}
					]
				}
			]
		};
	}
</script>

<Dialog title={mode === 'saveAs' ? t('projects.saveAs.title') : t('projects.title')} bind:open width="560px">
	{#if projects.error}
		<p class="error" role="alert">{projects.error}</p>
	{/if}
	{#if projects.list.length === 0}
		<p class="hint">{t('projects.empty')}</p>
	{:else}
		<div class="rows" role="list">
			<div class="head"><span>{t('projects.column.name')}</span><span>{t('projects.column.saved')}</span><span></span></div>
			{#each projects.list as entry (entry.name)}
				<div
					class="row"
					class:current={entry.current}
					role="listitem"
					ondblclick={() => (mode === 'saveAs' ? (typed = entry.name) : onOpen?.(entry.name))}
				>
					<span class="name">{entry.name}{#if entry.current} <em>{t('projects.current')}</em>{/if}</span>
					<span class="when">{when(entry.saved_at)}</span>
					<span class="verbs">
						{#if mode === 'open'}
							<button class="btn open" onclick={() => onOpen?.(entry.name)}>{t('projects.open')}</button>
						{:else}
							<button class="btn" onclick={() => (typed = entry.name)}>{t('projects.name')}</button>
						{/if}
						<button class="btn more" aria-haspopup="menu" aria-label={t('common.more')} onclick={(e) => menuFor(entry, e.currentTarget as HTMLElement)}>⋮</button>
					</span>
				</div>
			{/each}
		</div>
	{/if}
	{#if mode === 'saveAs'}
		<div class="saveas">
			<label>
				<span>{t('projects.name')}</span>
				<input class="project-name" type="text" maxlength={MAX_NAME} value={typed} oninput={nameTyped} />
			</label>
			<button class="btn primary save" disabled={Boolean(saveOff)} title={saveOff} onclick={() => save(false)}>{t('projects.save')}</button>
		</div>
	{/if}
	{#if ask?.kind === 'overwrite'}
		<p class="ask" role="alert">
			{t('projects.overwrite.ask', { name: ask.name })}
			<button class="btn danger" onclick={() => save(true)}>{t('projects.overwrite')}</button>
			<button class="btn" onclick={() => (ask = null)}>{t('common.cancel')}</button>
		</p>
	{:else if ask?.kind === 'rename'}
		<div class="ask rename" role="alert">
			<label>
				<span>{t('projects.rename.to', { name: ask.from })}</span>
				<input class="rename-name" type="text" maxlength={MAX_NAME} value={ask.typed} oninput={renameTyped} />
			</label>
			<button
				class="btn primary"
				disabled={!ask.typed || ask.typed === ask.from}
				title={!ask.typed ? t('reason.needsProjectName') : ask.typed === ask.from ? t('projects.rename.same') : undefined}
				onclick={applyRename}
			>{t('projects.rename')}</button>
			<button class="btn" onclick={() => (ask = null)}>{t('common.cancel')}</button>
		</div>
	{:else if ask?.kind === 'delete'}
		<p class="ask" role="alert">
			{t('projects.delete.ask', { name: ask.name })}
			<button class="btn danger" onclick={applyDelete}>{t('projects.delete')}</button>
			<button class="btn" onclick={() => (ask = null)}>{t('common.cancel')}</button>
		</p>
	{/if}
</Dialog>
{#if rowMenu}
	<Menu menu={rowMenu.list} x={rowMenu.x} y={rowMenu.y} onClose={() => (rowMenu = null)} />
{/if}

<style>
	.rows { display: grid; gap: 2px; }
	.head, .row { display: grid; grid-template-columns: 1fr auto auto; gap: var(--space-3); align-items: center; padding: var(--space-2) var(--space-3); }
	.head { font-size: var(--text-xs); color: var(--text-2); text-transform: uppercase; letter-spacing: 0.04em; }
	.row { border-radius: var(--radius-field); min-height: 44px; }
	.row:hover { background: var(--surface-2); }
	.row.current .name { font-weight: 600; }
	.row em { font-style: normal; color: var(--text-2); font-size: var(--text-xs); margin-left: var(--space-2); }
	.when { color: var(--text-2); font-size: var(--text-sm); white-space: nowrap; }
	.verbs { display: flex; gap: var(--space-2); }
	.saveas { display: flex; gap: var(--space-2); align-items: end; margin-top: var(--space-4); }
	.saveas label { display: grid; gap: 4px; flex: 1; }
	.saveas input { min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-field); font: inherit; }
	.ask { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; margin-top: var(--space-3); }
	.ask.rename label { display: grid; gap: 4px; flex: 1; min-width: 180px; }
	.ask.rename input { min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-field); font: inherit; width: 100%; }
	.hint, .error { color: var(--text-2); }
	.error { color: var(--danger, #b3261e); }
</style>
