<script lang="ts">
	/**
	 * One place where a failed command becomes visible.
	 *
	 * An import's error message lived in the Job tab, and you import from the top bar
	 * while you are in Design. Consequence: a broken file produced a neatly worded message
	 * nobody ever saw — all you saw was a bed that stayed empty. An error should appear
	 * where you are looking, not where it came from.
	 *
	 * It stays up until you click it away. A message that disappears by itself is one you
	 * miss precisely when you glanced at the machine.
	 *
	 * The refusal of an *edit* comes here for the same reason. It used to live only at the
	 * top of the design panel, and you draw from the tool rail, the right-click menu and
	 * the text window — from every tab, in other words. Placing a text with a placeholder
	 * no column fills while the Job tab was open therefore closed the window, put no shape
	 * on the bed and said nothing at all. Same complaint as the import, so the same answer,
	 * and the panel no longer says it a second time.
	 *
	 * `role="alert"` and not `status`: this is the answer to something you have just done,
	 * and the thing you asked for did not happen. That is worth interrupting for.
	 */
	import { t } from '$lib/i18n/index.svelte';
	import type { Controller } from '$lib/control.svelte';

	let {
		control,
		edits = null
	}: {
		control: Controller;
		/** A refused edit — drawing, moving, a layer. Anything with a sentence to clear. */
		edits?: { error: string | null } | null;
	} = $props();

	// Two senders, two sentences, and neither may push the other off the screen: a
	// machine that complains and a refused edit are separate facts. One below the other,
	// each with its own cross.
	let notices = $derived(
		[
			{
				key: 'control',
				text: control.error,
				clear: () => {
					control.error = null;
				}
			},
			{
				key: 'edits',
				text: edits?.error ?? null,
				clear: () => {
					if (edits) edits.error = null;
				}
			}
		].filter((notice) => Boolean(notice.text))
	);
</script>

{#if notices.length}
	<div class="notices">
		{#each notices as notice (notice.key)}
			<div class="notice" role="alert">
				<span class="stip" aria-hidden="true"></span>
				<p>{notice.text}</p>
				<button aria-label={t('message.close')} onclick={notice.clear}>×</button>
			</div>
		{/each}
	</div>
{/if}

<style>
	.notices {
		position: fixed;
		/* Top right, below the top bar. At first it was in the bottom right and covered
		   the zoom buttons; besides, most of these errors come from the top bar (open,
		   import, export) and that is where the answer should appear. */
		right: var(--space-4);
		/* Below the bars above the canvas, not over them (DESIGN-SYSTEM v4, "a message
		   does not cover a control"): at the old offset the card lay across the right
		   end of the action bar. `--topedge-height` is measured in `+page.svelte` and is
		   zero where there are no bars. The alarm card hangs from the same line. */
		top: calc(var(--topbar-height) + var(--topedge-height, 0px) + var(--space-3));
		z-index: 60;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: var(--space-2);
		max-width: min(420px, calc(100vw - 2 * var(--space-4)));
	}
	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-3);
		border: 1px solid var(--danger-solid);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		margin-top: var(--space-1h);
		border-radius: var(--radius-dot);
		background: var(--danger-solid);
	}
	p { margin: 0; }
	button {
		flex: none;
		width: 24px;
		height: 24px;
		margin: -4px -4px 0 0;
		border-radius: var(--radius-field);
		font-size: var(--text-md);
		line-height: 1;
		color: var(--text-2);
	}
	button:hover { background: var(--surface-2); color: var(--text-1); }
</style>
