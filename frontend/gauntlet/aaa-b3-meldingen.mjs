/**
 * B3 — meldingen en alarm. Schermafdrukken én metingen.
 *
 * Wat hier écht gebeurt en wat gezet is:
 *
 * - Het **alarm** is echt. We starten een job op een machine die niet aan de
 *   USB hangt; de engine zendt dan zelf `pipe;usb_status` met "USB connection
 *   did not exist." uit, en dat is wat de balk toont. Niets gesimuleerd.
 * - De **toestemmingstoestanden** zijn browsertoestanden: "toegestaan" zetten we
 *   met grantPermissions (dat is wat de browser ook doet), "geweigerd" met een
 *   override van `Notification.permission`, omdat Playwright geen weigering kent.
 * - De **lopende job** is gezet: het mock-apparaat springt binnen twee seconden
 *   naar 99,97% en blijft daar hangen, dus een job halverwege bestaat niet. We
 *   verbouwen de binnenkomende snapshot in de browser, zoals eerdere rondes ook
 *   deden. Alle UI eromheen is echte code.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8125';
const MAP = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/b3';
const RONDE = process.argv[2] ?? 'r1';
mkdirSync(MAP, { recursive: true });

const BREEDTES = [
	['1440', 1440, 900],
	['1024', 1024, 900],
	['390', 390, 844]
];

// 'chromium' = de nieuwe headless-modus. In de oude staat de toestemming voor
// meldingen altijd op 'denied', ook na grantPermissions — dan meet je niets.
const browser = await chromium.launch({ channel: 'chromium' });
const bevindingen = [];

async function maak({ width, height, theme, toestemming = 'default', job = false }) {
	const context = await browser.newContext({
		viewport: { width, height },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	if (toestemming === 'granted') await context.grantPermissions(['notifications'], { origin: BASE });
	const page = await context.newPage();
	await page.addInitScript(
		([t, perm, metJob]) => {
			const zet = () => document.documentElement?.setAttribute('data-theme', t);
			zet();
			document.addEventListener('DOMContentLoaded', zet);

			if (perm === 'denied') {
				Object.defineProperty(Notification, 'permission', {
					configurable: true,
					get: () => 'denied'
				});
			}

			// Meekijken zonder te vervangen: de echte melding gaat gewoon door.
			window.__meld = [];
			const orig = window.Notification;
			window.Notification = class extends orig {
				constructor(titel, opties) {
					window.__meld.push({ via: 'page', titel, body: opties?.body });
					super(titel, opties);
				}
			};
			Object.defineProperty(window.Notification, 'permission', {
				configurable: true,
				get: () => (perm === 'denied' ? 'denied' : orig.permission)
			});
			window.Notification.requestPermission = (...a) => orig.requestPermission(...a);
			if (window.ServiceWorkerRegistration) {
				const tonen = ServiceWorkerRegistration.prototype.showNotification;
				ServiceWorkerRegistration.prototype.showNotification = function (titel, opties) {
					window.__meld.push({ via: 'sw', titel, body: opties?.body });
					return tonen.call(this, titel, opties);
				};
			}

			if (metJob) {
				const Origineel = window.WebSocket;
				const verbouw = (tekst) => {
					try {
						const payload = JSON.parse(tekst);
						if (payload?.type !== 'snapshot') return tekst;
						for (const d of payload.data.devices ?? []) {
							d.spooler.idle = false;
							d.spooler.queue_length = 1;
							d.spooler.jobs = [
								{
									label: 'Spooler:1 items',
									type: 'plan',
									status: 'Running',
									priority: 0,
									running: true,
									steps_done: 1480,
									steps_total: 4000,
									progress: 0.37,
									loops_executed: 0,
									loops: 1,
									elapsed_seconds: 96,
									estimate_seconds: 260
								}
							];
						}
						return JSON.stringify(payload);
					} catch {
						return tekst;
					}
				};
				window.WebSocket = class extends Origineel {
					set onmessage(fn) {
						super.onmessage = (e) =>
							fn(new MessageEvent('message', { data: verbouw(e.data) }));
					}
				};
			}
		},
		[theme, toestemming, job]
	);
	await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .telefoon', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /^later$/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	return { context, page };
}

async function schiet(page, naam) {
	await page.screenshot({ path: `${MAP}/${RONDE}-${naam}.png` });
}

/** De instelkaart openen — telefoon klapt uit, desktop opent het venster. */
async function openInstellingen(page, width) {
	if (width < 768) {
		await page.getByRole('button', { name: 'Meldingen' }).first().click();
	} else {
		await page.locator('button.bel').click();
	}
	await page.waitForTimeout(400);
}

for (const [naam, width, height] of BREEDTES) {
	for (const theme of ['light', 'dark']) {
		// 1. Rust: niets aan de hand, toestemming nog niet gevraagd.
		{
			const { context, page } = await maak({ width, height, theme });
			await schiet(page, `rust-${naam}-${theme}`);
			await openInstellingen(page, width);
			await schiet(page, `instellingen-nietgevraagd-${naam}-${theme}`);
			await context.close();
		}

		// 2. Toestemming geweigerd: de toestand die je moet kunnen herstellen.
		{
			const { context, page } = await maak({ width, height, theme, toestemming: 'denied' });
			await openInstellingen(page, width);
			await schiet(page, `instellingen-geweigerd-${naam}-${theme}`);
			await context.close();
		}

		// 3. Toestemming gegeven, en een melding daadwerkelijk verstuurd.
		{
			const { context, page } = await maak({ width, height, theme, toestemming: 'granted' });
			await openInstellingen(page, width);
			await page.getByRole('button', { name: /testmelding/i }).click();
			await page.waitForTimeout(600);
			await schiet(page, `instellingen-aan-${naam}-${theme}`);
			const verstuurd = await page.evaluate(() => window.__meld);
			bevindingen.push(`${naam}/${theme} testmelding → ${JSON.stringify(verstuurd)}`);
			await context.close();
		}

		// 4. Lopende job + de aanleidingkaart voor de toestemmingsvraag.
		{
			const { context, page } = await maak({ width, height, theme, job: true });
			await page.waitForTimeout(1500);
			await schiet(page, `aanleiding-${naam}-${theme}`);
			await context.close();
		}

	}
}

// Het alarm helemaal aan het eind, en dat is geen willekeur: zodra je één job
// start op een machine die niet aan de USB hangt, blijft de engine "USB
// connection did not exist." herhalen — ook na `estop`. Elke schermafdruk
// daarna zou die balk erbij hebben. Wie deze reeks opnieuw draait, herstart
// eerst de server.
for (const [naam, width, height] of BREEDTES) {
	for (const theme of ['light', 'dark']) {
		const { context, page } = await maak({ width, height, theme, toestemming: 'granted' });
		await page.evaluate(() => fetch('/api/job/start', { method: 'POST' }));
		await page.waitForSelector('.alarm', { timeout: 20000 }).catch(() => {});
		await page.waitForTimeout(3500);
		await schiet(page, `alarm-${naam}-${theme}`);
		const inhoud = await page
			.locator('.alarm')
			.first()
			.innerText()
			.catch(() => '(geen alarm)');
		const gemeld = await page.evaluate(() => window.__meld);
		bevindingen.push(
			`${naam}/${theme} alarm → ${JSON.stringify(inhoud)} | verstuurd ${JSON.stringify(gemeld)}`
		);
		await context.close();
	}
}

await browser.close();
console.log(bevindingen.join('\n'));
