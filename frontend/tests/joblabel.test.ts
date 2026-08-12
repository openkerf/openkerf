/**
 * De naam van een job in de wachtrij.
 *
 * Draaien: `node --test frontend/tests/joblabel.test.ts`.
 *
 * Aanleiding: "Kader tonen" spoolt een losse beweging, en het Job-paneel toonde
 * daarvoor het label dat de engine meegeeft — de repr van een Python-tuple:
 * `('move_abs', 114.7544mm, 80.0mm)`. Gemeten op 0.9.9040 via
 * `/api/devices` → `spooler.jobs[0].label` tijdens een kaderjob.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { jobLabel } from '../src/lib/api.ts';

const job = (label: string) => ({ label }) as Parameters<typeof jobLabel>[0];

test('een bewegingsjob toont geen Python-tuple', () => {
	const uit = jobLabel(job("('move_abs', 114.7544mm, 80.0mm)"));
	assert.doesNotMatch(uit, /[()']/, `nog steeds engine-taal: ${uit}`);
	assert.doesNotMatch(uit, /move_abs/, `nog steeds de commandonaam: ${uit}`);
	assert.equal(uit, 'Kop verplaatsen naar 114.7544mm × 80.0mm');
});

test('een tuple zonder herkenbaar punt houdt een leesbare naam', () => {
	assert.equal(jobLabel(job("('home',)")), 'Naar huis');
	assert.equal(jobLabel(job("('rapid_mode',)")), 'Kop verplaatsen');
});

test('een onbekend commando wordt niet verzwegen maar wel leesbaar', () => {
	const uit = jobLabel(job("('iets_nieuws', 1, 2, 3)"));
	assert.equal(uit, 'Machinebeweging');
});

test('de bestaande vertalingen blijven staan', () => {
	assert.equal(jobLabel(job('Spooler:3 items')), '3 bewerkingen');
	assert.equal(jobLabel(job('Spooler:1 item')), '1 bewerking');
	assert.equal(jobLabel(job('mijn ontwerp.svg')), 'mijn ontwerp.svg');
	assert.equal(jobLabel(job('')), 'Naamloze job');
	assert.equal(jobLabel(null), 'Naamloze job');
});

test('tekst die toevallig op een tuple lijkt blijft ongemoeid', () => {
	assert.equal(jobLabel(job('(niet echt een tuple)')), '(niet echt een tuple)');
	assert.equal(jobLabel(job("plaat ('eik') 3mm")), "plaat ('eik') 3mm");
});
