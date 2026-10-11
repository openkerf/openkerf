<script lang="ts">
	import Icon from './Icon.svelte';

	/**
	 * A sentence about the state of things, boxed so it is not read as help.
	 *
	 * The tone sets the colour and the icon together, so the colour is never the only
	 * signal. `live` makes a screen reader announce it when it appears — for a notice that
	 * comes in response to something, not for one that is simply there. `class` adds a
	 * name that says *which* notice this is (a hook for tests and for the parent's layout),
	 * never a face of its own.
	 */
	let {
		tone = 'info',
		live = false,
		class: name = '',
		children
	}: {
		tone?: 'info' | 'ok' | 'warn' | 'danger';
		live?: boolean;
		class?: string;
		children: import('svelte').Snippet;
	} = $props();
</script>

<div class="notice {tone} {name}" role={live ? (tone === 'danger' ? 'alert' : 'status') : undefined}>
	<span class="notice-icon"><Icon name={tone} /></span>
	<div class="notice-body">{@render children()}</div>
</div>
