<script lang="ts">
	/**
	 * The language picker.
	 *
	 * Next to the theme toggle, because it is the same kind of thing: a preference
	 * about the whole app rather than about the document or the machine (see the
	 * placement rule in DESIGN-SYSTEM.md v4). It uses the same menu component as
	 * everything else, so it opens, walks and closes the way every other menu in
	 * the app does.
	 *
	 * The button shows the code and not a flag. A flag is a country, not a
	 * language — Dutch is spoken in two of them and English in dozens — and at
	 * 20 px a flag is a coloured smudge. The menu spells each language in its own
	 * tongue: someone hunting for their language is not reading the one they
	 * cannot read.
	 */
	import Menu from './Menu.svelte';
	import { i18n, LANGUAGES, t } from '$lib/i18n/index.svelte';
	import type { Menu as MenuList } from '$lib/actions';

	let open = $state(false);
	let at = $state({ x: 0, y: 0 });

	let list = $derived<MenuList>([
		{
			title: t('app.language'),
			items: LANGUAGES.map((language) => ({
				id: `language-${language.code}`,
				label: language.name,
				on: i18n.language === language.code,
				explain: language.name === language.english ? undefined : language.english,
				run: () => (i18n.language = language.code)
			}))
		}
	]);
</script>

<button
	class="language"
	aria-haspopup="menu"
	aria-expanded={open}
	title={t('app.language')}
	aria-label={t('app.language')}
	onclick={(event) => {
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		at = { x: Math.max(8, box.right - 200), y: box.bottom + 6 };
		open = !open;
	}}
>
	<svg
		width="15"
		height="15"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="1.7"
		stroke-linecap="round"
		aria-hidden="true"
	>
		<circle cx="12" cy="12" r="9" />
		<path d="M3.5 9h17M3.5 15h17" />
		<path d="M12 3c2.5 2.6 2.5 15.4 0 18M12 3c-2.5 2.6-2.5 15.4 0 18" />
	</svg>
	<span class="code">{i18n.language.toUpperCase()}</span>
</button>

{#if open}
	<Menu menu={list} x={at.x} y={at.y} onClose={() => (open = false)} />
{/if}

<style>
	.language {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		flex: none;
		padding: 0 var(--space-2);
		min-height: 32px;
		border: none;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-2);
	}
	.language:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Two letters in the numeric font, so EN and NL are the same width and the bar
	   does not shift when you switch. */
	.code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.04em;
	}
</style>
