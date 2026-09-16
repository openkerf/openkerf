# Job panel cleanup

Scope approved: step 3, focused on Job / machine controls. Keep Edit and Layers unchanged.

Use the current panel and native details elements rather than a new wizard or separate
machine tab. Job review, warnings and start/stop remain the primary content. Remove the
nested preflight card border and give the desktop Job panel 320px of reading width.
Machine controls start collapsed, close when work begins, and do not reopen on status
polls. When opened, jogging is immediately available. Saved positions, work origin,
print-and-cut and adjustments each have a named fold. Active setup values remain in
fold summaries; job warnings and the two-step start checklist stay visible.

Validation: browser checks in English/Dutch at desktop/tablet sizes, keyboard operation,
no clipped controls, job warning and start reachability. No real machine commands.

## Still pending — steps 1 and 2

The Ruida repair and honest status display have passed offline tests only. Before
production use, validate idle polling, disconnect/reconnect, network interruption,
and file upload without starting on the user's Ubuntu Docker host and Ruida through
the Cisco switch. Do not mark these hardware checks complete based on UI tests.

## Completed offline verification

- Build passed; Svelte/TypeScript check: 0 errors, 0 warnings.
- Frontend suite: 277 passed, 175 skipped without their dedicated test servers.
- Targeted browser regression also run separately against the built frontend in an
  isolated Docker container: English/Dutch at 1440×900, 1366×768 and 1024×768.
  Verified native keyboard folds, active overrides with unread values, no horizontal
  overflow, uncovered Start, simulated job transition/Stop, and no machine writes.
- Independent review resolved hidden adjustment state and notification-card overlap.
- Refreshed handbook screenshots; the screenshot fixture uses an isolated default
  device and does not represent a connected controller.
- Hardware validation for steps 1 and 2 remains OPEN.
