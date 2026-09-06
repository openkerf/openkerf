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
	// branch that runs when it is open.
	assert.ok(
		!/\{#if !showEvents\}/.test(source),
		'there is a branch again for what the shut fold says — a shut fold says its title'
	);
	const open = source.indexOf('{#if showEvents}');
	assert.notEqual(open, -1, 'the messages fold no longer branches on being open');
	assert.ok(at > open, 'the hint stands before the fold is opened');
});

test('a job waiting its turn shows no bar and no counters about not having started', () => {
	const source = code('JobPanel.svelte');
	for (const marker of ['class="progress"', 'class="figures mono"', 'class="meta mono"']) {
		const at = source.indexOf(marker);
		assert.notEqual(at, -1, `JobPanel no longer has ${marker}`);
		const guard = source.lastIndexOf('{#if', at);
		const condition = source.slice(guard, source.indexOf('}', guard));
		assert.ok(
			/job\.running/.test(condition),
			`${marker} stands under \`${condition.trim()}\` — a waiting job has no progress to show`
		);
	}
});

test('the keys are on the buttons they work, not in a paragraph under them', () => {
	const source = code('JobControls.svelte');
	const uses = [...source.matchAll(/t\('job\.keysHere'\)/g)].length;
	assert.ok(uses >= 2, `the keys sentence is on ${uses} button(s); pause and stop both need it`);
	assert.equal(
		/class="toetsen"/.test(source),
		false,
		'the paragraph of key advice is back under the transport buttons'
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
