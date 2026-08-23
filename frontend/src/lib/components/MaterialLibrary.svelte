<script lang="ts">
	import { tick, untrack } from 'svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import NumberField from './NumberField.svelte';
	import Menu from './Menu.svelte';
	import StarterOffer from './StarterOffer.svelte';
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
		type Preset
	} from '$lib/library.svelte';
	import { LASER_KINDS, laserKindLabel, type LaserKind } from '$lib/machines.svelte';
	import type { DesignOperation } from '$lib/design.svelte';

	let {
		library,
		operations,
		canEdit = false,
		sheetMaterialId = null,
		sheetMaterialName = null,
		onApplied,
		onMakeGrid,
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
		onApplied?: () => void;
		/** Opens the test grid dialog for this material. */
		onMakeGrid?: (materialId: number | null) => void;
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
	let editing = $state<number | null>(null);
	let herkomst = $state<number | null>(null);
	let weghalen = $state<number | null>(null);
	let shareError = $state<string | null>(null);
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

	let chosenOperation = $derived(
		operations.find((o) => o.id === targetOperation) ?? operations[0] ?? null
	);
	let layerNumber = $derived(
		chosenOperation ? operations.findIndex((o) => o.id === chosenOperation.id) + 1 : 0
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
	 * The API turns it into a catalogue entry and produces a pre-filled proposal on
	 * GitHub; we open that, so the user sees for themselves what they are sharing.
	 */
	async function share(preset: Preset) {
		shareError = null;
		const response = await fetch(`/api/presetariat/contribution/${preset.id}`);
		if (!response.ok) {
			shareError = (await response.json().catch(() => null))?.detail ?? t('library.share.failed');
			return;
		}
		const shared = await response.json();
		window.open(shared.issue_url, '_blank', 'noopener');
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
	<svg
		class="ico"
		width="13"
		height="13"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2.2"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		{#if kind === 'check'}
			<circle cx="12" cy="12" r="9" stroke-width="1.9" />
			<path d="M8 12.4l2.6 2.6L16 9.6" />
		{:else if kind === 'alert'}
			<path d="M12 4.5L21 19.5H3z" stroke-width="1.9" stroke-linejoin="round" />
			<path d="M12 10v4" />
			<path d="M12 17h.01" />
		{:else if kind === 'down'}
			<path d="M12 4v11" />
			<path d="M7.5 10.5L12 15l4.5-4.5" />
			<path d="M5 19h14" />
		{:else}
			<path d="M4 20l4-1 10-10-3-3L5 16z" stroke-width="1.9" />
			<path d="M15 6l3 3" />
		{/if}
	</svg>
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
					class="mini quiet"
					onclick={() => {
						adding = false;
						newMaterial = '';
					}}>{t('common.cancel')}</button
				>
				<button
					class={big ? 'btn primary' : 'mini'}
					disabled={library.busy || !newMaterial.trim()}
					onclick={createMaterial}>{t('common.save')}</button
				>
			</div>
		</div>
	{:else}
		<button class={big ? 'btn primary' : 'mini add'} onclick={() => (adding = true)}>
			{label}
		</button>
	{/if}
{/snippet}

{#snippet card(preset: Preset, showMaterial: boolean)}
	{@const source = sourceLabel(preset.source)}
	{@const past = !canEdit || pastBij(preset, chosenOperation)}
	{@const off = herkomst === preset.id || editing === preset.id}
	<article
		class="preset {source.tone}"
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
							class="mismatch"
							title={t('library.mismatch.title', {
								operation: operationLabel(preset.operation).toLowerCase(),
								n: layerNumber,
								layerKind: chosenOperation?.label.toLowerCase()
							})}
						>
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 17h.01" /><path d="M10.3 3.9 2.4 18a1.8 1.8 0 0 0 1.6 2.7h16a1.8 1.8 0 0 0 1.6-2.7L13.7 3.9a1.8 1.8 0 0 0-3.4 0Z" /></svg>
						{t('library.mismatch.tag')}
					</span>
				{/if}
			</div>

			<div class="values mono">
				<span title={t('library.speed')}>{preset.speed_mm_s}<small>mm/s</small></span>
				<span title={t('library.power')}>{preset.power_percent}<small>%</small></span>
				{#if preset.passes > 1}<span title={t('library.passes')}
						>{preset.passes}<small>×</small></span
					>{/if}
				{#if preset.interval_mm && preset.operation === 'graveren-raster'}
					<span title={t('library.interval')}>{preset.interval_mm}<small>mm</small></span>
				{/if}
			</div>

			<!-- The source as one badge, with the full explanation in the tooltip and in
			     the provenance. The paragraph that spelled this out on every card was
			     useful on one card and noise on thirteen. -->
			<span class="badge {source.tone}" title="{source.means}{source.advice ? ' ' + source.advice : ''}">
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
					class="doe"
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
					class="meer"
					aria-label={t('library.more.aria')}
					aria-haspopup="menu"
					title={t('library.more.title')}
					onclick={(e) => opendMenu(e, preset)}
				>
					<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="12" cy="19" r="1.7" /></svg>
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
				<button class="mini" onclick={() => (weghalen = null)}>{t('library.drop.keep')}</button>
				<button class="mini danger" onclick={() => library.removePreset(preset.id)}>
					{t('library.drop.confirm')}
				</button>
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
									<span class="benadering">{t('library.caption.approximate')}</span>
								{/if}
							{:else}
								{t('library.caption.grid')}
							{/if}
						</p>
					{:else if preset.grid_id}
						<p class="below">{t('library.caption.noPhoto')}</p>
						{#if canEdit}
							<label class="mini file">
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
							<button class="mini" onclick={() => onMakeGrid?.(preset.material_id)}>
								{t('library.makeGrid')}
							</button>
						{/if}
					{/if}
					{#if canEdit}
						<button class="mini" onclick={() => share(preset)}>{t('library.menu.share')}</button>
					{/if}
				</div>
				{#if canEdit && preset.import_batch}
					<!-- The import this row came in on, and one press back out of it. Twenty-six
					     of the thirty-five settings in this library arrived in one such batch, for
					     a machine nobody runs, and until now not one of them could be removed
					     again. It takes the settings of that batch and the materials the batch
					     created that nothing else uses — the rest stays. -->
					<div class="batch">
						<button class="mini danger" disabled={library.busy} onclick={() => undoImport(preset.import_batch ?? '')}>
							{t('library.batch.undo')}
						</button>
						<span class="fine">{t('library.batch.undo.why')}</span>
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
				<label class="wide"
					><span>{t('library.note')}</span>
					<input
						type="text"
						value={preset.note}
						placeholder={t('library.note.placeholder')}
						onchange={(e) => saveEdit(preset, { note: e.currentTarget.value })}
					/>
				</label>
				<label class="wide"
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
			<h2>{t('import.title')}</h2>
			<p class="source">
				<span class="mono">{fileName}</span>
				{#if preview.exported_at}
					<span class="scheiding">·</span>
					{t('import.exportedAt', { when: i18n.ago(preview.exported_at) })}
				{/if}
			</p>
			<ul class="contents">
				<li>{count(preview.contains.materials, 'materials')}</li>
				<li>{count(preview.contains.presets, 'presets')}</li>
				<li>{count(preview.contains.machines, 'machines')}</li>
				<li>{count(preview.contains.test_grids, 'testGrids')}</li>
				<li class:missing={preview.contains.photos === 0}>
					{count(preview.contains.photos, 'photos')}
				</li>
			</ul>
			<!-- What it will lie next to. Without this "6 settings" are six loose
			     numbers; beside it, it is a ratio. -->
			<p class="now">
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
				<span class="hint">{t('import.merge.explain')}</span>
			</label>
			<label class="choice danger" class:on={mode === 'replace'}>
				<input type="radio" name="importmode" value="replace" bind:group={mode} />
				<span class="titelklein">{t('import.replace')}</span>
				<span class="hint">{t('import.replace.explain')}</span>
			</label>
		</div>

		{#if mode === 'merge'}
			<ul class="gevolg">
				{#if s.materials.new.length}
					<li class="erbij">
						<strong>{t('import.newMaterials', { n: s.materials.new.length })}</strong>
						<span class="fine">{s.materials.new.join(', ')}</span>
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
						<span class="fine">{t('import.withPhotos')}</span>
					</li>
				{/if}
				{#if s.machines.new.length}
					<li class="erbij">
						<strong>{t('import.addedMachines', { n: s.machines.new.length })}</strong>
						<span class="fine">{s.machines.new.join(', ')}</span>
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
				<div class="block">
					<h3>{t('import.sameBoard')}</h3>
					<p class="fine">{t('import.sameBoard.body')}</p>
					{#each voorstellen as pair (pair.name)}
						<label class="samenvoeg">
							<input
								type="checkbox"
								checked={laidOnto[pair.name] === pair.material_id}
								onchange={(e) => linkTo(pair, e.currentTarget.checked)}
							/>
							<span>
								{t('import.mergeWith', { name: pair.name, match: pair.match })}
								<span class="fine">— {pair.why}</span>
							</span>
						</label>
					{/each}
				</div>
			{/if}

			{#if s.presets.conflicts.length}
				<div class="block clash">
					<h3>{t('import.conflicts', { n: s.presets.conflicts.length })}</h3>
					<p class="fine">{t('import.conflicts.body')}</p>
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
										<span class="k">{t('import.mine')}</span>
										<span class="mono"
											>{clash.mine.speed_mm_s} mm/s · {clash.mine.power_percent}%</span
										>
									</span>
									<span class="pijl" aria-hidden="true">→</span>
									<span class="side" class:wins={clashWinner === 'file'}>
										<span class="k">{t('import.theirs')}</span>
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
			<div class="block erase">
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
				<p class="fine">
					{t('import.wipe.backup')}
					<button class="mini" onclick={() => library.exportBundle()}>
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
			<p class="error" role="alert">{library.error}</p>
		{/if}

		<div class="actions">
			<button
				class="btn primary"
				class:danger={mode === 'replace'}
				disabled={library.busy || (mode === 'replace' && !wipeConfirmed)}
				onclick={importeren}
			>
				{mode === 'replace' ? t('import.doReplace') : t('import.merge')}
			</button>
			<button class="btn" onclick={() => (preview = null)}>{t('common.cancel')}</button>
		</div>
	</section>
{:else}

{#if ready}
	<!-- What actually happened, in the same words as the preview. -->
	<div class="ready" role="status" bind:this={readyEl}>
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
			<span class="fine">{t('import.done.hidden', { machine: library.activeMachine.name })}</span>
		{/if}
		<button class="mini" onclick={() => (ready = null)}>{t('common.close')}</button>
	</div>
{/if}

<!--
	The one moment this whole part of the app exists for, at the top of the body and
	above the search bar: a machine with no settings, and the offer to fetch some that
	match the kind of laser and its tube power.

	The same component the last step of the wizard renders, reading the same function —
	where two surfaces have to know one thing, it is written once. It fetches nothing
	when it appears, so opening this window still costs what it cost.

	`door` keeps one quiet line here when there is nothing to offer — a machine with
	settings of its own, or a reader who waved the offer away. Without it the shared
	catalogue is unreachable from anywhere in the app, and that is the state every
	machine ends up in: measured on the author's library, the active laser carries three
	settings it measured itself, so the card is gone and there is no other way in.
-->
<StarterOffer door onTestGrid={() => onMakeGrid?.(null)} onChanged={() => library.load()} />

{#if canEdit && library.activeMachine && library.coverage && library.coverage.unattached > 0}
	<!-- Settings that belong to no machine show up under every machine, because the
	     query that fetches them reads `machine_id = ? OR machine_id IS NULL`. Attaching
	     them to this one says they were measured here, and only the reader knows whether
	     that is true — so this is a count and a button, never a step that runs by
	     itself. -->
	<div class="strays">
		<p>
			{t('library.strays', { n: library.coverage.unattached })}
			{#if library.coverage.unattached_grids}
				{t('library.strays.grids', { n: library.coverage.unattached_grids })}
			{/if}
		</p>
		<p class="fine">{t('library.strays.why', { machine: library.activeMachine.name })}</p>
		<button class="mini" disabled={library.busy} onclick={() => library.adoptStrays()}>
			{t('library.strays.adopt', { machine: library.activeMachine.name })}
		</button>
	</div>
{/if}

{#if undone}
	<!-- What taking an import back actually took. One press made it and one press undid
	     it, and neither of the two is silent. -->
	<div class="ready" role="status">
		<span>{t('library.batch.undone', { n: undone.presets })}</span>
		{#if undone.kept_materials.length}
			<span class="fine">{t('library.batch.kept', { n: undone.kept_materials.length })}</span>
		{/if}
		<button class="mini" onclick={() => (undone = null)}>{t('common.close')}</button>
	</div>
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
				<span class="why">{t('library.onlyMaterial.why')}</span></span
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
	{#if operations.length}
		<label class="target">
			<span>{t('library.applyTo')}</span>
			{#if operations.length > 1}
				<select bind:value={targetOperation}>
					{#each operations as op, index (op.id)}
						<option value={op.id}>{t('library.layerOption', { n: index + 1, label: op.label })}</option>
					{/each}
				</select>
			{:else}
				<strong>{t('library.layerOption', { n: 1, label: operations[0].label })}</strong>
			{/if}
		</label>
	{/if}
	</div>
</div>
{/if}

<!-- Only sensible when there is something to apply. With an empty library this
     explanation about layers sat *above* the message that there are no materials
     yet: "you have nothing" twice, in the wrong order, and the answer to a question
     you had not asked yet. -->
{#if canEdit && operations.length === 0 && library.materials.length > 0}
	<!-- Say once why "Apply" cannot work, not on every card again. -->
	<p class="notice">{t('library.noLayer')}</p>
{/if}

{#if shareError}
	<p class="error" role="alert">{shareError}</p>
{/if}
{#if library.error}
	<p class="error" role="alert">{library.error}</p>
{/if}

{#if library.materials.length === 0}
	<!-- An empty library used to be one grey paragraph at the bottom of a window
	     full of filters with nothing to filter. This is the first thing a new user
	     sees here, so it takes the shape of an invitation: what this is, why it is
	     worth it, and the two ways in. -->
	<div class="welcome">
		<h2>{t('library.welcome.title')}</h2>
		<p>{t('library.welcome.body')}</p>
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
				<p class="fine">{t('library.welcome.presetariat')}</p>
			{/if}
		</div>
	</div>
{:else if groepen.length === 0}
	<!-- Nothing found is not a dead end as long as you can throw the search away
	     without having to look for the field. -->
	<div class="welcome narrow">
		<h2>{t('library.nothingFound', { query })}</h2>
		<p>{t('library.nothingFound.body', { materials: count(library.materials.length, 'materials') })}</p>
		<button class="btn" onclick={() => (query = '')}>{t('library.clearSearch')}</button>
	</div>
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
							class="matrij"
							class:on={materialId === null && !query.trim()}
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
							class="matrij"
							class:on={materialId === group.materialId}
							onclick={() => (materialId = group.materialId)}
							oncontextmenu={(e) => openMaterialMenu(e, group)}
						>
							<span class="matname">{group.name}</span>
							{#if group.materialId === sheetMaterialId}
								<!-- What is in the machine is the reason you are here; that belongs in
								     the list and not only in a filter checkbox. -->
								<span class="ligt" title={t('library.onSheet.title')}>{t('library.onSheet')}</span>
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
								class="meer"
								aria-label={t('library.material.more.aria', { material: group.name })}
								aria-haspopup="menu"
								title={t('library.more.title')}
								onclick={(e) => openMaterialMenu(e, group)}
							>
								<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="12" cy="19" r="1.7" /></svg>
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
					<h2 class="head">{t('library.recent')}</h2>
					{#each recent as preset (preset.id)}
						{@render card(preset, true)}
					{/each}
					<p class="fine">{t('library.pickMaterial')}</p>
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
						<h2 class="head">{group.name}</h2>
						{#if canEdit}
							<button class="mini" onclick={() => onMakeGrid?.(group.materialId)}>
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
							class="vraag"
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
							<label class="veld">
								<span>{t('library.material.name')}</span>
								<input
									type="text"
									bind:value={renameTo}
									onkeydown={(e) => e.key === 'Enter' && saveRename()}
								/>
							</label>
							<label class="veld">
								<span>{t('library.material.synonyms')}</span>
								<input
									type="text"
									bind:value={alsoCalled}
									placeholder={t('library.material.synonyms.placeholder')}
								/>
							</label>
							<p class="fine">{t('library.material.synonyms.why')}</p>
							<div class="knoppen">
								<button class="mini quiet" onclick={() => (renaming = null)}>
									{t('common.cancel')}
								</button>
								<button
									class="mini"
									disabled={library.busy || !renameTo.trim()}
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
							class="vraag"
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
							<label class="veld">
								<span>{t('library.material.merge.pick')}</span>
								<select bind:value={mergeInto}>
									<option value={null}>{t('library.material.merge.choose')}</option>
									{#each library.materials.filter((m) => m.id !== group.materialId) as other (other.id)}
										<option value={other.id}>{other.name}</option>
									{/each}
								</select>
							</label>
							<div class="knoppen">
								<button class="mini quiet" onclick={() => (merging = null)}>
									{t('common.cancel')}
								</button>
								<button
									class="mini"
									disabled={library.busy || mergeInto === null}
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
							class="vraag weg"
							role="alert"
							bind:this={askEl}
							onkeydown={(e) => {
								if (e.key !== 'Escape') return;
								e.stopPropagation();
								closeQuestion();
							}}
						>
							{#if !usage}
								<p>{t('common.busy')}</p>
							{:else if wouldGoWith(usage).length}
								<p>
									{t('library.material.remove.carries', {
										material: group.name,
										what: i18n.list(wouldGoWith(usage))
									})}
								</p>
							{:else}
								<p>{t('library.material.remove.empty', { material: group.name })}</p>
							{/if}
							{#if usage?.sheets}
								<p class="fine">{t('library.material.remove.sheet', { n: usage.sheets })}</p>
							{/if}
							<div class="knoppen">
								<button
									class="mini quiet"
									onclick={() => {
										removing = null;
										usage = null;
									}}>{t('library.material.remove.keep')}</button
								>
								<button class="mini danger" disabled={library.busy || !usage} onclick={doRemove}>
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
							<button class="chip" class:on={thickness === null} onclick={() => (thickness = null)}>
								{t('library.allThicknesses')}
							</button>
							{#each thicknesses as d (d)}
								<button class="chip" class:on={thickness === d} onclick={() => (thickness = d)}>
									{d === null ? t('library.noThickness') : `${d} mm`}
								</button>
							{/each}
						</div>
					{/if}

					{#if zichtbarePresets.length === 0}
						<p class="empty">
							{#if group.presets.length === 0}
								{t('library.noPresets', { material: group.name })}
							{:else}
								{t('library.noneForThickness', { thickness: thickness })}
							{/if}
						</p>
						{#if canEdit}
							<button class="btn primary" onclick={() => onMakeGrid?.(group.materialId)}>
								{t('library.makeGrid')}
							</button>
						{/if}
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
					<p class="empty">
						{chosen
							? t('library.filteredOut', { material: chosen.name, query })
							: t('library.pickMaterial')}
					</p>
					<button class="btn" onclick={() => (query = '')}>{t('library.clearSearch')}</button>
				{/if}
			{/if}
		</div>
	</div>
{/if}

{#if canEdit && library.materials.length}
	<details class="vouw">
		<summary>{t('library.manual')}</summary>
		<div class="grid">
			<label class="wide">
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
			<label>
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
		<p class="fine">{t('library.manual.note')}</p>
		<button
			class="btn"
			disabled={library.busy ||
				!draft.speed_mm_s ||
				!draft.power_percent ||
				(draft.material_id ?? materialId) === null}
			onclick={createPreset}
		>
			{t('common.save')}
		</button>
	</details>

	<details class="vouw">
		<summary>{t('library.profiles', { n: library.machines.length })}</summary>
		<p class="fine">{t('library.profiles.why')}</p>
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
									<span class="mark" title={t('library.profile.noDevice.title')}>
										{t('library.profile.noDevice')}
									</span>
								{:else}
									<span class="mark" title={t('library.profile.deviceGone.title')}>
										{t('library.profile.deviceGone')}
									</span>
								{/if}
							{/if}
							{#if !empty}
								<!-- What hangs off it, because that decides whether it can go: a profile
								     with settings or grids is evidence, a profile without is clutter.
								     Only naming what is there — "0 settings" next to a profile that
								     does carry a test grid is a half truth. -->
								<span class="fine">{evidence(machine)}</span>
							{:else if canEdit && !active}
								<button
									class="mini"
									disabled={library.busy}
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
									class="mini"
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
							<fieldset class="laser">
								<legend>{t('setup.laser')}</legend>
								<div class="paar">
									<label class="veld">
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
								<p class="fine">{t('setup.laser.watt.why')}</p>
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
<section class="uitwissel">
	<h3>{t('library.exchange')}</h3>
	<p class="fine">{t('library.exchange.body')}</p>
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
</section>
{/if}

{#if rowMenu}
	<Menu menu={rowMenu.list} x={rowMenu.x} y={rowMenu.y} onClose={() => (rowMenu = null)} />
{/if}

<style>
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
	/* *Why* this filter is on, in the toggle itself: otherwise it looks like a
	   preference somebody once switched on. */
	.why { color: var(--text-2); }
	.head {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: var(--space-4) 0 var(--space-2);
	}
	.empty { color: var(--text-2); margin: 0 0 var(--space-2); }
	/* An empty state may take up room: here it *is* the screen, not a footnote
	   under it. */
	.welcome {
		padding: var(--space-6) 0 var(--space-4);
		max-width: 46ch;
	}
	.welcome.narrow { padding: var(--space-5) 0; }
	.welcome h2 {
		font-size: var(--text-md);
		font-weight: 600;
		margin: 0 0 var(--space-2);
		color: var(--text-1);
	}
	.welcome p { margin: 0 0 var(--space-3); color: var(--text-2); }
	.wegen { display: grid; justify-items: start; gap: var(--space-3); }
	.wegen .fine { margin: 0; max-width: 42ch; }
	.fine { color: var(--text-2); font-size: var(--text-xs); margin: 0 0 var(--space-2); }
	.mini {
		font-size: var(--text-xs);
		color: var(--accent);
		padding: 4px var(--space-1h);
		border-radius: var(--radius-field);
	}
	.mini:hover { background: var(--surface-2); }
	.mini.quiet { color: var(--text-2); }
	.mini.danger { color: var(--danger); font-weight: 600; }
	.row { display: flex; gap: var(--space-2); margin: var(--space-2) 0; }
	.row input { flex: 1; min-width: 0; }
	input,
	select {
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.btn {
		padding: 8px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		white-space: nowrap;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}

	/* Material as image — but once per material. The same wood band ten times over is
	   wallpaper; one band above the group is identity. */
	/* Grain: two layers of stripes at a slight angle, on a warm ground. */
	/* Acrylic: smooth, with one diagonal highlight. */
	/* Leer: onregelmatige korrel off gestapelde radiale vlekken. */
	/* Cardboard: corrugated profile, seen from the side. */
	/* Metal: brushed, with a running highlight. */

	/* ── The diptych ─────────────────────────────────────────────────────────
	   On the left what you have, on the right what belongs with it. The left column is
	   fixed: it must not move as soon as you point at a material with a long name,
	   because then the list slides out from under your cursor. */
	.tweeluik {
		display: grid;
		grid-template-columns: 232px minmax(0, 1fr);
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
	.matrij {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: 7px var(--space-2);
		border: none;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-1);
		text-align: left;
		font: inherit;
		font-size: var(--text-sm);
	}
	.matrij:hover { background: var(--surface-2); }
	.matrij.on {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		font-weight: 500;
	}
	.matname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* The row and its ⋯ side by side: the menu button is a sibling of the row button and
	   not a child, because a button inside a button is not a button. */
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
	.mini.add { align-self: start; margin-top: var(--space-2); }
	/* A question about one material, in the pane that carries that material's name. The
	   left-hand row is 232 px wide, so it cannot stand there, and a window over a window
	   would hide the list the answer changes. */
	.vraag {
		display: grid;
		gap: var(--space-2);
		margin: 0 0 var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-left: 3px solid var(--accent);
		border-radius: var(--radius-card);
		background: var(--surface-2);
		font-size: var(--text-sm);
	}
	.vraag.weg { border-left-color: var(--danger); }
	.vraag p { margin: 0; }
	/* One field on a line keeps the width of half a line (v4, form rule 5), and its
	   label stands above it (rule 3). */
	.veld { display: grid; gap: 4px; max-width: 32ch; }
	.veld > span { font-size: var(--text-xs); color: var(--text-2); }
	/* A pair is one statement about one thing and stays on one line (rule 2). */
	.paar {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3);
		align-items: end;
	}
	.paar .veld { max-width: none; }
	/* Buttons at the foot, the one that acts on the right (rule 6). */
	.knoppen {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	/* A question is answered with buttons, not with words.
	   `.mini` is the borderless style of a row action — Apply, Make a test grid — and
	   these three blocks borrowed it, so the last step before four settings and their
	   photographs are gone read as two grey words in a corner. Every other question in
	   the app (the sheet question in setup, the offer card above) answers with a bordered
	   button, and this is a heavier question than either. */
	.vraag .knoppen button {
		min-height: 32px;
		padding: 6px 12px;
		border: 1px solid var(--line);
		background: var(--surface-1);
	}
	.vraag .knoppen button:hover {
		background: var(--surface-2);
	}
	.vraag .knoppen button.danger {
		border-color: color-mix(in srgb, var(--danger) 45%, transparent);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
	}
	/* With a glove on, 32 px is too little, and this window is on the tablet too. */
	@media (max-width: 1199px), (pointer: coarse) {
		.vraag .knoppen button {
			min-height: 44px;
		}
	}
	/* Settings that hang off no machine: a count, a reason and one button. */
	.strays {
		display: grid;
		justify-items: start;
		gap: var(--space-1h);
		margin: 0 0 var(--space-4);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--line);
		border-left: 3px solid var(--warn);
		border-radius: var(--radius-card);
		background: var(--surface-2);
		font-size: var(--text-sm);
	}
	.strays p { margin: 0; }
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
	.batch .fine { margin: 0; flex: 1; min-width: 14em; }
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
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.laser legend { padding: 0 4px; font-size: var(--text-xs); color: var(--text-2); }
	.laser .fine { margin: 0; max-width: 68ch; }
	.halve { max-width: calc(50% - var(--space-2)); }
	.mataantal { flex: none; font-size: var(--text-xs); color: var(--text-2); }
	.matrij.on .mataantal { color: inherit; }
	/* What is in the machine: one word, not a second colour. */
	.ligt {
		flex: none;
		font-size: 10px;
		letter-spacing: 0.03em;
		padding: 1px 5px;
		border-radius: var(--radius-dot);
		border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line));
		color: var(--accent);
		white-space: nowrap;
	}
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
	.chip {
		padding: 3px 10px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface-1);
		color: var(--text-2);
		font: inherit;
		font-size: var(--text-xs);
	}
	.chip:hover { background: var(--surface-2); color: var(--text-1); }
	.chip.on {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		font-weight: 500;
	}

	/* ── Eén instelling = één row ──────────────────────────────────────── */
	.preset {
		position: relative;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		margin-top: 4px;
		padding: 0 var(--space-2) 0 calc(var(--space-2) + 4px);
	}
	.preset:first-of-type { margin-top: 0; }
	/* The source is in the border too: while scrolling you see on the left which
	   settings are measured and which are guessed. */
	.preset::before {
		content: '';
		position: absolute;
		left: 0;
		top: -1px;
		bottom: -1px;
		width: 4px;
		border-radius: var(--radius-field) 0 0 var(--radius-field);
		background: var(--line);
	}
	.preset.ok::before { background: var(--ok); }
	.preset.warn::before { background: var(--warn-solid); }
	.preset.open {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
		box-shadow: var(--lift-1);
	}

	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 40px;
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
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-sm);
	}
	.operation .mat { font-weight: 500; }
	.values {
		flex: none;
		display: flex;
		gap: var(--space-3);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
	}
	.values span { min-width: 4.2em; text-align: right; }
	.values small { color: var(--text-2); margin-left: 1px; }

	.badge {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 3px;
		/* A floor and not a fixed width: the four badges line up under each other in
		   every language that fits, and the one that does not fit grows instead of
		   spilling over its neighbour. Measured in Dutch: "Geverifieerd" needed 3 px
		   more than 7.6em and "Geëxtrapoleerd" is two letters longer again, and
		   `white-space: nowrap` with a hard width puts those letters on the row beside
		   it. Alignment is worth a fixed width; a word that reads wrong is not. */
		min-width: 7.6em;
		font-size: var(--text-xs);
		font-weight: 600;
		padding: 1px 6px;
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
		white-space: nowrap;
	}
	.badge.ok {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-color: color-mix(in srgb, var(--ok) 40%, transparent);
		color: var(--ok);
	}
	.badge.warn {
		background: color-mix(in srgb, var(--warn) 16%, transparent);
		border-color: color-mix(in srgb, var(--warn) 45%, transparent);
		color: var(--warn);
	}
	.ico { flex: none; }

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

	.doe {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 5px 12px;
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		background: var(--accent);
		color: var(--accent-ink);
		font: inherit;
		font-size: var(--text-xs);
		font-weight: 500;
	}
	.doe:disabled { opacity: 0.4; cursor: not-allowed; }
	/* A setting for a different kind of operation may be applied, but not without you
	   knowing. One sign beside the operation, with the whole explanation in the
	   tooltip. */
	.mismatch {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		margin-left: 4px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--warn);
		white-space: nowrap;
	}
	.meer {
		flex: none;
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border: none;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-2);
	}
	.meer:hover { background: var(--surface-2); color: var(--text-1); }

	.zekerweg {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		padding: var(--space-2) 0 var(--space-2);
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
	}
	.zekerweg span { flex: 1; min-width: 12em; }

	.stretch { flex: 1; min-width: var(--space-6); }
	.zeker { font-size: var(--text-xs); color: var(--text-2); }

	.herkomst {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-3);
		margin-top: var(--space-2);
		padding-top: var(--space-2);
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
	.benadering { display: block; margin-top: 2px; color: var(--warn); }
	.bewijsvak {
		display: grid;
		justify-items: start;
		gap: 4px;
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
		padding-top: var(--space-2);
		border-top: 1px dashed var(--line);
	}
	.edit label { display: grid; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.edit label.wide { grid-column: 1 / -1; }
	.edit input,
	.edit select { width: 100%; }

	.vouw {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.vouw summary {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		cursor: pointer;
		margin-bottom: var(--space-2);
	}
	.profiles { list-style: none; margin: var(--space-2) 0; padding: 0; }
	/* A block and no longer a flex row: the machine you are working on carries the two
	   fields that describe it underneath its own line. */
	.profiles li {
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		margin-bottom: 4px;
		font-size: var(--text-xs);
	}
	/* The name pushes the rest to the right; that way the power and the badge line up,
	   even when one profile has a badge and the other does not. */
	.profielrij > .profielnaam { flex: 1; min-width: 0; }
	/* Orphaned is not an error but is worth knowing: muted, not red. */
	.profiles li.orphan { border-style: dashed; }
	.profiles li.orphan .profielnaam { color: var(--text-2); }
	.profiles .mark {
		flex: none;
		padding: 2px 8px;
		border-radius: var(--radius-pill, 999px);
		background: var(--surface-2);
		color: var(--text-2);
		white-space: nowrap;
	}
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.grid label { display: grid; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.grid label.wide { grid-column: 1 / -1; }
	.grid input,
	.grid select { width: 100%; }
	.hint {
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
	}
	.notice {
		margin: var(--space-2) 0 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--text-xs);
	}
	.error {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}

	/* ------------------------------------------- uitwisselen (besluit B7) */

	.uitwissel {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.uitwissel h3 {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.uitwissel .fine { max-width: 52ch; }
	.uitknoppen { display: flex; gap: var(--space-2); flex-wrap: wrap; }

	/* The preview is a screen of its own, not a strip below the list: this is where
	   the decision falls, so it gets the room and the reading width for it. */
	.wisselkop { margin-bottom: var(--space-4); }
	.wisselkop h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0;
		color: var(--text-1);
	}
	.source { margin: 4px 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); }
	.scheiding { opacity: 0.5; }
	.contents {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1h);
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.contents li {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
	}
	/* Zero photos is not a detail: then the evidence does not come along. */
	.contents li.missing { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
	.now { margin: var(--space-2) 0 0; font-size: var(--text-xs); color: var(--text-2); }

	.keuzes {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
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
	}
	.choice input { grid-area: radio; margin: 2px 0 0; }
	.choice .titelklein { grid-area: title; font-weight: 600; }
	.choice .hint { grid-area: hint; font-size: var(--text-xs); color: var(--text-2); }
	.choice.on { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
	.choice.danger.on {
		border-color: var(--danger);
		box-shadow: inset 0 0 0 1px var(--danger);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
	}

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
	.gevolg .fine { margin: 0; }

	.block {
		margin-top: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.block h3 {
		margin: 0 0 4px;
		font-size: var(--text-sm);
		font-weight: 600;
	}
	.block.clash { border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
	.block.erase {
		border-color: color-mix(in srgb, var(--danger) 50%, transparent);
		background: color-mix(in srgb, var(--danger) 9%, transparent);
	}
	.block.erase p { margin: 0 0 var(--space-2); }
	/* At touch widths a checkbox is 44px tall (design system), so aligning to the top
	   puts the glyph a line below its own label. Centring keeps it beside the text on
	   every device. */
	.samenvoeg {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		cursor: pointer;
	}
	.wins { display: flex; gap: var(--space-4); margin: var(--space-2) 0; }
	.botsingen { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
	/* Comparing two values only works when they are in a column. Every row therefore
	   shares the same grid: what, mine, the file's. */
	.botsingen li {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: start;
		gap: 4px var(--space-3);
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
	   side is bold and marked, the other stays readable — they are both numbers you
	   want to be able to see. */
	.side.wins { color: var(--text-1); font-weight: 600; }
	.side.wins .k::after {
		content: ' ✓';
		color: var(--ok);
	}
	.side .k {
		font-size: var(--text-xs);
		color: var(--text-2);
		font-weight: 400;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.pijl { display: none; }

	.actions {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.btn.danger {
		background: var(--danger);
		border-color: var(--danger);
		color: var(--on-color);
	}
	.ready {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		border: 1px solid color-mix(in srgb, var(--ok) 45%, transparent);
		background: color-mix(in srgb, var(--ok) 12%, transparent);
		font-size: var(--text-xs);
	}
	.ready .mini { margin-left: auto; }

	@media (max-width: 640px) {
		.keuzes { grid-template-columns: 1fr; }
		.botsingen li { align-items: flex-start; }
		.herkomst { grid-template-columns: 1fr; }
		.edit,
		.grid { grid-template-columns: 1fr; }
	}
</style>
