/**
 * The Job tab says its state in values, and stays quiet about what is off.
 *
 * Run: `node --test frontend/tests/job-quiet.test.ts` for the source checks;
 * `OK_BASE=http://127.0.0.1:8122 node --test frontend/tests/job-quiet.test.ts` adds the
 * measurement in a browser. The browser part skips itself without a reachable server
 * (`OK_REQUIRE_SERVER=1` turns that into a failure). Nothing is pressed that burns: the
 * panel is read as it opens.
 *
 * Why it exists. Measured at 1440 x 900 with `gauntlet/seed.mjs` on the bed: the Job tab
 * held 1 156 characters over 69 text nodes in a column of 1 559 px, against 267 in Layers
 * and 93 in Edit. Of those characters, 320 explained things that were *off* or *shut*:
 * 95 under a closed "Messages from the machine" fold saying what it would contain, 171
 * describing print-and-cut while its only button was dead, 54 saying the zero point was
 * not set. The reason the dead button gave — "Select exactly two shapes on the canvas
 * first" — existed only as a `title`, and a touch screen has no hover. And the estimate
 * stood twice, 400 px apart: a labelled row at the top and the same minutes on the start
 * button at the foot.
 *
 * Three of the six places the pattern named live in states this app cannot reach on
 * loopback without starting a job, which is the one thing that must never happen to
 * measure something. Those are read out of the source instead, the way
 * `notice-cards.test.ts` reads the offsets it cannot stage.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const here = dirname(fileURLToPath(import.meta.url));
const components = join(here, '..', 'src', 'lib', 'components');
const read = (file: string) => readFileSync(join(components, file), 'utf8');

/** A component with its comments taken out: a rule may not be proved by a comment. */
const code = (file: string) =>
	read(file)
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\/\*[\s\S]*?\*\//g, '');

// ─── Read out of the source: states a running job would be needed for ────────

test('the closed messages fold says nothing but its own title', () => {
	const source = code('JobPanel.svelte');
	const at = source.indexOf(`t('queue.messages.hint')`);
	assert.notEqual(at, -1, 'JobPanel no longer says what the messages are');
	// Nothing at all is rendered while the fold is shut, and the hint stands inside the
	// fold rather than under its shut title. Since P19 the fold is a `details` — the one
	// fold this app draws — so what used to be `{#if showEvents}` is now the element
	// itself: everything after the `</summary>` is what opening shows.
	assert.ok(
		!/\{#if !showEvents\}/.test(source),
		'there is a branch again for what the shut fold says — a shut fold says its title'
	);
	const open = source.indexOf('bind:open={showEvents}');
	assert.notEqual(open, -1, 'the messages fold is no longer a fold that knows whether it is open');
	const summaryEnds = source.indexOf('</summary>', open);
	assert.notEqual(summaryEnds, -1, 'the messages fold has no summary');
	assert.ok(at > summaryEnds, 'the hint stands outside the fold, where a shut fold would say it');
	assert.ok(
		at < source.indexOf('</details>', summaryEnds),
		'the hint stands after the fold closes'
	);
});

test('a job waiting its turn shows no bar and no counters about not having started', () => {
	const source = code('JobPanel.svelte');
	// The rule has one name in this file; the guards read it rather than spelling it out.
	assert.ok(
		/\{@const live = job\.running \|\| quiet\}/.test(source),
		'`live` — running, or the one job that can stall — is no longer named once in JobPanel'
	);
	for (const marker of ['class="progress"', 'class="figures mono"', 'class="meta mono"']) {
		const at = source.indexOf(marker);
		assert.notEqual(at, -1, `JobPanel no longer has ${marker}`);
		const guard = source.lastIndexOf('{#if', at);
		const condition = source.slice(guard, source.indexOf('}', guard));
		assert.ok(
			/\blive\b|job\.running/.test(condition),
			`${marker} stands under \`${condition.trim()}\` — a waiting job has no progress to show`
		);
	}
});

test('the keys are on the buttons they work, not in a paragraph under them', () => {
	const source = code('JobControls.svelte');
	const uses = [...source.matchAll(/t\('job\.keysHere'\)/g)].length;
	assert.ok(uses >= 2, `the keys sentence is on ${uses} button(s); pause and stop both need it`);
	// The paragraph came back, but only where a tooltip cannot be read: at
	// `screen.noHover` a title has no route at all, and the part of this sentence that
	// only it can carry — the keys stop working outside this window — is the part you
	// discover at the wrong moment. On a desk it stays off the screen.
	const paragraph = /\{#if screen\.noHover\}\s*<p class="toetsen">/.test(source);
	assert.ok(
		paragraph,
		'the key advice is a tooltip at every width, and a touch screen cannot open one'
	);
	assert.equal(
		/class="toetsen"/.test(source.replace(/\{#if screen\.noHover\}[\s\S]{0,120}?\{\/if\}/g, '')),
		false,
		'the paragraph of key advice stands under the transport buttons at every width'
	);
	// Both tooltips carry it, and each on its own line: a title with a newline is two
	// lines in every browser this app runs in.
	for (const key of ['job.pause.keepGoing', 'job.pause.stopHead', 'job.stop.now']) {
		const at = source.indexOf(key);
		assert.notEqual(at, -1, `${key} is gone from the transport buttons`);
		const rest = source.slice(at, at + 220);
		assert.ok(/job\.keysHere/.test(rest), `the tooltip at ${key} does not carry the keys sentence`);
	}
});

test('the reason a dead button gives is on the screen where there is no hover', () => {
	const source = code('JobControls.svelte');
	const at = source.indexOf(`t('job.printcut.needsTwo')`);
	assert.notEqual(at, -1, 'print and cut no longer says why its button is dead');
	const rendered = [...source.matchAll(/\{t\('job\.printcut\.needsTwo'\)\}/g)].length;
	assert.ok(rendered >= 1, 'the reason is only a title again — a touch screen has no hover');
	assert.ok(
		/screen\.noHover/.test(source),
		'the visible reason is not tied to the screen rule that explains it'
	);
});

// ─── Measured in a browser: the panel as it opens ────────────────────────────

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8122';
let reachable = false;
let browser: Browser | null = null;

/** What the Job tab holds, as it opens, at 1440 x 900. */
async function jobTab() {
	browser = await chromium.launch();
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	await page.goto(BASE, { waitUntil: 'networkidle' });
	// The estimate comes back from the engine, which builds the whole cut plan for it.
	// Reading before that is reading a panel that is not finished — see the handbook's
	// "a measurement taken too early is a wrong measurement".
	await page.click('.panel .tab:has-text("Job")');
	await page.waitForFunction(
		() => /\d:\d\d/.test(document.querySelector('.panel-scroll')?.textContent ?? ''),
		undefined,
		{ timeout: 20000 }
	);
	await page.waitForTimeout(500);
	return page.evaluate(() => {
		const root = document.querySelector('.panel-scroll') as HTMLElement;
		const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
		let nodes = 0;
		let chars = 0;
		let node: Node | null;
		while ((node = walk.nextNode())) {
			const text = (node.textContent ?? '').trim();
			if (!text) continue;
			const box = node.parentElement?.getBoundingClientRect();
			if (!box || (box.width === 0 && box.height === 0)) continue;
			nodes++;
			chars += text.length;
		}
		const text = root.innerText.replace(/\s+/g, ' ');
		const clock = /(\d+:\d\d)/.exec(text);
		return {
			nodes,
			chars,
			text,
			clock: clock ? clock[1] : null,
			clocks: clock ? (text.match(new RegExp(clock[1], 'g')) ?? []).length : 0
		};
	});
}

test('the panel as it opens holds no paragraph about a feature that is off', async (t) => {
	reachable = await fetch(BASE, { signal: AbortSignal.timeout(2000) }).then(
		() => true,
		() => false
	);
	if (!reachable) return noServer(t, BASE);
	const seen = await jobTab();
	await browser?.close();
	// The three paragraphs the pattern counted, by their opening words.
	for (const prose of [
		'Technical messages from the engine',
		'Off. The work burns where you drew it',
		'Off: the work burns at the coordinates'
	])
		assert.ok(!seen.text.includes(prose), `still on screen as the panel opens: "${prose}"`);
	// One clock, not two. Measured before: "Estimated time 2:31" at the top and
	// "Start job 2:31" at the foot, both on screen without scrolling.
	assert.equal(seen.clocks, 1, `the estimate ${seen.clock} stands ${seen.clocks} times`);
	// Layers, with the same seed on the bed, held 267 characters over 46 nodes.
	assert.ok(seen.chars < 850, `the Job tab holds ${seen.chars} characters over ${seen.nodes} nodes`);
});

/**
 * The two "Off" values in `Operate machine`, at one width: what they say, whether the
 * dotted underline that promises a sentence actually computes, and whether the sentence
 * itself is on the screen. The fold is open by rule, so no click is needed beyond the tab.
 */
async function offValues(width: number) {
	browser = await chromium.launch();
	const page = await browser.newPage({ viewport: { width, height: 1000 } });
	await page.goto(BASE, { waitUntil: 'networkidle' });
	await page.click('.panel .tab:has-text("Job")');
	await page.waitForSelector('.origin p.hint[title]', { timeout: 20000 });
	await page.waitForTimeout(500);
	return page.evaluate(() =>
		[...document.querySelectorAll('.origin')].map((block) => {
			const value = block.querySelector('p.hint[title]') as HTMLElement | null;
			return {
				value: value ? (value.textContent ?? '').trim() : null,
				decoration: value ? getComputedStyle(value).textDecorationLine : null,
				sentence: value?.getAttribute('title') ?? null,
				visible: (block as HTMLElement).innerText.replace(/\s+/g, ' ')
			};
		})
	);
}

test('a value that hides a sentence behind a hover carries a underline you can see', async (t) => {
	reachable = await fetch(BASE, { signal: AbortSignal.timeout(2000) }).then(
		() => true,
		() => false
	);
	if (!reachable) return noServer(t, BASE);
	const blocks = await offValues(1440);
	await browser?.close();
	const off = blocks.filter((b) => b.value === 'Off');
	assert.equal(off.length, 2, `${off.length} of the two "where does the work go" cards say Off`);
	for (const block of off) {
		// `text-decoration: underline dotted var(--line-1)` computed to `none`: the token
		// does not exist, so the whole shorthand was thrown away and the only cue that a
		// sentence was there was the cursor.
		assert.equal(
			block.decoration,
			'underline',
			`"Off" computes text-decoration-line: ${block.decoration} — nothing says a sentence is behind it`
		);
		assert.ok(
			!block.visible.includes(block.sentence ?? ''),
			'the sentence stands on the screen as well as in the title, where a pointer can hover'
		);
	}
});

test('where a pointer cannot hover, the value promises nothing it cannot give', async (t) => {
	reachable = await fetch(BASE, { signal: AbortSignal.timeout(2000) }).then(
		() => true,
		() => false
	);
	if (!reachable) return noServer(t, BASE);
	// 1100 px is a tablet by `screen.noHover`, and there a title has no route: no hover,
	// no focus, no gesture. So the same paragraph carries the sentence instead of the
	// word, and the dotted cue goes with it — it would say "hover me" to a finger.
	// Not the word *and* the sentence under it: both sentences open with "Off", and
	// saying it twice measured 144.4 px of the zero-point fold at 1024 against 119.5 px
	// for the sentence alone, which is what main showed there.
	const blocks = await offValues(1100);
	await browser?.close();
	assert.equal(blocks.length, 2, `${blocks.length} of the two "where does the work go" cards`);
	for (const block of blocks) {
		assert.equal(
			block.decoration,
			'none',
			'the underline still hints at a hover a touch screen cannot give'
		);
		assert.equal(
			block.value,
			block.sentence,
			`the card reads "${block.value}" and keeps its sentence in a title a finger cannot open`
		);
	}
});
