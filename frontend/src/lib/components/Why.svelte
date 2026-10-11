<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	/**
	 * The reasoning behind a control, one press away.
	 *
	 * The sentences that explain a setting are worth keeping — they are where the
	 * measured reasons live — but under every control at once they pushed Start and Stop
	 * down the panel on a tablet. This fold holds them. Instructions you need in order to
	 * act, refusals and warnings stay on screen; only the "why" goes in here.
	 */
	let {
		label,
		children
	}: {
		/** Defaults to "Why?"; a fold about something else names it. */
		label?: string;
		children: import('svelte').Snippet;
	} = $props();
</script>

<details class="fold why">
	<summary>{label ?? t('common.why')}</summary>
	<div class="help">{@render children()}</div>
</details>
