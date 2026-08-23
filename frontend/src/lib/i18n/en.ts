/**
 * The source catalogue. English, and the only complete one by definition.
 *
 * Rules for editing this file:
 *
 * - **Keys are semantic**, grouped by the surface they live on. Rewording the
 *   English costs one line here instead of a rename across the app.
 * - **Placeholders are `{name}`**, never positional. A translator moving a
 *   number to the other end of a sentence should not have to count.
 * - **A count gets `{ one, other }`.** Do not build "1 shape(s)" by hand; the
 *   runtime picks the variant and Dutch needs a different split than English.
 * - **Never assemble a sentence from fragments in the markup.** Word order is
 *   not a constant across languages, and a translator handed half a clause
 *   cannot do anything with it. One key per sentence.
 * - **Units stay outside the message** where they are the same everywhere
 *   (mm, %, mm/s); the number formatting is the runtime's job, because 3.5 and
 *   3,5 are the same length but not the same number.
 *
 * Adding a language: copy this file, translate the values, add it to
 * `LANGUAGES` and `CATALOGUES` in `index.svelte.ts`. The types then refuse to
 * compile until every key is present, and `frontend/tests/i18n.test.ts` checks
 * that the placeholders survived the translation.
 */
export const en = {
	// ── App ────────────────────────────────────────────────────────────────────
	'app.name': 'OpenKerf',
	'app.language': 'Language',

	// ── Top bar ────────────────────────────────────────────────────────────────
	'topbar.machine.setup': 'Set up machine',
	'topbar.material.choose': 'Choose material',
	'topbar.material.short': 'Material',
	'topbar.material.none': 'No material chosen for this sheet yet — click to fill it in',
	'topbar.material.isThickness': 'This sheet is {material}, {thickness} — click to change',
	'topbar.material.noThickness': 'This sheet is {material} (thickness not filled in) — click to change',
	'topbar.project': 'Project',
	'topbar.project.aria': 'Project — open and save',
	'topbar.project.title':
		'Project — open and save (design, sheets and library in one file)',
	'topbar.project.pick': 'Choose project file',
	'topbar.project.new': 'New project',
	'topbar.project.open': 'Open project…',
	'topbar.project.save': 'Save project',
	'topbar.project.hint': 'Design, sheets, materials and machine profiles in one file.',
	'topbar.import': 'Import',
	'topbar.import.title':
		'Import a file into this sheet — SVG, DXF, RD, G-code or an image',
	'topbar.import.aria': 'Import file into this sheet',
	'topbar.export': 'Export',
	'topbar.export.title': 'Save this sheet as SVG',
	'topbar.frame': 'Show frame',
	'topbar.frame.short': 'Frame',
	'topbar.frame.title': 'Send the head around the outline of your work, without burning',
	'topbar.frame.off': 'Nothing is on the bed, or this machine cannot move',
	'topbar.frame.noServer': 'Running the frame has to wait until the server is back.',
	'topbar.theme': 'Switch theme',

	// ── Transport (top bar, panel, status bar all read these) ──────────────────
	'transport.start': 'Start job',
	'transport.start.short': 'Start',
	'transport.start.preflight': 'Open the pre-flight',
	'transport.start.busy': 'A job is already under way',
	'transport.pause': 'Pause',
	'transport.pause.title': 'Pause the job — the head stops, the job stays (Pause)',
	'transport.pause.unsupported': 'This machine has no pause — use the button on the machine',
	'transport.pause.nothing': 'Nothing is running to pause',
	'transport.resume': 'Resume',
	'transport.resume.title': 'Carry on where it left off (Pause)',
	'transport.stop': 'Stop',
	'transport.stop.onMachine': 'Stop on the machine',
	'transport.stop.now': 'Abort the job right away ({key})',
	'transport.stop.armed':
		'Nothing is running — this aborts a job the moment one starts ({key})',
	'transport.noServer': 'No connection to OpenKerf — this button will not arrive.',
	'transport.noServer.stop': 'Stopping is only possible with the emergency stop on the machine now.',
	'transport.noServer.pause': 'Pausing is only possible with the button on the machine now.',
	'transport.noServer.resume': 'Resuming is only possible on the machine now.',
	'transport.noServer.start': 'Wait until the server is back.',

	// ── Tool rail ──────────────────────────────────────────────────────────────
	'rail.aria': 'Tools',
	'rail.needsToken': '{label} — requires a token',
	'rail.tool.select': 'Select',
	'rail.tool.nodes': 'Nodes — pick a shape first, then drag the points',
	'rail.tool.nodes.short': 'Nodes',
	'rail.tool.rect': 'Rectangle',
	'rail.tool.circle': 'Circle',
	'rail.tool.line': 'Line',
	'rail.tool.pen': 'Pen — click for a corner, drag for a curve, Enter finishes',
	'rail.tool.pen.short': 'Pen',
	'rail.tool.text': 'Text',
	'rail.tool.measure': 'Measure',
	'rail.placeImage': 'Place image',
	'rail.generators': 'Generators — repeats, boxes, codes and a living hinge',
	'rail.generators.short': 'Generators',
	'rail.clipart': 'Search clipart in public collections',
	'rail.clipart.short': 'Search clipart',
	'rail.series': 'Series — one design burned once per row of a list',
	'rail.series.short': 'Series',
	'rail.library.short': 'Material',
	'rail.more': 'More',
	'rail.group.tools': 'Tools',
	'rail.group.add': 'Add',
	'rail.group.file': 'File',
	'rail.importHere': 'Import into this sheet',
	'rail.sheetAsSvg': 'This sheet as SVG',

	// ── Status bar ─────────────────────────────────────────────────────────────
	'status.head': 'head',
	'status.mouse': 'mouse',
	'status.lastSeen': 'last seen',
	'status.noJob': 'no job',
	'status.remaining': '{remaining} left',
	'status.total': 'total {total}',
	'status.estimated': '~{total} estimated',
	'status.restart.title': 'The server has restarted',
	'status.restart.body':
		'This page still shows the design from before the restart; the engine started empty. Reload to see what is really there.',
	'status.restart.reload': 'Reload',
	'status.machine.unknown': 'Machine unknown',
	'status.machine.notConnected': 'Machine not connected',
	'status.machine.connectionUnknown': 'Connection unknown',
	'status.machine.connected': 'Connected to the laser',
	'status.machine.connectionUnknown.hint':
		'The engine is running, but this driver does not report whether a machine is attached. You will notice on the first job: it stays in the queue if nothing is listening.',
	'status.connect': 'Connect',
	'status.connect.busy': 'Connecting…',
	'status.connect.title': 'Open the connection to the machine. This moves nothing.',
	'status.disconnect': 'Disconnect',
	'status.disconnect.busy': 'Disconnecting…',
	'status.disconnect.title': 'Release the connection to the machine',
	'status.disconnect.ask':
		'Disconnect? Reconnecting afterwards does not always work; sometimes only a restart of the server helps.',
	'status.disconnect.keep': 'Leave it',
	'status.needsToken': 'Fill in a token first',
	'status.openkerf.live': 'OpenKerf live',
	'status.openkerf.away': 'OpenKerf away',
	'status.openkerf.live.title': 'The page is receiving live data from the OpenKerf server',
	'status.openkerf.away.title':
		'The page has no connection to the OpenKerf server; what you see is the last state',

	// ── Machine state ──────────────────────────────────────────────────────────
	'machine.state.offline': 'Offline',
	'machine.state.unplugged': 'Not connected',
	'machine.state.ready': 'Ready',
	'machine.state.busy': 'Busy',
	'machine.state.paused': 'Paused',
	'machine.state.alarm': 'Alarm',
	'machine.hint.offline': 'No connection to OpenKerf. Check whether the engine is running.',
	'machine.hint.unplugged': 'The engine is running, but no machine is attached.',
	'machine.hint.alarm': 'The machine reports an alarm. Unlock it before starting anything.',

	// ── The job ────────────────────────────────────────────────────────────────
	'job.label.operations': {
		one: '1 operation',
		other: '{n} operations'
	},
	'job.label.unnamed': 'Unnamed job',
	'job.move.head': 'Move head',
	'job.move.home': 'Go home',
	'job.move.setOrigin': 'Set zero point',
	'job.move.unknown': 'Machine movement',
	'job.move.to': '{what} to {x} × {y}',
	'axis.speed': 'Speed',
	'axis.power': 'Power',
	'axis.interval': 'Interval',
	'job.status.paused': 'Paused',
	'job.status.running': 'Busy',
	'job.status.queued': 'In the queue',
	'job.status.done': 'Done',
	'job.phase.nothing.title': 'Nothing to burn',
	'job.phase.nothing.body':
		'There is no work on the bed. Draw something, or import a file.',
	'job.phase.ready.title': 'Ready to start',
	'job.phase.ready.body': 'Run through the checks and then start the job.',
	'job.phase.queued.title': 'In the queue',
	'job.phase.queued.body':
		'The job is ready, but the machine has not picked it up. That normally takes a second; if it stays like this, check the connection.',
	'job.phase.burning.title': 'Burning',
	'job.phase.burning.body': 'Stay with it and keep the stop button within reach.',
	'job.phase.paused.title': 'Paused',
	'job.phase.paused.body': 'The head is standing still. Resuming carries on where it left off.',
	'job.phase.done.title': 'Done',
	'job.phase.done.body':
		'The work is finished. The engine does not sign a job off, so it stays in the queue until you clear it.',

	// ── Action bar ─────────────────────────────────────────────────────────────
	'bar.aria': 'Edit',
	'bar.history': 'History',
	'bar.alignH': 'Align, horizontal',
	'bar.alignV': 'Align, vertical',
	'bar.arrange': 'Arrange',
	'bar.more': 'More',
	'bar.more.title': 'All operations — or right-click a shape',
	'bar.selection.none': 'Pick a shape on the bed',
	'bar.selection.count': { one: '1 shape selected', other: '{n} shapes selected' },

	// ── Operations (menus, action bar, keyboard — all read these) ──────────────
	'action.cut': 'Cut',
	'action.copy': 'Copy',
	'action.paste': 'Paste',
	'action.pasteHere': 'Paste here',
	'action.duplicate': 'Duplicate',
	'action.delete': 'Delete',
	'action.selectAll': 'Select all',
	'action.clearSelection': 'Clear selection',
	'action.undo': 'Undo',
	'action.redo': 'Redo',
	'action.align': 'Align and distribute',
	'action.align.left': 'Align left',
	'action.align.centerH': 'Centre horizontally',
	'action.align.right': 'Align right',
	'action.align.spaceH': 'Distribute horizontally',
	'action.align.top': 'Align top',
	'action.align.centerV': 'Centre vertically',
	'action.align.bottom': 'Align bottom',
	'action.align.spaceV': 'Distribute vertically',
	'action.group': 'Group',
	'action.ungroup': 'Ungroup',
	'action.mirrorH': 'Mirror horizontally',
	'action.mirrorV': 'Mirror vertically',
	'action.rotate': 'Rotate',
	'action.rotateLeft': '90° anticlockwise',
	'action.rotateRight': '90° clockwise',
	'action.rotate180': '180°',
	'action.combine': 'Combine',
	'action.union': 'Union',
	'action.difference': 'Difference',
	'action.intersection': 'Intersection',
	'action.xor': 'Exclude',
	'action.path': 'Edit path',
	'action.offset': 'Offset…',
	'action.simplify': 'Simplify',
	// Locking: the shapes you must not touch are the ones you touch by accident.
	'action.duplicates': 'Remove duplicates…',
	'duplicates.title': 'Shapes lying on top of each other',
	'duplicates.none': 'No two shapes in this design lie on top of each other.',
	'duplicates.found': {
		one: 'One shape lies on top of another. Removing it leaves the one that was there first.',
		other: '{n} shapes lie on top of another one, all in the same place. Removing them leaves the one that was there first.'
	},
	'duplicates.foundSpread': '{n} shapes lie on top of another one, in {stacks} places. Removing them leaves the one that was there first in each place.',
	'duplicates.why': 'A duplicate is invisible and it burns twice: the same line again, which scorches the edge on thin material and simply costs the time on thick.',
	'duplicates.skipped': {
		one: 'One shape was not compared, because it has no outline to compare (an image or a group).',
		other: '{n} shapes were not compared, because they have no outline to compare (images and groups).'
	},
	'duplicates.remove': 'Remove {n}',
	'notice.duplicates.removed': {
		one: '1 duplicate removed.',
		other: '{n} duplicates removed.'
	},
	'action.lock': 'Lock',
	'action.unlock': 'Unlock',
	'reason.locked': 'This shape is locked',
	'reason.someLocked': '{n} of the shapes you picked are locked',
	'notice.lock.locked': {
		one: '1 shape locked — it cannot be moved, sized or deleted until you unlock it.',
		other: '{n} shapes locked — they cannot be moved, sized or deleted until you unlock them.'
	},
	'notice.lock.unlocked': {
		one: '1 shape unlocked.',
		other: '{n} shapes unlocked.'
	},
	'panel.locked': 'Locked',
	'panel.locked.body': 'Protected from moving, sizing and deleting. Its layer, colour and bridges can still be changed.',
	'action.nest': 'Nest',
	'action.split': 'Split into separate shapes',
	'action.splitInto': 'Split into {n} shapes',
	'action.hatch': 'Hatch',
	'action.wobble': 'Wobble',
	'action.corners': 'Corners…',
	'action.bridges': 'Add bridges (4 × 2 mm)',
	'action.bridgesOff': 'Remove bridges',
	'action.fill': 'Fill — for rastering',
	'action.unfill': 'Remove fill',
	// "Burn only once": one row, two wordings, for a jig frame in a series. The word is
	// "plate" and not "row", because what the reader is holding is a plate.
	'action.burnOnce': 'Burn only once',
	'action.burnEvery': 'Burn on every plate',
	'action.layer': 'Layer',
	'action.onlyCut': 'Only in the cut layer',
	'action.onlyEngrave': 'Only in the engrave layer',
	'action.onlyRaster': 'Only in the raster layer',
	'action.toSheet': 'Move to another sheet',
	'action.editText': 'Edit text…',
	'action.crop': 'Crop',
	'action.uncrop': 'Undo crop',
	'action.vectorise': 'Vectorise',
	'action.view': 'View',
	'action.zoomAll': 'Fit everything in view',
	'action.zoomSelection': 'To the selection',
	'action.zoomBed': 'The whole bed',
	'action.zoomHundred': '100 % — actual size',
	'action.snap': 'Snap to grid and shapes',
	'action.layerNumbers': 'Layer numbers next to the shapes',
	'action.rescue': 'Put everything on the bed',
	// Node editing (P1). "Curve" and "corner" and not "quadratic" and "straight": the word
	// on the row is the thing that happens to the line, not the name of the maths.
	'action.nodeAdd': 'Add a node here',
	'action.nodeCurve': 'Make this piece a curve',
	'action.nodeCorner': 'Make this piece straight',
	'action.nodeRemove': 'Remove this node',

	// ── Why an operation cannot run now ────────────────────────────────────────
	'reason.needsToken': 'Requires a token',
	'reason.busy': 'Another operation is still running',
	'reason.pickShape': 'Pick a shape first',
	'reason.needsTwo': 'Select at least two shapes',
	'reason.needsThree': 'Distributing needs at least three shapes',
	'reason.notInGroup': 'This selection is not in a group',
	'reason.noBridges': 'A line, text or an image carries no bridges',
	'reason.noList': 'No list is attached in the Series window',
	'reason.onePiece': 'This shape is a single piece',
	'reason.clipboardEmpty': 'Nothing is on the clipboard',
	'reason.nothingSelected': 'Nothing is selected',
	'reason.bedEmpty': 'Nothing is on the bed',
	'reason.layerEmpty': 'This layer is empty',
	'reason.alreadyFirst': 'This layer already burns first',
	'reason.alreadyLast': 'This layer already burns last',
	'reason.testGridLayer': 'This layer belongs to a test grid',
	'reason.pickNode': 'Click a node on the shape first',
	'reason.nodeIsLast': 'This is the last node; there is no piece after it',
	'reason.nodeOpenTwo': 'A line needs two nodes',
	'reason.nodeClosedThree': 'A closed shape needs three nodes',

	// ── What an operation means, when nothing is in the way ────────────────────
	'explain.group': 'The shapes move together from now on',
	'explain.mirrorH': 'About the vertical axis. Clicking again puts it back.',
	'explain.mirrorV': 'About the horizontal axis. Clicking again puts it back.',
	'explain.combine': 'The result is one path; the shapes disappear',
	'explain.nest': 'Pack the selection close together to save material',
	'explain.corners': 'Round or chamfer, with the preview beside it',
	'explain.bridges': 'Small gaps in the cut, so the part stays in the sheet instead of dropping into the machine',
	'explain.bridgesOff': 'The cut closes again and the part comes loose',
	'explain.fill': 'A raster layer then burns the area instead of just the outline',
	'explain.unfill': 'Without a fill a shape only rasters its outline',
	'explain.burnOnce':
		'In a series this shape burns on the first plate only — a jig frame, or the pockets the pieces sit in',
	'explain.burnEvery': 'This shape goes onto every plate of the series again',
	'explain.crop': 'Then drag a frame over the image',
	'explain.vectorise': 'Turns the image into paths',
	'explain.pasteHere': 'The top-left corner lands where you clicked',
	'explain.snap': 'Hold Alt to skip it for one move',
	'explain.rescue': 'Including what lies off screen and cannot be clicked',
	'explain.burns': 'Off means: this layer does not go to the machine',
	'explain.visible': 'Changes nothing about the job',
	'explain.layerSettings': 'Name, speed, power, passes, colour',
	'explain.layerRemove': 'The shapes stay on the bed',
	'explain.nodeAdd': 'Halfway along the piece after this node. A double-click on the line puts one exactly where you click.',
	'explain.nodeCurve': 'The line stays where it is and gets a handle to pull it with',

	// ── The menu on a layer row ───────────────────────────────────────────────
	'layerMenu.selectShapes': {
		one: 'Select the shape in this layer',
		other: 'Select the {n} shapes in this layer'
	},
	'layerMenu.putIn': 'Put selection in this layer',
	'layerMenu.takeOut': 'Take selection out of this layer',
	'layerMenu.burns': 'Burns along',
	'layerMenu.visible': 'Visible on the canvas',
	'layerMenu.earlier': 'Burn earlier',
	'layerMenu.later': 'Burn later',
	'layerMenu.settings': 'Settings…',
	'layerMenu.remove': 'Remove layer',

	// ── Camera ────────────────────────────────────────────────────────────────
	'camera.button': 'Camera',
	'camera.title': 'Camera view of the bed',
	'camera.opacity': 'Camera image opacity',
	'camera.calibrate': 'Calibrate',
	'camera.recalibrate': 'Recalibrate',

	// ── Shared wording ────────────────────────────────────────────────────────
	'common.cancel': 'Cancel',
	'common.dismiss': 'Dismiss message',
	'common.done': 'Done',
	'common.save': 'Save',
	'common.remove': 'Remove',
	'common.close': 'Close',
	'common.back': 'Back',
	'common.busy': 'Working…',

	// ── Work from an earlier session ──────────────────────────────────────────
	'recovery.title': 'Work from an earlier session',
	'recovery.body': 'There is an automatically saved design from {when}. Restore it?',
	'recovery.discard': 'Discard',
	'recovery.later': 'Not now',
	'recovery.restore': 'Restore',

	// ── Replacing what is on the bed ──────────────────────────────────────────
	'replace.title.new': 'Start over',
	'replace.title.unsaved': 'Unsaved changes',
	'replace.title.project': 'There is already work in this project',
	'replace.changed': 'This design has changed since it was last saved.',
	'replace.workInProject': 'There is work in this project.',
	'replace.opensProject': {
		one: 'Opening replaces the whole project: the design, the sheet and the material come from the file.',
		other: 'Opening replaces the whole project: the design, all {n} sheets and the material come from the file.'
	},
	'replace.emptiesBed': 'Starting over empties the bed. Your materials and settings stay.',
	'replace.emptiesSheets': 'Starting over empties the bed and removes all {n} sheets. Your materials and settings stay.',
	'replace.recoverable': 'An automatically saved version of this sheet from {when} stays; it is offered at the next start. The other sheets are not.',
	'replace.saveAndStart': 'Save and start',
	'replace.saveAndOpen': 'Save and open',
	'replace.dontSave': 'Do not save',

	// ── Window titles ─────────────────────────────────────────────────────────
	'notifications.title': 'Notifications',
	'sheetMaterial.title': 'Material of this sheet',
	'library.title': 'Material library',
	'testgrid.title': 'Test grid',
	'series.title': 'Series',

	// ── Panel tabs ─────────────────────────────────────────────────────────────
	'tabs.edit': 'Edit',
	'tabs.layers': 'Layers',
	'tabs.job': 'Job',
	'tabs.notifications.on': 'Notifications are on',
	'tabs.notifications.off': 'Notifications are off',
	'tabs.notifications.onAria': 'Notifications — on',
	'tabs.notifications.offAria': 'Notifications — off',
	'panel.aria': 'Properties',
	'panel.collapse': 'Collapse panel',
	'panel.expand': 'Expand panel',
	// ── Canvas ────────────────────────────────────────────────────────────────────
	'canvas.headUnknown': 'Position of the laser head unknown',
	'canvas.headAt': 'Laser head at {x} by {y} millimetres',
	'canvas.selectShape': 'Select {name}',
	'canvas.dragEndpoint': 'Drag endpoint {n}',
	'canvas.dragNode': 'Drag node {n}',
	'canvas.dragHandle': 'Drag the handle of piece {n}',
	'canvas.pen.hint': 'Click for a corner, drag for a curve. Enter finishes the line, Backspace takes back the last point, Escape stops.',
	'canvas.nodes.hint': 'Double-click the line to add a node. With a node in hand: Delete removes it, Shift+U curves the piece after it, Shift+L straightens it.',
	'canvas.layerNumbers.on': 'Layer numbers next to the shapes are on',
	'canvas.layerNumbers.off': 'Layer numbers next to the shapes are off',
	'canvas.snap.on': 'Snapping is on — hold Alt to skip it for one move',
	'canvas.snap.off': 'Snapping is off — hold Alt to use it for one move',
	'canvas.bedSize': 'bed {width} × {height} mm',
	'canvas.empty.body': 'Use Import in the top bar for an existing design, or pick a shape on the left and click the bed.',
	// Alt+click walks down a pile of shapes; this says where you are in it.
	'canvas.deeper': 'Shape {index} of {total} under the pointer — Alt+click for the next.',
	'canvas.under': 'Under the pointer',
	// Numbered by depth, so two shapes of the same kind and size are still two
	// different rows — and the number is the one the hint counts with.
	'canvas.under.item': '{index}. {name} · {width} × {height} mm',
	'canvas.nodes.pickOne': 'Nodes works on one shape. Click one on the bed.',
	'canvas.nodes.tooMany': 'Nodes works on one shape at a time; {n} are selected. Click just one of them.',
	'canvas.nodes.noPoints': 'This shape has no loose points. Make it a path first with Combine, in the panel on the right.',
	'canvas.nodes.failed': 'The nodes of this shape could not be read. Try clicking it again; if it keeps failing, the engine is not answering.',
	'canvas.trace': 'Trace of the head — measured, including the jumps between shapes.',
	'canvas.traceProgress': '{percent}% shows as a ring around the head.',
	'canvas.outsideBed': {
		one: 'One shape lies outside the bed — the head does not reach there.',
		other: '{n} shapes lie outside the bed — the head does not reach there.'
	},
	'canvas.outsideSheet': {
		one: 'One shape lies outside {sheet} — there is no material there.',
		other: '{n} shapes lie outside {sheet} — there is no material there.'
	},
	'canvas.theSheet': 'the sheet',
	'canvas.burnsHere': 'burns here',
	'canvas.selectImage': 'Select image',
	'canvas.dragMove': 'Drag to move',
	'canvas.dragRotate': 'Drag to rotate',
	'canvas.dragScale': 'Drag to scale',
	'canvas.zoomOut.title': 'Zoom out (−)',
	'canvas.zoomOut': 'Zoom out',
	'canvas.zoomLevels': 'Zoom levels',
	'canvas.fit.title': 'Fit everything in view (3)',
	'canvas.zoomIn.title': 'Zoom in (+)',
	'canvas.zoomIn': 'Zoom in',
	'canvas.empty.title': 'Empty bed',
	'canvas.fit': 'Fit',
	'canvas.noMachine': 'No machine connected',
	'canvas.tooBig': 'This sheet is larger than the bed.',
	'canvas.burnInTiles': 'Burn in tiles?',

	// ── Layer palette ─────────────────────────────────────────────────────────────
	'palette.layerNamed': 'layer {n} · {label}',
	'palette.noLayerYetRemembered': 'no layer yet — starts from what this colour did before',
	'palette.noLayerYetBlank': 'no layer yet — starts blank',
	'palette.noLayerYet': 'no layer yet',
	'palette.putInColour': {
		one: 'Puts the selection in this colour.',
		other: 'Puts {n} shapes in this colour.'
	},
	'palette.setForNewWork': 'Sets the colour for new work.',
	'palette.remembered': 'remembered',
	'palette.aria': 'Layer colours',
	'palette.forNewWork': 'Colour for new work',
	'palette.selectionToLayer': 'Selection to layer',
	'palette.colourAria': 'Colour {n}. {description}',
	'palette.layerValues': 'The values of the layer itself.',
	'palette.memory': 'Remembered per machine and colour — what you last did with it. A preset is something else: that belongs to a material and thickness and carries provenance.',
	'palette.nothingRemembered': 'nothing remembered yet',
	'palette.clickHintOne': 'Click a colour: that one shape moves to that layer',
	'palette.clickHintMany': 'Click a colour: those {n} shapes move to that layer',
	'palette.clickHintNew': 'Click a colour: what you draw next lands in it',
	'palette.inUse': 'in use',
	'palette.newWork': 'new work',

	// ── Job panel ─────────────────────────────────────────────────────────────────
	'job.frame.title': 'Send the head around the outline of your work — the laser stays off',
	'job.origin.clearTitle': 'Back to the machine\'s own zero',
	'job.noRaster.title': 'This server cannot burn raster layers.',
	'job.autofocus': 'Autofocus is started on the machine itself.',
	'job.spotName.placeholder': 'e.g. corner of the jig',
	'job.adjust.resetTitle': 'Back to what the layer says',
	'job.progressAria': 'Progress of the job',
	'job.forgetSpot': 'Forget this position',
	'job.nothing.title': 'There is nothing to burn',
	'job.adjust.title': 'Adjust during the job',
	'job.token.placeholder': 'paste the token',
	'job.checklist.air': 'Extraction and air assist on',
	'job.layerAria': 'Layer {n}',
	'job.checklist.workpiece': 'Workpiece is clamped and flat',
	'job.jog.down': 'Move down',
	'job.jog.right': 'Move right',
	'job.printcut': 'Print and cut',
	'job.printcut.off': 'Off. The work burns where you drew it. Pick the two marks that are on your material as well — printed crosses, drilled holes, an engraved corner — and point them out here.',
	'job.printcut.needsTwo': 'Select exactly two shapes on the canvas first',
	'job.printcut.use': 'Use the two selected shapes',
	'job.printcut.useTitle': 'Take these two shapes as the marks that are on the material',
	'job.printcut.driveTo': {
		one: 'One of the two marks has been measured. Drive the head over the other one and press the button.',
		other: 'Drive the head over a mark and press the button for it. Both are needed: with one point there is no angle.'
	},
	'job.printcut.capture': 'The head is on mark {n}',
	'job.printcut.again': 'Mark {n} again',
	'job.printcut.captureTitle': 'Take {x}, {y} mm as the place of mark {n}',
	'job.printcut.pose': 'mark 1 has moved that far, and the sheet lies {angle}° out',
	'job.printcut.instead': 'The job goes onto the sheet as measured. The zero point stays out of it while this is on: both at once would shift the work twice.',
	'job.printcut.clear': 'Forget the alignment',
	'job.printcut.clearTitle': 'The next job burns where it was drawn again',
	'job.printcut.lapsed.marks': 'The alignment has lapsed: one of the two marks is no longer in the drawing. Point two marks out again.',
	'job.printcut.lapsed.machine': 'The alignment has lapsed: it was measured on another machine, and those coordinates mean nothing on this bed.',
	'job.noPosition.printcut': 'The machine does not say where its head is, so there is nothing to take',
	'job.workOrigin': 'Zero point of the work',
	'job.jog.up': 'Move up',
	'job.jog.left': 'Move left',
	'job.keepSpot': 'Keep this spot',
	'job.checklist.title': 'Run through this',
	'job.estimatedTime': 'Estimated time',
	// A series is one plate on the bed and an afternoon in front of you, and the clock
	// above this line is about the plate. The count and the total both come from
	// `/api/job/estimate` (`burns_left`, `seconds_total`), so the panel never
	// multiplies anything itself: two places counting plates is how a number on the
	// screen comes to be nobody's.
	'job.seriesLeft': 'This is the plate now on the bed; the {burns} still to go take about {time} together.',
	'job.toOrigin': 'To origin',
	'job.toPoint': 'Go to a point',
	'job.keep': 'Keep',
	'job.unlock': 'Unlock',
	'job.toZero': 'To zero point',
	'job.clearZero': 'Clear',
	'job.material': 'Material',
	'job.frame': 'Show frame',
	'job.adjust.reset': 'Reset',
	'job.checklist.lid': 'Lid closed',
	'job.calculating': 'calculating…',
	'job.origin': 'Zero point',
	'job.move': 'Move',
	'job.home': 'Home',
	'job.first': 'First',
	'job.layer': 'Layer',
	'job.source': 'Source',
	'job.section.preparing': 'Getting ready',
	'job.section.theJob': 'The job',
	'job.token.rejected': 'This token is being refused',
	'job.token.label': 'Token for write actions',
	'job.token.rejectedHint': 'Look in the window the engine runs in: that is where the token for this server is printed.',
	'job.token.hint': 'The engine logs the token when the API starts.',
	'job.noRaster.one': 'The layer "{label}" produces nothing — the converter from raster area to laser lines lives in the wxPython version of the engine. The clock below therefore counts zero for it. Make it an engrave or cut layer, or burn this job from the wxPython UI.',
	'job.noRaster.many': '{n} raster layers produce nothing — the converter from raster area to laser lines lives in the wxPython version of the engine. The clock below therefore counts zero for them. Make them engrave or cut layers, or burn this job from the wxPython UI.',
	'job.material.none': 'not filled in for this sheet',
	'job.origin.here': 'what you draw at 0,0 burns here. The sheet moves along: the zero point is the corner of the material lying in it.',
	'job.origin.off': 'Off: the work burns at the coordinates you drew it on.',
	'job.origin.set': 'Zero point here',
	'job.origin.reset': 'Zero point here again',
	'job.notResponding': 'The machine is not responding. This job goes into the queue and only starts once the connection is there — switch it on or check the cable.',
	'job.estimateSlow': 'The engine builds the whole cut plan to estimate this; on a heavy design that takes a moment. Starting works regardless — the machine does not wait for it.',
	'job.queueAhead': {
		one: 'There is already 1 job in the queue; this one goes behind it.',
		other: 'There are already {n} jobs in the queue; this one goes behind them.'
	},
	'job.risky': {
		one: 'One layer uses settings that were not measured with a test grid. On unknown material: try a scrap first.',
		other: '{n} layers use settings that were not measured with a test grid. On unknown material: try a scrap first.'
	},
	'job.nothing.body': 'The bed is empty, or everything on it sits in a layer that does not burn. Draw or import something, give it a layer, and come back here.',
	'job.startJob': 'Start job',
	'job.starting': 'Working…',
	'job.resume': 'Resume',
	'job.pause': 'Pause',
	'job.stop': 'Stop',
	'job.stop.onMachine': 'on the machine',
	'job.stepSize': 'Step size',
	'job.startNow': 'Start now',
	'job.steps': '{done} / {total} steps',
	'job.pass': 'pass {n} of {total}',
	'job.elapsed': '{time} elapsed',
	'job.clearQueue': 'Clear queue ({n})',
	'job.queueEmpty': 'The queue is already empty',
	'job.keysWork': '{pause} and {stop} work everywhere in the app, as long as this window is in front — outside it a browser cannot receive keystrokes.',
	'job.machineControls': 'Operate machine',
	'job.machineControls.notNow': 'not during a job',
	'job.jog.z': 'Head {step} mm {direction}',
	'job.jog.zUp': 'up',
	'job.jog.zDown': 'down',
	'job.toOrigin.title': 'Send the head to 0,0 of the bed',
	'job.toSpot.title': 'Go to {x}, {y} mm',
	'job.forgetSpotAria': 'Forget {name}',
	'job.noPosition.keep': 'This machine reports no position, so there is nothing to keep',
	'job.noPosition.origin': 'This machine reports no position, so no zero point can be set',
	'job.keepSpot.title': 'Keep {x}, {y} mm under a name',
	'job.origin.setTitle': 'Put the zero point at {x}, {y} mm — where the head is now',
	'job.origin.goTitle': 'Send the head to the zero point',
	'job.adjust.asDesigned': 'as designed',
	'job.adjust.more': 'More {what}',
	'job.adjust.less': 'Less {what}',
	'job.adjust.hint': 'This scales what the machine is doing right now. The layer keeps its own setting — which may come from a preset, and then it is evidence.',
	'job.zAxis.noCommand': 'This profile reports a Z axis, but the driver for this machine has no command to move the head. Focusing is done by hand.',
	'job.noPause': 'This device has no pause/resume — those commands come from the device service.',
	'job.pause.keepGoing': 'Carry on where the head left off',
	'job.pause.stopHead': 'Stop the head without losing the job',
	'job.stop.now': 'Abort the job right away',
	'job.stop.noServer': 'No connection to OpenKerf — this button will not arrive. Stopping is only possible with the emergency stop on the machine now.',
	'job.blocked.noServer': 'No connection to OpenKerf — the command will not arrive',
	'job.blocked.token': 'Fill in a valid token first',
	'job.blocked.noServerMove': 'No connection to OpenKerf — the head will not move from here',
	'job.blocked.duringJob': 'Not possible while a job is running',
	'job.adjust.power': 'Power',
	'job.adjust.speed': 'Speed',
	'preset.source.measured': 'measured',
	'preset.source.unmeasured': 'not measured',
	'preset.source.extrapolated': 'extrapolated — not measured',
	'preset.source.manual': 'set by hand',
	'preset.source.someoneElse': 'from someone else\'s machine',
	'preset.source.otherMaterial': 'other material',
	'preset.source.otherThickness': 'other thickness',

	// ── Queue ─────────────────────────────────────────────────────────────────────
	'queue.messages': 'Messages from the machine',
	'queue.messages.none': 'Nothing reported yet.',
	'queue.elapsed': 'Elapsed',
	'queue.remaining': 'remaining',
	'queue.title': 'Queue',
	'queue.total': 'Total',
	'queue.passes': 'Passes',
	'queue.unknown': 'Unknown — without a connection we cannot tell what is in the queue. What you read here is from just before the silence.',
	'queue.noQueue': 'This machine reports no queue. Starting works; you just will not see the progress.',
	'queue.after': {
		one: 'One more job after this one. They start in this order.',
		other: '{n} more jobs after this one. They start in this order.'
	},
	'queue.messages.hint': 'Technical messages from the engine. Handy when hunting a fault; otherwise you do not need them.',

	// ── Job preview ───────────────────────────────────────────────────────────────
	'preview.onSheet': 'on {name}, {width} by {height} millimetres',
	'preview.countOutsideBed': '{n} lie outside the bed',
	'preview.countOutsideSheet': '{n} fall outside the sheet',
	'preview.countNoLayer': '{n} sit in no layer',
	'preview.sheetFallback': 'the sheet',
	'preview.whatBurns': 'What gets burned',
	'preview.bigger': 'View larger',
	'preview.outsideBed.title': 'Outside the bed.',
	'preview.work': 'work',
	'preview.nothingOnSheet': 'Nothing on the sheet.',
	'preview.shapesBurn': {
		one: '1 shape burns',
		other: '{n} shapes burn'
	},
	'preview.viewLargerAria': '{description} View larger.',
	'preview.outsideBed.body': {
		one: 'One shape lies outside the reach of the machine{reach}. The head does not go there: move or scale it.',
		other: '{n} shapes lie outside the reach of the machine{reach}. The head does not go there: move or scale them.'
	},
	'preview.reach': ', which reaches to {width} × {height} mm',
	'preview.outsideSheet': {
		one: 'One shape falls outside {sheet}. There is no material there — whatever sticks out burns into your honeycomb or your bench.',
		other: '{n} shapes fall outside {sheet}. There is no material there — whatever sticks out burns into your honeycomb or your bench.'
	},
	'preview.silent': {
		one: 'One shape sits in no layer that burns — dashed grey above. The machine skips it.',
		other: '{n} shapes sit in no layer that burns — dashed grey above. The machine skips them.'
	},

	// ── The cut path (gap S1 / L1) ────────────────────────────────────────────────
	'cutpath.title': 'Cut path',
	'cutpath.show': 'Show cut path',
	'cutpath.show.title':
		'See in what order the machine burns, where the head travels without burning, and how the time builds up',
	'cutpath.unreachable': 'The path cannot be fetched while the server is away.',
	'cutpath.building': 'Working out the path…',
	'cutpath.building.slow':
		'This is a big design, so the path takes a while. Starting the job does not wait for it.',
	'cutpath.empty': 'Nothing is going to be burned, so there is no path to walk.',
	'cutpath.busy':
		'The job itself needed the cut plan, so the path had to give way. It comes back on its own.',
	'cutpath.tooBig':
		'This design is too heavy to walk through beforehand: {n} segments against a ceiling of {limit}. Building the path would cost seconds to a minute of work, and the answer would run to megabytes.',
	'cutpath.tooBig.hint':
		'Switch a layer off or split the work over sheets, and the path appears for what is left.',
	'cutpath.failed': 'The path could not be built. The engine said: {message}',
	'cutpath.limited':
		'This path holds {n} steps, more than the {limit} this window can draw at once.',
	'cutpath.limited.totals':
		'The totals are the whole job: {time} on the clock and {travel} mm of travel.',
	'cutpath.aria': 'The cut path over the bed: {n} steps in {total}.',
	'cutpath.status.ready': 'The path is ready: {n} steps in {total}.',
	'cutpath.play': 'Play',
	'cutpath.pause': 'Pause',
	'cutpath.scrub': 'Move through the job',
	// At a job of about twenty seconds the rate rounds to 1, and "runs 1 times faster"
	// was on screen. One is not a multiplier, it is the machine's own pace.
	'cutpath.rate': {
		one: 'The replay runs at about the speed of the machine.',
		other: 'The replay runs {n} times faster than the machine.'
	},
	'cutpath.sum.time': 'On the clock',
	'cutpath.sum.burning': 'Burning',
	'cutpath.sum.travelling': 'Travelling',
	'cutpath.sum.contours': 'Contours',
	'cutpath.tooManyNumbers':
		'There are {n} contours, too many to number on the drawing. Play the path to see the order.',
	'cutpath.cluster':
		'Numbers that would cover each other are drawn as one: “7+3” is contour 7 and three more that start in the same spot. The list below names every contour in order.',
	'cutpath.order.title': 'The order, in words ({n} contours)',
	'cutpath.order.item': '{n}: {layer}, {w} × {h} mm, starting at {x}, {y}.',
	'cutpath.order.itemPasses':
		'{n}: {layer}, {w} × {h} mm, starting at {x}, {y}, walked {passes} times.',
	'cutpath.order.noLayer': 'no layer',
	'cutpath.legend.travel': 'Moving without burning',
	'cutpath.honest.title': 'What this cannot promise.',
	'cutpath.honest.body':
		'The order and the travel are exactly what the machine has been given. The clock is the cut plan’s own arithmetic, and the machine can be slower: the engine mixes its burn model with the pace measured on a finished pass, and neither of the two knows how your laser slows down in a corner.',
	'cutpath.honest.slower':
		'This clock also counts longer than the estimate on the start button: the plan’s accounting per step carries the engine’s allowance for acceleration and every sweep of a raster layer, and the estimate does not. Measured on nine cut squares of 30 mm: 2:01 here against 1:51 there, and on one filled area of 60 × 40 mm in a raster layer 7:30 here against 0:00 there — the estimate does not see a filled area at all.',
	'cutpath.honest.here':
		'On this design this window says {here} and the start button says {there}.',
	'cutpath.built': 'Building this path took {seconds} seconds.',

	// ── Tile run ──────────────────────────────────────────────────────────────────
	'tiles.mark': 'mark {n}',
	'tiles.layPlate': 'Lay the plate so its top-left corner can sit under the head. Jog to it and press Here.',
	'tiles.shift': 'Shift the plate {mm} mm {direction}, until the two marks can sit under the head.',
	'tiles.shiftUnknown': 'Shift the plate along until the two marks can sit under the head.',
	'tiles.jogTo': 'Jog to {mark} and press Here.',
	'tiles.hereCorner': 'Here · corner of the plate',
	'tiles.hereMark': 'Here · {mark} of {total}',
	'tiles.aria': 'Tile run',
	'tiles.progressAria': 'Progress',
	'tiles.next': 'Tile done, next',
	'tiles.burnAgain': 'Burn it again anyway',
	'tiles.burnThis': 'Burn this tile',
	'tiles.stop': 'Stop the run',
	'tiles.current': 'Tile {n} of {total}',
	'tiles.originIgnored': 'The zero point you set does not apply now: the marks decide where the burning happens.',
	'tiles.refreshWarning': 'Refresh the page and you start tapping the marks again. The marks themselves simply stay where they are.',
	'tiles.aligned': 'Aligned',
	'tiles.skew': '{degrees}° off square',
	'tiles.distanceError': '{mm} mm deviation',
	'tiles.up': 'up',
	'tiles.left': 'left',
	'tiles.noPosition': 'This machine reports no position, so Here does not know where it is.',

	// ── Job started ───────────────────────────────────────────────────────────────
	'jobStart.title': 'Job started',

	// ── Design panel ──────────────────────────────────────────────────────────────
	'panel.design': 'Design',
	'panel.selection': 'Selection',
	'panel.elements': {
		one: '1 element',
		other: '{n} elements'
	},
	'panel.empty': 'Nothing on the bed yet. Import in the top bar brings in an SVG, DXF or image; with the tools on the left you draw your own.',
	'panel.shapes': '{n} shapes',
	'panel.noLayer': 'in no layer',
	'panel.noLayer.title': 'This shape does not burn',
	'panel.layerChip': 'Layer {n}: {label}',
	'panel.clear': 'Clear',
	'panel.widthShort': 'W',
	'panel.heightShort': 'H',
	'panel.width': 'Width',
	'panel.height': 'Height',
	'panel.positionX': 'Position X',
	'panel.positionY': 'Position Y',
	'panel.inMillimetres': '{what} in millimetres',
	'panel.ratio.locked': 'Ratio locked — width and height scale together',
	'panel.ratio.free': 'Width and height apart',
	'panel.ratio.lockedShort': 'Ratio locked',
	'panel.ratio.freeShort': 'Ratio free',
	'panel.angle': 'Angle in degrees',
	'panel.angle.mixed': 'These shapes sit at different angles — turn them with the steps',
	'panel.angle.title': 'The current angle. Type a number to turn exactly to it.',
	'panel.angle.mixedNote': 'These shapes sit at different angles. The steps work; typing an angle would set them all the same, and that is rarely what you mean.',
	'panel.rotate.step': 'Rotate {angle}°',
	'panel.rotate.stepAria': 'Rotate {angle} degrees',
	'panel.anchor.since': 'Since you grabbed it: {what}',
	'panel.anchor.mirrored': 'Mirrored with respect to the original',
	'panel.anchor.back': 'Put back',
	'panel.anchor.backTitle': 'Back to how it was when you clicked this selection',
	'panel.inEffect': 'Part of effect: {label}',
	'panel.bridges': 'Bridges',
	'panel.bridges.on': 'Leave gaps in the cut',
	'panel.bridges.count': 'Number',
	'panel.bridges.length': 'Length per bridge',
	'panel.bridges.off': 'No bridges: this shape comes loose the moment the cut closes.',
	'panel.bridges.explain': '{count} gaps of {length} mm, spread over a contour of {total} mm. What is left to cut is {cut} mm.',
	'panel.bridges.explainTightest': 'Each of these {n} shapes gets {count} gaps of {length} mm. The tightest contour among them is {total} mm long, which leaves {cut} mm to cut there.',
	'panel.bridges.places': 'At {places} percent along the contour, each {length} mm long.',
	'panel.bridges.notSupported': 'This shape carries no bridges. They work on a rectangle, an ellipse, a polyline or a path — not on a line, text or an image.',
	'panel.bridges.mixed': 'These shapes have different bridges. Setting a number here gives them all the same.',
	'panel.bridges.notCut': 'This shape is not in a cut layer, so the gaps change nothing yet. They only matter to a cut.',
	'panel.splittable': {
		one: 'This shape consists of {pieces} loose pieces. An export from a CAD program is often one path; the pieces can only be clicked separately after splitting.',
		other: 'These {n} shapes consist of {pieces} loose pieces. An export from a CAD program is often one path; the pieces can only be clicked separately after splitting.'
	},
	'panel.dragHint': 'Drag the box to move, the corners to scale. Arrow keys: 0.1 mm, with shift 1 mm.',
	'panel.needsToken': 'Editing requires a token.',
	'panel.nothingSelected': 'Nothing selected. Click a shape on the canvas, or drag a box to grab several.',
	'panel.layers': 'Layers',
	'panel.burnOrder': '1 → {n} = burn order',
	'panel.list': 'List',
	'panel.list.title': 'Operations on the whole list',
	'panel.list.sort': 'Put in burn order',
	'panel.list.sort.explain': 'Raster, engrave, dots, cut last',
	'panel.list.sort.already': 'The layers are already in burn order',
	'panel.list.prune': 'Clear out empty layers',
	'panel.list.pruneCount': {
		one: 'Clear out 1 empty layer',
		other: 'Clear out {n} empty layers'
	},
	'panel.list.prune.explain': 'Shapes and filled layers stay',
	'panel.list.prune.none': 'There is no empty layer in the list',
	'panel.list.dropAll': 'Remove all layers…',
	'panel.density.compact': 'Compact list — click for roomy rows',
	'panel.density.roomy': 'Roomy list — click for compact rows',
	'panel.density.compactLabel': 'Compact',
	'panel.density.roomyLabel': 'Roomy',
	'panel.empties': {
		one: 'One layer is empty.',
		other: '{n} layers are empty.'
	},
	'panel.tidyUp': 'Clear out',
	'panel.dropAll.ask': 'Throw away all {n} layers?',
	'panel.dropAll.oneShape': 'The shape on the bed stays, in no layer after this.',
	'panel.dropAll.shapes': 'The {n} shapes on the bed stay, in no layer after this.',
	'panel.dropAll.noShapes': 'There is no shape on the bed yet.',
	'panel.dropAll.gridsStay': 'Test grids stay.',
	'panel.dropAll.confirm': 'Throw away all layers',
	'panel.noLayers': 'No layers yet. A layer is an operation — cut, engrave or raster — with a speed and power of its own. Make one below; then select a shape to put into it.',
	'panel.layer.dragAria': 'Order of {label} — drag, or use the arrow keys',
	'panel.layer.dragTitle': 'Drag to reorder (or arrow up/down). Right-click for burning earlier or later.',
	'panel.layer.chipTitle': 'Layer {n} of {total} — settings and colour',
	'panel.layer.openAria': 'Open layer {label}',
	'panel.layer.count': {
		one: '1 shape in this layer',
		other: '{n} shapes in this layer'
	},
	'panel.layer.burnsOn': 'Burns along — click to switch off',
	'panel.layer.burnsOff': 'Switched off — click to burn along',
	'panel.layer.burnsAria': 'Burn along for {label}',
	'panel.layer.moreTitle': 'More for {label} — or right-click the row',
	'panel.layer.moreAria': 'More for {label}',
	'panel.layer.valuesTitle': 'Speed, power and passes — click to adjust them',
	'panel.layer.valuesAria': 'Settings of {label}: {values}',
	'panel.layer.speedAria': 'Speed of {label} in mm per second',
	'panel.layer.powerAria': 'Power of {label} in per cent',
	'panel.layer.passesAria': 'Number of passes of {label}',
	'panel.tag.doesNotBurn': 'does not burn',
	'panel.tag.hidden': 'hidden',
	'panel.tag.air': 'air',
	'panel.air.on': 'Air assist is on — click to switch off',
	'panel.air.off': 'Air assist is off — click to switch on',
	'panel.air.aria': 'Air assist during {label}',
	'panel.assign.title': 'Put the selection in {label}',
	'panel.assign.label': 'into this',
	'panel.colourAria': 'Colour of {label}',
	'panel.swatch': 'Layer colour {colour}',
	'panel.memory.remembered': '{values} remembered for this colour on {machine} — a next layer in this colour starts from it. Not a preset: this carries no provenance.',
	'panel.memory.thisMachine': 'this machine',
	'panel.memory.none': 'This colour has remembered nothing on this machine yet. As soon as you adjust speed or power, a next layer in this colour starts from that.',
	'panel.name': 'Name',
	'panel.kind': 'Kind of operation',
	'panel.kindOf': 'Kind of operation of {label}',
	'panel.kind.hint': 'The shapes and the settings stay; only what the machine does with them changes.',
	'panel.visibleOnCanvas': 'Visible on the canvas (changes nothing about the job)',
	'panel.airDuring': 'Air assist during this layer',
	'panel.kind.cut': 'Cut',
	'panel.kind.engrave': 'Engrave',
	'panel.kind.raster': 'Raster',
	'panel.kind.dots': 'Dots',
	'panel.kind.cutNoun': 'Cut layer',
	'panel.kind.engraveNoun': 'Engrave layer',
	'panel.kind.rasterNoun': 'Raster layer',
	'panel.kind.dotsNoun': 'Dots layer',
	'panel.kind.layerNoun': 'Layer',
	'panel.zStep': 'Drop per pass',
	'panel.zStep.off': 'Off. Every pass cuts at the same height.',
	'panel.zStep.onePass': 'Does nothing yet: this layer burns one pass. Raise the number of passes to cut in layers.',
	'panel.zStep.explain': '{passes}× cutting, {step} mm {direction} each time. After the last pass the head goes back to the height it started at.',
	'panel.zStep.lower': 'lower',
	'panel.zStep.higher': 'higher',
	'panel.overscan': 'Overscan',
	'panel.bidirectional': 'Engrave back and forth',
	'panel.order': 'Order · {kind}',
	'panel.order.earlier': 'Earlier',
	'panel.order.later': 'Later',
	'panel.order.burnEarlier': 'Burn earlier',
	'panel.order.burnLater': 'Burn later',
	'panel.drop.ask': 'Throw away “{label}”? The shapes stay, the settings do not.',
	'panel.drop.confirm': 'Remove',
	'panel.drop.layer': 'Remove layer…',
	'panel.grid.title': 'Test grid #{id}',
	'panel.grid.cells': '{n} cells · speed and power are fixed',
	'panel.grid.showCells': 'Show the cells of grid {id}',
	'panel.grid.cell': 'row {row}, column {column}',
	'panel.grid.remove': 'Remove grid from the design',
	'panel.addLayer': 'Add layer',
	'panel.assign.hint': '“{into}” puts the current selection into that layer.',
	'panel.assign.hintNone': 'Select a shape on the canvas; then you can put it into a layer here with one tap.',
	'panel.moved.rotated': 'rotated to {angle}°',
	'panel.moved.mirrored': 'mirrored',
	'panel.moved.arranged': 'arranged',
	'panel.moved.scaled': 'scaled',
	'panel.moved.moved': 'moved',
	'panel.moved.changed': 'changed',
	'panel.type.cut': 'cut',
	'panel.type.engrave': 'engrave',
	'panel.type.grid': 'raster',
	'panel.type.image': 'image',
	'panel.type.dots': 'dots',

	// ── Notifications ─────────────────────────────────────────────────────────────
	'notify.permission.unsupported': 'This browser cannot show notifications.',
	'notify.permission.default': 'The browser has not been asked yet.',
	'notify.permission.granted': 'The browser may show notifications.',
	'notify.permission.denied': 'The browser blocks notifications for this site.',
	'notify.refused': 'The browser refused to show the notification. With an installed app it often helps to open it again.',
	'notify.test.title': 'Test notification',
	'notify.test.body': 'This is what a notification looks like. Done or fault arrives the same way.',
	'notify.ask.title': 'Shall I tell you when this job is done?',
	'notify.ask.body': 'Then you do not have to sit and watch it. You also get word on a fault, or when the counter stops moving. OpenKerf never intervenes by itself.',
	'notify.ask.notNow': 'Not now',
	'notify.ask.turnOn': 'Turn on notifications',
	'notify.ask.after': 'The browser asks for permission itself after this. You can always turn it on later under Notifications.',
	'notify.switch.title': 'Tell me when a job finishes or gets stuck',
	'notify.switch.body': 'Even when this tab is in the background.',
	'notify.askPermission': 'Ask for permission',
	'notify.blocked.howto': 'Click the padlock or the ⓘ sign on the left of the address bar, set Notifications to Allow, and refresh this page. On a phone it is under the browser\'s site settings.',
	'notify.sendTest': 'Send a test notification',
	'notify.last': 'Last notification {time} — “{title}”',
	'notify.last.notShown': '(not shown as a pop-up: the screen was on, or notifications are off)',
	'notify.limits': 'OpenKerf reports, but does not intervene: there is no flame or smoke detection. The camera hangs off the computer and not off the machine, so we cannot see whether something is going wrong in the bed. Stay near a running job.',
	'notify.job.unnamed': 'The job',
	'notify.job.done': 'Job done',
	'notify.job.doneBody': '{name} — {time} of burning.',
	'notify.job.endedBody': '{name} has finished.',
	'notify.lost.title': 'The connection dropped during a job',
	'notify.lost.body': 'OpenKerf can no longer reach the server while it was burning. The machine is probably still going; stopping is only possible on the machine itself.',
	'notify.stalled.title': 'The job is not making progress',
	'notify.stalled.body': 'The counter has been standing still at {percent}% for {minutes} minutes.',
	'notify.stalled.advice': 'Check whether the machine is still moving. All we know is that the number is not changing.',
	'fault.noConnection': 'No connection to the machine',
	'fault.usb.none': 'There was no USB connection to the machine.',
	'fault.usb.none.advice': 'So nothing has been burned. Check the cable and the power, and try again.',
	'fault.usb.failed': 'The connection to the machine was not established.',
	'fault.usb.failed.advice': 'Check the cable and the power. Nothing has been sent to the laser.',
	'fault.usb.notFound': 'No controller was found on the USB port.',
	'fault.usb.notFound.advice': 'Check whether the machine is on and whether the cable is in this computer.',
	'fault.usb.noDriver': 'The USB driver the engine needs is missing on this computer.',
	'fault.usb.noDriver.advice': 'Install LibUSB. Until then OpenKerf cannot drive this machine.',
	'fault.usb.noPermission': 'The operating system gives no access to the USB port.',
	'fault.usb.noPermission.advice': 'Give the engine USB rights; without them the machine stays unreachable.',
	'fault.usb.busy': 'Another program is holding the machine\'s USB port.',
	'fault.usb.busy.advice': 'Close other laser software (LightBurn, RDWorks) and try again.',
	'fault.usb.serial': 'The machine asks for confirmation of its serial number.',
	'fault.usb.serial.advice': 'Confirm the serial number in the engine\'s settings.',

	// ── Material library ──────────────────────────────────────────────────────────
	'count.materials': { one: '1 material', other: '{n} materials' },
	'count.presets': { one: '1 setting', other: '{n} settings' },
	'count.machines': { one: '1 machine profile', other: '{n} machine profiles' },
	'count.testGrids': { one: '1 test grid', other: '{n} test grids' },
	'count.photos': { one: '1 photo', other: '{n} photos' },
	'count.rasters': { one: '1 grid', other: '{n} grids' },
	'count.burns': { one: '1 burn', other: '{n} burns' },
	'count.rows': { one: '1 row', other: '{n} rows' },
	'count.recipes': { one: '1 recipe', other: '{n} recipes' },
	'import.title': 'This is what is going to happen',
	'import.exportedAt': 'exported {when}',
	'import.yoursNow': 'Your library now: {materials} · {presets} · {grids}',
	'import.merge': 'Merge',
	'import.merge.explain': 'What you have stays; what is not there yet is added.',
	'import.replace': 'Replace',
	'import.replace.explain': 'Your current library goes away and becomes this file.',
	'import.newMaterials': { one: '1 new material', other: '{n} new materials' },
	'import.recognised': {
		one: '1 material recognised as one you already have',
		other: '{n} materials recognised as ones you already have'
	},
	'import.addedPresets': { one: '1 setting added', other: '{n} settings added' },
	'import.identical': {
		one: '1 setting is identical — that one stays as it is',
		other: '{n} settings are identical — those stay as they are'
	},
	'import.addedGrids': { one: '1 test grid added', other: '{n} test grids added' },
	'import.withPhotos': 'with the photos that belong to them',
	'import.addedMachines': { one: '1 machine profile added', other: '{n} machine profiles added' },
	'import.nothingNew': 'Nothing is added: this file is already entirely in your library.',
	'import.sameBoard': 'Same board, different name?',
	'import.sameBoard.body': 'These materials from the file look like something you already have. Merging puts their settings with the material you already know; leave it and you get two.',
	'import.mergeWith': 'Merge {name} with {match}',
	'import.conflicts': { one: '1 setting clashes', other: '{n} settings clash' },
	'import.conflicts.body': 'Same board, same cut, different numbers. Choose which wins — your own values were measured on your machine.',
	'import.keepMine': 'Keep my values',
	'import.takeTheirs': 'Take the ones from the file',
	'import.mine': 'Mine',
	'import.theirs': 'From the file',
	'import.strongerEvidence': 'The one from the file was burned on a test grid; yours is {source}.',
	'import.wipe.title': 'This wipes what you have now',
	'import.wipe.body': '{materials}, {presets} and {grids} disappear, along with the photos that belong to them. That cannot be undone.',
	'import.wipe.backup': 'Do you want to be able to get it back?',
	'import.wipe.export': 'Export it first',
	'import.wipe.confirm': 'Yes, wipe my library and put this file in its place.',
	'import.doReplace': 'Wipe and import',
	'import.done.replaced': 'Library replaced',
	'import.done.merged': 'Library merged',
	'import.done.updated': '{n} updated',
	'import.done.skipped': '{n} left unchanged',
	'import.done.hidden': 'Some of it belongs to another machine; switch off “Only {machine}” to see it.',
	'library.evidence.lost': 'This setting says it was measured, but no test grid hangs off it — because it came from an import, for instance. So the evidence is no longer with it.',
	'library.evidence.none': 'No test grid: these values were not measured but entered.',
	'library.makeGrid': 'Make a test grid',
	'library.thickness': 'Thickness',
	'library.note.placeholder': 'e.g. clean underside, no scorch mark',
	'library.machineProfile': 'Machine profile',
	'library.search': 'Search material, thickness or operation',
	'library.searchAria': 'Search the library',
	'library.newMaterial': 'New material',
	'library.onlyMaterial': 'Only {material}',
	'library.onlyMaterial.why': '— from this sheet',
	'library.onlyMachine': 'Only {machine}',
	'library.applyTo': 'Apply to',
	'library.layerOption': 'Layer {n} · {label}',
	'library.noLayer': 'There is no layer to put a setting on yet. Make one in the Layers tab; after that one tap puts the speed and power on it.',
	'library.material.placeholder': 'e.g. birch plywood',
	'library.welcome.title': 'No materials yet',
	'library.welcome.body': 'Here you record what works on your own laser: a speed and a power per material and thickness, with the photo of the test grid they come from. Next time 3 mm birch is one tap instead of working it out again.',
	'library.welcome.first': 'Add the first material',
	'library.welcome.presetariat':
		'Or take a starting point from the shared catalogue — that is the offer at the top of this window.',
	'library.nothingFound': 'Nothing found for “{query}”',
	'library.nothingFound.body': 'The library holds {materials}. Search on the material name itself — “birch” finds more than “birch 3mm cut”.',
	'library.clearSearch': 'Clear the search',
	'library.materials': 'Materials',
	'library.recent': 'Recently used',
	'library.onlyThis': 'Show only this material',
	'library.onSheet': 'on the sheet',
	'library.onSheet.title': 'The material of this sheet',
	'library.pickMaterial': 'Pick a material on the left for everything that goes with it.',
	'library.allThicknesses': 'All thicknesses',
	'library.noThickness': 'no thickness',
	'library.noPresets': 'No settings for {material} yet. A test grid burns a series of squares on this material; from the best square you make a setting that ends up here.',
	'library.noneForThickness': 'No setting for {thickness} mm. Pick another thickness, or burn a test grid for it.',
	'library.manual': 'Add a setting by hand',
	'library.material': 'Material',
	'library.pickMaterialOption': 'Pick a material',
	'library.filteredMaterial': 'Filtered material',
	'library.operation': 'Operation',
	'library.manual.note': 'Entered by hand means: not measured. This setting therefore gets the “Manual” badge.',
	'library.profiles': 'Machine profiles ({n})',
	'library.profiles.why': 'A setting is only reusable when you know which machine it was made on — which is why the profile stands apart from the setting.',
	// Two states, not one. A machine that is not here may come back when you plug it in;
	// a profile that points at no machine at all is one somebody typed or one this
	// library let go of when its slot went to another laser, and its way out is a merge.
	'library.profile.deviceGone': 'machine not here',
	'library.profile.deviceGone.title':
		'No machine the engine knows about belongs to this profile. Plug the laser in, or its settings were wiped.',
	'library.profile.noDevice': 'no machine',
	'library.profile.noDevice.title':
		'This profile points at no machine at all. Merge it into the machine it belongs to.',
	'library.profile.tidy': 'Clear out',
	// Still the placeholder in the wizard's name step, where naming a machine is the
	// whole point. It is no longer offered here: a form in this window that could create
	// a profile with a tube power and no machine behind it is exactly how a phantom
	// called `5030 CO2` — the app's own example — came to hold twenty-seven settings.
	'library.machine.placeholder': 'e.g. 5030 CO2',
	'library.profile.mergeInto': 'Merge into {machine}',
	'library.profile.mergeInto.why':
		'Two profiles for one laser: the settings, the boards and the tube power move to {machine}, and this row goes.',
	'library.exchange': 'Exchange the library',
	'library.exchange.body': 'One file with your materials, settings, machine profiles and the photos of your test grids — for a backup or another computer.',
	'library.export': 'Export the library',
	'library.export.nothing': 'There is nothing to export yet',
	'library.import': 'Import a library…',
	'library.mismatch.title': 'These are values for {operation}; layer {n} is a {layerKind} layer',
	'library.mismatch.tag': 'other kind',
	'library.speed': 'Speed',
	'library.power': 'Power',
	'library.passes': 'Passes',
	'library.interval': 'Line spacing',
	'library.photoAria': 'Photo of the test grid',
	'library.photo.circled': 'The test grid, with the square at row {row}, column {column} circled',
	'library.photo.title': 'Photo of the test grid these settings come from',
	'library.apply.title': 'Put speed and power on layer {n}',
	'library.apply.mismatch': 'Careful: these are values for {operation}, and layer {n} is not meant for that',
	'library.more.aria': 'More for this setting',
	'library.more.title': 'More — or right-click the row',
	'library.drop.ask': 'Throw away {thickness}{operation} of {material}?',
	'library.drop.measured': 'This one was measured on a test grid.',
	'library.drop.keep': 'Keep',
	'library.drop.confirm': 'Throw away',
	'library.source': 'Source',
	'library.sourceLine': '{badge} — {means}',
	'library.machine': 'Machine',
	'library.machine.unknown': 'Unknown — profile not linked',
	'library.grid': 'Test grid',
	'library.grid.burned': 'burned {when}',
	'library.grid.cell': 'square at row {row}, column {column}',
	'library.note': 'Note',
	'library.air': 'Air assist',
	'library.on': 'on',
	'library.off': 'off',
	'library.lastUsed': 'Last used',
	'library.photo.alt': 'Photo of test grid {id}',
	'library.photo.altCircled': 'Photo of test grid {id}, with the square at row {row}, column {column} circled',
	'library.caption.cell': 'The outline marks the square at row {row}, column {column} — that is where these values come from.',
	'library.caption.approximate': 'The alignment of this photo has not been set, so the outline is approximate — align the grid for an exact mark.',
	'library.caption.grid': 'The burned grid these values come from.',
	'library.caption.noPhoto': 'There is no photo of this grid yet. Without a photo there is nothing to read the choice off.',
	'library.addPhoto': 'Add a photo',
	'library.menu.applyTo': 'Apply to layer {n}',
	'library.menu.apply': 'Apply',
	'library.menu.needsLayer': 'Make a layer in the Layers tab first',
	'library.menu.provenance': 'Provenance and evidence',
	'library.menu.provenance.explain': 'Where these values come from',
	'library.menu.adjust': 'Adjust the values',
	'library.menu.makeGrid': 'Make a test grid for {material}',
	'library.menu.share': 'Share with Presetariat',
	'library.menu.remove': 'Remove setting',
	'library.share.failed': 'Sharing did not work.',
	// ── Offering one of your own ──────────────────────────────────────────────────
	//
	// Sharing was one press and a GitHub tab, and what went in that tab was refused by
	// the catalogue's own CI: `by` and `tier` are required over there and neither was
	// ever written. Both are answers only the reader has — a GitHub handle, and what
	// came out of the material — so the press opens a panel that says what would go out
	// and under which of the two labels, and asks for what is missing.
	'library.share.tier.measured': 'This goes in as a measurement, read off board {board}.',
	'library.share.tier.startingPoint': 'This goes in as a starting point, not as a measurement.',
	'library.share.why.notMeasured':
		'Nobody read these numbers off a test board, so the catalogue takes them as a considered guess.',
	'library.share.why.derived':
		'These numbers came out of the catalogue itself, from {id}, so they go back as a guess that leans on that entry rather than as evidence.',
	'library.share.why.boardGone':
		'The test board behind this setting is gone, and a measurement in the catalogue is followed back to its board.',
	'library.share.why.otherMachine':
		'This setting is filed under a different laser than the board it was burned on, so for this machine it is a starting point.',
	'library.share.why.noOutcome':
		'The board is still here, but nobody wrote down what came out of the material, and a speed with no outcome beside it is not something anybody else can judge.',
	'library.share.charring': 'The edge',
	'library.share.charring.pick': '— say how the edge came out —',
	'library.share.charring.none': 'Clean, no charring',
	'library.share.charring.light': 'Lightly charred',
	'library.share.charring.heavy': 'Heavily charred',
	'library.share.cutThrough': 'Cut through',
	'library.share.cutThrough.unsure': 'Rather not say',
	'library.share.cutThrough.yes': 'Yes, the piece came free',
	'library.share.cutThrough.no': 'No, it stayed attached',
	'library.share.kerf': 'Kerf',
	'library.share.outcome.why':
		'Say how it came out and this goes in as a measurement, with its board behind it. It is kept on the setting, so you are asked once.',
	'library.share.handle': 'Your GitHub handle',
	'library.share.handle.placeholder': 'e.g. jelle-t',
	'library.share.handle.why':
		'The catalogue is shared under CC BY 4.0, so every entry names who offered it — that is the credit anybody reusing it has to be able to give. It is asked once and kept on this computer.',
	'library.share.by': 'Offered as {by}.',
	'library.share.handle.change': 'Use another handle',
	'library.share.open': 'Open the proposal on GitHub',
	'library.share.open.why':
		'It opens a pre-filled proposal in a new tab, so you can read what you are about to share before anybody else does.',
	'library.share.close': 'Close this panel',
	// ── What you can do to a material ─────────────────────────────────────────────
	//
	// Adding a material was the only thing possible here, which is why this library
	// holds both `Multiplex berken` and `Berkentriplex` for one board, and why a reader
	// concluded that removing a material could not be done: the route existed and
	// nothing ever called it. All three verbs sit behind the same ⋯ the settings have.
	'library.material.more.aria': 'More for {material}',
	'library.material.menu.rename': 'Rename this material…',
	'library.material.menu.merge': 'Merge into another material…',
	'library.material.menu.remove': 'Remove this material',
	'library.material.name': 'Name of this material',
	'library.material.synonyms': 'Also called',
	'library.material.synonyms.placeholder': 'e.g. birch plywood, multiplex birch',
	'library.material.synonyms.why':
		'Names other people use for the same board, separated by commas. An imported library that calls it by one of these lands on this material instead of making a second one.',
	'library.material.merge.needsTwo': 'There is only one material to merge',
	'library.material.merge.body':
		'Everything on {material} moves over: the settings, the test boards, the recipes and the photographs. The name stays as a name the other material also answers to, so an import that still uses it lands in the right place.',
	'library.material.merge.pick': 'Merge into',
	'library.material.merge.choose': '— pick a material —',
	'library.material.merge.confirm': 'Merge',
	'library.material.remove.carries':
		'{material} carries {what}. Removing the material takes all of that with it, photographs included.',
	'library.material.remove.empty': 'Nothing hangs off {material}, so removing it loses no work.',
	'library.material.remove.sheet': {
		one: 'One sheet on the table names this material; that link is cleared, the sheet itself stays.',
		other: '{n} sheets name this material; those links are cleared, the sheets themselves stay.'
	},
	'library.material.remove.keep': 'Keep it',
	'library.material.remove.confirm': 'Remove',
	'library.material.remove.confirmAll': 'Remove it with everything on it',
	'library.filteredOut':
		'The search “{query}” hides every setting for {material}. Clear it to see them again.',
	// ── Where an imported setting comes from ──────────────────────────────────────
	//
	// The catalogue these come from is CC BY, so the credit is a condition of the copy
	// and belongs wherever the row is read. And the batch is the way back out: an import
	// you can undo is not a dump.
	'library.origin': 'Measured on',
	'library.origin.laser': '{kind}, {watt} W',
	'library.origin.unknown':
		'Not recorded. This setting came in on an import that did not say which laser it was measured on.',
	'library.credit': 'Credit',
	'library.batch.undo': 'Take this import back',
	'library.batch.undo.why':
		'Removes every setting that came in with this import, and the materials it brought along that nothing else uses.',
	'library.batch.undone': {
		one: 'One setting removed, with the materials that came in with it.',
		other: '{n} settings removed, with the materials that came in with them.'
	},
	'library.batch.kept': {
		one: 'One material stays behind: something else uses it.',
		other: '{n} materials stay behind: something else uses them.'
	},
	// ── Settings that belong to no machine ────────────────────────────────────────
	'library.strays': {
		one: 'One setting belongs to no machine, so it turns up whatever machine you are on.',
		other: '{n} settings belong to no machine, so they turn up whatever machine you are on.'
	},
	'library.strays.grids': {
		one: 'One test board belongs to no machine either.',
		other: '{n} test boards belong to no machine either.'
	},
	'library.strays.why':
		'Only you know whether these were measured on {machine}. Attaching them says they were.',
	'library.strays.adopt': 'Attach these to {machine}',

	// ── Test grid ─────────────────────────────────────────────────────────────────
	'grid.passes.unit': '× per square',
	'grid.rowsDown': 'Rows, downwards',
	'grid.columnsRight': 'Columns, to the right',
	'grid.fixedAxis': '{axis} (fixed, whole board)',
	'grid.axisRange': '{axis} ({unit})',
	'grid.from': 'from',
	'grid.to': 'to',
	'grid.stepsLabel': 'Steps',
	'grid.stepsUnit.rows': 'rows',
	'grid.stepsUnit.columns': 'columns',
	'grid.gap': 'Gap',
	'grid.measureFrom': 'Measure the position from',
	'grid.anchor.corner': 'The top-left corner of the board',
	'grid.anchor.center': 'The centre of the board',
	'grid.centerX': 'Centre X',
	'grid.centerY': 'Centre Y',
	'grid.startX': 'Start X',
	'grid.startY': 'Start Y',
	'grid.extras': 'What else goes on the board',
	'grid.extras.text': 'Engrave the caption and axis labels',
	'grid.extras.border': 'Border around the board',
	'grid.extras.noText': 'Without a caption the board is a puzzling piece of wood in two weeks — and the axis values will not be on it either.',
	'grid.extras.bothOn': 'The border runs around everything, caption included. Handy for aligning the photo later.',
	'grid.extras.borderOnly': 'The border is a line around the whole board; it makes aligning the photo easier.',
	'grid.label.speed': '{layer}: speed',
	'grid.label.power': '{layer}: power',
	'grid.caption': 'Caption on the board',
	'grid.caption.placeholder': 'e.g. test back side',
	'grid.caption.hint': 'Engraved along with it, with the material, thickness and date behind it. A board without a caption is a puzzling piece of wood in two weeks.',
	'grid.preview': 'Preview of the board',
	'grid.preview.lastValid': 'Below is your last valid board.',
	'grid.preview.overlap': 'This board falls over grid #{id}, which is still on your sheet. Move the {anchor} along.',
	'grid.anchor.centreWord': 'centre',
	'grid.anchor.startWord': 'start point',
	'grid.cells': '{n} squares',
	'grid.passesPerCell': '{n}× per square',
	'grid.ofWhich': 'Of which {size} is squares; the rest is {extras}.',
	'grid.extras.both': 'caption and border',
	'grid.extras.captionOnly': 'caption',
	'grid.extras.borderOnly2': 'border',
	'grid.burnTime': 'Burn time roughly {time}, without the captions.',
	'grid.cellTitle': '{row} by {column}',
	'grid.tooFar': 'The board starts at {position}, and that is outside the bed.',
	'grid.tooFar.labels': 'The row labels need roughly {mm} mm on the left.',
	'grid.tooFar.move': 'Move the {anchor} to the right or downwards{orText}.',
	'grid.tooFar.orText': ', or switch the caption off',
	'grid.legend.rows': 'Rows: {axis} in {unit}.',
	'grid.legend.columns': 'Columns: {axis}.',
	'grid.legend.fixed': '{axis} fixed at {value}.',
	'grid.legend.darker': 'Darker is more burning.',
	'grid.legend.deepest': 'Darker is more burning — {corner} goes deepest.',
	'grid.suggested': {
		one: 'Range suggested on the basis of 1 existing preset.',
		other: 'Range suggested on the basis of {n} existing presets.'
	},
	'grid.suggested.none': 'No presets for this combination yet; this is a broad starting point.',
	'grid.done.title': 'Grid #{id} is on the bed',
	'grid.done.body': '— {cells} squares, as one group in your design. Check the frame first, burn it after, and come back for step 3.',
	'grid.frameRunning': 'Frame is running…',
	'grid.starting': 'Starting…',
	'grid.frameDone': 'The head is tracing the outline of the bed. Is your board in the right place?',
	'grid.startDone': 'The job is in the queue. Stay with it until the board comes out of the machine.',
	'grid.watchOut': 'Careful: {what}',
	'grid.suggestRange': 'Suggest a range',
	'grid.another': 'Set up another grid',
	'grid.draw': 'Draw the grid',
	'grid.drawAnyway': 'Draw it anyway, without a material',
	'grid.drawWith': 'Draw the grid — {cells} squares, {size}',
	'grid.error.refused': 'The engine refused the grid ({status}).',
	'grid.labelLayer.caption': 'Caption',
	'grid.labelLayer.border': 'Border',
	'grid.corner.left': 'left',
	'grid.corner.right': 'right',
	'grid.corner.top': 'top',
	'grid.corner.bottom': 'bottom',
	'grid.corner': '{horizontal} {vertical}',
	'grid.time.seconds': '{n} s',
	'grid.time.minutes': '{minutes} min {seconds} s',
	'grid.time.hours': '{hours} h {minutes} min',
	'grid.block.outsideBed': {
		one: 'One shape lies outside the bed — the head does not reach there. Set Start X or Start Y higher and draw the grid again.',
		other: '{n} shapes lie outside the bed — the head does not reach there. Set Start X or Start Y higher and draw the grid again.'
	},
	'grid.watch.outsideSheet': {
		one: 'One shape falls outside the sheet: there is no material there.',
		other: '{n} shapes fall outside the sheet: there is no material there.'
	},
	'grid.steps': 'Steps of the test-grid flow',
	'grid.step.setUp': 'Set up',
	'grid.step.burn': 'Burn',
	'grid.step.photograph': 'Photograph',
	'grid.step.bestCell': 'Best square → preset',
	'grid.needsToken': 'Generating a test grid requires a token.',
	'grid.lead': 'You burn a board of squares: {columns} increases to the right, {rows} downwards. Afterwards you photograph the board — with a phone beside the machine is fine — and tap the square that turned out best. OpenKerf makes a preset out of that.',
	'grid.lead.right': '{axis} increases to the right',
	'grid.lead.down': '{axis} downwards',
	'grid.recipe': 'Recipe',
	'grid.recipe.none': '— no saved settings yet —',
	'grid.recipe.pick': '— pick a saved setting —',
	'grid.recipe.allMaterials': 'all materials',
	'grid.recipe.dontSave': 'Do not save',
	'grid.recipe.save': 'Save this…',
	'grid.recipe.namePlaceholder': 'Name, e.g. birch 3 mm cut',
	'grid.recipe.nameAria': 'Name of this recipe',
	'grid.recipe.saveFailed': 'Saving failed ({status}).',
	'grid.recipe.deleteFailed': 'Deleting failed ({status}).',
	'grid.recipe.hint': 'Saves everything on this form except the caption.',
	'grid.recipe.hint.noMaterial': 'With no material chosen this becomes a recipe for all materials.',
	'grid.recipe.hint.material': 'Belongs to the chosen material; a recipe of the same name is updated.',
	'grid.none': '— none —',
	'grid.noMaterial.title': 'Pick a material.',
	'grid.noMaterial.body': 'A preset is a statement about one particular laser on one particular material — without a material the burned board yields nothing later.',
	'grid.newMaterial.placeholder': 'New material, e.g. birch plywood',
	'grid.newMaterial.aria': 'Name of a new material',
	'grid.newMaterial.create': 'Create and choose',
	'grid.noRaster.body': 'The converter that turns a raster area into laser lines lives in the wxPython version of the engine and is missing here. A raster board comes out of the machine blank. Choose Engrave · vector or Cut, or burn this grid from the wxPython UI.',
	'grid.carriedOver': 'Settings carried over from your previous grid for this material ({date}, #{grid}). Feel free to adjust them.',
	'grid.cell': 'Square',

	// ── Generators ────────────────────────────────────────────────────────────────
	'gen.withLid': 'With a lid',
	'gen.makePanels': 'Make panels{tail}',
	'gen.underneath': 'Along the underside',
	'gen.barcode.type': 'Type',
	'genPreview.panels': '{n} panels',
	'genPreview.panelsSheets': '{n} panels · sheet 1 of {sheets}',
	'genPreview.pieces': '{n} pieces',
	'genPreview.modules': '{n} modules',
	'genPreview.bars': '{n} bars',
	'genPreview.lastValid': 'Below is your last valid shape.',
	'genPreview.aria': 'Preview of what this generator makes, {width} by {height} millimetres',
	'genPreview.sketchAria': 'Sketch of what this generator makes',
	'genPreview.calculatingAria': 'The preview is being calculated',
	'genPreview.space': 'space',
	'genPreview.offSheet': 'This falls outside the sheet.',
	'gen.title': 'Generators',
	'gen.tab.grid': 'Repeat',
	'gen.tab.radial': 'Circle',
	'gen.tab.polygon': 'Polygon',
	'gen.tab.box': 'Box',
	'gen.tab.qrcode': 'QR code',
	'gen.tab.barcode': 'Barcode',
	'gen.tab.arctext': 'Arc text',
	'gen.tab.hinge': 'Living hinge',
	'gen.tab.focus': 'Focus test',
	'gen.cannotDraw': 'The engine cannot draw this.',
	'gen.incomplete': 'Not complete yet: fill in the empty fields.',
	'gen.needsSelection': 'Select what should be repeated first.',
	'gen.grid.lead': 'Repeat the selection in rows and columns. The distance is the space between the shapes, because that is where the cut goes.',
	'gen.columns': 'Columns',
	'gen.rows': 'Rows',
	'gen.gapX': 'Space X',
	'gen.gapY': 'Space Y',
	'gen.grid.go': 'Make {n} copies{tail}',
	// The gap this closes: `grid` copies with a plain `copy(node)` and knows nothing
	// about a list, so a repeated {name} gave the same name as many times as you asked
	// for. The reason it is greyed out is the API's own sentence, `api.gen.noList` —
	// one fact, one sentence, whether you read it here or get it back from the server.
	'gen.followList': 'Each copy takes the next name from the list',
	'gen.radial.lead': 'Repeat the selection around a centre point.',
	'gen.count': 'Count',
	'gen.radius': 'Radius',
	'gen.rotateAlong': 'Rotate along',
	'gen.radial.go': 'Place around{tail}',
	'gen.polygon.lead': 'A regular polygon. Fill in an inner radius and it becomes a star.',
	'gen.corners': 'Corners',
	'gen.innerRadius': 'Inner radius',
	'gen.centreX': 'Centre X',
	'gen.centreY': 'Centre Y',
	'gen.draw': 'Draw{tail}',
	'gen.box.lead': 'Loose panels with finger joints. The sizes are outside sizes; the kerf is added to the teeth because the laser takes material off both sides. If it does not fit on one sheet, the rest goes to a next sheet.',
	'gen.width': 'Width',
	'gen.depth': 'Depth',
	'gen.height': 'Height',
	'gen.materialThickness': 'Material thickness',
	'gen.finger': 'Finger',
	'gen.kerf': 'Kerf',
	'gen.spreadSheets': 'Spread over sheets when it does not fit',
	'gen.qr.lead': 'A QR code as areas, not as a picture: engraved bitmaps often come out vague on wood, filled squares do not.',
	'gen.content': 'Content',
	'gen.size': 'Size',
	'gen.barcode.lead': 'A barcode as areas. EAN and UPC make demands on length and check digit; if it does not add up the app says so instead of making a code that will not scan.',
	'gen.arc.lead': 'Text along an arc, for a round sign or a lid. Note: after this it is a path and no longer text — the engine would otherwise render the text straight again on the next change and wipe the arc away.',
	'gen.text': 'Text',
	'gen.letterHeight': 'Letter height',
	'gen.font': 'Font',
	'gen.font.default': 'Default',
	'gen.place': 'Place{tail}',
	'gen.preview.sketch': 'Sketch, not to scale',
	'gen.preview.typeSomething': 'Type something and it appears here',
	'gen.preview.calculating': 'Calculating…',
	'gen.tail.sheets': '{parts} on this sheet, {sheets} sheets',
	'gen.tail.fits': '{parts} pieces, fits on this sheet',
	'gen.tail.size': '{width} × {height} mm',
	'gen.hinge.lead': 'A field of slits that lets rigid sheet material bend. The slits lie across, and a sheet bends around a line parallel to its slits, so this one curls from top to bottom. Turn the group a quarter afterwards and it bends the other way.',
	'gen.hinge.pattern': 'Pattern',
	'gen.hinge.straight': 'Straight slits',
	'gen.hinge.staggered': 'Staggered rows',
	'gen.hinge.wavy': 'Wavy slits',
	'gen.hinge.slit': 'Slit length',
	'gen.hinge.gap': 'Gap in a row',
	'gen.hinge.rows': 'Between rows',
	'gen.hinge.material': 'Between two slits in a row {gap} of material stays behind, and between two rows {row}. That bridge is what twists, and what breaks.',
	'gen.hinge.fromSelection': 'Fill the area of the selected shape',
	'gen.hinge.noSelection': 'Select a shape first to use its area',
	'gen.hinge.left': 'Left',
	'gen.hinge.top': 'Top',
	'gen.hinge.go': 'Make the hinge{tail}',
	'gen.focus.lead':
		'The same short line burned at a series of heights, so you can see where this lens actually focuses. Burn the board, look for the thinnest and darkest mark, and set the head at the height written under it.',
	'gen.focus.from': 'Sweep start',
	'gen.focus.to': 'Sweep end',
	'gen.focus.marks': 'Marks',
	'gen.focus.mark': 'Mark length',
	'gen.focus.gap': 'Space between marks',
	'gen.focus.text': 'Burn the height under every mark',
	'gen.focus.direction': 'The numbers are offsets from the height the head is at when the job starts: a plus drops the head, a minus raises it. Afterwards it goes back to where it began.',
	'gen.focus.step': '{step} between two marks, over a sweep of {span}.',
	'gen.focus.go': 'Make the board{tail}',
	'genPreview.marks': '{n} marks, {step} apart in height.',
	'genPreview.slits': '{n} slits in {rows} rows',

	// ── Edit notices ──────────────────────────────────────────────────────────────
	'notice.corners.skipped': {
		one: 'One corner was skipped: the sides are too short for it, or an arc meets there.',
		other: '{n} corners were skipped: the sides are too short for it, or an arc meets there.'
	},
	'notice.split.done': '{n} shapes — clickable separately.',
	'notice.split.nothing': 'This shape consists of one piece; there is nothing to split.',
	'notice.import.added': {
		one: '1 shape imported and selected — drag it into place.',
		other: '{n} shapes imported and selected — drag them into place.'
	},
	'notice.fill.filled': {
		one: '1 shape filled — a raster layer now burns the area.',
		other: '{n} shapes filled — a raster layer now burns the area.'
	},
	'notice.fill.cleared': {
		one: 'Fill removed from 1 shape.',
		other: 'Fill removed from {n} shapes.'
	},
	'notice.bridges.done': {
		one: 'One shape got {count} bridges of {length} mm.',
		other: '{n} shapes got {count} bridges of {length} mm.'
	},
	'notice.bridges.doneSkipped': {
		one: 'One shape got {count} bridges of {length} mm; one was skipped, because its type carries no bridges.',
		other: '{n} shapes got {count} bridges of {length} mm; {skipped} were skipped, because their type carries no bridges.'
	},
	'notice.bridges.cleared': {
		one: 'The bridges are gone from one shape; the cut closes again.',
		other: 'The bridges are gone from {n} shapes; the cut closes again.'
	},
	'notice.fill.skipped': {
		one: 'One was skipped: a line has no inside.',
		other: '{n} were skipped: a line has no inside.'
	},
	'notice.layer.assigned': {
		one: '1 shape into {layer}{removed}.',
		other: '{n} shapes into {layer}{removed}.'
	},
	'notice.layer.newLayer': 'a new layer “{name}”',
	'notice.layer.existing': 'layer “{name}”',
	'notice.layer.removedFrom': {
		one: ', taken out of 1 assignment',
		other: ', taken out of {n} assignments'
	},
	'notice.prune.done': {
		one: '1 empty layer gone.',
		other: '{n} empty layers gone.'
	},
	'notice.prune.none': 'There was no empty layer in the list.',
	'notice.failed': 'That did not work.',
	'notice.sheets.spread': 'This does not fit on one sheet: it is now on {n} sheets. Look in the sheet bar above the canvas.',

	// ── Setup ─────────────────────────────────────────────────────────────────────
	'setup.head.type': 'OpenKerf — machine type',
	'setup.whichKind': 'Which {kind}?',
	'setup.whichModel': 'Which model?',
	'setup.catalogue.from': 'This list comes from MeerK40t itself.',
	'setup.catalogue.filtered': 'Only the models that go with your choice.',
	'setup.catalogue.showAllLink': 'Show everything',
	'setup.catalogue.unsure': 'Not sure of the brand? Pick the family that matches your controller.',
	'setup.catalogue.later': 'You can still adjust the settings afterwards.',
	'setup.searchTypes': 'Search by brand or type…',
	'setup.loadingCatalogue': 'Loading the catalogue…',
	'setup.nothingFound': 'Nothing found for “{query}”.',
	'setup.nothingFound.within': 'Nothing found for “{query}” within this kind.',
	'setup.kindEmpty': 'This kind yields no models. The kind in the address is probably wrong.',
	'setup.catalogue.empty': 'The catalogue is empty. Is the engine running?',
	'setup.showAllModels': 'Show all models',
	'setup.head.name': 'OpenKerf — name',
	'setup.noType': 'No machine type chosen',
	'setup.noType.body': 'Pick a type first; then I know what to create.',
	'setup.toTypeChoice': 'To the type choice',
	'setup.nameIt': 'Give the machine a name',
	'setup.nameIt.body': 'This is how you recognise it in the top bar.',
	'setup.nameIt.bodyModel': 'This is how you recognise it in the top bar: “{model}”.',
	'setup.found': 'From the search: {what}. The connection is ready for the next step; it is only made when you start a job.',
	'setup.nameClash': 'There is already a machine called “{name}”. In the top bar they cannot be told apart.',
	'setup.nameClash.fix': 'Make it “{name}”',
	'setup.create': 'Create',
	'setup.head.kind': 'OpenKerf — what kind of machine',
	'setup.whatKind': 'What kind of machine is it?',
	'setup.whatKind.body': 'If the laser is on and attached to this computer or the same network, OpenKerf finds it itself. Otherwise you pick it from the list below.',
	'setup.scan.title': 'Let OpenKerf search',
	'setup.scan.again': 'Search again',
	'setup.scan.start': 'Search for machines',
	'setup.scan.running': 'Searching… {seconds}s',
	'setup.scan.what': 'USB and serial ports are checked in a moment; the network costs a few seconds, because every address in your subnet gets one question.',
	'setup.scan.slow': 'This is taking longer than usual. You can stop and pick the machine below yourself — that yields exactly the same thing.',
	'setup.scan.stop': 'Stop',
	'setup.scan.promise': 'Searching only looks. Nothing is created and no command goes to a machine until you press add below.',
	'setup.scan.found': {
		one: 'One machine found',
		other: '{n} machines found'
	},
	'setup.transport.usb': 'USB',
	'setup.transport.serial': 'Serial',
	'setup.transport.network': 'Network',
	'setup.certainty.answered': 'Answered',
	'setup.certainty.answered.why': 'This device answered by itself.',
	'setup.certainty.probable': 'Probably',
	'setup.certainty.probable.why': 'Recognised by the control chip, but the device said nothing back.',
	'setup.certainty.guess': 'Guess',
	'setup.certainty.guess.why': 'This chip sits on more than one kind of machine. Check the model yourself.',
	'setup.whichModel.short': 'Which model?',
	'setup.model': 'Model',
	'setup.suggestion': 'Suggestion: {label}',
	'setup.addThis': 'Add this one',
	'setup.noModel': 'We recognise the device, but not which model is behind it — this installation does not know that model. Pick it below yourself; at least you now know something is connected.',
	'setup.nothing': 'Nothing found',
	'setup.nothing.body': 'Is the machine on and the cable in? Otherwise pick it below yourself — that works just as well.',
	'setup.searchedIn': 'Searched in {where} · {seconds}s',
	'setup.searchedIn.nothing': 'nothing',
	'setup.orPick': 'Or pick it yourself',
	'setup.orPick.body': 'Pick what stands in your workshop. The next step shows only the models that go with it — and if you know exactly, you can search there.',
	'setup.models': {
		one: '1 model',
		other: '{n} models'
	},
	'setup.models.none': 'no models',
	'setup.notListed': 'Is your machine not among them?',
	'setup.fullList': 'See the full list',
	'setup.head.workarea': 'OpenKerf — work area',
	'setup.noMachine': 'No machine chosen',
	'setup.noMachine.body': 'Start at the overview and pick or make a machine.',
	'setup.toOverview': 'To the overview',
	'setup.connection.filled': 'Connection filled in from the search.',
	'setup.connection.unknown': 'This machine does not know those settings; nothing has been changed.',
	'setup.connection.notYet': 'This does not connect it yet: OpenKerf only talks to the machine when you start a job.',
	'setup.connection.word.interface': 'Connection',
	'setup.connection.word.address': 'Address',
	'setup.connection.word.port': 'Port',
	'setup.connection.value.udp': 'network (UDP)',
	'setup.connection.value.usb': 'USB',
	'setup.bedSize': 'How big is the bed?',
	'setup.bedSize.body': 'Measure the work area, not the outside of the case. This becomes the bed on your canvas — if it is wrong, OpenKerf thinks there is room where the head does not go.',
	'setup.noBedSize': 'This machine reports no bed size.',
	'setup.whereIsZero': 'Where is 0,0?',
	'setup.corner.auto': 'As the machine says itself',
	'setup.corner.topLeft': 'Top left',
	'setup.corner.topRight': 'Top right',
	'setup.corner.bottomLeft': 'Bottom left',
	'setup.corner.bottomRight': 'Bottom right',
	'setup.corner.centre': 'Centre',
	'setup.corner.hint': 'The corner the head goes to when you send it home. If you do not know, leave what the machine says itself.',
	'setup.bedAria': 'The bed is {width} by {height} millimetres',
	'setup.zeroOnDot': '0,0 is on the dot.',
	'setup.zeroByMachine': 'The machine decides where 0,0 is itself.',
	// ── The laser itself ──────────────────────────────────────────────────────────
	//
	// The kind of laser and the tube power. Both are asked once, in the wizard, because
	// they are facts about the machine and not about a drawing — and because without
	// them nothing can tell which of somebody else's settings would suit this laser.
	// MeerK40t's registry carries no wattage anywhere, so the power has to be asked;
	// the kind is derived from the catalogue line the machine was made from and shown
	// prefilled, because a reader should not have to translate a driver name.
	'setup.laser': 'The laser itself',
	'setup.laser.body':
		'What kind of light this machine makes, and how much of it. OpenKerf needs both before it can tell which settings other people have measured would suit your laser.',
	'setup.laser.kind': 'Kind of laser',
	'setup.laser.kind.hint':
		'Filled in from the model you picked. A glass tube and an RF metal tube cannot be told apart from that, so correct it if you know better.',
	'setup.laser.watt': 'Tube power',
	'setup.laser.watt.why':
		'The number on the tube or on the invoice. It decides which settings can be a starting point for this laser: the same percentage on twice the power chars and burns through.',
	'setup.laser.wattUnknown': 'I am not sure how powerful my tube is',
	'setup.laser.wattUnknown.then':
		'Then OpenKerf matches on the kind of laser alone, and says so on every setting it offers you.',
	'setup.laser.lens': 'Lens',
	// The six kinds. Values of `catalogue_schema.LASER_KINDS`, so a preset from the
	// shared catalogue and a machine of ours speak of the same thing.
	'laser.kind.co2Glass': 'CO2 with a glass tube',
	'laser.kind.co2Rf': 'CO2 with an RF metal tube',
	'laser.kind.diode': 'Diode',
	'laser.kind.fiber': 'Fibre',
	'laser.kind.uv': 'UV',
	'laser.kind.unknown': 'I do not know',
	'setup.capabilities': 'What does this machine have?',
	'setup.hasZ': 'A Z axis (height-adjustable bed or head)',
	'setup.hasAutofocus': 'Autofocus',
	'setup.more': 'More of this machine',
	'setup.more.what': '— mirroring, connection, and whatever else the engine knows',
	'setup.more.warning': 'These fields come straight from MeerK40t and are therefore in English. You only need them if your machine works mirrored or rotated; otherwise you can leave them.',
	'setup.showHidden': 'Also show everything we normally hide',
	'setup.skip': 'Skip',
	'setup.saving': 'Saving…',
	'setup.saveAndFinish': 'Save and finish',
	'setup.head.done': 'OpenKerf — done',
	'setup.gone': 'This machine does not exist (any more)',
	'setup.gone.path': 'There is no machine with the path “{path}”.',
	'setup.gone.noPath': 'There was no machine in the address.',
	'setup.gone.bookmark': 'You have probably ended up here via an old bookmark.',
	'setup.toYourMachines': 'To your machines',
	'setup.firstJob': 'The connection to the laser is only made at the first job. Do that first time with the lid open and without a workpiece — then you see whether the head moves as you expect without anything being able to burn.',
	'setup.sheetFits': 'Does your sheet come along to this bed?',
	'setup.sheetFits.body': 'Your sheet is {sheet}, the bed of {machine} is {bed}.',
	'setup.sheetFits.thisMachine': 'this machine',
	'setup.sheetFits.offcut': 'A sheet is the piece of material you put in, not the bed itself — so if this is an offcut {width} mm wide, it is right as it is.',
	'setup.firstCut': 'From here to your first cut',
	'setup.anotherMachine': 'Another machine',
	'setup.toWorkArea': 'To the work area',
	'setup.crumb': 'Set up a machine',
	'setup.backToWorkArea': 'to the work area',
	'setup.progress': 'Progress',
	'setup.stepOf': 'Step {n} of {total}',
	'setup.done.draw.title': 'Draw or import something',
	'setup.done.draw.body': 'Grab a shape on the left and click the bed, or open an SVG with Import.',
	'setup.done.layer.title': 'Give it a layer',
	'setup.done.layer.body': 'The layer decides speed and power. Not sure of the material? Burn a test grid first.',
	'setup.done.frame.body': 'The head traces the outline without burning. That is how you see whether your workpiece is in the right place.',
	'setup.done.start.body': 'Lid closed, extraction on, and stay and watch.',
	'setup.ready': '{machine} is ready.',
	'setup.ready.plain': 'Ready.',
	'setup.sheetToBed': 'Set the sheet to the bed size',
	'setup.sheetLeave': 'Leave it',
	'setup.sheetNow': '{sheet} is now {size}.',
	// ── The offer of starting points ──────────────────────────────────────────────
	//
	// One card, two surfaces: the top of the material library and the last step of
	// setup. It exists for one moment — a machine has just been defined and there is
	// not one setting for it — and everything in it is measured on the author's own
	// library, where the active laser had three settings of its own and a phantom
	// profile beside it carried twenty-six.
	'starter.region': 'Settings for this machine',
	'starter.title.nothing': 'This machine has no settings yet.',
	'starter.title.unburned': 'Nothing has been burned on this machine yet.',
	'starter.title.askMachine': 'What kind of laser is this?',
	// Two headings for one state, because it has two causes. The wizard fills the kind
	// in from the entry the machine was made from, so on most machines the wattage is
	// the only thing missing — and heading that card "What kind of laser is this?" asks
	// a question the two lines below it already answer.
	'starter.title.askWatt': 'How powerful is this laser?',
	'starter.away': 'Not now',
	'starter.away.why': 'Put this away. It will not be offered again for this machine.',
	'starter.machine.none': 'No machine is active, so there is nothing to fetch settings for.',
	// One word for both values, because a machine that has not said what kind of laser
	// it is and one that has not said how strong it is are the same silence.
	'starter.unrecorded': 'not recorded',
	'starter.has.emptyLibrary': 'There are no materials in this library yet either.',
	'starter.has.none': {
		one: 'The one material in this library has no setting for it.',
		other: 'Not one of the {n} materials in this library has a setting for it.'
	},
	'starter.has.some': {
		one: 'One material of the {known} in this library has a setting for it.',
		other: '{n} materials of the {known} in this library have a setting for it.'
	},
	'starter.has.unburned': {
		one: 'Its one setting came out of a catalogue and has never been burned here.',
		other: 'Its {n} settings came out of a catalogue and not one of them has been burned here.'
	},
	'starter.ask.body':
		'Without these two OpenKerf cannot tell which settings would suit this laser: a CO2 setting on a diode is not a starting point, and the same percentage on twice the power chars and burns through.',
	'starter.ask.record': 'Save and look',
	'starter.ask.notSure': 'I am not sure',
	'starter.ask.kindFirst':
		'Choose the kind of laser first: without it nothing can be matched, whatever the tube power says.',
	'starter.ask.notSure.body':
		'Not knowing the tube power is a fair answer: then the match is on the kind of laser alone, and every setting offered says so.',
	'starter.unburned.body':
		'A setting out of a catalogue is somebody else’s number on somebody else’s laser. One board burned on this one turns it into a measurement of your own.',
	'starter.unburned.grid': 'Burn a test grid',
	'starter.look': 'Show what would suit this laser',
	'starter.hide': 'Fold this list up again',
	'starter.looking': 'Looking…',
	'starter.look.hint':
		'Nothing is fetched until you press this: the shared catalogue lives on the network, and opening a window should not wait for it.',
	'starter.from.seed': 'These starting points ship with OpenKerf itself.',
	'starter.from.seedOffline':
		'The shared catalogue could not be reached, so these are the starting points that ship with OpenKerf itself.',
	'starter.from.shared': 'From the shared catalogue, copied to this computer on {when}.',
	'starter.from.sharedUndated': 'From the shared catalogue, of an unknown date.',
	'starter.from.old': 'This copy is more than a month old.',
	'starter.refresh': 'Fetch a fresh copy',
	// CC BY is not decoration: a row copied without its credit cannot lawfully be
	// passed on again, so the credit is on screen at the moment of copying.
	'starter.licence': 'Shared under {license} by {who}, and the credit travels with them.',
	'starter.powerUnknown.note':
		'The tube power of this machine is not recorded, so these match on the kind of laser alone.',
	'starter.skipped': {
		one: 'One entry in this catalogue was not understood and has been left out.',
		other: '{n} entries in this catalogue were not understood and have been left out.'
	},
	'starter.rows.count': {
		one: 'One material has a starting point for this laser.',
		other: '{n} materials have a starting point for this laser.'
	},
	'starter.allStartingPoints':
		'Every one of these is a number somebody typed, not one measured off a board. Burn a test grid before you trust one of them.',
	'starter.take': 'Add these',
	'starter.take.why': 'Add the settings for {material} to this library, for this machine.',
	'starter.tier.measured': 'burned',
	'starter.tier.startingPoint': 'starting point',
	'starter.row.values': '{speed} mm/s at {power}%',
	'starter.row.unmatched': 'power not matched',
	'starter.rows.none': 'The catalogue holds no starting point for this laser yet.',
	'starter.took': {
		one: 'One setting for {material} came in.',
		other: '{n} settings for {material} came in.'
	},
	'starter.undo': 'Take this back',
	// The door for when there is nothing to offer: a machine with settings of its own,
	// or one whose reader waved the offer away. Without it the shared catalogue has no
	// way in at all, which is measured — on the author's own library the active laser
	// carries three settings it measured itself, so the card never appears.
	'starter.door': 'Look in the shared catalogue',
	'starter.door.body': 'What other people measured on a laser like {machine}, one material at a time.',
	'setup.step.kind': 'Kind',
	'setup.step.model': 'Model',
	'setup.step.name': 'Name',
	'setup.step.settings': 'Set up',
	'setup.step.done': 'Done',
	'setup.imported': '{label} has been added. Check the address and the bed size before you burn anything.',
	'setup.imported.skipped': {
		one: '{label} has been added — 1 setting was unknown to this version and has been skipped. Check the address and the bed size before you burn anything.',
		other: '{label} has been added — {n} settings were unknown to this version and have been skipped. Check the address and the bed size before you burn anything.'
	},
	'setup.head.machines': 'OpenKerf — machines',
	'setup.yourMachines': 'Your machines',
	'setup.none.title': 'No machine set up yet.',
	'setup.none.body': 'Add the laser that stands in your workshop. That decides the bed on the canvas, which controls you get, and how OpenKerf addresses it.',
	'setup.inUse': 'In use',
	'setup.use': 'Use',
	'setup.settings': 'Settings',
	'setup.exportProfile': 'Export the profile',
	'setup.addMachine': 'Add a machine',
	'setup.importProfile': 'Import a profile…',
	'setup.field.bedwidth': 'Bed width',
	'setup.field.bedheight': 'Bed height',
	'setup.field.interface': 'Connection',
	'setup.field.address': 'Address',
	'setup.field.serialPort': 'Serial port',
	'setup.field.port': 'Port',
	'setup.import.failed': 'Reading it failed ({status}).',
	'setup.create.failed': 'Creating it failed ({status}).',
	'setup.profile.title': 'This profile: {label}',
	'setup.profile.known': '{name} — {n} settings.',
	'setup.profile.unknown': 'This profile was made for machine type {type}, and this installation does not know that type. Creating it will fail; update MeerK40t first.',
	'setup.profile.local': 'Belongs to the setup this profile comes from — check it here: {values}.',
	'setup.profile.create': 'Create the machine',
	'setup.profile.cancel': 'Never mind',
	'setup.placeholder.title': 'The engine\'s default device',
	'setup.placeholder.body': 'MeerK40t creates a device itself at startup ({label}) so that something is always active. Nobody chose it, and the bed sizes and connection are guesswork — do not burn anything on it without checking them.',
	'setup.placeholder.yours': 'Do you happen to have exactly such a machine? Then give it a name and its real bed size; from then on it counts as your machine.',
	'setup.placeholder.adopt': 'Check it and adopt it',

	// ── Errors from our own layer ────────────────────────────────────────────────
	'shape.textNamed': 'Text “{text}”',
	'shape.rect': 'Rectangle',
	'shape.ellipse': 'Ellipse',
	'shape.circle': 'Circle',
	'shape.line': 'Line',
	'shape.polyline': 'Polyline',
	'shape.path': 'Path',
	'shape.point': 'Point',
	'shape.text': 'Text',
	'shape.image': 'Image',
	'shape.group': 'Group',
	'error.searchFailed': 'The search failed.',
	'error.insertFailed': 'Inserting it failed.',
	'error.importFailed': 'Importing it failed.',
	'error.materialFailed': 'Creating the material failed.',
	'error.photoFailed': 'Saving the photo failed.',
	'error.presetFailed': 'Making the preset failed.',
	'error.noToken': 'No token, or the wrong one — editing is blocked.',
	'error.network': 'Network error: {message}',
	'error.editRefused': 'The engine refused the edit ({status}).',
	'error.noNetwork': 'This device has no network. The machine simply carries on; as soon as you have a connection again you will see it here.',
	'error.serverGone': 'The OpenKerf server is not responding — the command did not arrive. Check whether it is still running.',
	'error.tokenRefused': 'The server refuses this token. Fill in the token printed in the engine\'s window below.',
	'error.tokenNeeded': 'This OpenKerf is reachable from the network and therefore asks for a token before anything may move. Fill it in below.',
	'error.machineRefused': 'The machine refused the command (error code {status}).',
	'error.engineRefused': 'The engine refused the command ({status}).',
	'error.libraryRefused': 'The library refused the command ({status}).',
	'error.noMachine': 'No connection to the machine. Try again.',
	'operation.cut': 'Cut',
	'operation.engraveVector': 'Engrave · vector',
	'operation.engraveRaster': 'Engrave · raster',
	'operation.mark': 'Mark',
	'source.verified': 'Verified',
	'source.verified.means': 'Burned and judged on a test grid',
	'source.manual': 'Manual',
	'source.manual.means': 'Entered by hand, not measured',
	'source.extrapolated': 'Extrapolated',
	'source.extrapolated.means': 'Calculated from another thickness — never burned',
	'source.extrapolated.advice': 'Try it on scrap material first; start lower in power.',
	'source.imported': 'Imported',
	'source.imported.means': 'From someone else\'s machine',
	'source.imported.advice': 'Another laser, another result — treat this as a starting value.',
	'kind.co2Ruida': 'CO2 with Ruida or Newly',
	'kind.co2Ruida.blurb': 'Large cabinet, glass tube, water cooling, usually a Z axis. K50/K60 and up.',
	'kind.k40': 'K40 CO2',
	'kind.k40.blurb': 'The blue 40 W box, with an M2 or M3 Nano board.',
	'kind.diode': 'Diode on GRBL',
	'kind.diode.blurb': 'Open frame without cooling. Ortur, Longer, Sculpfun, home-built.',
	'kind.galvo': 'Galvo — fibre or UV',
	'kind.galvo.blurb': 'Mirror head on a stand, marks metal. Balor control.',

	// ── Phone view ────────────────────────────────────────────────────────────────
	'phone.photoSaved': 'Photo saved. You get the preset out of it on the desktop.',
	// The refusal itself comes from the API, which knows which two boards it is about.
	// This is the fallback for the case where the answer carries no sentence at all — a
	// network that went away mid-upload, or a 500 — and it says the one thing the phone
	// can be sure of: the picture is not filed, so the plank is still wanted.
	'phone.photoFailed': 'The photo was not saved. Keep the board and try again.',
	'phone.noConnection': 'No connection',
	'phone.noMachine': 'no machine',
	'phone.cameraAlt': 'Camera image of the bed',
	'phone.bed': 'Bed',
	// The − and + of a number field, named after the field itself.
	'field.decrease': 'Decrease {label}',
	'field.increase': 'Increase {label}',
	'phone.bedAria.size': 'Bed {width} by {height} millimetres',
	'phone.bedAria.empty': 'empty',
	'phone.bedAria.noLayer': '{n} in no layer',
	'phone.bedAria.offBed': '{n} off the bed',
	'phone.bedAria.offSheet': '{n} off the sheet',
	'phone.bedAria.head': 'head at {position}',
	'phone.head': 'Head',
	'phone.onTheBed': 'On the bed',
	'phone.nothing': 'nothing',
	'phone.noLayer': ', {n} in no layer',
	'phone.lastSeen': 'This is the last state we saw.',
	'phone.unplugged': 'There is no machine attached to the server. Check whether it is on and the cable is in.',
	'phone.idle': 'Nothing is burning. You start a job on the desktop.',
	'phone.cameraNoImage': 'The camera is on but delivers no image. Cable loose?',
	'phone.cameraStarting': 'Starting the camera…',
	'phone.cameraRetry': 'Try again',
	'phone.cameraOn': 'Switch the camera on',
	'phone.noCamera': 'No camera linked to this machine.',
	'phone.waitingPhoto': {
		one: '{n} test grid is waiting for a photo',
		other: '{n} test grids are waiting for a photo'
	},
	'phone.waitingAlign': {
		one: '{n} test grid is waiting to be aligned',
		other: '{n} test grids are waiting to be aligned'
	},
	'phone.photoIn': 'photo in — align it on the desktop',
	'phone.again': 'Again',
	'phone.takePhoto': 'Take a photo',
	'phone.newPhotoOf': 'New photo of test grid {id}',
	'phone.notBurning': 'Nothing is burning',
	'phone.paused': 'paused',
	'phone.pauseAsked': 'pause requested…',
	'phone.remaining': '{time} left',
	'phone.doneAt': 'done at {time}',
	'phone.burning': 'burning',
	'phone.designElsewhere': 'You design on the desktop — this screen keeps an eye on the machine.',
	'phone.stopOnMachine': 'No connection — stopping is only possible with the button on the machine.',
	'phone.retry': 'Try again',
	'phone.retry.auto': 'Try again (automatically in {seconds} s)',
	'phone.resume': 'Resume',
	'phone.pausing': 'Pausing…',
	'phone.operation.cut': 'cut',
	'phone.operation.engrave': 'engrave',
	'phone.operation.raster': 'raster',
	'phone.operation.mark': 'mark',

	// ── Welcome ───────────────────────────────────────────────────────────────────
	'welcome.title': 'No machine has been set up yet.',
	'welcome.lead': 'Without a machine the canvas does not know how big your bed is. Four steps, about a minute — and everything can still be changed later.',
	'welcome.asks.kind': 'Four kinds in workshop language — no board names needed.',
	'welcome.asks.model': 'Only the models that go with that kind.',
	'welcome.asks.name': 'What you recognise it by in the top bar.',
	'welcome.asks.workarea': 'Work area',
	'welcome.asks.workarea.body': 'Width, height and where 0,0 is. This draws your bed.',
	'welcome.after': 'After that:',
	'welcome.after.design': 'Design',
	'welcome.after.cut': 'Cut',
	'welcome.lookAround': 'Look around without a machine',
	'welcome.lookAround.body': 'Drawing works, burning does not — the bed sizes and the status are then those of a default device the engine invents itself.',

	// ── Connection ────────────────────────────────────────────────────────────────
	'connection.minutes': '{n} min',
	'connection.lost': 'No connection to OpenKerf',
	'connection.lost.body': 'The server is not responding. What you draw or set now does not arrive, and the values below are the last ones we saw.',
	'connection.lost.bodyFor': 'The server has not responded for {duration}. What you draw or set now does not arrive, and the values below are the last ones we saw.',
	'connection.stillBurning': 'The machine carries on. Stopping is only possible with the button on the machine itself now.',
	'connection.retryNow': 'Try again now',
	'connection.autoIn': 'automatically in {seconds} s',
	'connection.connecting': 'connecting…',

	// ── Test-grid result ──────────────────────────────────────────────────────────
	'result.title': 'Steps 3 and 4 — photo and preset',
	'result.pickGrid': 'Choose a test grid',
	'result.pickGrid.option': 'Choose a grid…',
	'result.noMaterial': 'no material',
	'result.withPhoto': '· with photo',
	'result.waitingPhoto': '· waiting for a photo',
	'result.noGrids': 'No test grids yet. As soon as you draw and burn one above, you can photograph it here and point at the best square.',
	'result.saved': {
		one: '1 preset saved with {material}. You will find it in the material library.',
		other: '{n} presets saved with {material}. You will find them in the material library.'
	},
	'result.thisMaterial': 'this material',
	'result.burnFirst': 'Burn this grid and photograph the board.',
	'result.burnFirst.how': 'Straight from above, the whole board in frame — you align the corners yourself afterwards.',
	'result.orPhone': 'Or grab your phone: open OpenKerf on it and this grid is under “Photograph a test grid”.',
	'result.photoAlt': 'Photo of the burned grid',
	'result.corner.drag': 'Drag corner {corner}',
	'result.corner.topLeft': 'top left',
	'result.corner.topRight': 'top right',
	'result.corner.bottomRight': 'bottom right',
	'result.corner.bottomLeft': 'bottom left',
	'result.dragCorners': 'Drag the four corners to the corners of the burned grid',
	'result.rowColumn': 'row {row}, column {column} · {values}',
	'result.tapBest': 'Tap the square that turned out best',
	'result.alignDone': 'Aligning done',
	'result.align': 'Align the overlay',
	'result.otherPhoto': 'Another photo',
	'result.undoChoice': 'Row {row}, column {column}, {values}: undo the choice',
	'result.chip': 'row {row}, col {column} · {values}',
	'result.noneChosen': 'No square chosen yet',
	'result.makePresets': {
		one: 'Make a preset from 1 square',
		other: 'Make presets from {n} squares'
	},
	'result.makePreset': 'Make a preset',
	'result.becamePreset': 'Became a preset:',
	'result.pointHighlights': '— pointing at it highlights the square on the photo.',
	'result.gridNoMaterial': 'This grid belongs to no material, so no preset can come out of it. Link a material when generating the next grid.',
	'result.align.failed': 'The alignment could not be saved.',
	'result.align.failedOffline': 'The alignment could not be saved — no connection.',

	// ── Sheet material ────────────────────────────────────────────────────────────
	'sheetMat.applies': 'Applies to {sheet} — {size}. Every sheet keeps its own material, so thin and thick can be in one project.',
	'sheetMat.notFilled': 'Not filled in',
	'sheetMat.add': 'Add',
	'sheetMat.notListed': 'The material is not in the list',
	'sheetMat.thickness': 'Thickness in millimetres',
	'sheetMat.other': 'other',
	'sheetMat.otherAria': 'Another thickness in millimetres',
	'sheetMat.noMaterial': 'Without a material the library shows everything and the preflight cannot see whether a setting belongs to this sheet.',
	'sheetMat.noPresets': 'No settings in the library for this material yet. A test grid is the shortest way there.',
	'sheetMat.presets': {
		one: '1 setting in the library for this material.',
		other: '{n} settings in the library for this material.'
	},
	'sheetMat.presetsAround': {
		one: '1 setting in the library for this material around {thickness} mm.',
		other: '{n} settings in the library for this material around {thickness} mm.'
	},

	// ── Sheet tabs ────────────────────────────────────────────────────────────────
	'sheets.elements': {
		one: '1 element',
		other: '{n} elements'
	},
	'sheets.materialNotFilled': 'not filled in',
	'sheets.removeSheet': 'Remove the sheet',
	'sheets.needsOne': 'A project has at least one sheet',
	'sheets.removeAsk': '{sheet} holds {what}. Removing it throws that work away — this cannot be undone.',
	'sheets.removeConfirm': 'Remove the sheet and {what}',

	// ── Camera calibration & fonts ────────────────────────────────────────────────
	'calibrate.title': 'Calibrate the camera',
	'calibrate.lead': 'Drag the four points to the corners of the bed, starting top left and going clockwise. After that the app knows where every point in the image lies on the bed, and your design lands in the right place.',
	'calibrate.stageAria': 'Camera image with four draggable corner points',
	'calibrate.rawAlt': 'Unprocessed camera image',
	'font.label': 'Font ({n} available)',
	'font.label.current': 'Font ({n} available) — now: {current}',
	'font.search': 'Search for a font…',
	'font.listAria': 'Font',
	'font.default': 'Default',
	'font.sample': 'Handmade 123',
	'font.more': '{n} more — type to search.',
	'font.import.close': 'Close the import',
	'font.import.open': 'Font not in the list?',
	'font.import.why': 'The engine only reads .ttf files. These are on your computer but are not seen; importing makes a usable copy of one.',
	'font.import.search': 'Search in {n} fonts…',
	'font.import.nothing': 'Nothing found that is still missing.',

	// ── Clipart ───────────────────────────────────────────────────────────────────
	'clipart.title': 'Search for clipart',
	'clipart.lead': 'Searches public collections. What you find belongs to someone else: the licence is with every result, and it decides whether you may sell what you cut with it.',
	'clipart.placeholder': 'e.g. heart, star, bird…',
	'clipart.width': 'Width (mm)',
	'clipart.searching': 'Searching…',
	'clipart.search': 'Search',
	'clipart.unavailable': '{source} {reason}. The rest is there.',
	'clipart.insert': 'Insert at {width} mm wide',
	'clipart.licenceUnknown': 'licence unknown',
	'clipart.source': 'source',
	'clipart.nothing': 'Nothing found. English words usually give more results.',
	'clipart.typeWord': 'Type a word and press Enter.',
	'clipart.shown': '{n} shown',
	'clipart.fetching': 'Fetching…',
	'clipart.more': 'More results',

	// ── Corners & offset ──────────────────────────────────────────────────────────
	'corners.title': 'Corners',
	'corners.styleAria': 'Corner style',
	'corners.round': 'Round',
	'corners.chamfer': 'Chamfer',
	'corners.size': 'Size',
	'corners.chamferWarning': 'This turns the shape into a path: width and height can no longer be changed separately afterwards. Undo brings it back.',
	'corners.roundKeeps': 'A rectangle stays a rectangle, so you can adjust the radius later.',
	'corners.doRound': 'Round the corners',
	'corners.doChamfer': 'Chamfer the corners',
	'corners.shapes': {
		one: '1 shape',
		other: '{n} shapes'
	},
	'corners.button': '{shapes}: {what}',
	'corners.buttonSize': '{shapes}: {what} — {size} mm',
	'offset.title': 'Offset',
	'offset.distance': 'Distance',
	'offset.outward': 'outward',
	'offset.inward': 'inward',
	'offset.reading': '{mm} mm {direction}',
	'offset.fillIn': 'Fill in a distance; negative is inward.',
	'offset.explain': 'A new path appears beside the existing one. The original shape stays.',
	'offset.make': 'Make an offset',
	'offset.button': '{shapes} — {mm} mm {direction}',

	// ── Leftovers found by looking ────────────────────────────────────────────────
	'alarm.seen': 'Seen',
	'message.close': 'Dismiss the message',
	'calibrate.corner': 'Corner {corner}',
	'calibrate.clear': 'Clear the calibration',
	'clipart.thatIsAll': 'that is all',
	'panel.image': 'Image',
	'panel.image.on': '{n} on',
	'panel.image.clearAll': 'Clear everything',
	'panel.image.kind': 'kind',
	'sheets.addSheet': 'Add a sheet',
	'text.height': 'Height (mm)',
	'text.update': 'Update',
	'text.place': 'Place',
	'text.title': 'Place text',
	'text.label': 'Text',
	'text.placeholder': 'e.g. Stellendam',
	'text.tracking': 'Letter spacing',
	'text.alignment': 'Alignment',
	'text.left': 'Left',
	'text.centred': 'Centred',
	'text.right': 'Right',
	'layout.lookingForMachine': 'Just checking which machine is there…',

	// ── The rotary: burning on a cylinder ─────────────────────────────────────
	//
	// Machine-wide, so it lives with the machine settings. The sentences here say what
	// the numbers *do*, because a factor of 1.036 means nothing on its own — and because
	// the one thing that goes wrong on a rotary (a job that silently comes out stretched)
	// costs the workpiece and there is only one of those.
	'rotary.head': 'Rotary — OpenKerf',
	'rotary.title': 'Rotary',
	'rotary.intro':
		'A rotary turns the workpiece under the head, so the height of your drawing becomes rotation around the object instead of distance across the bed. A millimetre stays a millimetre on the surface: what you draw 30 mm tall comes off the cup 30 mm tall.',
	'rotary.forMachine': 'These settings belong to {machine}.',
	'rotary.needsMachine':
		'Choose a machine first: a rotary is bolted into one particular bed, so the settings belong to that machine.',
	'rotary.backToMachines': 'Back to the machines',
	'rotary.engineOwn':
		'This machine brings MeerK40t’s own rotary along, and that one stays in charge. Set it up in the machine’s own settings; OpenKerf leaves it alone here.',
	'rotary.use': 'Burn on a cylinder',
	'rotary.use.hint':
		'Switch this on once the rotary is in the bed and the workpiece turns freely.',
	'rotary.kind': 'Kind of rotary',
	'rotary.kind.chuck': 'Chuck — I know the diameter',
	'rotary.kind.roller': 'Rollers — I know the circumference',
	'rotary.diameter': 'Diameter of the object',
	'rotary.diameter.hint':
		'Measure it with calipers at the height where the design goes; a mug tapers.',
	'rotary.circumference': 'Circumference of the object',
	'rotary.circumference.hint':
		'Mark a line, roll the object round once, and measure how far it travelled. On rollers this is more reliable than the diameter, because they slip.',
	'rotary.circumference.is': 'Once round is {mm} mm.',
	'rotary.scale': 'Y scale',
	'rotary.scale.explain':
		'The scale corrects a rotary that turns a little too far or not far enough. Leave it at 1 when the controller already converts Y to rotation itself, because two corrections multiply.',
	'rotary.scale.source.none': 'No correction — the controller does the conversion',
	'rotary.scale.source.manual': 'A factor I fill in',
	'rotary.scale.source.steps': 'Computed from the two motors',
	'rotary.scale.factor': 'Factor',
	'rotary.scale.flatSteps': 'Steps per mm of the flat bed',
	'rotary.scale.rotarySteps': 'Steps per mm of the rotary',
	'rotary.scale.now': 'Y goes into the machine multiplied by {factor}.',
	'rotary.scale.example': 'A shape {drawn} mm tall burns {burned} mm around the object.',
	'rotary.scale.range':
		'A factor between {min} and {max} is a calibration; anything beyond that is a resize and the machine refuses it.',
	'rotary.calibrate.title': 'Calibrate from a burned line',
	'rotary.calibrate.body':
		'Burn a line of a known length around the object, measure what came out, and fill both in. Calibrating again later builds on what is set now instead of starting over.',
	'rotary.calibrate.commanded': 'Length I asked for',
	'rotary.calibrate.measured': 'Length I measured',
	'rotary.calibrate.preview': 'That gives a factor of {factor}.',
	'rotary.calibrate.apply': 'Use this factor',
	'rotary.calibrate.last':
		'Last calibrated on {commanded} mm asked for and {measured} mm measured, giving {factor}.',
	'rotary.save': 'Save the rotary',
	'rotary.saved': 'Saved. The next job goes into the machine with this scale.',
	'rotary.overlap':
		'The work is {work} mm tall and once round is {circumference} mm, so the end burns over the beginning.',
	'rotary.failed': 'The machine refused this rotary setting ({status}).',
	'rotary.safety.title': 'What changes on the machine',
	'rotary.safety.home':
		'Homing is refused while the rotary is on: the head would drive into it. Take the rotary out first, or confirm that the bed is clear.',
	'rotary.safety.frame':
		'The frame still traces a rectangle, but its height is rotation: you see the object turn under a head that stays where it is.',
	'rotary.safety.preflight':
		'Before every start the pre-flight says that the rotary is on and by how much Y is scaled.',
	'rotary.safety.position':
		'The scale counts from the machine zero, so a shape further up the drawing also lands further along. Put your work near the top of the sheet and burn the calibration line in the same place.',
	'rotary.scope.title': 'What this deliberately does not do',
	'rotary.scope.firmware':
		'Nothing is written into the controller. A Ruida keeps its own rotary page, and on a GRBL machine OpenKerf leaves $101 alone at the start of a job: that is firmware, and it is set where the firmware lives.',
	'rotary.scope.rest':
		'The feeder, the dual laser and galvo mode are not part of this either.',
	'rotary.checklist.title': 'At the machine: the first ring',
	'rotary.checklist.intro':
		'Whether a burned ring comes out round and the right size cannot be tested without the hardware, so nothing below has been driven by us. This is the order to do it in, and the number to expect at each step.',
	'rotary.checklist.1':
		'Fit the rotary, put a straight-sided tumbler in it, and switch the laser off at the key. Move the head by hand to the middle of the object.',
	'rotary.checklist.2':
		'Set the rotary up on the Ruida’s own panel (pulse per rotation and diameter). That is the controller’s conversion; ours stays at 1 as long as it does the work.',
	'rotary.checklist.3':
		'Switch the rotary on here, fill in the diameter, and leave the scale at "no correction".',
	'rotary.checklist.4':
		'Press Home. Expected: it is refused, with the reason. That refusal is the safety part of this feature.',
	'rotary.checklist.5':
		'Draw a rectangle 100 mm tall and 10 mm wide, put it in a cutting layer at low power, and look at the pre-flight. Expected: it says the rotary is on, with the diameter and a factor of 1.',
	'rotary.checklist.6':
		'Burn it, and measure with a flexible tape how far the burned line runs around the object.',
	'rotary.checklist.7':
		'Fill that measurement in above: 100 asked for, what you measured. Expected: a factor of 100 divided by your measurement — 96.5 mm gives 1.0363.',
	'rotary.checklist.8':
		'Burn the same rectangle again and measure again. Expected: within half a millimetre of 100 mm. If it is worse, calibrate once more — it builds on the first factor.',
	'rotary.checklist.9':
		'Now burn a ring all the way round: a rectangle as tall as the circumference this page reports. Expected: the end meets the beginning. A gap or an overlap means the diameter is wrong, not the factor.',
	'rotary.checklist.10':
		'Write the factor down beside the machine. It belongs to this rotary with this object; a different diameter is a different measurement.',
	'setup.rotary': 'Rotary',
	'job.rotary.chuck': 'The rotary is on: a chuck of {diameter} mm, Y scaled by {factor}.',
	'job.rotary.roller': 'The rotary is on: {circumference} mm round, Y scaled by {factor}.',
	'job.rotary.frame':
		'On a rotary the frame turns the object; the head hardly crosses the bed.',
	'job.home.rotary.title': 'Home with the rotary fitted?',
	'job.home.rotary.body':
		'Homing drives the head across the bed and into the rotary. Only continue if the rotary is out or the head can reach the corner freely.',
	'job.home.rotary.confirm': 'The bed is clear — home',
	'job.home.rotary.cancel': 'Do not home',
	// ── Series: one design, burned once per row of a list ─────────────────────────
	//
	// The interface never says "wordlist": that is the engine's word for it, not a
	// reader's. Here it is a list, and what it makes is burns. The window's own title
	// stays the fixed key 'series.title' so that a page can name it; the file it is
	// reading is a line inside the body.
	'series.burns.aria': 'The burns this list makes',
	'series.search': 'Search the names',
	'series.searchAria': 'Search what the burns engrave',
	'series.summary': 'This list makes {burns} out of {rows}.',
	'series.step': 'This design takes {n} rows per burn, so one sheetful is that many rows.',
	'series.from.file': 'These rows came from the file {file}.',
	'series.from.numbers': 'These rows were counted from {first} to {last}.',
	// What one burn puts on the material. Several values in one line go through
	// i18n.list(), because in Dutch the comma is the decimal mark.
	'series.onBed': 'On the bed',
	'series.onBed.title': 'This is the burn the bed is showing, and the one that burns next.',
	'series.done': 'Burned',
	'series.done.title': 'This burn is marked as done, so moving on skips over it.',
	'series.burn.blank': 'This one has nothing to put on the material.',
	'series.burn.short': {
		one: 'One place on this sheet has no row left, so it stays empty.',
		other: '{n} places on this sheet have no row left, so they stay empty.'
	},
	'series.rowMenu': 'More about this burn',
	'series.menu.show': 'Show this one on the bed',
	'series.menu.again': 'Burn this one again',
	'series.menu.again.needsRun': 'No series is going, so there is nothing to burn again.',
	'series.nothingReads':
		'No text on the bed takes its value from this list, so each of these burns would be the same. Put a column into a text first.',
	'series.nothingFound': 'No burn engraves {query}.',
	'series.clearSearch': 'Show them all again',
	'series.empty': 'No list is attached, so every burn would be the same.',
	'series.empty.how':
		'Import a file with a column of names, or count a range of numbers. A text on the bed reading {example} then takes its value from the column of that name, one row per burn.',
	// Where the rows come from. Two doors and one list: numbers are not a second kind
	// of series, only another way of filling the rows in.
	'series.source': 'Where the rows come from',
	'series.source.file': 'A file',
	'series.source.numbers': 'Numbers',
	'series.pick': 'Choose a file',
	'series.pick.again': 'Choose another file',
	'series.pick.hint': 'A spreadsheet saved as CSV, with one column per thing that changes.',
	'series.chosen': 'Reading {file}.',
	'series.numbers.first': 'First number',
	'series.numbers.last': 'Last number',
	'series.numbers.step': 'Step',
	'series.numbers.padding': 'Digits',
	'series.numbers.column': 'Column name',
	'series.numbers.hint':
		'Digits writes the number that many places wide, so 3 gives 001. A text reading {example} then takes the next number.',
	'series.unfinished': 'Fill the numbers in and the rows appear below.',
	// What this app decided about somebody's file. A decision taken silently is one
	// they cannot overrule, so each one is on screen and the header is a control.
	'series.firstRows': 'The first rows, as this app reads them',
	'series.header': 'The first row',
	'series.header.names': 'Column names',
	'series.header.data': 'Data',
	'series.header.guess.names':
		'This app read the first row as the column names. Change it if that row is a value.',
	'series.header.guess.data':
		'This app read the first row as a value rather than as column names. Change it if those are the names.',
	'series.delimiter': 'Separated by',
	'series.delimiter.comma': 'Commas',
	'series.delimiter.semicolon': 'Semicolons',
	'series.delimiter.tab': 'Tabs',
	'series.delimiter.bar': 'Vertical bars',
	'series.encoding': 'Read as',
	'series.moreRows': {
		one: 'One more row follows these.',
		other: '{n} more rows follow these.'
	},
	'series.columns': 'The columns in this list',
	'series.column': 'Column',
	'series.column.placeholder': 'In a text',
	'series.column.blanks': 'Empty',
	'series.column.used': 'In use',
	'series.column.used.title': 'A text on the bed reads this column.',
	'series.column.reserved.short': 'Kept name',
	'series.column.reserved':
		'The engine keeps this name for itself, so this column can never be read. Rename it in your file and import it again.',
	// A text asking for a column the list has not got. It burns nothing and cannot be
	// clicked either, so it is listed here rather than marked on the bed.
	'series.ghosts': 'Texts that ask for a column this list has not got',
	'series.ghosts.why':
		'Each of these burns nothing at all, and cannot be clicked on the bed either — which is why they are listed here rather than marked on the bed. Give the list a column of that name, or take the shape away.',
	'series.ghost.missing': 'It asks for {columns}.',
	'series.ghost.delete': 'Delete the shape',
	'series.skipBlank': 'Skip a row with an empty cell',
	'series.skipBlank.cannot':
		'This design takes {n} rows per burn, and a sheetful cannot skip a row: the engine reads the rows next to each other.',
	// Filling the plate: one piece per row, as many as the material holds. The numbers
	// are the reader's, so they go through Intl; the sizes are millimetres and go
	// through i18n.mm for the same reason.
	'series.plate': 'On one plate',
	'series.plate.sheet': '{name} is {size} mm',
	'series.plate.materialThick': '{thickness} mm {name}',
	'series.plate.width': 'Plate width',
	'series.plate.height': 'Plate height',
	'series.plate.material': 'Choose the material',
	'series.plate.material.change': 'Change the material',
	'series.plate.size': '{w} × {h}',
	'series.plate.fits': 'A piece of {piece} mm goes {places} times on this plate: {across} across and {down} down.',
	'series.plate.more': 'The whole list is {burns} plates of this one, and the last of them uses {last} of the places.',
	'series.plate.done': 'This plate is laid out with {n} pieces, one per row of the list.',
	'series.plate.gap': 'Between the pieces',
	'series.plate.margin': 'Free at the edge',
	'series.plate.fill': 'Lay out {n} pieces',
	'series.plate.fillPlain': 'Lay the pieces out',
	'series.plate.already': 'This plate is already laid out: its pieces read further down the list than the first row.',
	'series.startAt': 'Start at row',
	'series.startAt.hint': 'Which row the first burn takes. The rest follow in the order of the file.',
	'series.attach': 'Use this list',
	'series.attach.instead': 'Use this list instead',
	'series.detach': 'Take the list away',
	'series.running': 'A series is going. Stop it in the Job panel before you change the list.',
	// The two verbs outside the window. "Insert a column" opens the submenu of columns;
	// with one column the row is the action itself and names it, because one option is
	// not a choice.
	'series.insert': 'Insert a column',
	'series.insert.named': 'Insert {column}',
	'series.show': 'Set up a series',
	'series.show.title': 'Attach a list, see what every burn engraves, and choose where to start',
	// The read-back line under the text in the panel. The quotation marks are there so
	// that a column with nothing in it reads as nothing rather than as a missing word.
	'series.panelValue': 'For the burn now on the bed this reads “{text}”.',
	// The run itself, read standing at the machine with a plate in your hand. The
	// wordings deliberately differ from the tile run's: the two runs rhyme, and one
	// sentence shared between them would be one of the two saying something it does
	// not quite mean — "Stop the run" says nothing about which run.
	// Before the first plate. The panel orders itself by the phase of the process, so
	// "nothing has been burned yet" is a state of its own and not an empty version of
	// the running one.
	'series.ready.aria': 'The series that is ready to go',
	'series.ready': 'A list is attached and it makes {burns} burns. Nothing has been burned yet.',
	'series.ready.first': 'The first one engraves {what}.',
	'series.begin': 'Start the series',
	'series.begin.title':
		'This only starts the count of plates. Nothing goes to the machine until you press Burn this one.',
	'series.run.aria': 'The series now running',
	'series.current': 'Burn {n} of {total}',
	'series.engraves': 'This one engraves {what}.',
	'series.progress': '{done} of {total} burns have been made.',
	'series.progressAria': 'How far along this series is',
	'series.burnThis': 'Burn this one',
	'series.next': 'Burned, next one',
	'series.next.title':
		'This burns nothing. It moves the bed on to the next burn that still has to happen.',
	'series.stop': 'Stop the series',
	'series.stop.title':
		'The list stays and so does the row; only the count of what has been burned goes.',
	'series.burnAgain': 'Burn this one over again',
	'series.sent': 'Burn {n} has gone to the machine.',
	'series.finished': 'Every burn in this list is done, so the series has ended.',
	// A run goes stale in two ways and the server tells them apart, because the
	// punishment differs: shapes that have moved mean the plates already made belong
	// to another drawing, while a changed number of places on a sheet means the rows
	// fall into different burns than the ones ticked off.
	'series.stale.geometry':
		'The shapes have moved or been altered since this series began, so what is already burned belongs to the drawing as it was.',
	'series.stale.places':
		'A sheet now holds a different number of places than when this series began, so the rows fall into other burns than the ones already made.',
	'series.stale.how':
		'Stop the series and begin again to burn on with the drawing as it is now. What is already burned stays burned.',

	// ── Refusals the API can name ─────────────────────────────────────────────────
	//
	// The engine layer sends a code in `X-OpenKerf-Error` beside its English
	// sentence, so a refusal that is part of a normal flow can be read in the
	// reader's own language. What the sentence needs besides the code — a count of
	// ours, a column name, a row number — rides in `X-OpenKerf-Error-Values` and
	// arrives here as a placeholder of the same name, so the translated sentence
	// keeps every number and every name the English one had. A refusal that bakes a
	// number into its sentence and sends no values has no entry here: half a sentence
	// with the number missing is worse than the English one with it.
	'api.bridges.notSupported': 'Bridges only work on a rectangle, an ellipse, a polyline or a path.',
	'api.bridges.needsCount': 'Ask for at least one bridge, or clear them instead.',
	'api.bridges.needsLength': 'A bridge needs a length greater than zero.',
	// The one refusal here whose sentence carries a number: it is a constant of ours, not
	// a measurement, so it travels beside the code in `X-OpenKerf-Error-Values` and
	// `MAX_COUNT` in `bridges.py` stays the only place it is written down.
	'api.bridges.tooMany': 'More than {max} bridges in one contour is not a cut any more.',
	'api.bridges.percentRange': 'A bridge sits somewhere between 0 and 100 percent along the path.',
	'api.corners.none': 'Not one corner can be rounded or bevelled: no two straight sides meet there, or the size is too big for the sides. Choose a smaller size.',
	'api.draw.backwardsPlaceholder':
		'A placeholder cannot count backwards. It would read the list\'s own bookkeeping instead of a row.',
	'api.draw.badAlign': 'Text alignment has to be start, middle or end.',
	'api.draw.badFontName':
		'A font name cannot hold a quotation mark. Pick the font from the list instead of typing it.',
	'api.draw.booleanEmpty': 'That combination yielded nothing — do the shapes actually overlap?',
	'api.draw.bracesInText':
		'A curly bracket has to open and close once around a column name, and a bracket cannot be burned as a bracket.',
	'api.draw.emptyText': 'Text cannot be empty.',
	'api.draw.noFonts': 'No font support available.',
	'api.draw.noLayer': 'The engine created no layer.',
	'api.draw.noOffset': 'The engine made no offset.',
	'api.draw.notALine': 'This element is not a line.',
	'api.draw.notInGroup': 'This selection is not in a group.',
	'api.draw.notText': 'This element is not editable text.',
	'api.draw.quotesInText': 'Quotation marks in text are not supported yet.',
	'api.edit.mixedAngle': 'The angle of this selection cannot be read off; use the 1° or 90° steps.',
	'api.edit.needsElement': 'Name at least one element.',
	'api.edit.staleElement': 'That shape is gone. Refresh the design.',
	'api.gen.needsSelection': 'Choose what should be repeated first.',
	'api.gen.hingeEmpty': 'Nothing is left of this field inside the area.',
	'api.gen.hingeNeedsSelection': 'Choose the shape whose area the slits have to fill first.',
	// The two refusals of "each copy takes the next name from the list". `gen.noList`
	// is also what the greyed checkbox says, so the reason before the press and the
	// answer after it are one sentence.
	'api.gen.noList':
		'No list is attached, so there is no next name to take. Import a list in the Series window first.',
	'api.gen.nothingToFollow':
		'None of the shapes you are repeating has a placeholder in its text, so there is no name for the copies to take. Put a column into a text first.',
	'api.gen.noBarcodeLib': 'Barcodes need the python-barcode package.',
	'api.gen.noFont': 'There is not one usable font on this computer.',
	'api.gen.noQrLib': 'QR codes need the segno package; install it beside the API.',
	'api.gen.noShape': 'The text yielded no shape.',
	'api.gen.qrTooLong': 'This text is too long for a readable QR code.',
	'api.gen.tooThick': 'The material is too thick for these outside sizes; the walls would touch each other.',
	'api.gen.fingerTooWide': 'The finger is too wide: three of them do not fit on an edge.',
	'api.gen.arcTooLong': 'This text is too long for this radius; it would run over itself. Choose a larger radius or a smaller letter.',
	'api.layer.gridCell': 'This is a cell of a test grid; the kind of operation is the test.',
	'api.layer.noAirAssist': 'This machine has no command for air assist, so a switch here would do nothing. Set up at the machine first which method drives the blower.',
	'api.layer.noZAxis': 'This machine has no Z axis the driver can move, so a step per pass would do nothing. Switch the Z axis on at the machine, or leave this field empty.',
	// The refusals around starting points. Only the ones whose sentence carries no
	// number measured per call: "{machine} already has 3 settings of its own" keeps its
	// English, because the numbers do not travel in a header and a translated sentence
	// without them says less than the English one with them.
	'api.library.machine.wattRange': 'A tube power between {min} and {max} watt, please.',
	'api.library.starter.needsKind':
		'OpenKerf does not know what kind of laser {machine} is. A CO2 setting on a diode is not a starting point.',
	'api.library.starter.needsWatt':
		'OpenKerf does not know how powerful {machine} is, so it cannot tell which settings would suit it. Fill in the tube power, or say you are not sure and see everything for this kind of laser.',
	'api.library.starter.noMachine':
		'There is no machine active, so there is nothing to fetch settings for.',
	'api.library.starter.dismissNoMachine':
		'There is no machine active, so there is no offer to put away.',
	// The refusals the material library's own verbs can produce. Every one of these is
	// the answer to a button a reader just pressed, so it has to be in the language the
	// button was in. The plan left `nameTaken` English because it carries a name; that
	// name is in the field the reader typed it into, one line above the refusal, so a
	// Dutch sentence without it loses nothing and an English one loses the reader.
	'api.library.material.nameTaken':
		'There is already a material of that name. Merge the two instead of giving them the same name.',
	'api.library.material.mergeSelf': 'A material cannot be merged into itself.',
	'api.library.machine.mergeSelf':
		'Choose a different machine profile to move this one’s work into.',
	'api.library.machine.mergeActive':
		'This is the machine you are working on; move the other profile into this one instead.',
	'api.library.machine.mergeTwoReal':
		'Both of these profiles belong to a machine that exists. Two lasers are not one, and merging them would file one machine’s measurements under the other.',
	'api.library.preset.kerfRange':
		'The catalogue holds a kerf between 0 and {max} millimetres, and this one is {kerf}.',
	'api.library.adopt.noMachine':
		'There is no machine active, so there is nothing to attach these settings to.',
	'api.presetariat.share.noWatt':
		'This setting belongs to a machine whose tube power is not recorded, so nobody else can tell whether it applies to theirs.',
	'api.presetariat.share.noKind':
		'This setting belongs to a machine whose kind of laser is not recorded, and a CO2 setting is not a starting point for a diode.',
	'api.presetariat.share.badHandle':
		'A GitHub handle is letters and digits, with single hyphens between them and none at either end.',
	'api.presetariat.share.materialNameTooShort':
		'The catalogue searches on the material name, so it needs at least two characters; rename this material before offering its settings.',
	'api.presetariat.share.outOfRange':
		'The catalogue holds {field} between {low} and {high}, and this setting says {value}.',
	'api.presetariat.share.needsCharring':
		'Say how the edge came out, because a speed and a power with no outcome beside them is not something anybody else can judge.',
	'api.presetariat.share.handleNotKept':
		'Your handle could not be saved on this computer, so it will be asked for again.',
	'api.presetariat.badShape': 'That file does not look like a preset catalogue.',
	'api.presetariat.tooNew': 'This catalogue comes from a newer version of OpenKerf. Update first.',
	'api.presetariat.unreachable':
		'The shared catalogue could not be fetched, and there is no earlier copy on this computer.',
	'api.nest.needsTwo': 'Choose at least two shapes to nest.',
	'api.nodes.notEditable': 'The nodes of this shape cannot be edited.',
	'api.project.noDesign': 'The project holds no design.',
	'api.project.notOurs': 'This is not an OpenKerf project.',
	'api.rotary.needsDiameter': 'A chuck rotary needs the diameter of the object, measured with calipers.',
	'api.rotary.needsCircumference': 'A roller rotary needs the circumference of the object: mark a line, roll it round once, and measure.',
	'api.rotary.needsSteps': 'Computing the Y scale from the motors needs both numbers: the steps per millimetre of the flat bed and of the rotary.',
	'api.rotary.unknownKind': 'A rotary is either a chuck or a roller.',
	'api.rotary.unknownScaleSource': 'The Y scale comes from the two motors, from a number you fill in, or nowhere at all.',
	'api.rotary.needsMeasurement': 'Calibrating needs both lengths: what you asked the machine for and what you measured on the object.',
	'api.rotary.noMachine': 'There is no machine selected, so there is no rotary to set up.',
	'api.rotary.homeWhileActive': 'The rotary is switched on. Homing drives the head over the bed and into the rotary. Take the rotary out first, or confirm that it is clear.',
	// A series, in the order the reader meets them: reading a file, counting a range,
	// attaching a list, and the run itself.
	//
	// One of its codes is deliberately absent: the two stale refusals have their code
	// built in an expression, so the test that keeps these honest cannot find it — and
	// the run block says both sentences itself (`series.stale.*`) with the button
	// already off, so that refusal is unreachable from the interface.
	// Filling a plate with one piece per row. The two with numbers in them carry the
	// numbers the layer measured, through the values header.
	'api.plate.alreadyFilled':
		'This plate is already laid out: its pieces read further down the list than the first row. Undo that first, or lay out the single piece you started from.',
	'api.plate.badGap': 'A negative gap makes two pieces overlap, and then it is one cut.',
	'api.plate.badMargin': 'A negative margin lays the work over the edge of the plate.',
	'api.plate.fixedRow':
		'This piece names a fixed row, so its copies would all engrave that one row. Take the row number out of the placeholder first.',
	'api.plate.noList':
		'No list is attached, so every copy would say the same thing. Import a list in the Series window first, or use Repeat if you want plain copies.',
	'api.plate.noSize':
		'This piece has no size on the plate, so there is nothing to lay out. A text that reads a column the list has not got is the usual reason.',
	'api.plate.nothing': 'There is nothing on the plate to lay out. Draw the piece first.',
	'api.plate.nothingReads':
		'Nothing in this piece reads from the list, so the copies would all be the same. Put a column into a text first.',
	'api.plate.onlyOne':
		'Only one of these fits on the plate, so there is nothing to lay out. The series burns them one plate at a time.',
	'api.plate.tooBig':
		'This piece is {piece_w}×{piece_h} mm and the plate has {room_w}×{room_h} mm free inside its margin, so not even one fits. Make the piece smaller, the margin narrower, or the sheet bigger.',
	'api.plate.tooMany':
		'{places} pieces on one plate is more than this app lays out; keep it under {max}. Above that the plan takes longer to build than the job takes to burn.',
	'api.series.badColumnName':
		'A column name cannot contain a curly bracket, because that is what marks a placeholder. Rename the column in your file.',
	'api.series.needsColumnName':
		'A numbered list needs a column name, because that is what goes between the curly brackets in the text.',
	'api.series.unreadable':
		'This file is not text this app can read. Save it from your spreadsheet as CSV UTF-8 and try again.',
	'api.series.emptyFile':
		'This file is empty. Save your list from the spreadsheet again and check that there is something in it.',
	'api.series.headerOnly': 'This file has column names but no rows under them.',
	'api.series.reservedColumn':
		'A column cannot be called date, time or version, or begin with op_ — the engine keeps those names. Rename the column in your file and import it again.',
	'api.series.braceInCell':
		'Row {row} has a curly bracket in the column “{column}”, and a curly bracket cannot be burned as a bracket. Take it out of the cell.',
	'api.series.tooManyRows': 'This list has {rows} rows and this app carries at most {max}.',
	'api.series.noFileChosen':
		'No file has been chosen, so there is no list to read. Pick a file, or fill in the numbers to count from.',
	'api.series.uploadGone': 'That file is no longer on the server. Pick it again.',
	'api.series.fileTooBig':
		'This file is larger than {max_mb} MB. A list of names is a few kilobytes; this is probably not the file you meant.',
	// The four ends of a counted range. One code each, because the sentence names which
	// end it is about and an English word wedged into a Dutch sentence would be the only
	// English left in it. The `which` the layer sends travels for a client without a
	// catalogue; here the code has already said it.
	'api.series.notAWholeNumber.first':
		'Numbered rows run from one whole number to another, and the first number is not a whole number.',
	'api.series.notAWholeNumber.last':
		'Numbered rows run from one whole number to another, and the last number is not a whole number.',
	'api.series.notAWholeNumber.step':
		'Numbered rows run from one whole number to another, and the step is not a whole number.',
	'api.series.notAWholeNumber.padding':
		'Numbered rows run from one whole number to another, and the number of digits is not a whole number.',
	'api.series.numberStepZero':
		'A step of nothing never reaches the last number. Count in ones, or in whatever step the parts really go up by.',
	'api.series.badPadding':
		'A number written {padding} digits wide is not a part number. Use 0 for no padding, or up to {max}.',
	'api.series.emptyRange':
		'Counting from {first} to {last} in steps of {step} makes no rows at all. Turn the step around, or swap the two ends.',
	'api.series.noRows': 'This list has no rows in it, so there is nothing to burn.',
	'api.series.everyRowBlank':
		'Every row is missing a value in {column}, so there is nothing to burn. Fill the column in, or switch off skipping blank rows.',
	'api.series.unknownColumn':
		'There is no column called {column} in the list, so this text would burn nothing. Take the placeholder out of the text, or add the column to the list and import it again.',
	'api.series.noList':
		'No list is attached, so a text with a placeholder in it cannot become anything. Attach a list in the Series window, or take the placeholder out of the text.',
	'api.series.nothingAttached':
		'No list is attached, so there is no row to burn. Import a list in the Series window first.',
	'api.series.bundleUnreadable':
		'The list in this project file cannot be read, so the project has opened without it. Import the list again from your spreadsheet.',
	'api.series.badRow': 'A row is counted with a whole number, starting at the first row.',
	'api.series.startPastEnd': 'This list has {rows} rows, so it cannot start at row {row}.',
	'api.series.blankRow':
		'Row {row} has nothing in it for the columns this design burns, and blank rows are being skipped, so there is no burn here. Switch off skipping blank rows, or move to another row.',
	'api.series.nothingVariable':
		'None of the text on the bed comes from the list, so every burn would be the same. Put a column into a text first.',
	'api.series.noBurns':
		'Every row in this list is missing a value the design needs, so with blank rows skipped there is nothing to burn. Switch off skipping blank rows, or fill the list in.',
	'api.series.alreadyStarted':
		'A series is already going. Stop it first — starting another one would throw away which plates have been burned.',
	'api.series.runGoing':
		'A series is going, so this button would burn one plate and count nothing. Press Burn this one instead: that is the button that counts the plates.',
	'api.series.runGoingTiles':
		'A series is going, and a series and a tile run both decide what the next burn is. Finish or stop the series first.',
	'api.series.otherRunGoing':
		'A tile run is going, and a tile run and a series both decide what the next burn is. Finish or stop one of the two.',
	'api.series.runGoingProject':
		'A series is going. Stop it before you replace the drawing, because the plates you have already burned belong to the design that would go.',
	'api.series.listLocked':
		'A series is going. Stop it before you change the list, otherwise what has been burned no longer matches what is left.',
	'api.series.noRun': 'There is no series going.',
	'api.series.alreadyBurned':
		'This one has already been burned. Burning it again means the laser goes over work that is already there — only do that when the last attempt was spoiled. Confirm to carry on.',
	'api.series.noSuchBurn': 'There is no burn for row {row} in this series.',
	'api.series.noRunner': 'This series has no way to reach the machine.',
	'api.sheet.needsName': 'A sheet needs a name.',
	'api.sheet.needsOne': 'The last sheet cannot go; a project has one.',
	'api.sheet.nothingSelected': 'Choose what should come along first.',
	'api.sheet.sameSheet': 'That is the sheet you are already working on.',
	'api.sheet.tooThick': 'A sheet more than 500 mm thick does not go in.',
	'api.sheet.marginTooBig': 'A margin of more than 100 mm leaves no bed.'
} as const;
