/**
 * What a test does when there is no server to measure against.
 *
 * Fourteen files in this directory drive a real browser at a running OpenKerf and
 * skip themselves when there is none — which is the honest thing at a keyboard,
 * where usually there is no server, and the wrong thing in a run that claims to
 * have checked. A skip is at least visible in the output where a green tick is
 * not, but it is still silence.
 *
 * So: `OK_REQUIRE_SERVER=1` turns every one of those skips into a failure. The
 * default is unchanged — no server, still a skip — and a run that means to cover
 * this class sets the variable and finds out.
 *
 * One function and not fourteen copies of three lines, for the reason in
 * CLAUDE.md: the second copy is where the two drift apart. It was one copy in
 * `upload-reach.test.ts` first, which is how the shape got tried before it got
 * spread.
 */
import assert from 'node:assert/strict';

/**
 * Skip because nothing is listening — or fail, if this run said it would check.
 *
 * `base` is passed rather than read from `BASE` here: a few of these files point
 * at a port of their own, and a message naming the wrong one would send somebody
 * to look at a server that was never the subject.
 */
export function noServer(t: { skip: (why: string) => void }, base: string) {
	if (process.env.OK_REQUIRE_SERVER)
		assert.fail(`no server on ${base} and OK_REQUIRE_SERVER is set`);
	return t.skip(`no server on ${base}`);
}
