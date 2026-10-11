<script lang="ts">
	import { tick, untrack } from 'svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import NumberField from './NumberField.svelte';
	import Menu from './Menu.svelte';
	import StarterOffer from './StarterOffer.svelte';
	import EmptyState from './EmptyState.svelte';
	import Icon from './Icon.svelte';
	import Notice from './Notice.svelte';
	import Why from './Why.svelte';
	import type { Menu as MenuList } from '$lib/actions';
	import {
		OPERATION_LAYER,
		operations as operationChoices,
		sourceLabel,
		operationName,
		wouldGoWith,
		type ImportPreview,
		type ImportResult,
		type ImportUndone,
		type MaterialUsage,
		type PresetConflict,
		type LibraryStore,
		type Contribution,
		type Preset
	} from '$lib/library.svelte';
	import { LASER_KINDS, laserKindLabel, type LaserKind } from '$lib/machines.svelte';
	import { drawnLayers, layerNamed, type DesignOperation } from '$lib/design.svelte';

	let {
		library,
		operations,
		canEdit = false,
		sheetMaterialId = null,
		sheetMaterialName = null,
		targetLayer = null,
		onApplied,
		onMakeGrid,
		onReadBoard,
		token = ''
	}: {
		library: LibraryStore;
		operations: DesignOperation[];
		canEdit?: boolean;
		/** The material of the sheet you are working on (decision B1). The library
		 *  opens filtered on it: you are looking for settings for what is *in* the
		 *  machine, not for everything you have ever burned. */
		sheetMaterialId?: number | null;
		sheetMaterialName?: string | null;
		/** The layer Apply should point at, when this window was opened from one. */
		targetLayer?: string | null;
		onApplied?: () => void;
		/** Opens the test grid dialog for this material. */
		onMakeGrid?: (materialId: number | null) => void;
		/** Opens the test grid dialog at the half that reads a burned board back. */
		onReadBoard?: () => void;
		token?: string;
	} = $props();

	// The dialog is rebuilt on every opening, so this really is the state you find it
	// in every time. Deliberately only the initial value: if the sheet changes while
	// this is open, the filter should not slide out from under your hands — hence
	// untrack.
	let materialId = $state<number | null>(untrack(() => sheetMaterialId));
	let query = $state('');
	let adding = $state(false);
	let newMaterial = $state('');
	let draft = $state({
		material_id: null as number | null,
		operation: 'snijden',
		thickness_mm: '3',
		speed_mm_s: '',
		power_percent: ''
	});
	let targetOperation = $state<string>('');

	// Opened from a layer's own menu: then Apply points at that layer and not at
	// whichever one happens to be first. Guarded on the layer still existing, because
	// this window outlives the drawing it was opened over — delete the layer while the
	// library is open and the target would name nothing.
	$effect(() => {
		if (targetLayer && layers.some((o) => o.id === targetLayer)) {
			targetOperation = targetLayer;
		}
	});
	let editing = $state<number | null>(null);
	let herkomst = $state<number | null>(null);
	let weghalen = $state<number | null>(null);
	let shareError = $state<string | null>(null);
	/**
	 * The setting whose contribution is open, with what the API says it would be.
	 *
	 * Sharing used to be one press that opened a GitHub tab, and what went in that tab
	 * was refused by the catalogue's own CI: no `by`, no `tier`. Both are answers only
	 * the reader has, so the press now opens this panel instead — it says what would go
	 * out and under which of the two labels, and asks for what is missing.
	 */
	let sharing = $state<{ preset: number; report: Contribution } | null>(null);
	/** The handle, as typed. Prefilled with the remembered one, so it can be corrected. */
	let handleDraft = $state('');
	/** Whether the field is on screen even though a handle is already remembered. */
	let changingHandle = $state(false);
	/** What came out of the material, as the panel collects it. */
	let outcome = $state({ charring: '', cutThrough: '', kerf: '' });
	/** The field that appears when you press "New material", so it can take the caret. */
	let newField = $state<HTMLInputElement | null>(null);

	// ---------------------------------------------- the three verbs on a material
	//
	// A material could be added and nothing else: no rename, no merge, no removal. That
	// is why this library holds both `Multiplex berken` and `Berkentriplex` for one
	// board, and why a reader concluded that removing a material was impossible — the
	// route was there and nothing ever called it. All three now sit behind the same ⋯
	// the setting rows already have, because two lists in one window disagreeing about
	// where verbs live is precisely what made that conclusion reasonable.

	/** Which material is being renamed, and what it is being renamed to. */
	let renaming = $state<number | null>(null);
	let renameTo = $state('');
	let alsoCalled = $state('');
	/** Which material is being merged away, and into which one. */
	let merging = $state<number | null>(null);
	let mergeInto = $state<number | null>(null);
	/**
	 * Which material the removal question is about, with what hangs off it.
	 *
	 * The counts are fetched before the question is asked, never guessed from what is on
	 * screen: the list here is filtered by machine and by search, so a material that
	 * looks empty can still carry six settings of another laser.
	 */
	let removing = $state<number | null>(null);
	let usage = $state<MaterialUsage | null>(null);
	/** What taking an import back actually took, said once and then dismissed. */
	let undone = $state<ImportUndone | null>(null);

	/**
	 * The menu on a setting.
	 *
	 * Provenance, edit, share and remove used to be four buttons on every row. They
	 * belong to one setting and none of the four is the operation you come here to
	 * do, so they sit behind one ⋯ — and behind the right-click, as everywhere else
	 * in the app.
	 */
	let rowMenu = $state<{ list: MenuList; x: number; y: number } | null>(null);

	function presetMenu(preset: Preset): MenuList {
		return [
			{
				items: [
					{
						id: 'toepassen',
						label: chosenOperation
							? t('library.menu.applyTo', { n: layerNumber })
							: t('library.menu.apply'),
						off: chosenOperation ? undefined : t('library.menu.needsLayer'),
						run: () => apply(preset)
					}
				]
			},
			{
				items: [
					{
						id: 'herkomst',
						label: t('library.menu.provenance'),
						on: herkomst === preset.id,
						explain: t('library.menu.provenance.explain'),
						run: () => {
							editing = null;
							herkomst = herkomst === preset.id ? null : preset.id;
						}
					},
					{
						id: 'bewerken',
						label: t('library.menu.adjust'),
						on: editing === preset.id,
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => {
							herkomst = null;
							editing = editing === preset.id ? null : preset.id;
						}
					},
					{
						id: 'grid',
						label: t('library.menu.makeGrid', { material: preset.material_name }),
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => onMakeGrid?.(preset.material_id)
					},
					{
						id: 'parts',
						label: t('library.menu.share'),
						on: sharing?.preset === preset.id,
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => share(preset)
					}
				]
			},
			{
				items: [
					{
						id: 'gone',
						label: t('library.menu.remove'),
						off: canEdit ? undefined : t('reason.needsToken'),
						danger: true,
						run: () => (weghalen = preset.id)
					}
				]
			}
		];
	}

	function opendMenu(event: MouseEvent, preset: Preset) {
		event.preventDefault();
		const target = event.currentTarget as HTMLElement | null;
		const box = target?.getBoundingClientRect();
		rowMenu = {
			list: presetMenu(preset),
			// A click on the ⋯ button hangs the menu below that button; a right-click on
			// the row hangs it at the cursor.
			x: event.type === 'contextmenu' || !box ? event.clientX : box.left - 180,
			y: event.type === 'contextmenu' || !box ? event.clientY : box.bottom + 4
		};
	}

	/**
	 * The menu on a material.
	 *
	 * Same shape and same order as the one on a setting: first what you came to do, then
	 * what you can do to this material, and the removal last and alone in red — so
	 * whoever misses has hit "Show only this material" and not the delete.
	 */
	function materialMenu(group: Groep): MenuList {
		return [
			{
				items: [
					{
						id: 'only',
						label: t('library.onlyThis'),
						on: materialId === group.materialId,
						run: () => (materialId = group.materialId)
					},
					{
						id: 'grid',
						label: t('library.makeGrid'),
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => onMakeGrid?.(group.materialId)
					}
				]
			},
			{
				items: [
					{
						id: 'rename',
						label: t('library.material.menu.rename'),
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => startRename(group)
					},
					{
						id: 'merge',
						label: t('library.material.menu.merge'),
						// One material cannot be merged into itself, and with one material
						// there is nothing else to merge into. Saying so beats a select
						// with nothing in it.
						off: !canEdit
							? t('reason.needsToken')
							: library.materials.length < 2
								? t('library.material.merge.needsTwo')
								: undefined,
						run: () => startMerge(group)
					}
				]
			},
			{
				items: [
					{
						id: 'gone',
						label: t('library.material.menu.remove'),
						off: canEdit ? undefined : t('reason.needsToken'),
						danger: true,
						run: () => askRemove(group)
					}
				]
			}
		];
	}

	/** The ⋯ hangs under its button; the right-click opens at the cursor. */
	function openMaterialMenu(event: MouseEvent, group: Groep) {
		event.preventDefault();
		const target = event.currentTarget as HTMLElement | null;
		const box = target?.getBoundingClientRect();
		rowMenu = {
			list: materialMenu(group),
			x: event.type === 'contextmenu' || !box ? event.clientX : box.left - 180,
			y: event.type === 'contextmenu' || !box ? event.clientY : box.bottom + 4
		};
	}

	/**
	 * Every one of the three verbs shows its question in the right-hand pane, under the
	 * name of the material it is about — and never two at once. The left-hand row is
	 * 232 px wide, so the question cannot stand there, and a window over a window would
	 * hide the very list the answer changes.
	 */
	function askAbout(group: Groep) {
		materialId = group.materialId;
		renaming = merging = removing = null;
		usage = null;
		undone = null;
	}

	function startRename(group: Groep) {
		askAbout(group);
		renameTo = group.name;
		alsoCalled = (library.materials.find((m) => m.id === group.materialId)?.synonyms ?? []).join(
			', '
		);
		renaming = group.materialId;
	}

	async function saveRename() {
		if (renaming === null || !renameTo.trim()) return;
		const words = alsoCalled
			.split(',')
			.map((word) => word.trim())
			.filter(Boolean);
		const saved = await library.renameMaterial(renaming, {
			name: renameTo.trim(),
			synonyms: words
		});
		if (saved) renaming = null;
	}

	function startMerge(group: Groep) {
		askAbout(group);
		mergeInto = null;
		merging = group.materialId;
	}

	async function doMerge() {
		if (merging === null || mergeInto === null) return;
		const target = mergeInto;
		const done = await library.mergeMaterial(merging, target);
		if (done) {
			merging = null;
			// Land on the material everything moved to: that list is the answer to
			// whether the merge did what you meant.
			materialId = target;
		}
	}

	async function askRemove(group: Groep) {
		askAbout(group);
		removing = group.materialId;
		usage = await library.materialUsage(group.materialId);
	}

	async function doRemove() {
		if (removing === null) return;
		const carries = !!usage && !!(usage.presets || usage.test_grids || usage.grid_recipes);
		const done = await library.removeMaterial(removing, carries);
		if (done) {
			removing = null;
			usage = null;
			materialId = null;
		}
	}

	async function undoImport(batch: string) {
		const done = await library.removeImport(batch);
		if (done) {
			undone = done;
			herkomst = null;
		}
	}

	// A material that is no longer there cannot stay chosen: after a merge or a removal
	// the right-hand pane would otherwise be blank with nothing saying why. Only once
	// there is a list to judge by — an empty one means the first load has not landed
	// yet, and clearing then would throw away the sheet's own material filter before
	// anybody saw it.
	$effect(() => {
		const known = library.materials.some((m) => m.id === materialId);
		if (materialId !== null && library.materials.length > 0 && !known)
			untrack(() => (materialId = null));
	});

	// The field is the whole point of pressing the button, so it takes the caret. Without
	// this the reader presses "New material" and then has to find the field that appeared.
	$effect(() => {
		if (adding) newField?.focus();
	});

	/**
	 * The question a verb asks takes the caret, and Escape answers it with "no".
	 *
	 * Same rule as the field above, and measured to be missing on all three: choosing
	 * *Rename this material…* left `document.activeElement` on `<body>`, so a reader who
	 * had come this far with the keyboard had nothing to type into. Worse, Escape then
	 * did nothing at all — the window's own Escape handler sits on its panel and a
	 * keystroke on the body never reaches it — and once the caret *was* in the field,
	 * Escape closed the whole material library and threw the half-typed name away with
	 * it. So the block stops that key here and closes only itself.
	 */
	let askEl = $state<HTMLElement | null>(null);
	$effect(() => {
		if (!askEl) return;
		// The first focusable is the safe one in all three: the name field when renaming,
		// the target list when merging, and "Keep it" in front of the red button.
		askEl.querySelector<HTMLElement>('input, select, button')?.focus();
	});

	function closeQuestion() {
		renaming = merging = removing = null;
		usage = null;
	}

	// The layers you draw in, and only those. A test grid's sixteen cells are layers in
	// the engine; the panel folds them under the board's own row and this window used to
	// offer every one of them by name. Counting over the raw list on top of that gave the
	// same layer two numbers: what the panel calls 5 · Board labels was offered here as
	// "Layer 21 · Board labels" (P12). `drawnLayers` is the list the panel counts over.
	let layers = $derived(drawnLayers(operations));
	let chosenOperation = $derived(
		layers.find((o) => o.id === targetOperation) ?? layers[0] ?? null
	);
	let layerNumber = $derived(
		chosenOperation ? layers.findIndex((o) => o.id === chosenOperation.id) + 1 : 0
	);
	$effect(() => {
		const chosen = chosenOperation;
		if (chosen && targetOperation !== chosen.id) targetOperation = chosen.id;
	});

	const operationLabel = operationName;

	/** Searching everything on the card: name, thickness, operation, note. */
	function raakt(preset: Preset, term: string) {
		if (!term) return true;
		const hooiberg = [
			preset.material_name,
			preset.thickness_mm !== null ? `${preset.thickness_mm} mm` : '',
			operationLabel(preset.operation),
			preset.operation,
			preset.note,
			preset.machine_name ?? '',
			sourceLabel(preset.source).text
		]
			.join(' ')
			.toLowerCase();
		return term
			.toLowerCase()
			.split(/\s+/)
			.filter(Boolean)
			.every((woord) => hooiberg.includes(woord));
	}

	/**
	 * Every setting that matches the search term and the machine filter —
	 * deliberately **not** the chosen material.
	 *
	 * Since v4 the material is the list on the left, and that list has to keep showing
	 * every material: filtering itself, one click would leave one row and there would
	 * be no way on to the next material. Narrowing by material happens in
	 * `zichtbarePresets`, on the right-hand side.
	 */
	let visible = $derived(library.presetsFor(null).filter((p) => raakt(p, query.trim())));

	function gebruikt(preset: Preset) {
		return preset.last_used_at ? Date.parse(`${preset.last_used_at.replace(' ', 'T')}Z`) : 0;
	}

	/**
	 * What you used yesterday is at the top today.
	 *
	 * Sorting alphabetically is fair and unusable: anybody cutting the same plywood
	 * every day scrolled past acrylic, cardboard and leather to get to it.
	 */
	let recent = $derived(
		visible
			.filter((p) => p.last_used_at)
			.sort((a, b) => gebruikt(b) - gebruikt(a))
			.slice(0, 3)
	);

	/** Which thickness is being filtered on within the chosen material. */
	let thickness = $state<number | null>(null);
	// Switching material resets the thickness filter: a thickness this material does
	// not have gives an empty panel without you seeing why.
	$effect(() => {
		void materialId;
		untrack(() => (thickness = null));
	});

	/** The thicknesses this material really has, thin to thick. */
	let thicknesses = $derived.by(() => {
		const group = groepen.find((g) => g.materialId === materialId);
		const values = new Set<number | null>();
		for (const preset of group?.presets ?? []) values.add(preset.thickness_mm);
		return [...values].sort((a, b) => (a ?? -1) - (b ?? -1));
	});

	/**
	 * What is on the right, in reading order: thin to thick, and within a thickness
	 * the measured settings first. A measured value is worth more than an estimated
	 * one, so it belongs at the top and not in alphabetical order.
	 */
	const SOURCE_ORDER: Record<string, number> = { testraster: 0, presetariat: 1, geextrapoleerd: 2, handmatig: 3 };
	let zichtbarePresets = $derived.by(() => {
		const group = groepen.find((g) => g.materialId === materialId);
		const list = (group?.presets ?? []).filter((p) => thickness === null || p.thickness_mm === thickness);
		return [...list].sort(
			(a, b) =>
				(a.thickness_mm ?? -1) - (b.thickness_mm ?? -1) ||
				(SOURCE_ORDER[a.source] ?? 9) - (SOURCE_ORDER[b.source] ?? 9) ||
				a.operation.localeCompare(b.operation, 'nl')
		);
	});

	type Groep = { name: string; materialId: number; presets: Preset[]; laatst: number };
	let groepen = $derived.by<Groep[]>(() => {
		const card = new Map<number, Groep>();
		for (const preset of visible) {
			let group = card.get(preset.material_id);
			if (!group) {
				group = {
					name: preset.material_name,
					materialId: preset.material_id,
					presets: [],
					laatst: 0
				};
				card.set(preset.material_id, group);
			}
			group.presets.push(preset);
			group.laatst = Math.max(group.laatst, gebruikt(preset));
		}
		// Materials without presets belong here too: without that group there is
		// nowhere that "make a test grid" sits logically.
		for (const material of library.materials) {
			if (card.has(material.id)) continue;
			if (query.trim() && !material.name.toLowerCase().includes(query.trim().toLowerCase()))
				continue;
			card.set(material.id, {
				name: material.name,
				materialId: material.id,
				presets: [],
				laatst: 0
			});
		}
		return [...card.values()].sort(
			(a, b) => b.laatst - a.laatst || a.name.localeCompare(b.name, 'nl')
		);
	});

	async function createMaterial() {
		if (!newMaterial.trim()) return;
		const created = await library.addMaterial(newMaterial.trim());
		if (created) {
			materialId = created.id;
			newMaterial = '';
			adding = false;
		}
	}

	async function createPreset() {
		const target = draft.material_id ?? materialId;
		if (target === null) return;
		const created = await library.addPreset({
			material_id: target,
			operation: draft.operation,
			thickness_mm: draft.thickness_mm === '' ? null : Number(draft.thickness_mm),
			speed_mm_s: Number(draft.speed_mm_s),
			power_percent: Number(draft.power_percent)
		});
		if (created) draft = { ...draft, speed_mm_s: '', power_percent: '' };
	}

	/**
	 * Offering one of your own presets to the shared catalogue.
	 *
	 * This used to be the whole feature: one fetch and a GitHub tab. The tab held a file
	 * the catalogue's own CI refused — `by` and `tier` are required over there and
	 * neither was ever written — so the press now opens the panel below, which says what
	 * would go out, under which label, and what is still missing.
	 */
	async function share(preset: Preset) {
		shareError = null;
		if (sharing?.preset === preset.id) {
			sharing = null;
			return;
		}
		const report = await library.contribution(preset.id);
		if (!report) {
			shareError = library.error ?? t('library.share.failed');
			return;
		}
		sharing = { preset: preset.id, report };
		handleDraft = report.by ?? '';
		changingHandle = false;
		outcome = { charring: '', cutThrough: '', kerf: '' };
		herkomst = null;
		editing = null;
	}

	/** The three answers the panel has collected, in the shape the route takes. */
	function shareAnswers() {
		const typed = handleDraft.trim();
		const answers: {
			by?: string;
			result?: { charring: string; cut_through?: boolean | null; kerf_mm?: number | null };
		} = {};
		if (typed && typed !== sharing?.report.by) answers.by = typed;
		if (outcome.charring) {
			answers.result = { charring: outcome.charring };
			// "Not saying" is a real answer and not a missing one: half the boards in a
			// workshop are engraved, where cutting through is not a question at all.
			if (outcome.cutThrough) answers.result.cut_through = outcome.cutThrough === 'yes';
			if (outcome.kerf.trim()) answers.result.kerf_mm = Number(outcome.kerf);
		}
		return answers;
	}

	/**
	 * Hand it over: write what the panel collected, then open the proposal.
	 *
	 * `window.open` right after the one await, because the tab is what the reader
	 * pressed for — and the link stays on screen underneath it, so a blocked popup is a
	 * link and not a dead end.
	 */
	async function offer(preset: Preset) {
		shareError = null;
		const answers = shareAnswers();
		let report = sharing?.report ?? null;
		if (Object.keys(answers).length > 0 || !report?.ready) {
			report = await library.offerContribution(preset.id, answers);
			if (!report) {
				shareError = library.error ?? t('library.share.failed');
				return;
			}
			sharing = { preset: preset.id, report };
			handleDraft = report.by ?? '';
			changingHandle = false;
		}
		if (report.issue_url) window.open(report.issue_url, '_blank', 'noopener');
	}

	/** How the edge came out, in the three words the catalogue's schema allows. */
	function charrings(): { value: string; label: string }[] {
		return [
			{ value: 'none', label: t('library.share.charring.none') },
			{ value: 'light', label: t('library.share.charring.light') },
			{ value: 'heavy', label: t('library.share.charring.heavy') }
		];
	}

	/** Why this contribution is not a measurement, in the reader's language. */
	function shareWhy(report: Contribution): string {
		switch (report.tier_reason) {
			case 'derived':
				return t('library.share.why.derived', { id: report.derived_from ?? '' });
			case 'boardGone':
				return t('library.share.why.boardGone');
			case 'otherMachine':
				return t('library.share.why.otherMachine');
			case 'noOutcome':
				return t('library.share.why.noOutcome');
			default:
				return t('library.share.why.notMeasured');
		}
	}

	async function saveEdit(preset: Preset, fields: Record<string, unknown>) {
		await library.updatePreset(preset.id, fields);
	}

	/**
	 * What the machine is, changed where the machine is listed.
	 *
	 * This replaces a form that could *create* a profile with a wattage and no device —
	 * the only writer in the app that could, and therefore the only thing that can have
	 * made the phantom `5030 CO2` that carries twenty-seven settings for a machine
	 * nobody runs. What is left is the half that was actually needed: every live profile
	 * here has `power_watt: null`, so somebody who is already past the wizard needs a
	 * door to fill the two fields in. Each field writes on change, like the values on a
	 * setting do, because there is nothing to weigh up in between.
	 */
	function saveMachine(id: number, fields: Record<string, unknown>) {
		return library.updateMachineProfile(id, fields);
	}

	async function apply(preset: Preset) {
		const target = chosenOperation;
		if (!target) return;
		if (await library.applyTo(preset.id, target.id)) onApplied?.();
	}

	/**
	 * Which texture belongs to a material.
	 *
	 * Guessing on the name is crude, but the alternative is a field nobody fills in.
	 * An unknown material gets a neutral band — that is more honest than suggesting
	 * wood.
	 */
	function textuur(name: string | null): string {
		const n = (name ?? '').toLowerCase();
		if (/multiplex|plywood|hout|wood|mdf|berk|populier|eiken/.test(n)) return 'hout';
		if (/acryl|acrylic|plexi|pmma/.test(n)) return 'acryl';
		if (/leer|leather/.test(n)) return 'leer';
		if (/karton|papier|paper|card/.test(n)) return 'karton';
		if (
			/staal|metaal|alu|steel|metal|messing|rvs|inox|chroom|koper|brass|copper|titaan/.test(n)
		)
			return 'metaal';
		return 'unknown';
	}

	let busyPhoto = $state<number | null>(null);

	async function photoFor(gridId: number, file: File) {
		busyPhoto = gridId;
		try {
			const form = new FormData();
			form.append('file', file);
			const response = await fetch(`/api/library/testgrids/${gridId}/photo`, {
				method: 'POST',
				headers: token ? { Authorization: `Bearer ${token}` } : {},
				body: form
			});
			if (response.ok) await library.load();
		} finally {
			busyPhoto = null;
		}
	}

	// ------------------------------------------------ uitwisselen (besluit B7)

	type Suggestion = ImportPreview['merge']['materials']['similar'][number];

	let preview = $state<ImportPreview | null>(null);
	let fileName = $state('');
	let mode = $state<'merge' | 'replace'>('merge');
	let clashWinner = $state<'mine' | 'file'>('mine');
	/** Which material from the file is laid onto which of your own materials. */
	let laidOnto = $state<Record<string, number>>({});
	let wipeConfirmed = $state(false);
	let ready = $state<ImportResult | null>(null);
	/**
	 * Every proposal we ever showed, including after it has been ticked.
	 *
	 * As soon as you link them, the material counts as known and disappears from the
	 * server's proposals — and with it the tick you just made would disappear. Then
	 * the choice can no longer be undone without cancelling.
	 */
	let seen = $state<Record<string, Suggestion>>({});
	let voorstellen = $derived.by(() => {
		const list = [...(preview?.merge.materials.similar ?? [])];
		for (const name of Object.keys(laidOnto)) {
			if (seen[name] && !list.some((p) => p.name === name)) list.push(seen[name]);
		}
		return list.sort((a, b) => a.name.localeCompare(b.name, 'nl'));
	});

	/** Did something come in that the current filter does not show? */
	let hidden = $state(false);
	let wisselEl = $state<HTMLElement | null>(null);
	let readyEl = $state<HTMLElement | null>(null);

	/**
	 * The dialog is the scroll container, and you pressed a button at the bottom.
	 *
	 * Without this the preview appears with its heading and its tallies *above* the
	 * viewport: you land in the middle of a decision and have to go up first to see
	 * what it is about.
	 */
	async function toTop(welke: 'preview' | 'ready') {
		await tick();
		(welke === 'ready' ? readyEl : wisselEl)?.scrollIntoView({ block: 'start' });
	}

	async function pickFile(file: File) {
		ready = null;
		mode = 'merge';
		clashWinner = 'mine';
		laidOnto = {};
		seen = {};
		wipeConfirmed = false;
		fileName = file.name;
		preview = await library.uploadBundle(file);
		if (preview) toTop('preview');
	}

	/**
	 * Tying two names for the same board together.
	 *
	 * The preview is fetched again afterwards: the number of new materials changes
	 * because of it, and a tally that does not move with your choice is a tally you
	 * cannot trust.
	 */
	async function linkTo(pair: Suggestion, on: boolean) {
		// Remember it before recomputing: after that the server knows this material and
		// no longer offers the proposal.
		seen = { ...seen, [pair.name]: pair };
		laidOnto = on
			? { ...laidOnto, [pair.name]: pair.material_id }
			: Object.fromEntries(Object.entries(laidOnto).filter(([k]) => k !== pair.name));
		if (preview) {
			const again = await library.previewBundle(preview.bundle, laidOnto);
			if (again) preview = again;
		}
	}

	async function importeren() {
		if (!preview) return;
		const visibleFor = library.presets.length;
		const outcome = await library.importBundle(preview.bundle, mode, laidOnto, clashWinner);
		if (outcome) {
			// "4 settings added" while the screen does not change is not reassurance but
			// a riddle: they belong to another machine then and fall outside the filter.
			// Measured rather than guessed.
			hidden =
				outcome.presets.added > 0 &&
				library.presets.length - visibleFor < outcome.presets.added;
			ready = outcome;
			preview = null;
			toTop('ready');
		}
	}

	/**
	 * Does the side from the file carry the better evidence?
	 *
	 * "Keep my values" is the safe rule, but not when your value is calculated and the
	 * one from the file was burned on a grid. Then the rule beats the measurement, and
	 * somebody should see that before they choose.
	 */
	function sterkerBewijs(clash: PresetConflict) {
		return clash.theirs.source === 'testraster' && clash.mine.source !== 'testraster';
	}

	/** "3 settings" — and "1 setting", because that is what a person reads too. */
	function count(n: number, what: 'materials' | 'presets' | 'machines' | 'testGrids' | 'photos') {
		return t(`count.${what}` as never, { n });
	}

	/**
	 * What hangs off a machine profile; only what is really there.
	 *
	 * `count.grids` used to stand here and that key is in neither catalogue, so the
	 * words `count.grids` were printed on the screen beside every profile that carries a
	 * board. The key is `count.testGrids`, and it is the same one the import screen uses
	 * for the same thing.
	 */
	function evidence(machine: { presets: number; test_grids: number }) {
		const parts = [];
		if (machine.presets) parts.push(count(machine.presets, 'presets'));
		if (machine.test_grids) parts.push(count(machine.test_grids, 'testGrids'));
		return i18n.list(parts);
	}

	/**
	 * The grid photo, with the chosen square circled when we know which square it was.
	 *
	 * The server draws the marker into the image (`?cell=<row>-<column>`), so a plain
	 * `<img>` suffices and no overlay maths is needed here. Without a known square we
	 * ask for the photo unprocessed — that is the safe fallback.
	 */
	function photoUrl(preset: Preset) {
		const basis = `/api/library/testgrids/${preset.grid_id}/photo`;
		return preset.grid_cell
			? `${basis}?cell=${preset.grid_cell.row}-${preset.grid_cell.column}`
			: basis;
	}

	/** Does this preset suit the layer type it is being put on? */
	function pastBij(preset: Preset, layer: DesignOperation | null) {
		if (!layer) return true;
		const toegestaan = OPERATION_LAYER[preset.operation];
		return !toegestaan || toegestaan.includes(layer.type);
	}
</script>

{#snippet sourceIcon(kind: string)}
	{#if kind === 'check'}
		<Icon name="ok" />
	{:else if kind === 'alert'}
		<Icon name="warn" />
	{:else if kind === 'down'}
		<Icon name="arrow-down" />
	{:else}
		<!-- A pencil: entered by hand. Only here, so it stays inline on the shared stroke. -->
		<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"
			><path d="M4 20l4-1 10-10-3-3L5 16z" /><path d="M15 6l3 3" /></svg
		>
	{/if}
{/snippet}

{#snippet addMaterial(label: string, big: boolean)}
	<!--
		The trigger and the field it summons, in one place.

		They were 1,020 px apart: the button sat at the right-hand end of the search bar
		at x=1197 and the field it opened appeared at x=177, under two paragraphs, so
		pressing it looked as though nothing had happened. Now the field takes the
		button's own place and the caret with it, and both live in the column where
		materials live.
	-->
	{#if adding}
		<div class="addrow">
			<input
				type="text"
				bind:this={newField}
				bind:value={newMaterial}
				aria-label={t('library.material.name')}
				placeholder={t('library.material.placeholder')}
				onkeydown={(e) => {
					if (e.key === 'Enter') createMaterial();
					// Escape is the way out of a field you opened by accident, and it must
					// not close the whole window on the way.
					if (e.key === 'Escape') {
						e.stopPropagation();
						adding = false;
						newMaterial = '';
					}
				}}
			/>
			<div class="addbuttons">
				<button
					class="btn ghost mini"
					onclick={() => {
						adding = false;
						newMaterial = '';
					}}>{t('common.cancel')}</button
				>
				<button
					class={big ? 'btn primary' : 'btn primary mini'}
					disabled={library.busy || !newMaterial.trim()} title={library.busy ? t('reason.busy') : t('reason.needsName')}
					onclick={createMaterial}>{t('common.save')}</button
				>
			</div>
		</div>
	{:else}
		<button class={big ? 'btn primary' : 'btn ghost mini add'} onclick={() => (adding = true)}>
			<Icon name="plus" />{label}
		</button>
	{/if}
{/snippet}

{#snippet card(preset: Preset, showMaterial: boolean)}
	{@const source = sourceLabel(preset.source)}
	{@const past = !canEdit || pastBij(preset, chosenOperation)}
	{@const off = herkomst === preset.id || editing === preset.id}
	<article
		class="preset"
		class:open={off}
		role="presentation"
		oncontextmenu={(e) => canEdit && opendMenu(e, preset)}
	>
		<!--
			One line per setting instead of a 200 px card.

			What the task asks for is comparing: which thickness, which operation, how
			hard, and was it measured or guessed. That is four things and they fit on
			one line. In the old card the same four things were spread over four blocks
			with a subheading per value, plus a full paragraph of explanation and five
			buttons — 200 px together, so two settings per screenful. Measured in the
			old layout: thirteen settings was 2,600 px of scrolling. Whatever else
			there is to know about a setting is still there, but only when you ask.
		-->
		<div class="row">
			<div class="wat">
				<span class="size mono">
					{#if preset.thickness_mm !== null}{preset.thickness_mm} mm{:else}—{/if}
				</span>
				<span class="operation">
					{#if showMaterial}<span class="mat">{preset.material_name}</span> · {/if}
					{operationLabel(preset.operation)}
				</span>
				{#if !past}
						<!-- The operation of this setting does not match the layer it would be
						     put on. That is a property of this row, so it sits with the
						     operation — not as a colour on the button. With ten of thirteen
						     rows amber the screen reads as ten mistakes instead of as one
						     mismatch you chose yourself. -->
						<span
							class="badge warn mismatch"
							title={t('library.mismatch.title', {
								operation: operationLabel(preset.operation).toLowerCase(),
								n: layerNumber,
								layerKind: chosenOperation?.label.toLowerCase()
							})}
						>
							<Icon name="warn" />
						{t('library.mismatch.tag')}
					</span>
				{/if}
			</div>

			<div class="values mono">
				<span title={t('library.speed')}>{preset.speed_mm_s}<small>mm/s</small></span>
				<span title={t('library.power')}>{preset.power_percent}<small>%</small></span>
				{#if preset.passes > 1}<span title={t('library.passes')}
						>{preset.passes}<small>&times;</small></span
					>{/if}
				{#if preset.interval_mm && preset.operation === 'graveren-raster'}
					<span title={t('library.interval')}>{preset.interval_mm}<small>mm</small></span>
				{/if}
			</div>

			<!-- The source as one badge, with the full explanation in the tooltip and in
			     the provenance. The paragraph that spelled this out on every card was
			     useful on one card and noise on thirteen. -->
			<span class="badge source {source.tone}" title="{source.means}{source.advice ? ' ' + source.advice : ''}">
				{@render sourceIcon(source.icon)}
				{source.text}
			</span>

			{#if preset.grid_photo}
				<button
					class="bewijs"
					aria-label={t('library.photoAria')}
					onclick={() => (herkomst = herkomst === preset.id ? null : preset.id)}
					title={preset.grid_cell
						? t('library.photo.circled', {
								row: preset.grid_cell.row + 1,
								column: preset.grid_cell.column + 1
							})
						: t('library.photo.title')}
				>
					<img src={photoUrl(preset)} alt="" />
				</button>
			{:else}
				<span class="geenfoto" aria-hidden="true"></span>
			{/if}

			{#if canEdit}
				<!-- One button that finishes the task, and the rest behind a menu. There
				     used to be four buttons on every row — apply, provenance, edit, remove
				     — and then the button you want 95 % of the time is one of four. -->
				<button
					class="btn primary mini doe"
					disabled={library.busy || !chosenOperation}
					title={chosenOperation
						? past
							? t('library.apply.title', { n: layerNumber })
							: t('library.apply.mismatch', {
									operation: operationLabel(preset.operation).toLowerCase(),
									n: layerNumber
								})
						: t('library.menu.needsLayer')}
					onclick={() => apply(preset)}
				>
					{t('library.menu.apply')}
				</button>
				<button
					class="btn ghost icon meer"
					aria-label={t('library.more.aria')}
					aria-haspopup="menu"
					title={t('library.more.title')}
					onclick={(e) => opendMenu(e, preset)}
				>
					<Icon name="more" />
				</button>
			{/if}
		</div>

		{#if weghalen === preset.id}
			<!-- Confirming under the row it concerns, not in a window: it is one setting
			     and the question belongs next to what is going away. -->
			<div class="zekerweg" role="alert">
				<span>
					{t('library.drop.ask', {
						thickness: preset.thickness_mm !== null ? `${preset.thickness_mm} mm ` : '',
						operation: operationLabel(preset.operation).toLowerCase(),
						material: preset.material_name
					})}
					{#if preset.source === 'testraster'}{t('library.drop.measured')}{/if}
				</span>
				<div class="ask-actions">
					<button class="btn mini" onclick={() => (weghalen = null)}>{t('library.drop.keep')}</button>
					<button class="btn mini danger" onclick={() => library.removePreset(preset.id)}>
						{t('library.drop.confirm')}
					</button>
				</div>
			</div>
		{/if}

		{#if sharing?.preset === preset.id}
			{@const report = sharing.report}
			<!-- Under the row like the other two panels, because it is about this one
			     setting — and before the tab opens, because what goes in that tab is a
			     public claim under the reader's own name. -->
			<div class="delen">
				<p class="kop">
					{#if report.tier === 'measured' && report.board}
						{t('library.share.tier.measured', { board: report.board })}
					{:else}
						{t('library.share.tier.startingPoint')}
					{/if}
				</p>
				{#if report.tier !== 'measured'}
					<p class="help">{shareWhy(report)}</p>
				{/if}

				{#if report.tier_reason === 'noOutcome'}
					<!-- The one thing the app cannot work out for itself. It is asked here
					     rather than assumed, and kept on the setting, so the next offer of
					     the same row does not ask again. -->
					<div class="uitkomst">
						<label class="field-label">
							<span>{t('library.share.charring')}</span>
							<select bind:value={outcome.charring}>
								<option value="">{t('library.share.charring.pick')}</option>
								{#each charrings() as choice (choice.value)}
									<option value={choice.value}>{choice.label}</option>
								{/each}
							</select>
						</label>
						<label class="field-label">
							<span>{t('library.share.cutThrough')}</span>
							<select bind:value={outcome.cutThrough}>
								<option value="">{t('library.share.cutThrough.unsure')}</option>
								<option value="yes">{t('library.share.cutThrough.yes')}</option>
								<option value="no">{t('library.share.cutThrough.no')}</option>
							</select>
						</label>
						<NumberField
							label={t('library.share.kerf')}
							unit="mm"
							step={0.05}
							min={0}
							bind:value={outcome.kerf}
						/>
						<p class="help wide">{t('library.share.outcome.why')}</p>
					</div>
				{/if}

				{#if report.by && !changingHandle}
					<p class="help">
						{t('library.share.by', { by: report.by })}
						<button class="link" onclick={() => (changingHandle = true)}>
							{t('library.share.handle.change')}
						</button>
					</p>
				{:else}
					<label class="field-label">
						<span>{t('library.share.handle')}</span>
						<input
							type="text"
							bind:value={handleDraft}
							placeholder={t('library.share.handle.placeholder')}
						/>
					</label>
					<!-- Not bookkeeping: the catalogue is CC BY 4.0, so this is the credit
					     somebody downstream has to be able to give. -->
					<Why>{t('library.share.handle.why')}</Why>
				{/if}

				<div class="ask-actions">
					<button class="btn ghost mini" onclick={() => (sharing = null)}>
						{t('library.share.close')}
					</button>
					<button
						class="btn primary mini"
						disabled={library.busy || !handleDraft.trim()} title={library.busy ? t('reason.busy') : t('reason.needsName')}
						onclick={() => offer(preset)}
					>
						{t('library.share.open')}
					</button>
				</div>
				<p class="help">{t('library.share.open.why')}</p>
			</div>
		{/if}

		{#if herkomst === preset.id}
			<!-- The community provenance is a first-class element, not a hidden
			     database: who, which machine, which square, which photo. -->
			<div class="herkomst">
				<dl>
					<dt>{t('library.source')}</dt>
					<dd>{t('library.sourceLine', { badge: source.text, means: source.means.toLowerCase() })}</dd>
					<dt>{t('library.machine')}</dt>
					<dd>{preset.machine_name ?? t('library.machine.unknown')}</dd>
					{#if preset.grid_id}
						<dt>{t('library.grid')}</dt>
						<dd>
							<!-- With the photo beside it the caption already names the square;
							     repeating the same thing two lines further on is noise. -->
							#{preset.grid_id}{preset.grid_date
								? ` · ${t('library.grid.burned', { when: i18n.ago(preset.grid_date) })}`
								: ''}{preset.grid_cell && !preset.grid_photo
								? ` · ${t('library.grid.cell', {
										row: preset.grid_cell.row + 1,
										column: preset.grid_cell.column + 1
									})}`
								: ''}
						</dd>
					{/if}
					{#if preset.note}
						<dt>{t('library.note')}</dt>
						<dd>{preset.note}</dd>
					{/if}
					{#if preset.source === 'geimporteerd'}
						<!-- Where an imported setting was really measured, which is not the machine
						     it is filed under: an import files a stranger's 80 W measurement under
						     your laser. A NULL wattage on an imported row means the origin is
						     unknown, and that is what the twenty-six prefilled rows carry — their
						     note records no machine at all. -->
						<dt>{t('library.origin')}</dt>
						<dd>
							{#if preset.origin_laser_type && preset.origin_power_watt}
								{t('library.origin.laser', {
									kind: laserKindLabel(preset.origin_laser_type),
									watt: i18n.number(preset.origin_power_watt)
								})}
							{:else if preset.origin_laser_type}
								{laserKindLabel(preset.origin_laser_type)}
							{:else}
								{t('library.origin.unknown')}
							{/if}
						</dd>
						{#if preset.origin_by}
							<dt>{t('library.credit')}</dt>
							<!-- The shared catalogue is CC BY, so the credit is a condition of the
							     copy and it belongs wherever the row is read. A contributor's handle
							     is their own data and goes on screen as it stands. -->
							<dd>{preset.origin_by}</dd>
						{/if}
					{/if}
					<dt>{t('library.air')}</dt>
					<dd>{preset.air_assist ? t('library.on') : t('library.off')}</dd>
					{#if preset.last_used_at}
						<dt>{t('library.lastUsed')}</dt>
						<dd>{i18n.ago(preset.last_used_at)}</dd>
					{/if}
				</dl>
				<div class="bewijsvak">
					{#if preset.grid_photo}
						<img
							src={photoUrl(preset)}
							alt={preset.grid_cell
								? t('library.photo.altCircled', {
										id: preset.grid_id,
										row: preset.grid_cell.row + 1,
										column: preset.grid_cell.column + 1
									})
								: t('library.photo.alt', { id: preset.grid_id })}
						/>
						<p class="below">
							{#if preset.grid_cell}
								<!-- The mark follows the alignment of the grid; when that has not
								     been set the server falls back to the whole image and the
								     outline is approximate. So the caption names the square instead
								     of claiming the circle is exact. -->
								{t('library.caption.cell', {
									row: preset.grid_cell.row + 1,
									column: preset.grid_cell.column + 1
								})}
								{#if preset.grid_aligned === false}
									<span class="help warn benadering">{t('library.caption.approximate')}</span>
								{/if}
							{:else}
								{t('library.caption.grid')}
							{/if}
						</p>
					{:else if preset.grid_id}
						<p class="below">{t('library.caption.noPhoto')}</p>
						{#if canEdit}
							<label class="btn mini file">
								{busyPhoto === preset.grid_id ? t('common.busy') : t('library.addPhoto')}
								<input
									type="file"
									accept="image/*"
									capture="environment"
									onchange={(e) => {
										const f = e.currentTarget.files?.[0];
										e.currentTarget.value = '';
										if (f && preset.grid_id) photoFor(preset.grid_id, f);
									}}
								/>
							</label>
						{/if}
					{:else}
						<!-- Two different cases, and they must not get the same sentence. If the
						     source says "measured" but no grid hangs off it, *that* is the
						     message — not "not measured", because that contradicts the badge on
						     the same line. -->
						<p class="below">
							{#if preset.source === 'testraster'}
								{t('library.evidence.lost')}
							{:else}
								{t('library.evidence.none')}
							{/if}
						</p>
						{#if canEdit}
							<button class="btn mini" onclick={() => onMakeGrid?.(preset.material_id)}>
								{t('library.makeGrid')}
							</button>
						{/if}
					{/if}
					{#if canEdit}
						<button class="btn ghost mini" onclick={() => share(preset)}>{t('library.menu.share')}</button>
					{/if}
				</div>
				{#if canEdit && preset.import_batch}
					<!-- The import this row came in on, and one press back out of it. Twenty-six
					     of the thirty-five settings in this library arrived in one such batch, for
					     a machine nobody runs, and until now not one of them could be removed
					     again. It takes the settings of that batch and the materials the batch
					     created that nothing else uses — the rest stays. -->
					<div class="batch">
						<button class="btn mini danger" disabled={library.busy} title={library.busy ? t('reason.busy') : undefined} onclick={() => undoImport(preset.import_batch ?? '')}>
							{t('library.batch.undo')}
						</button>
						<span class="help">{t('library.batch.undo.why')}</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if canEdit && editing === preset.id}
			<!-- Material, operation and source are fixed: that is the identity of a
			     preset, not a setting. -->
			<div class="edit">
				<NumberField
					label={t('library.speed')}
					unit="mm/s"
					step={1}
					min={0.1}
					value={String(preset.speed_mm_s)}
					onchange={(v) => saveEdit(preset, { speed_mm_s: Number(v) })}
				/>
				<NumberField
					label={t('library.power')}
					unit="%"
					step={1}
					min={1}
					max={100}
					value={String(preset.power_percent)}
					onchange={(v) => saveEdit(preset, { power_percent: Number(v) })}
				/>
				{#if preset.operation === 'graveren-raster'}
					<NumberField
						label={t('library.interval')}
						unit="mm"
						step={0.01}
						min={0.01}
						value={String(preset.interval_mm ?? '')}
						onchange={(v) => saveEdit(preset, { interval_mm: Number(v) })}
					/>
				{/if}
				<NumberField
					label={t('library.passes')}
					step={1}
					min={1}
					value={String(preset.passes)}
					onchange={(v) => saveEdit(preset, { passes: Number(v) })}
				/>
				<NumberField
					label={t('library.thickness')}
					unit="mm"
					step={0.5}
					min={0}
					value={String(preset.thickness_mm ?? '')}
					onchange={(v) => saveEdit(preset, { thickness_mm: Number(v) })}
				/>
				<label class="field-label wide"
					><span>{t('library.note')}</span>
					<input
						type="text"
						value={preset.note}
						placeholder={t('library.note.placeholder')}
						onchange={(e) => saveEdit(preset, { note: e.currentTarget.value })}
					/>
				</label>
				<label class="field-label wide"
					><span>{t('library.machineProfile')}</span>
					<select
						value={preset.machine_name ?? ''}
						onchange={(e) => {
							const found = library.machines.find((m) => m.name === e.currentTarget.value);
							saveEdit(preset, { machine_id: found?.id ?? null });
						}}
					>
						<option value="">—</option>
						{#each library.machines as machine (machine.id)}
							<option value={machine.name}>{machine.name}</option>
						{/each}
					</select>
				</label>
			</div>
		{/if}
	</article>
{/snippet}

{#if preview}
	<!-- The import preview takes over the whole dialog. This is the moment
	     where the decision falls; going on browsing beside it through the library you
	     are about to overwrite helps nobody. -->
	{@const s = preview.merge}
	<section class="wissel" bind:this={wisselEl}>
		<header class="wisselkop">
			<h2 class="title">{t('import.title')}</h2>
			<p class="source">
				<span class="mono">{fileName}</span>
				{#if preview.exported_at}
					<span aria-hidden="true">·</span>
					{t('import.exportedAt', { when: i18n.ago(preview.exported_at) })}
				{/if}
			</p>
			<ul class="contents">
				<li class="badge">{count(preview.contains.materials, 'materials')}</li>
				<li class="badge">{count(preview.contains.presets, 'presets')}</li>
				<li class="badge">{count(preview.contains.machines, 'machines')}</li>
				<li class="badge">{count(preview.contains.test_grids, 'testGrids')}</li>
				<!-- Zero photos is not a detail: then the evidence does not come along. -->
				<li class="badge" class:warn={preview.contains.photos === 0}>
					{count(preview.contains.photos, 'photos')}
				</li>
			</ul>
			<!-- What it will lie next to. Without this "6 settings" are six loose
			     numbers; beside it, it is a ratio. -->
			<p class="help now">
				{t('import.yoursNow', {
					materials: count(preview.current.materials, 'materials'),
					presets: count(preview.current.presets, 'presets'),
					grids: count(preview.current.test_grids, 'testGrids')
				})}
			</p>
		</header>

		<!-- The two choices sit side by side and both carry their consequence, so that
		     "replace" is not picked by accident because it sounds shorter. -->
		<div class="keuzes">
			<label class="choice" class:on={mode === 'merge'}>
				<input type="radio" name="importmode" value="merge" bind:group={mode} />
				<span class="titelklein">{t('import.merge')}</span>
				<span class="help">{t('import.merge.explain')}</span>
			</label>
			<label class="choice danger" class:on={mode === 'replace'}>
				<input type="radio" name="importmode" value="replace" bind:group={mode} />
				<span class="titelklein">{t('import.replace')}</span>
				<span class="help">{t('import.replace.explain')}</span>
			</label>
		</div>

		{#if mode === 'merge'}
			<ul class="gevolg">
				{#if s.materials.new.length}
					<li class="erbij">
						<strong>{t('import.newMaterials', { n: s.materials.new.length })}</strong>
						<span class="help">{s.materials.new.join(', ')}</span>
					</li>
				{/if}
				{#if s.materials.existing.length}
					<li class="zelfde">
						{t('import.recognised', { n: s.materials.existing.length })}
					</li>
				{/if}
				{#if s.presets.new}
					<li class="erbij">
						<strong>{t('import.addedPresets', { n: s.presets.new })}</strong>
					</li>
				{/if}
				{#if s.presets.identical}
					<li class="zelfde">
						{t('import.identical', { n: s.presets.identical })}
					</li>
				{/if}
				{#if s.test_grids.new}
					<li class="erbij">
						<strong>{t('import.addedGrids', { n: s.test_grids.new })}</strong>
						<span class="help">{t('import.withPhotos')}</span>
					</li>
				{/if}
				{#if s.machines.new.length}
					<li class="erbij">
						<strong>{t('import.addedMachines', { n: s.machines.new.length })}</strong>
						<span class="help">{s.machines.new.join(', ')}</span>
					</li>
				{/if}
				{#if !s.materials.new.length && !s.presets.new && !s.test_grids.new && !s.presets.conflicts.length}
					<li class="zelfde">{t('import.nothingNew')}</li>
				{/if}
			</ul>

			{#if voorstellen.length}
				<!-- The trap from M5: "birch plywood" and "plywood, birch" are one board.
				     Merging them ourselves would be a guess with someone else's numbers on
				     your material; pointing it out is something the user may do. -->
				<div class="block card inset">
					<h3>{t('import.sameBoard')}</h3>
					<p class="help">{t('import.sameBoard.body')}</p>
					{#each voorstellen as pair (pair.name)}
						<label class="samenvoeg">
							<input
								type="checkbox"
								checked={laidOnto[pair.name] === pair.material_id}
								onchange={(e) => linkTo(pair, e.currentTarget.checked)}
							/>
							<span>
								{t('import.mergeWith', { name: pair.name, match: pair.match })}
								<!-- On a line of its own: the reason is the server's sentence, and
								     glued behind a dash it read as half of this one. -->
								<span class="help block-line">{pair.why}</span>
							</span>
						</label>
					{/each}
				</div>
			{/if}

			{#if s.presets.conflicts.length}
				<div class="block card inset clash">
					<h3>{t('import.conflicts', { n: s.presets.conflicts.length })}</h3>
					<p class="help">{t('import.conflicts.body')}</p>
					<div class="wins">
						<label class="bereik">
							<input type="radio" name="clash" value="mine" bind:group={clashWinner} />
							<span>{t('import.keepMine')}</span>
						</label>
						<label class="bereik">
							<input type="radio" name="clash" value="file" bind:group={clashWinner} />
							<span>{t('import.takeTheirs')}</span>
						</label>
					</div>
					<ul class="botsingen">
						{#each s.presets.conflicts as clash (`${clash.material}-${clash.operation}-${clash.thickness_mm}`)}
							<li>
								<span class="wat">
									{clash.material}{clash.thickness_mm !== null
										? `, ${clash.thickness_mm} mm`
										: ''} · {operationLabel(clash.operation)}
								</span>
								<span class="pair">
									<span class="side" class:wins={clashWinner === 'mine'}>
										<span class="label-section k"
											>{t('import.mine')}{#if clashWinner === 'mine'}<span class="won"
													><Icon name="check" /></span
												>{/if}</span
										>
										<span class="mono"
											>{clash.mine.speed_mm_s} mm/s · {clash.mine.power_percent}%</span
										>
									</span>
									<span class="pijl" aria-hidden="true">→</span>
									<span class="side" class:wins={clashWinner === 'file'}>
										<span class="label-section k"
											>{t('import.theirs')}{#if clashWinner === 'file'}<span class="won"
													><Icon name="check" /></span
												>{/if}</span
										>
										<span class="mono"
											>{clash.theirs.speed_mm_s} mm/s · {clash.theirs.power_percent}%</span
										>
									</span>
								</span>
								{#if sterkerBewijs(clash)}
									<span class="beter">
										{t('import.strongerEvidence', {
											source:
												sourceLabel(clash.mine.source as Preset['source'])?.text.toLowerCase() ??
												clash.mine.source
										})}
									</span>
								{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		{:else}
			<div class="block card inset erase">
				<h3>{t('import.wipe.title')}</h3>
				<p>
					{t('import.wipe.body', {
						materials: count(preview.replace.removes.materials, 'materials'),
						presets: count(preview.replace.removes.presets, 'presets'),
						grids: count(preview.replace.removes.test_grids, 'testGrids')
					})}
				</p>
				<!-- The advice has to be actionable here. Otherwise it says "make a backup
				     first" on a screen you have to leave in order to make one, and then
				     nobody does it. -->
				<p class="help">
					{t('import.wipe.backup')}
					<button class="btn mini" onclick={() => library.exportBundle()}>
						{t('import.wipe.export')}
					</button>
				</p>
				<label class="samenvoeg">
					<input type="checkbox" bind:checked={wipeConfirmed} />
					<span>{t('import.wipe.confirm')}</span>
				</label>
			</div>
		{/if}

		{#if library.error}
			<div class="failure"><Notice tone="danger" live>{library.error}</Notice></div>
		{/if}

		<!-- The shared ask row: the way out first, the answer last. Replacing wipes the
		     library, so then the answer is the danger button rather than the primary. The
		     library sits inside a dialog it does not own, so the row is its own. -->
		<div class="actions ask-actions">
			<button class="btn" onclick={() => (preview = null)}>{t('common.cancel')}</button>
			<button
				class="btn"
				class:primary={mode !== 'replace'}
				class:danger={mode === 'replace'}
				disabled={library.busy || (mode === 'replace' && !wipeConfirmed)}
				title={library.busy ? t('reason.busy') : wipeConfirmed ? undefined : t('import.wipe.confirm')}
				onclick={importeren}
			>
				{mode === 'replace' ? t('import.doReplace') : t('import.merge')}
			</button>
		</div>
	</section>
{:else}

{#if ready}
	<!-- What actually happened, in the same words as the preview. -->
	<div class="ready" bind:this={readyEl}><Notice tone="ok" live>
		<strong>
			{ready.mode === 'replace' ? t('import.done.replaced') : t('import.done.merged')}
		</strong>
		<span>
			{t('import.addedPresets', { n: ready.presets.added })}{ready.presets.updated
				? `, ${t('import.done.updated', { n: ready.presets.updated })}`
				: ''}{ready.presets.skipped
				? `, ${t('import.done.skipped', { n: ready.presets.skipped })}`
				: ''} · {count(ready.test_grids, 'testGrids')}.
		</span>
		{#if hidden && library.activeMachine}
			<span class="help">{t('import.done.hidden', { machine: library.activeMachine.name })}</span>
		{/if}
		<button class="btn ghost mini close" onclick={() => (ready = null)}>{t('common.close')}</button>
	</Notice></div>
{/if}

{#if canEdit && library.activeMachine && library.coverage && library.coverage.unattached > 0}
	<!-- Settings that belong to no machine show up under every machine, because the
	     query that fetches them reads `machine_id = ? OR machine_id IS NULL`. Attaching
	     them to this one says they were measured here, and only the reader knows whether
	     that is true — so this is a count and a button, never a step that runs by
	     itself. -->
	<div class="strays"><Notice tone="warn">
		<p>
			{t('library.strays', { n: library.coverage.unattached })}
			{#if library.coverage.unattached_grids}
				{t('library.strays.grids', { n: library.coverage.unattached_grids })}
			{/if}
		</p>
		<p class="help">{t('library.strays.why', { machine: library.activeMachine.name })}</p>
		<button class="btn mini close" disabled={library.busy} title={library.busy ? t('reason.busy') : undefined} onclick={() => library.adoptStrays()}>
			{t('library.strays.adopt', { machine: library.activeMachine.name })}
		</button>
	</Notice></div>
{/if}

{#if undone}
	<!-- What taking an import back actually took. One press made it and one press undid
	     it, and neither of the two is silent. -->
	<div class="ready"><Notice tone="ok" live>
		<span>{t('library.batch.undone', { n: undone.presets })}</span>
		{#if undone.kept_materials.length}
			<span class="help">{t('library.batch.kept', { n: undone.kept_materials.length })}</span>
		{/if}
		<button class="btn ghost mini close" onclick={() => (undone = null)}>{t('common.close')}</button>
	</Notice></div>
{/if}

<!-- Filters over an empty collection are furniture: three controls with nothing
     to control, above a window saying there is nothing. With an empty library they
     disappear and the invitation has the floor. -->
{#if library.materials.length > 0}
<div class="kopblok">
	<div class="bar">
	<input
		class="search"
		type="search"
		bind:value={query}
		placeholder={t('library.search')}
		aria-label={t('library.searchAria')}
	/>
	<!-- There used to be an "All materials" dropdown here. It did exactly what the
	     list on the left does, and two controls for one choice mainly raises the
	     question which of the two is the real one. The list won: it also shows how
	     many settings a material has, and which material is on the sheet.

	     "New material" used to stand here too, at the far right of this bar, while the
	     field it opened appeared at the far left of the body. It now sits at the foot of
	     the list of materials, with its field in the same spot. -->
</div>

<div class="context">
	<!-- The two narrowings belong together: together they say "this is what goes
	     with this laser and this sheet". Apart, at the two ends of the bar, it reads
	     as two loose settings. -->
	<div class="filters">
	{#if sheetMaterialId !== null && sheetMaterialName}
		<!-- The same switch as "only this machine", because it is the same kind of
		     narrowing: a preset holds for one laser on one material. Switching it off
		     shows the rest — this filter is a starting point, not a wall. -->
		<label class="bereik">
			<input
				type="checkbox"
				checked={materialId === sheetMaterialId}
				onchange={(e) => (materialId = e.currentTarget.checked ? sheetMaterialId : null)}
			/>
			<span
				>{t('library.onlyMaterial', { material: sheetMaterialName })}
				<span class="help block-line">{t('library.onlyMaterial.why')}</span></span
			>
		</label>
	{/if}
	{#if library.activeMachine}
		<!-- A preset holds for one laser on one material. By default you see those of
		     the machine that is on now; the rest is one checkbox away. -->
		<label class="bereik">
			<input
				type="checkbox"
				checked={library.onlyThisMachine}
				onchange={() => library.toggleScope()}
			/>
			<span>{t('library.onlyMachine', { machine: library.activeMachine.name })}</span>
		</label>
	{/if}
	</div>
	<!-- The target used to appear only with two or more layers. But "Apply" must
	     always say *onto what*, even with one layer: otherwise the button is a
	     promise without an address, and then the warning that the operation does not
	     match has nowhere to land either. -->
	{#if layers.length}
		<label class="target">
			<span>{t('library.applyTo')}</span>
			{#if layers.length > 1}
				<select bind:value={targetOperation}>
					{#each layers as op, index (op.id)}
						<option value={op.id}>{layerNamed(index + 1, op.label)}</option>
					{/each}
				</select>
			{:else}
				<strong>{layerNamed(1, layers[0].label)}</strong>
			{/if}
		</label>
	{/if}
	</div>
</div>
{/if}

<div class="library-tools">
	<details class="fold starter-disclosure">
		<summary>{t('library.startingPoints')}</summary>
		<StarterOffer door onTestGrid={() => onMakeGrid?.(null)} onChanged={() => library.load()} />
	</details>
	{#if canEdit}
		<details class="fold photo-disclosure">
			<summary>{t('library.boardPhoto')}</summary>
			<p class="help">{t('library.readBoard.how')}</p>
			<button class="btn" onclick={() => onReadBoard?.()}>{t('library.readBoard')}</button>
		</details>
	{/if}
	<details class="fold">
	<summary>{t('library.exchange')}</summary>
	<p class="help">{t('library.exchange.body')}</p>
	<div class="uitknoppen">
		<button
			class="btn"
			disabled={library.busy || library.materials.length === 0}
			title={library.materials.length === 0 ? t('library.export.nothing') : undefined}
			onclick={() => library.exportBundle()}
		>
			{t('library.export')}
		</button>
		{#if canEdit}
			<label class="btn file">
				{t('library.import')}
				<input
					type="file"
					accept=".openkerf-lib,application/zip"
					onchange={(e) => {
						const f = e.currentTarget.files?.[0];
						e.currentTarget.value = '';
						if (f) pickFile(f);
					}}
				/>
			</label>
		{/if}
	</div>
</details>
</div>

<!-- Only sensible when there is something to apply. With an empty library this
     explanation about layers sat *above* the message that there are no materials
     yet: "you have nothing" twice, in the wrong order, and the answer to a question
     you had not asked yet. -->
{#if canEdit && layers.length === 0 && library.materials.length > 0}
	<!-- Say once why "Apply" cannot work, not on every card again. -->
	<div class="nolayer"><Notice tone="info">{t('library.noLayer')}</Notice></div>
{/if}

{#if shareError}
	<div class="failure"><Notice tone="danger" live>{shareError}</Notice></div>
{/if}
{#if library.error}
	<div class="failure"><Notice tone="danger" live>{library.error}</Notice></div>
{/if}

{#if library.materials.length === 0}
	<!-- An empty library used to be one grey paragraph at the bottom of a window
	     full of filters with nothing to filter. This is the first thing a new user
	     sees here, so it takes the shape of an invitation: what this is, why it is
	     worth it, and the two ways in. -->
	<div class="welcome">
	<EmptyState title={t('library.welcome.title')} text={t('library.welcome.body')}>
		{#snippet action()}
		<div class="wegen">
			{#if canEdit}
				{@render addMaterial(t('library.welcome.first'), true)}
			{/if}
			{#if library.activeMachine}
				<!-- It points at the offer at the top of this window, and only when there is
				     a machine for that offer to be about. Measured before this: the sentence
				     said "Or fetch one from the Presetariat" 275 px below the button that
				     does exactly that, and named a window that no longer exists — the last
				     place in the interface that still treated the catalogue as somewhere you
				     go. With no machine active neither surface renders, and then the sentence
				     would point at nothing. -->
				<p class="help">{t('library.welcome.presetariat')}</p>
			{/if}
		</div>
		{/snippet}
	</EmptyState>
	</div>
{:else if groepen.length === 0}
	<!-- Nothing found is not a dead end as long as you can throw the search away
	     without having to look for the field. -->
	<EmptyState
		title={t('library.nothingFound', { query })}
		text={t('library.nothingFound.body', { materials: count(library.materials.length, 'materials') })}
	>
		{#snippet action()}
			<button class="btn" onclick={() => (query = '')}>{t('library.clearSearch')}</button>
		{/snippet}
	</EmptyState>
{:else}
	<!--
		Two panes instead of one long column.

		The task is "find the setting for what is in the machine". That is picking a
		material first and then pointing at one row. In the old layout *all* materials
		were stacked with *all* settings expanded, so step one was scrolling and step
		two was scrolling again. Now the left says what you have and the right says
		what goes with it — the shape LightBurn and xTool both use for it, and the
		shape that fits the question.
	-->
	<div class="tweeluik">
		<nav class="materials" aria-label={t('library.materials')}>
			<ul>
				<!-- Recently used is the first row and not a separate section with
				     duplicate cards: it is a *choice* in the same list. -->
				{#if recent.length}
					<li>
						<button
							class="listrow matrij"
							aria-current={materialId === null && !query.trim() ? 'true' : undefined}
							onclick={() => {
								materialId = null;
								query = '';
							}}
						>
							<span class="matname">{t('library.recent')}</span>
							<span class="mataantal mono">{recent.length}</span>
						</button>
					</li>
				{/if}
				{#each groepen as group (group.materialId)}
					<li class="matregel">
						<button
							class="listrow matrij"
							aria-current={materialId === group.materialId ? 'true' : undefined}
							onclick={() => (materialId = group.materialId)}
							oncontextmenu={(e) => openMaterialMenu(e, group)}
						>
							<span class="matname">{group.name}</span>
							{#if group.materialId === sheetMaterialId}
								<!-- What is in the machine is the reason you are here; that belongs in
								     the list and not only in a filter checkbox. -->
								<span class="badge ligt" title={t('library.onSheet.title')}>{t('library.onSheet')}</span>
							{/if}
							<span class="mataantal mono">{group.presets.length}</span>
						</button>
						{#if canEdit}
							<!-- The same ⋯ a setting row has, in the same place on the row. Renaming,
							     merging and removing a material had no button anywhere, and one of
							     the two lists in this window did have a menu — which is why a reader
							     could reasonably conclude that a material could not be removed at
							     all. Beside the button, not inside it: a button in a button is not a
							     button. -->
							<button
								class="btn ghost icon meer"
								aria-label={t('library.material.more.aria', { material: group.name })}
								aria-haspopup="menu"
								title={t('library.more.title')}
								onclick={(e) => openMaterialMenu(e, group)}
							>
								<Icon name="more" />
							</button>
						{/if}
					</li>
				{/each}
			</ul>
			{#if canEdit}
				<!-- Adding a material at the foot of the list of materials: the one place
				     where a reader looking for "one more material" is already looking. -->
				{@render addMaterial(t('library.newMaterial'), false)}
			{/if}
		</nav>

		<div class="settings">
			{#if materialId === null}
				{#if recent.length}
					<h2 class="label-section head">{t('library.recent')}</h2>
					{#each recent as preset (preset.id)}
						{@render card(preset, true)}
					{/each}
					<p class="help pick">{t('library.pickMaterial')}</p>
				{:else}
					{#each groepen as group (group.materialId)}
						{#each group.presets as preset (preset.id)}
							{@render card(preset, true)}
						{/each}
					{/each}
				{/if}
			{:else}
				{@const group = groepen.find((g) => g.materialId === materialId)}
				{#if group}
					<div class="materiaalkop">
						<h2 class="label-section head">{group.name}</h2>
						{#if canEdit && zichtbarePresets.length > 0}
							<button class="btn ghost mini" onclick={() => onMakeGrid?.(group.materialId)}>
								{t('library.makeGrid')}
							</button>
						{/if}
					</div>

					{#if renaming === group.materialId}
						<!-- Renaming where the name is read, with the settings it belongs to still
						     below it: this is the difference between a typo you can correct and a
						     second material beside the first, which is how this library came to
						     hold two names for one board. -->
						<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
						<div
							class="vraag card inset"
							role="group"
							bind:this={askEl}
							onkeydown={(e) => {
								if (e.key !== 'Escape') return;
								// Not up to the window: Escape here means "never mind this question".
								// Without the stop it reaches the dialog's panel and closes the whole
								// library, half-typed answer and all. The block is a container and not a
								// control, which is what the a11y note above is about.
								e.stopPropagation();
								closeQuestion();
							}}
						>
							<label class="field-label">
								<span>{t('library.material.name')}</span>
								<input
									type="text"
									bind:value={renameTo}
									onkeydown={(e) => e.key === 'Enter' && saveRename()}
								/>
							</label>
							<label class="field-label">
								<span>{t('library.material.synonyms')}</span>
								<input
									type="text"
									bind:value={alsoCalled}
									placeholder={t('library.material.synonyms.placeholder')}
								/>
							</label>
							<p class="help">{t('library.material.synonyms.why')}</p>
							<div class="ask-actions">
								<button class="btn" onclick={() => (renaming = null)}>
									{t('common.cancel')}
								</button>
								<button
									class="btn primary"
									disabled={library.busy || !renameTo.trim()} title={library.busy ? t('reason.busy') : t('reason.needsName')}
									onclick={saveRename}>{t('common.save')}</button
								>
							</div>
						</div>
					{/if}

					{#if merging === group.materialId}
						<!-- A merge keeps both sides' work: the settings, the boards, the recipes
						     and the photographs move over, and the old name stays as a name the
						     other material answers to — so the next import that still uses it lands
						     on the right board. -->
						<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
						<div
							class="vraag card inset"
							role="group"
							bind:this={askEl}
							onkeydown={(e) => {
								if (e.key !== 'Escape') return;
								// Not up to the window: Escape here means "never mind this question".
								e.stopPropagation();
								closeQuestion();
							}}
						>
							<p>{t('library.material.merge.body', { material: group.name })}</p>
							<label class="field-label">
								<span>{t('library.material.merge.pick')}</span>
								<select bind:value={mergeInto}>
									<option value={null}>{t('library.material.merge.choose')}</option>
									{#each library.materials.filter((m) => m.id !== group.materialId) as other (other.id)}
										<option value={other.id}>{other.name}</option>
									{/each}
								</select>
							</label>
							<div class="ask-actions">
								<button class="btn" onclick={() => (merging = null)}>
									{t('common.cancel')}
								</button>
								<button
									class="btn primary"
									disabled={library.busy || mergeInto === null}
									title={library.busy ? t('reason.busy') : t('reason.needsMaterial')}
									onclick={doMerge}>{t('library.material.merge.confirm')}</button
								>
							</div>
						</div>
					{/if}

					{#if removing === group.materialId}
						<!-- The counts are read before the question is asked. Removing a material
						     is `preset` CASCADE, `grid_recipe` CASCADE and `test_grid.material_id`
						     SET NULL: measured on a copy of this library, one press took six
						     settings — two of them measured, with photographs — orphaned two boards
						     and answered "removed: 6". So the question names what would go, and the
						     button says that it takes all of it. -->
						<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
						<div
							class="vraag card inset"
							role="group"
							bind:this={askEl}
							onkeydown={(e) => {
								if (e.key !== 'Escape') return;
								e.stopPropagation();
								closeQuestion();
							}}
						>
							{#if !usage}
								<p>{t('common.busy')}</p>
							{:else}
								<Notice tone="danger" live>
									{#if wouldGoWith(usage).length}
										{t('library.material.remove.carries', {
											material: group.name,
											what: i18n.list(wouldGoWith(usage))
										})}
									{:else}
										{t('library.material.remove.empty', { material: group.name })}
									{/if}
								</Notice>
							{/if}
							{#if usage?.sheets}
								<p class="help">{t('library.material.remove.sheet', { n: usage.sheets })}</p>
							{/if}
							<div class="ask-actions">
								<button
									class="btn"
									onclick={() => {
										removing = null;
										usage = null;
									}}>{t('library.material.remove.keep')}</button
								>
								<button
									class="btn danger"
									disabled={library.busy || !usage}
									title={library.busy ? t('reason.busy') : t('reason.notLoaded')}
									onclick={doRemove}
								>
									{usage && wouldGoWith(usage).length
										? t('library.material.remove.confirmAll')
										: t('library.material.remove.confirm')}
								</button>
							</div>
						</div>
					{/if}

					{#if thicknesses.length > 1}
						<!-- Thickness is the second question everyone asks and the first you can
						     tick off. As a filter and not as a heading, because you sometimes want
						     the neighbouring thickness in view. -->
						<div class="thicknesses" role="group" aria-label={t('library.thickness')}>
							<button class="chip" aria-pressed={thickness === null} onclick={() => (thickness = null)}>
								{t('library.allThicknesses')}
							</button>
							{#each thicknesses as d (d)}
								<button class="chip" aria-pressed={thickness === d} onclick={() => (thickness = d)}>
									{d === null ? t('library.noThickness') : `${d} mm`}
								</button>
							{/each}
						</div>
					{/if}

					{#if zichtbarePresets.length === 0}
						<!-- The empty state's shape — what is missing, and the one thing that
						     fills it — without its title face: the sentence is two sentences
						     long, and set at title weight it shouted over the pane. -->
						<div class="empty">
							<p class="help">
								{group.presets.length === 0
									? t('library.noPresets', { material: group.name })
									: t('library.noneForThickness', { thickness: thickness })}
							</p>
							{#if canEdit}
								<button class="btn primary" onclick={() => onMakeGrid?.(group.materialId)}>
									{t('library.makeGrid')}
								</button>
							{/if}
						</div>
					{:else}
						{#each zichtbarePresets as preset (preset.id)}
							{@render card(preset, false)}
						{/each}
					{/if}
				{:else}
					<!-- A material is chosen and the search hides everything it has. There used
					     to be no `{:else}` here at all, so the pane was simply blank: no list, no
					     reason, and the search field far above with a term in it. -->
					{@const chosen = library.materials.find((m) => m.id === materialId)}
					<div class="empty">
						<p class="help">
							{chosen
								? t('library.filteredOut', { material: chosen.name, query })
								: t('library.pickMaterial')}
						</p>
						<button class="btn" onclick={() => (query = '')}>{t('library.clearSearch')}</button>
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}

{#if canEdit && library.materials.length}
	<details class="fold vouw">
		<summary>{t('library.manual')}</summary>
		<div class="grid">
			<label class="field-label wide">
				<span>{t('library.material')}</span>
				<select bind:value={draft.material_id}>
					<option value={null}
						>{materialId === null
							? t('library.pickMaterialOption')
							: t('library.filteredMaterial')}</option
					>
					{#each library.materials as material (material.id)}
						<option value={material.id}>{material.name}</option>
					{/each}
				</select>
			</label>
			<label class="field-label">
				<span>{t('library.operation')}</span>
				<select bind:value={draft.operation}>
					{#each operationChoices() as op (op.value)}
						<option value={op.value}>{op.label}</option>
					{/each}
				</select>
			</label>
			<NumberField
				label={t('library.thickness')}
				unit="mm"
				step={0.5}
				min={0}
				bind:value={draft.thickness_mm}
			/>
			<NumberField
				label={t('library.speed')}
				unit="mm/s"
				step={1}
				min={0.1}
				bind:value={draft.speed_mm_s}
			/>
			<NumberField
				label={t('library.power')}
				unit="%"
				step={1}
				min={1}
				max={100}
				bind:value={draft.power_percent}
			/>
		</div>
		<p class="help manual-note">{t('library.manual.note')}</p>
		<button
			class="btn"
			disabled={library.busy ||
				!draft.speed_mm_s ||
				!draft.power_percent ||
				(draft.material_id ?? materialId) === null}
			title={library.busy
				? t('reason.busy')
				: (draft.material_id ?? materialId) === null
					? t('reason.needsMaterial')
					: t('library.manual.needsNumbers')}
			onclick={createPreset}
		>
			{t('common.save')}
		</button>
	</details>

	<details class="fold vouw">
		<summary>{t('library.profiles', { n: library.machines.length })}</summary>
		<Why>{t('library.profiles.why')}</Why>
		{#if library.machines.length}
			<ul class="profiles">
				{#each library.machines as machine (machine.id)}
					{@const empty = machine.presets + machine.test_grids === 0}
					{@const active = machine.id === library.activeMachine?.id}
					<li class:orphan={machine.orphaned}>
						<div class="profielrij">
							<span class="profielnaam">{machine.name}</span>
							<span class="mono">{machine.power_watt ? `${machine.power_watt} W` : ''}</span>
							{#if machine.orphaned}
								<!-- Two states, told apart, because the answer differs: a machine that
								     is not here may come back when you plug it in, while a profile
								     that points at no machine at all is one somebody typed or one this
								     library let go of when its slot went to another laser — and its
								     way out is a merge, not a wait. -->
								{#if machine.orphaned_because === 'no-device'}
									<span class="badge" title={t('library.profile.noDevice.title')}>
										{t('library.profile.noDevice')}
									</span>
								{:else}
									<span class="badge" title={t('library.profile.deviceGone.title')}>
										{t('library.profile.deviceGone')}
									</span>
								{/if}
							{/if}
							{#if !empty}
								<!-- What hangs off it, because that decides whether it can go: a profile
								     with settings or grids is evidence, a profile without is clutter.
								     Only naming what is there — "0 settings" next to a profile that
								     does carry a test grid is a half truth. -->
								<span class="help">{evidence(machine)}</span>
							{:else if canEdit && !active}
								<button
									class="btn ghost mini"
									disabled={library.busy} title={library.busy ? t('reason.busy') : undefined}
									onclick={() => library.removeMachineProfile(machine.id)}
									>{t('library.profile.tidy')}</button
								>
							{/if}
							{#if canEdit && !empty && machine.orphaned_because === 'no-device' && library.activeMachine && !active}
								<!-- Both halves of one laser, joined into the one you are working on.
								     The case is measured rather than imagined: a device-less profile
								     with sixty watts and twenty-seven settings sits beside the
								     device-bound one with three settings and no wattage, and they are
								     one machine. -->
								<button
									class="btn mini"
									disabled={library.busy}
									title={t('library.profile.mergeInto.why', {
										machine: library.activeMachine.name
									})}
									onclick={() =>
										library.activeMachine &&
										library.mergeMachineProfile(machine.id, library.activeMachine.id)}
									>{t('library.profile.mergeInto', { machine: library.activeMachine.name })}</button
								>
							{/if}
						</div>

						{#if canEdit && active}
							<!-- The machine you are working on, described. Every profile in this
							     library carries `power_watt: null`, so somebody who is already past
							     the wizard has no other door — and without the kind and the wattage
							     nothing can match: an 80 W catalogue showed all twenty-six of its rows
							     to a machine nobody had described. The wizard asks these two once;
							     this is the same two fields for the machine you already have, writing
							     through the same route. There is deliberately no form here that
							     *creates* a profile: that form was the only thing in the app that
							     could make a profile with a wattage and no machine behind it. -->
							<fieldset class="laser card inset">
								<legend>{t('setup.laser')}</legend>
								<div class="paar">
									<label class="field-label">
										<span>{t('setup.laser.kind')}</span>
										<select
											value={machine.laser_type || 'unknown'}
											onchange={(e) =>
												saveMachine(machine.id, {
													laser_type: e.currentTarget.value as LaserKind
												})}
										>
											<option value="unknown">{t('laser.kind.unknown')}</option>
											{#each LASER_KINDS as one (one)}
												<option value={one}>{laserKindLabel(one)}</option>
											{/each}
										</select>
									</label>
									<NumberField
										label={t('setup.laser.watt')}
										unit="W"
										step={10}
										min={1}
										max={1000}
										value={machine.power_watt === null ? '' : String(machine.power_watt)}
										onchange={(v) =>
											saveMachine(machine.id, { power_watt: v === '' ? null : Number(v) })}
									/>
								</div>
								<!-- On its own line, and half a line wide: one field over the full width
								     of a fieldset lines up with nothing (v4, form rule 5). -->
								<div class="halve">
									<NumberField
										label={t('setup.laser.lens')}
										unit="mm"
										step={0.5}
										min={0}
										value={machine.lens_mm === null ? '' : String(machine.lens_mm)}
										onchange={(v) =>
											saveMachine(machine.id, { lens_mm: v === '' ? null : Number(v) })}
									/>
								</div>
								<Why>{t('setup.laser.watt.why')}</Why>
							</fieldset>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</details>
{/if}

<!-- Decision B7. Outside the block above, because importing into an empty library
     is precisely the ordinary reason to be here: a new computer. -->

{/if}

{#if rowMenu}
	<Menu menu={rowMenu.list} x={rowMenu.x} y={rowMenu.y} onClose={() => (rowMenu = null)} />
{/if}

<style>
	/*
	 * The three occasional tools — starting points, reading a board photo, and
	 * exchanging the library — as folds stacked one under the other, not side by side.
	 *
	 * Side by side they read as tabs that were not tabs: three summaries on one line, and
	 * opening one dropped its content under the row with the other two summaries still
	 * standing beside an empty space. Real tabs would not fit either: each of these is
	 * visited now and then — once per machine, once per board photo, once per new
	 * computer — and tabs keep one panel open all the time, which would push the material
	 * list, the thing you open this window for every time, further down. Stacked folds
	 * cost one quiet line each while shut, open at the full width of the window, and
	 * can be open together when that helps.
	 */
	.library-tools {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-2) 0 var(--space-3);
		border-bottom: 1px solid var(--line);
		margin-bottom: var(--space-3);
	}
	.library-tools details[open] > summary { margin-bottom: var(--space-2); }
	.library-tools details > :not(summary) { margin-left: var(--space-4); }
	.library-tools .help { margin-bottom: var(--space-2); }

	/* Search has to stay reachable while you scroll through twenty materials; the
	   window itself is the scroll container, so this sticks to its top. */
	.kopblok {
		position: sticky;
		top: calc(-1 * var(--space-4));
		z-index: 2;
		margin: calc(-1 * var(--space-4)) calc(-1 * var(--space-4)) 0;
		padding: var(--space-4) var(--space-4) 0;
		background: var(--surface-1);
	}
	.bar {
		display: flex;
		gap: var(--space-2);
		align-items: center;
	}
	.search { flex: 1; min-width: 0; }
	.context {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--line);
	}
	.target {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.filters {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}
	.bereik {
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* A reason that is a sentence of its own goes on a line of its own: glued behind a
	   dash it read as the second half of the label. */
	.block-line { display: block; }
	.head { margin: var(--space-4) 0 var(--space-2); }
	.pick { margin-top: var(--space-2); }
	/* An empty library: the empty state *is* the screen here, not a footnote under it. */
	.welcome { padding: var(--space-2) 0; }
	.wegen { display: grid; justify-items: start; gap: var(--space-3); }
	.empty { display: grid; justify-items: start; gap: var(--space-3); padding: var(--space-2) 0; }
	.empty .help { font-size: var(--text-sm); }

	/* ── The diptych ─────────────────────────────────────────────────────────
	   On the left what you have, on the right what belongs with it. The left column is
	   fixed: it must not move as soon as you point at a material with a long name,
	   because then the list slides out from under your cursor. */
	.tweeluik {
		display: grid;
		grid-template-columns: 280px minmax(0, 1fr);
		gap: var(--space-4);
		align-items: start;
	}
	.materials ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	/* The row is a `.listrow`; here only its two columns: the name (with the sheet
	   badge under it) and the count. */
	.matrij {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		padding-inline: var(--space-2);
	}
	.matname { grid-column: 1; min-width: 0; overflow-wrap: break-word; }
	.matrij .mataantal { grid-column: 2; grid-row: 1 / span 2; }
	.matrij .ligt { grid-column: 1; justify-self: start; }
	.mataantal { font-size: var(--text-xs); color: var(--text-2); }
	/* The row and its menu side by side: the menu button is a sibling of the row button
	   and not a child, because a button inside a button is not a button. */
	.matregel { display: flex; align-items: center; gap: 2px; }
	.matregel .matrij { flex: 1; min-width: 0; }
	/* The field for a new material where the button that summons it stands. */
	.addrow {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
	.addbuttons {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.materials :global(.add) { margin-top: var(--space-2); }
	/* A question about one material, in the pane that carries that material's name. The
	   left-hand row is 232 px wide, so it cannot stand there, and a window over a window
	   would hide the list the answer changes. It is answered with bordered buttons in
	   the shared ask row, because the heaviest of the three takes settings and their
	   photographs with it. */
	.vraag {
		display: grid;
		gap: var(--space-2);
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
	}
	.vraag p { margin: 0; }
	/* One field on a line keeps the width of half a line (v4, form rule 5). */
	.vraag .field-label { max-width: 32ch; }
	/* A pair is one statement about one thing and stays on one line (rule 2). */
	.paar {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3);
		align-items: end;
	}
	.strays,
	.ready,
	.failure,
	.nolayer { margin: 0 0 var(--space-3); }
	.close { justify-self: start; }
	/* The import a setting came in on spans both columns of the provenance, under them. */
	.batch {
		grid-column: 1 / -1;
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px dashed var(--line);
	}
	.batch .help { flex: 1; min-width: 14em; }
	/* A profile is a row plus, for the machine you are on, the two fields that describe
	   it. So the row itself is a line of its own inside the item. */
	.profielrij {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.profielnaam { font-weight: 500; }
	.laser {
		display: grid;
		gap: var(--space-2);
		margin: var(--space-2) 0 0;
	}
	.laser legend { padding: 0; font-size: var(--text-xs); color: var(--text-2); }
	.halve { max-width: calc(50% - var(--space-2)); }
	.materiaalkop {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		margin-bottom: var(--space-2);
	}
	.materiaalkop .head { margin: 0; }
	.thicknesses {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1h);
		margin-bottom: var(--space-3);
	}

	/* ── One setting, one row ─────────────────────────────────────────────
	   The source used to be a coloured stripe down the left of the row as well. The
	   badge on the same line already says it, in a word and an icon, so the stripe was
	   the same fact a second time — in colour alone. */
	.preset {
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		margin-top: var(--space-1);
		padding: 0 var(--space-2) 0 var(--space-3);
	}
	.preset:first-of-type { margin-top: 0; }
	.preset.open {
		border-color: var(--accent-edge);
		box-shadow: var(--lift-1);
	}

	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 40px;
		margin: var(--space-2) 0;
	}
	.wat { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: var(--space-2); }
	/* The thickness in a column of its own with a fixed width: that is what the eye
	   runs along when you are looking for "3 mm", and then the numbers have to line
	   up under each other. */
	.size {
		flex: none;
		width: 4.4em;
		font-weight: 600;
		font-size: var(--text-sm);
	}
	.operation {
		min-width: 0;
		white-space: normal;
		overflow-wrap: break-word;
		font-size: var(--text-sm);
	}
	.operation .mat { font-weight: 500; }
	.values {
		flex: none;
		display: flex;
		gap: var(--space-3);
		font-size: var(--text-sm);
	}
	.values span { min-width: 4.2em; text-align: right; }
	.values small { color: var(--text-2); margin-left: 1px; }

	/* A floor and not a fixed width: the four source badges line up under each other in
	   every language that fits, and the one that does not fit grows instead of spilling
	   over its neighbour. Measured in Dutch: "Geverifieerd" needed 3 px more than 7.6em
	   and "Geëxtrapoleerd" is two letters longer again. */
	.badge.source { flex: none; min-width: 7.6em; }
	/* A setting for a different kind of operation may be applied, but not without you
	   knowing. One badge beside the operation, with the whole explanation in the
	   tooltip. */
	.mismatch { flex: none; align-self: center; }

	.bewijs,
	.geenfoto {
		flex: none;
		width: 28px;
		height: 28px;
		padding: 0;
		border-radius: var(--radius-field);
		overflow: hidden;
	}
	.bewijs {
		border: 1px solid var(--line);
		background: var(--surface-2);
	}
	.bewijs img { width: 100%; height: 100%; object-fit: cover; display: block; }
	.doe, .meer { flex: none; }

	.zekerweg {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		padding: var(--space-2) 0;
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
	}
	.zekerweg span { flex: 1; min-width: 12em; }

	/* The share panel. Same shape as the two panels above it: under the row, a dashed
	   rule to say it belongs to it, and the same field and button idiom as the material
	   verbs so that nothing here has to be learned twice. */
	.delen {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-2) 0;
		border-top: 1px dashed var(--line);
	}
	.delen .kop { margin: 0; font-size: var(--text-xs); font-weight: 600; }
	.delen input,
	.delen select { width: 100%; }
	.uitkomst {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.uitkomst .wide { grid-column: 1 / -1; }

	.herkomst {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-3);
		margin-top: var(--space-2);
		padding: var(--space-2) 0;
		border-top: 1px dashed var(--line);
	}
	.herkomst dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px var(--space-2);
		margin: 0;
		font-size: var(--text-xs);
	}
	.herkomst dt { color: var(--text-2); }
	.herkomst dd { margin: 0; }
	/* Without a stored alignment the server falls back on the whole image; on a skewed
	   photo with a lot of margin the outline is then half a cell out. Saying so is
	   better than a marker that looks exact and is not. */
	.benadering { display: block; margin-top: 2px; }
	.bewijsvak {
		display: grid;
		justify-items: start;
		gap: var(--space-1);
		max-width: 180px;
	}
	.bewijsvak img {
		width: 100%;
		max-width: 160px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
	}
	.bewijsvak .below { margin: 0; font-size: var(--text-xs); color: var(--text-2); }
	.file { position: relative; overflow: hidden; }
	.file input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

	.edit {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-2) 0;
		border-top: 1px dashed var(--line);
	}
	.edit .wide { grid-column: 1 / -1; }
	.edit input,
	.edit select { width: 100%; }

	.vouw {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.vouw > summary { margin-bottom: var(--space-2); }
	.profiles { list-style: none; margin: var(--space-2) 0; padding: 0; }
	/* A block and no longer a flex row: the machine you are working on carries the two
	   fields that describe it underneath its own line. */
	.profiles li {
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		margin-bottom: var(--space-1);
		font-size: var(--text-xs);
	}
	/* The name pushes the rest to the right; that way the power and the badge line up,
	   even when one profile has a badge and the other does not. */
	.profielrij > .profielnaam { flex: 1; min-width: 0; }
	/* Orphaned is not an error but is worth knowing: muted, not red. */
	.profiles li.orphan { border-style: dashed; }
	.profiles li.orphan .profielnaam { color: var(--text-2); }
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.grid .wide { grid-column: 1 / -1; }
	.grid input,
	.grid select { width: 100%; }
	.manual-note { margin-bottom: var(--space-2); }

	.uitknoppen { display: flex; gap: var(--space-2); flex-wrap: wrap; }

	/* The preview is a screen of its own, not a strip below the list: this is where
	   the decision falls, so it gets the room and the reading width for it. */
	.wisselkop { margin-bottom: var(--space-4); }
	.source { margin: var(--space-1) 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); }
	.contents {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1h);
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.now { margin-top: var(--space-2); }

	.keuzes {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	/* The two answers as cards you pick, with the consequence in each. Chosen is the
	   tint and the edge every chosen thing has; replacing is chosen in red. */
	.choice {
		display: grid;
		grid-template-columns: auto 1fr;
		grid-template-areas: 'radio title' '. hint';
		gap: 2px var(--space-2);
		align-items: start;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		cursor: pointer;
		transition: background var(--transition), border-color var(--transition);
	}
	.choice input { grid-area: radio; margin: 2px 0 0; }
	.choice .titelklein { grid-area: title; font-weight: 600; }
	.choice .help { grid-area: hint; }
	.choice.on { border-color: var(--accent-edge); background: var(--accent-tint); }
	.choice.danger.on { border-color: var(--danger-edge); background: var(--danger-tint); }

	.gevolg {
		list-style: none;
		margin: var(--space-3) 0 0;
		padding: 0;
		display: grid;
		gap: var(--space-1h);
	}
	.gevolg li {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding-left: var(--space-4);
		position: relative;
		font-size: var(--text-sm);
	}
	/* Added or unchanged, in shape and not only in colour. */
	.gevolg li::before {
		position: absolute;
		left: 0;
		top: 0;
		font-weight: 700;
	}
	.gevolg li.erbij::before { content: '+'; color: var(--ok); }
	.gevolg li.zelfde::before { content: '='; color: var(--text-2); }
	.gevolg li.zelfde { color: var(--text-2); }

	.block {
		display: grid;
		gap: var(--space-1);
		margin-top: var(--space-3);
	}
	.block h3 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: 600;
	}
	.block.clash { border-color: var(--warn-edge); }
	.block.erase { border-color: var(--danger-edge); background: var(--danger-tint); }
	.block.erase p { margin: 0 0 var(--space-1); }
	/* At touch widths a checkbox is 44px tall (design system), so aligning to the top
	   puts the glyph a line below its own label. Centring keeps it beside the text on
	   every device. */
	.samenvoeg {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-1);
		font-size: var(--text-xs);
		cursor: pointer;
	}
	.wins { display: flex; gap: var(--space-4); margin: var(--space-1) 0; }
	.botsingen { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-1); }
	/* Comparing two values only works when they are in a column. Every row therefore
	   shares the same grid: what, mine, the file's. */
	.botsingen li {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: start;
		gap: var(--space-1) var(--space-3);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-size: var(--text-xs);
	}
	.botsingen .wat { font-weight: 500; }
	.beter { grid-column: 1 / -1; color: var(--warn); }
	.pair { display: contents; }
	.side {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
		color: var(--text-2);
	}
	/* Which side wins can be read off without re-reading the choice above: the winning
	   side is bold and carries the check, the other stays readable — they are both
	   numbers you want to be able to see. */
	.side.wins { color: var(--text-1); font-weight: 600; }
	.k { display: inline-flex; align-items: center; gap: 2px; }
	.won { display: inline-flex; color: var(--ok); }
	.pijl { display: none; }

	.actions {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}

	@media (max-width: 640px) {
		.keuzes { grid-template-columns: 1fr; }
		.botsingen li { align-items: flex-start; }
		.herkomst { grid-template-columns: 1fr; }
		.edit,
		.grid { grid-template-columns: 1fr; }
	}
</style>
