<script lang="ts">
	/**
	 * Turning notifications on and off, and seeing what the browser makes of it.
	 *
	 * Two guises, one component, because it is about the same thing:
	 *
	 * - `aanleiding` — the question itself, and we only ask it at the moment there
	 *   is something to report (a job that has just started). A permission prompt
	 *   without an occasion gets clicked away, and that refusal does not come back:
	 *   the browser remembers it for good. So we ask first ourselves, with the
	 *   reason, and only after a "yes" do we ask the browser.
	 * - `instellingen` — the fixed place. Permission denied is a state you have to
	 *   be able to see *and* undo, so it says not only that it is blocked but also
	 *   where you turn that back.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { permissionText, type Meldingen } from '$lib/notifications.svelte';

	let {
		notifications,
		variant = 'instellingen',
		onKlaar
	}: {
		notifications: Meldingen;
		variant?: 'aanleiding' | 'instellingen';
		onKlaar?: () => void;
	} = $props();

	let bezig = $state(false);

	async function aanzetten() {
		bezig = true;
		try {
			await notifications.ask();
		} finally {
			bezig = false;
		}
		if (notifications.permission === 'granted') onKlaar?.();
	}

	// The clock in the reader's own notation: 14:05 here, 2:05 pm elsewhere.
	function tijdstip(ms: number) {
		return new Intl.DateTimeFormat(i18n.locale, { timeStyle: 'short' }).format(new Date(ms));
	}
</script>

<div class="kaart" class:ask={variant === 'aanleiding'}>
	{#if variant === 'aanleiding'}
		<h3>{t('notify.ask.title')}</h3>
		<p>{t('notify.ask.body')}</p>
		<div class="acties">
			<button class="btn" onclick={() => { notifications.notNow(); onKlaar?.(); }}
				>{t('notify.ask.notNow')}</button
			>
			<button class="btn primary" disabled={bezig} onclick={aanzetten}>
				{bezig ? t('common.busy') : t('notify.ask.turnOn')}
			</button>
		</div>
		<p class="klein">{t('notify.ask.after')}</p>
	{:else}
		<!--
			The switch is off as long as the browser does not co-operate, even when the
			preference is "on". Otherwise a teal switch promises something that does
			not happen: on a blocked site it was on while no notification would ever
			arrive. The preference is kept, though — it springs back the moment the
			permission is there.
		-->
		<label class="schakel" class:machteloos={notifications.permission !== 'granted'}>
			<input
				type="checkbox"
				checked={notifications.aan && notifications.permission === 'granted'}
				disabled={notifications.permission !== 'granted'}
				onchange={(e) => notifications.set(e.currentTarget.checked)}
			/>
			<span class="spoor" aria-hidden="true"><span class="knikker"></span></span>
			<span class="tekst">
				<span class="titel">{t('notify.switch.title')}</span>
				<span class="klein">{t('notify.switch.body')}</span>
			</span>
		</label>

		<p
			class="stand"
			class:mis={notifications.permission === 'denied'}
			class:goed={notifications.permission === 'granted'}
		>
			<span class="stip" aria-hidden="true"></span>
			{permissionText(notifications.permission)}
		</p>

		{#if notifications.permission === 'default'}
			<button class="btn primary" disabled={bezig} onclick={aanzetten}>
				{bezig ? t('common.busy') : t('notify.askPermission')}
			</button>
		{:else if notifications.permission === 'denied'}
			<p class="herstel">{t('notify.blocked.howto')}</p>
		{:else if notifications.permission === 'granted'}
			<button class="btn" onclick={() => notifications.test()}>{t('notify.sendTest')}</button>
		{/if}

		{#if notifications.failure}
			<p class="failure" role="alert">{notifications.failure}</p>
		{/if}

		{#if notifications.last}
			<p class="last">
				{t('notify.last', {
					time: tijdstip(notifications.last.tijd),
					title: notifications.last.titel
				})}
				{#if !notifications.last.getoond}
					<span class="klein">{t('notify.last.notShown')}</span>
				{/if}
			</p>
		{/if}

		<p class="klein grens">{t('notify.limits')}</p>
	{/if}
</div>

<style>
	.kaart {
		display: grid;
		gap: var(--space-3);
	}
	.kaart.ask {
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
	.klein {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.grens {
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.acties {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
		flex-wrap: wrap;
	}
	.btn {
		min-height: 36px;
		padding: 0 var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
		justify-self: start;
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}

	/* Schakelaar: aan/uit per stuk, conform de patroonkeuzewijzer. */
	.schakel {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		cursor: pointer;
	}
	.schakel input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.spoor {
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
	.knikker {
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
	.schakel input:checked + .spoor {
		background: var(--accent);
		border-color: var(--accent);
	}
	.schakel input:checked + .spoor .knikker {
		transform: translateX(16px);
	}
	.schakel input:focus-visible + .spoor {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.schakel.machteloos {
		cursor: default;
	}
	.schakel.machteloos .spoor,
	.schakel.machteloos .knikker {
		opacity: 0.55;
	}
	.tekst {
		display: grid;
		gap: 2px;
	}
	.titel {
		font-weight: 500;
	}

	.stand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	/* Kleur naast het woord, nooit in plaats ervan: de zin zegt het al, de stip
	   maakt het scanbaar. */
	.stand.goed .stip {
		background: var(--ok);
	}
	.stand.mis {
		color: var(--warn);
	}
	.stand.mis .stip {
		background: var(--warn-solid);
	}
	.herstel {
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
