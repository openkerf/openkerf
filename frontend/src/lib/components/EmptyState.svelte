<script lang="ts">
	import Icon from './Icon.svelte';

	/**
	 * What is missing, why, and the one thing that fills it.
	 *
	 * Twelve empty states were drawn twelve ways, and the projects window ended in a
	 * muted line with nothing to press. An empty state teaches the screen: the title says
	 * what would be here, the text says how it gets here, the action does it.
	 */
	let {
		title,
		text,
		center = false,
		icon = true,
		action
	}: {
		title: string;
		text?: string;
		center?: boolean;
		icon?: boolean;
		action?: import('svelte').Snippet;
	} = $props();
</script>

<div class="empty-state" class:center>
	{#if icon}<span class="empty-icon"><Icon name="empty" size={20} /></span>{/if}
	<p class="title">{title}</p>
	{#if text}<p class="help">{text}</p>{/if}
	{#if action}<div>{@render action()}</div>{/if}
</div>
