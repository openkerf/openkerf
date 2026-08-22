<script module lang="ts">
	/** How many dialogs are open, counted over every instance of this component. */
	let openDialogs = 0;
</script>

<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	/**
	 * An overlay dialog for libraries and tools.
	 *
	 * By DESIGN-SYSTEM.md: the right-hand panel is for the here and now (selection,
	 * layers, machine, job); things you search and compare in get the room of a dialog of
	 * their own.
	 */
	let {
		title,
		open = $bindable(),
		width = '560px',
		children
	}: {
		title: string;
		open: boolean;
		width?: string;
		children: import('svelte').Snippet;
	} = $props();

	let panel = $state<HTMLElement | null>(null);

	/**
	 * A flag on the root while any dialog is open, and how many are.
	 *
	 * The alarm about the machine sits above everything on purpose (AlarmCard: "an
	 * alarm belongs behind nothing"), and it is right about that — but it lay across
	 * the middle of the cut-path drawing, which is one picture and nothing else:
	 * measured 620 x 111 px over a drawing of 1006 x 522, hiding contour number 1.
	 * So the alarm stays on top and steps aside instead; it reads this flag.
	 */
	$effect(() => {
		if (!open) return;
		openDialogs += 1;
		document.documentElement.dataset.modal = 'open';
		return () => {
			openDialogs -= 1;
			if (openDialogs <= 0) {
				openDialogs = 0;
				delete document.documentElement.dataset.modal;
			}
		};
	});

	/**
	 * Focus goes in when the window opens and comes back out when it closes.
	 *
	 * Measured before this: Tab from an open cut-path window visited Close, Play and the
	 * scrubber and then walked out of the dialog into the page behind it (stop 4 of 10
	 * was already outside `[role=dialog]`), and Escape left `document.activeElement` on
	 * BODY — so the keyboard was back at the top of the page instead of at the button it
	 * came from. One fix here, for every dialog in the app.
	 */
	$effect(() => {
		if (!open) return;
		const before = document.activeElement as HTMLElement | null;
		panel?.focus();
		return () => before?.focus?.();
	});

	/** Everything inside the panel that can take focus, in document order. */
	function focusable(): HTMLElement[] {
		if (!panel) return [];
		return [
			...panel.querySelectorAll<HTMLElement>(
				'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])'
			)
		].filter((node) => node.offsetParent !== null || node === document.activeElement);
	}

	function cycle(event: KeyboardEvent) {
		const stops = focusable();
		if (!stops.length) {
			// Nothing to move to: keep the ring on the panel rather than letting Tab out.
			event.preventDefault();
			panel?.focus();
			return;
		}
		const first = stops[0];
		const last = stops[stops.length - 1];
		const here = document.activeElement;
		if (event.shiftKey && (here === first || here === panel)) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && here === last) {
			event.preventDefault();
			first.focus();
		} else if (!panel?.contains(here)) {
			event.preventDefault();
			first.focus();
		}
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="backdrop"
		onclick={(e) => {
			if (e.target === e.currentTarget) open = false;
		}}
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
		<section
			class="panel"
			style="width: min({width}, calc(100vw - 2 * var(--space-6)))"
			role="dialog"
			aria-modal="true"
			aria-label={title}
			tabindex="-1"
			bind:this={panel}
			onkeydown={(e) => {
				if (e.key === 'Escape') {
					e.stopPropagation();
					open = false;
				} else if (e.key === 'Tab') {
					cycle(e);
				}
			}}
		>
			<header>
				<h2>{title}</h2>
				<button class="close" aria-label={t('common.close')} onclick={() => (open = false)}>×</button>
			</header>
			<div class="body">
				{@render children()}
			</div>
		</section>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		/* Above the notification stack (Message and ConnectionCard are both 60), below the
		   alarm (200) — an alarm about the machine outranks anything you are reading. It
		   was 20, and then the "No connection to the machine" card covered the top-left
		   490 x 130 px of the cut-path drawing and hid contour number 1 entirely
		   (measured, twice). Every other dialog holds text that reflows; this one is one
		   picture, and half a picture is a wrong picture. */
		z-index: 100;
		display: grid;
		place-items: center;
		padding: var(--space-6);
		/* v2: a dialog lies *in front of* the app, not in it. */
		background: var(--scrim);
	}
	.panel {
		display: flex;
		flex-direction: column;
		max-height: min(80vh, 760px);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--lift-2);
		outline: none;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--line);
	}
	h2 {
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.close {
		font-size: var(--text-lg);
		line-height: 1;
		color: var(--text-2);
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
	}
	.close:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.body {
		overflow-y: auto;
		padding: var(--space-4);
	}
</style>
