/**
 * One truth about "is the server still there".
 *
 * The status connection knows it (its WebSocket drops), but the buttons that have
 * to react are in components that are not handed that connection — and threading a
 * flag through five components touches files that belong to other people. Hence one
 * module everybody may read: whoever sends something to the server looks here
 * first.
 *
 * Why this matters: without it Stop, Pause and Home kept looking entirely operable
 * after the server had dropped out. Somebody standing next to the machine presses
 * Stop, sees no reaction at all, and believes the machine is stopping.
 */

export const connection = $state({
	/** Is the OpenKerf server reachable? */
	online: true,
	/** Since when it has not been (ms since epoch), for "gone for 2 minutes". */
	since: null as number | null,
	/** Seconds until the next attempt; 0 = trying right now. */
	inSeconds: 0,
	/** Try again now, instead of waiting out the backoff. */
	retryNow: (() => {}) as () => void,
	/**
	 * The server has restarted since this page was loaded (gap E2).
	 *
	 * The socket reconnects by itself and the bar goes green again, but the engine
	 * behind it has an empty element tree: the design you see on screen no longer
	 * exists on the other side. Everything you do after that is about nothing. That
	 * must not happen silently, and it must not reload by itself either — that throws
	 * work away without anybody asking. So: one flag, one sentence, one button.
	 */
	restarted: false
});
