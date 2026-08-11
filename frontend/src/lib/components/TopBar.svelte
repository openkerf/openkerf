<script lang="ts">
	import { STATE_LABEL, type Device, type MachineState } from '$lib/api';
	import Logo from './Logo.svelte';

	let {
		device,
		state: machineState,
		canStart,
		canStop,
		canEdit = false,
		onStart,
		onStop,
		onOpenFile,
		onOpenProject,
		onToggleTheme
	}: {
		device: Device | null;
		state: MachineState;
		canStart: boolean;
		canStop: boolean;
		canEdit?: boolean;
		onStart: () => void;
		onStop: () => void;
		onOpenFile?: (file: File) => void;
		onOpenProject?: (file: File) => void;
		onToggleTheme: () => void;
	} = $props();

	// Tijdens het slepen leest `box` de voorvertoning, dus de velden lopen mee.
	// Ze zijn dan niet te bewerken: je bent al aan het slepen.
</script>

<header class="topbar">
	<div class="brand" title="OpenKerf"><Logo />OpenKerf</div>

	<!-- Machine-eerst: de gebruiker weet altijd of de laser "er is". Klikken
	     leidt naar de setup — ook de route als er nog géén machine is. -->
	<a class="machine" href="/setup" title="Machine kiezen of instellen">
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span>{device?.label ?? 'Machine instellen'}</span>
		<span class="muted">{STATE_LABEL[machineState]}</span>
	</a>

	<div class="spacer"></div>

	<!-- Openen hoort naast opslaan: in de Job-tab vindt niemand het. -->
	<label class="btn file" title="Ontwerp openen">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 17v-5m0 0-2 2m2-2 2 2"/></svg>
		<span class="btn-label">Openen</span>
		<input
			type="file"
			aria-label="Bestand kiezen"
			accept=".svg,.dxf,.rd,.egv,.gcode,.nc,.lbrn,.lbrn2,.ezd,.xcs,.png,.jpg,.jpeg,.gif,.bmp"
			onchange={(e) => {
				const input = e.currentTarget as HTMLInputElement;
				const file = input.files?.[0];
				input.value = '';
				if (file) onOpenFile?.(file);
			}}
		/>
	</label>

	<label class="btn file" title="Project openen (ontwerp + bibliotheek)">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 18v-5m0 0-2 2m2-2 2 2"/></svg>
		<span class="btn-label">Project</span>
		<input
			type="file"
			aria-label="Bestand kiezen"
			accept=".openkerf,.zip"
			onchange={(e) => {
				const input = e.currentTarget as HTMLInputElement;
				const file = input.files?.[0];
				input.value = '';
				if (file) onOpenProject?.(file);
			}}
		/>
	</label>
	<a class="btn" href="/api/project/export.openkerf" download="project.openkerf" title="Project opslaan">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 13v5m0 0-2-2m2 2 2-2"/></svg>
		<span class="btn-label">Project opslaan</span>
	</a>

	<!-- Opslaan als SVG: MeerK40t's eigen schrijver, dus operaties komen bij
	     terugladen weer mee. -->
	<a class="btn" href="/api/design/export.svg" download="ontwerp.svg" title="Ontwerp opslaan">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11l3 3v13H5z"/><path d="M12 9v6m0 0-2.5-2.5M12 15l2.5-2.5"/></svg>
		<span class="btn-label">Opslaan</span>
	</a>

	<!-- Kader tonen beweegt de kop: dat is fase 3, niet fase 2. -->
	<button class="btn" disabled title="Beschikbaar in fase 3">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="4 3"/></svg>
		<span class="btn-label">Kader tonen</span>
	</button>
	<!-- Stoppen kan altijd, overal, in één tik. -->
	<button class="btn danger" disabled={!canStop} onclick={onStop} title="Job direct afbreken">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
		<span class="btn-label blijft">Stop</span>
	</button>
	<!-- Opent geen dialoog maar de pre-flight in het rechterpaneel. -->
	<button class="btn primary" disabled={!canStart} onclick={onStart}>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
		Start job
	</button>
	<button class="iconbtn" onclick={onToggleTheme} title="Thema wisselen" aria-label="Thema wisselen">
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
	</button>
</header>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		/* Zonder deze twee duwt de knoppenrij de héle pagina breder dan het
		   scherm — op een tablet scroll je dan horizontaal langs je eigen app. */
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.topbar::-webkit-scrollbar { display: none; }

	/* Smal scherm: knoppen tonen alleen hun icoon. De titel staat in de
	   tooltip en het aria-label, dus er gaat geen betekenis verloren.
	   De grens ligt op 1200px, niet op 900: op een tablet van 1024 breken de
	   labels anders over twee regels en groeit de balk mee. */
	@media (max-width: 1199px) {
		/* De twee knoppen die de machine aansturen houden hun woord: een rood
		   vierkantje zonder tekst is geen noodstop. */
		.topbar :global(.btn-label:not(.blijft)) { display: none; }
		.machine .muted { display: none; }
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
		letter-spacing: -0.01em;
	}
	.machine {
		white-space: nowrap;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 8px 8px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: inherit;
		text-decoration: none;
		transition: background var(--transition);
	}
	.machine:hover {
		background: var(--line);
	}
	.muted {
		color: var(--text-2);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		flex: none;
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }
	.spacer { flex: 1; }
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		transition: background var(--transition);
	}
	.btn { text-decoration: none; color: inherit; }
	.btn.file { cursor: pointer; }
	.btn.file input { display: none; }
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.primary:hover:not(:disabled) { background: var(--accent); filter: brightness(1.06); }
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
	}
	.btn.danger:hover:not(:disabled) { background: var(--danger-solid); filter: brightness(1.06); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.iconbtn {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		transition: background var(--transition);
	}
	.iconbtn:hover { background: var(--surface-2); color: var(--text-1); }
</style>
