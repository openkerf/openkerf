<script lang="ts">
	/**
	 * The question in front of New, Open and Upload when the work is not saved.
	 *
	 * Three answers and nothing else: Cancel, Discard, Save. Save on an untitled project
	 * goes through Save as… first, which the page arranges; this window only asks.
	 *
	 * The order is the app's one ask row (`.ask-actions` in `tokens.css`): the way out
	 * first, the answer that throws the work away in the middle, the primary last. It
	 * read Save | Discard | Cancel here — the primary on the left, Cancel where every
	 * other window in the app has its primary — and this is the one dialog where the
	 * wrong reflex costs exactly what it is asking about.
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
	{#snippet footer()}
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
		<button class="btn danger" onclick={() => { open = false; onDiscard(); }}>{t('unsaved.discard')}</button>
		<button class="btn primary" onclick={() => { open = false; onSave(); }}>{t('unsaved.save')}</button>
	{/snippet}
</Dialog>
