<script lang="ts">
	import Dialog from './Dialog.svelte';
	import FontPicker from './FontPicker.svelte';

	let {
		open = $bindable(),
		initial = null,
		onConfirm
	}: {
		open: boolean;
		/** Gevuld bij bewerken van bestaande tekst. */
		initial?: {
			text: string;
			font: string;
			font_size_mm: number | null;
			spacing: number;
			align: string;
		} | null;
		onConfirm: (options: {
			text: string;
			font: string;
			font_size_mm: number;
			spacing: number;
			align: string;
		}) => void;
	} = $props();

	let text = $state('');
	let font = $state('');
	let size = $state('10');
	let spacing = $state('1');
	let align = $state('start');
	let filled = false;

	// Bij bewerken beginnen met wat er staat, niet met lege velden.
	$effect(() => {
		if (!open) {
			filled = false;
			return;
		}
		if (filled || !initial) return;
		filled = true;
		text = initial.text;
		size = String(initial.font_size_mm ?? 10);
		spacing = String(initial.spacing ?? 1);
		align = initial.align ?? 'start';
		font = '';
	});

	function confirm() {
		if (!text.trim()) return;
		onConfirm({
			text: text.trim(),
			font,
			font_size_mm: Number(size) || 10,
			spacing: Number(spacing) || 1,
			align
		});
		text = '';
		open = false;
	}
</script>

<Dialog title="Tekst plaatsen" bind:open width="480px">
	<label class="field">
		<span>Tekst</span>
		<!-- svelte-ignore a11y_autofocus -->
		<input
			type="text"
			bind:value={text}
			autofocus
			placeholder="bijv. Stellendam"
			onkeydown={(e) => {
				if (e.key === 'Enter') confirm();
			}}
		/>
	</label>

	<div class="row">
		<label class="field">
			<span>Hoogte (mm)</span>
			<input class="mono" type="number" step="0.5" min="0.5" bind:value={size} />
		</label>
		<label class="field">
			<span>Letterspatiëring</span>
			<input class="mono" type="number" step="0.05" min="0.1" bind:value={spacing} />
		</label>
	</div>

	<label class="field">
		<span>Uitlijning</span>
		<select bind:value={align}>
			<option value="start">Links</option>
			<option value="middle">Gecentreerd</option>
			<option value="end">Rechts</option>
		</select>
	</label>

	<FontPicker bind:font sample={text} current={initial?.font ?? null} />

	<div class="actions">
		<button class="btn" onclick={() => (open = false)}>Annuleren</button>
		<button class="btn primary" disabled={!text.trim()} onclick={confirm}>
			{initial ? 'Bijwerken' : 'Plaatsen'}
		</button>
	</div>
</Dialog>

<style>
	.field {
		display: grid;
		gap: 2px;
		margin-bottom: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}
	input,
	select {
		font: inherit;
		width: 100%;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.btn {
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
</style>
