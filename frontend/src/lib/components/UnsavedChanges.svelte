<script lang="ts">
	/**
	 * The question in front of New, Open and Upload when the work is not saved.
	 *
	 * Three answers and nothing else: Save, Discard, Cancel. Save on an untitled project
	 * goes through Save as… first, which the page arranges; this window only asks.
	 */
	import Dialog from './Dialog.svelte';
	import { t } from '$lib/i18n/index.svelte';
	let {
		open = $bindable(),
		name,
		onSave,
		onDiscard
	}: { open: boolean; name: string | null; onSave: () => void; onDiscard: () => void } = $props();
</script>

<Dialog title={t('unsaved.title')} bind:open width="420px">
	<p>{t('unsaved.body', { name: name ?? t('topbar.project.untitled') })}</p>
	<div class="answers">
		<button class="btn primary" onclick={() => { open = false; onSave(); }}>{t('unsaved.save')}</button>
		<button class="btn danger" onclick={() => { open = false; onDiscard(); }}>{t('unsaved.discard')}</button>
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
	</div>
</Dialog>

<style>
	.answers { display: flex; gap: var(--space-2); justify-content: flex-end; margin-top: var(--space-4); }
</style>
