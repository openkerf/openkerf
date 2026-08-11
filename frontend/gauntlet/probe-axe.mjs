import AxeBuilder from '@axe-core/playwright';
import { browser, open, reset } from './harness.mjs';
await reset();
const b = await browser();
const page = await open(b, { width: 1440, theme: 'dark' });
const r = await new AxeBuilder({ page }).withTags(['wcag2aa']).analyze();
for (const v of r.violations) {
	for (const n of v.nodes.slice(0, 3)) {
		console.log(v.id, '|', n.target.join(' '), '|', (n.any?.[0]?.message ?? '').slice(0, 130));
	}
}
await b.close();
