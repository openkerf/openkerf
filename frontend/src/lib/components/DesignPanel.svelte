<!--
  De Bewerken-tab uit de mockup. De materialenbibliotheek (fase 4) en het
  lagenmodel (fase 3) bestaan nog niet in de API, dus dit is bewust
  voorbeelddata — expliciet gelabeld zodat niemand het voor live aanziet.
-->
<div class="section">
	<p class="notice">
		<strong>Voorbeeld</strong> — materiaal en lagen komen in fase 3 en 4 uit de API.
	</p>
</div>

<div class="section">
	<h2 class="section-title">Materiaal</h2>
	<div class="matcard">
		<div class="matcard-head">
			<div class="thumb" aria-hidden="true">
				{#each ['#D9B98A', '#C9A167', '#B08347', '#8C5E2A', '#CFAE76', '#BC9153', '#9A6D33', '#71481F', '#C29B5F', '#A97E41', '#835626', '#5A3617', '#B58B4E', '#966B35', '#6E441D', '#432610'] as cell (cell)}
					<i style="background: {cell}"></i>
				{/each}
			</div>
			<div class="mat-text">
				<div class="mat-name">Multiplex berken</div>
				<div class="mat-sub mono">3.0 mm · snijden</div>
			</div>
			<span class="badge"><span class="bdot"></span>12×</span>
		</div>
		<div class="matcard-params">
			<div class="param"><div class="k">Snelheid</div><div class="v mono">12 <small>mm/s</small></div></div>
			<div class="param"><div class="k">Vermogen</div><div class="v mono">65 <small>%</small></div></div>
			<div class="param"><div class="k">Passes</div><div class="v mono">1</div></div>
		</div>
		<div class="matcard-foot">
			<span>Geverifieerd · 12 bevestigingen</span>
		</div>
	</div>
</div>

<div class="section">
	<h2 class="section-title">Lagen</h2>
	{#each [{ n: 1, color: '#E5484D', op: 'Snijden', obj: 'Omtrek + gaten', speed: '12', power: '65%', ink: '#fff' }, { n: 2, color: '#F76B15', op: 'Graveren · raster', obj: 'Tekst "Stellendam"', speed: '300', power: '18%', ink: '#fff' }, { n: 3, color: '#FFC53D', op: 'Graveren · vector', obj: 'Kompas-ornament', speed: '80', power: '22%', ink: '#5A4300' }] as layer (layer.n)}
		<div class="layer">
			<span class="chip mono" style="background: {layer.color}; color: {layer.ink}">{layer.n}</span>
			<div class="layer-name">
				<div class="op">{layer.op}</div>
				<div class="obj">{layer.obj}</div>
			</div>
			<div class="layer-vals">
				<span class="pill mono">{layer.speed}</span>
				<span class="pill mono">{layer.power}</span>
			</div>
		</div>
	{/each}
</div>

<style>
	.section + .section { margin-top: var(--space-6); }
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.notice {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn) 12%, transparent);
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.matcard {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		overflow: hidden;
	}
	.matcard-head {
		display: flex;
		gap: 10px;
		padding: 10px;
		align-items: center;
	}
	.thumb {
		width: 44px;
		height: 44px;
		flex: none;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		grid-template-rows: repeat(4, 1fr);
		gap: 1px;
		padding: 3px;
	}
	.thumb i { border-radius: 1px; }
	.mat-text { flex: 1; min-width: 0; }
	.mat-name { font-weight: 600; }
	.mat-sub { color: var(--text-2); font-size: 12px; }
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: var(--text-xs);
		font-weight: 500;
		padding: 2px 8px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--ok) 12%, transparent);
		color: var(--ok);
	}
	.bdot {
		width: 6px;
		height: 6px;
		border-radius: var(--radius-dot);
		background: currentColor;
	}
	.matcard-params {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		border-top: 1px solid var(--line);
	}
	.param { padding: 8px 10px; }
	.param + .param { border-left: 1px solid var(--line); }
	.param .k {
		font-size: 10px;
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.param .v { font-size: 14px; margin-top: 1px; }
	.param .v small { font-size: 10px; color: var(--text-2); }
	.matcard-foot {
		border-top: 1px solid var(--line);
		padding: 7px 10px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.layer {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 7px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.layer + .layer { margin-top: 6px; }
	.chip {
		width: 20px;
		height: 20px;
		flex: none;
		border-radius: 4px;
		display: grid;
		place-items: center;
		font-size: 10px;
		font-weight: 500;
	}
	.layer-name { flex: 1; min-width: 0; }
	.layer-name .op { font-weight: 500; }
	.layer-name .obj { font-size: var(--text-xs); color: var(--text-2); }
	.layer-vals { display: flex; gap: var(--space-1); }
	.pill {
		font-size: var(--text-xs);
		padding: 3px 7px;
		border-radius: 4px;
		background: var(--surface-2);
	}
</style>
