<script lang="ts">
	/**
	 * Turning notifications on and off, and seeing what the browser makes of it.
	 *
	 * Two guises, one component, because it is about the same thing:
	 *
	 * - `prompt` — the question itself, and we only ask it at the moment there
	 *   is something to report (a job that has just started). A permission prompt
	 *   without an occasion gets clicked away, and that refusal does not come back:
	 *   the browser remembers it for good. So we ask first ourselves, with the
	 *   reason, and only after a "yes" do we ask the browser.
	 * - `settings` — the fixed place. Permission denied is a state you have to
	 *   be able to see *and* undo, so it says not only that it is blocked but also
	 *   where you turn that back.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { permissionText, type Notifications } from '$lib/notifications.svelte';

	let {
		notifications,
		variant = 'settings',
		onDone
	}: {
		notifications: Notifications;
		variant?: 'prompt' | 'settings';
		onDone?: () => void;
	} = $props();

	let busy = $state(false);

	async function turnOn() {
		busy = true;
		try {
			await notifications.ask();
		} finally {
			busy = false;
		}
		if (notifications.permission === 'granted') onDone?.();
	}

	// The clock in the reader's own notation: 14:05 here, 2:05 pm elsewhere.
	function clockTime(ms: number) {
		return new Intl.DateTimeFormat(i18n.locale, { timeStyle: 'short' }).format(new Date(ms));
	}
</script>

<div class="card" class:ask={variant === 'prompt'}>
	{#if variant === 'prompt'}
		<h3>{t('notify.ask.title')}</h3>
		<p>{t('notify.ask.body')}</p>
		<div class="actions">
			<button class="btn" onclick={() => { notifications.notNow(); onDone?.(); }}
				>{t('notify.ask.notNow')}</button
			>
			<button class="btn primary" disabled={busy} onclick={turnOn}>
				{busy ? t('common.busy') : t('notify.ask.turnOn')}
			</button>
		</div>
		<p class="small">{t('notify.ask.after')}</p>
	{:else}
		<!--
			The switch is off as long as the browser does not co-operate, even when the
			preference is "on". Otherwise a teal switch promises something that does
			not happen: on a blocked site it was on while no notification would ever
			arrive. The preference is kept, though — it springs back the moment the
			permission is there.
		-->
		<label class="toggle" class:powerless={notifications.permission !== 'granted'}>
			<input
				type="checkbox"
				checked={notifications.on && notifications.permission === 'granted'}
				disabled={notifications.permission !== 'granted'}
				onchange={(e) => notifications.set(e.currentTarget.checked)}
			/>
			<span class="track" aria-hidden="true"><span class="knob"></span></span>
			<span class="words">
				<span class="title">{t('notify.switch.title')}</span>
				<span class="small">{t('notify.switch.body')}</span>
			</span>
		</label>

		<p
			class="state"
			class:bad={notifications.permission === 'denied'}
			class:good={notifications.permission === 'granted'}
		>
			<span class="dot" aria-hidden="true"></span>
			{permissionText(notifications.permission)}
		</p>

		{#if notifications.permission === 'default'}
			<button class="btn primary" disabled={busy} onclick={turnOn}>
				{busy ? t('common.busy') : t('notify.askPermission')}
			</button>
		{:else if notifications.permission === 'denied'}
			<p class="fix">{t('notify.blocked.howto')}</p>
		{:else if notifications.permission === 'granted'}
			<button class="btn" onclick={() => notifications.test()}>{t('notify.sendTest')}</button>
		{/if}

		{#if notifications.failure}
			<p class="failure" role="alert">{notifications.failure}</p>
		{/if}

		{#if notifications.last}
			<p class="last">
				{t('notify.last', {
					time: clockTime(notifications.last.time),
					title: notifications.last.title
				})}
				{#if !notifications.last.shown}
					<span class="small">{t('notify.last.notShown')}</span>
				{/if}
			</p>
		{/if}

		<p class="small edge">{t('notify.limits')}</p>
	{/if}
</div>

<style>
	.card {
		display: grid;
		gap: var(--space-3);
	}
	.card.ask {
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	p {
		margin: 0;
		color: var(--text-1);
	}
	.small {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.edge {
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
		flex-wrap: wrap;
	}

	/* Toggle: on/off per item, in line with the pattern guide. */
	.toggle {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		cursor: pointer;
	}
	.toggle input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.track {
		flex: none;
		position: relative;
		width: 40px;
		height: 24px;
		margin-top: 1px;
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		transition: background var(--transition), border-color var(--transition);
	}
	.knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 18px;
		height: 18px;
		border-radius: var(--radius-dot);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
		transition: transform var(--transition);
	}
	.toggle input:checked + .track {
		background: var(--accent);
		border-color: var(--accent);
	}
	.toggle input:checked + .track .knob {
		transform: translateX(16px);
	}
	.toggle input:focus-visible + .track {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.toggle.powerless {
		cursor: default;
	}
	.toggle.powerless .track,
	.toggle.powerless .knob {
		opacity: 0.55;
	}
	.words {
		display: grid;
		gap: 2px;
	}
	.title {
		font-weight: 500;
	}

	.state {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.dot {
		flex: none;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	/* Colour beside the word, never instead of it: the sentence already says it,
	   the dot makes it scannable. */
	.state.good .dot {
		background: var(--ok);
	}
	.state.bad {
		color: var(--warn);
	}
	.state.bad .dot {
		background: var(--warn-solid);
	}
	.fix {
		font-size: var(--text-xs);
		line-height: 1.5;
		padding: var(--space-3);
		border-left: 3px solid var(--warn-solid);
		border-radius: var(--radius-sharp);
		background: var(--surface-2);
	}
	.failure {
		font-size: var(--text-xs);
		color: var(--danger);
	}
	.last {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
</style>
