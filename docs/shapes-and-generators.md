# Shapes, text, images and generators

The drawing tools on the left give you a rectangle, a circle, a line and a pen path with curves in it. Everything else that puts geometry on the bed is on this page: text, images, clipart from public collections, and the eight generators that compute a shape out of a handful of numbers.

The second half covers what you do to geometry once it is there — combining, offsetting, splitting, rounding corners, filling, hatching and nesting. Those all live in the right-click menu on a shape, so they read as one set.

## Text

Pick **Text** in the tool rail and click the bed. The window **Place text** opens, and where you clicked is where the text lands.

![The Place text window over the canvas: a Text field reading "Made on the 5030", a Height (mm) field set to 10 and a Letter spacing field set to 1, an Alignment menu on Left, and below them a font list headed "Font (188 available)" with a search box. Default is picked; the rows below it — Academy Engraved LET, Andale Mono, Apple Braille — each show "Made on the 5030" on the right in that font. At the bottom a link "Font not in the list?" and the buttons Cancel and Place.](images/20-text.png)

Four fields decide the shape:

- **Text** — one line. Enter places it straight away.
- **Height (mm)** — the letter height in millimetres, not a point size. The default is 10.
- **Letter spacing** — the space between the letters, as a factor. 1 is the font's own spacing.
- **Alignment** — **Left**, **Centred** or **Right**, relative to the point you clicked.

The font list is the useful part. The name sits on the left in the interface typeface and the sample on the right in the font itself, filled with your own text — so a symbol font or an alphabet you cannot read still shows a name you can find again. The heading counts what was found (`Font (188 available)` on the machine in the picture); the search box filters on name. Sixty rows show at a time, and below them the line `{n} more — type to search.` **Default** at the top leaves the choice to the engine.

Text is placed as geometry, but the engine keeps the wording, so you can come back to it: right-click the text and choose **Edit text…**. The same window opens with your values filled in and the button reads **Update** instead of **Place**.

### Variables in text

A text can take its wording from a list instead of from you. Put a column name in curly brackets — `{name}` — and that text reads a different value on every plate the machine makes: fifty keyrings with fifty names on them is one drawing and fifty burns. The list is a CSV out of your spreadsheet, or a counted range of numbers for parts 001 to 250.

You do not have to type the brackets. Right-click the text and the menu offers **Insert a column**, with a row per column of the list; with exactly one column that row *is* the column and reads **Insert {column}**. Without a list attached the row is greyed and says why: `No list is attached in the Series window`.

With a placeholder in it, the panel on the right shows two lines instead of one — the text as you typed it, and what it comes out as for the plate that is next: `For the burn now on the bed this reads “Anna”.`

Two brackets are refused as you type them, because neither can be burned: a bracket that does not open and close once around a name (`A curly bracket has to open and close once around a column name, and a bracket cannot be burned as a bracket.`) and one that counts backwards (`A placeholder cannot count backwards. It would read the list's own bookkeeping instead of a row.`).

The whole of it — the list, the window, the run at the machine, and a jig frame that burns only on the first plate — is on [Variable text](variable-text.md).

### Fonts the app cannot see

The engine reads `.ttf` and keeps its list in a cache, so a freshly installed font — or an `.otf` — is not in the list. The link **Font not in the list?** opens a second list of fonts that are on your computer but unseen, with the explanation: `The engine only reads .ttf files. These are on your computer but are not seen; importing makes a usable copy of one.` Clicking one makes a usable copy and picks it. Fonts whose file has since been deleted are dropped from the list rather than shown, because they can only fail.

### When it goes wrong

- Empty text: `Text cannot be empty.`
- Quotation marks in the text: `Quotation marks in text are not supported yet.`
- No usable font at all on the machine: `There is not one usable font on this computer.` If the engine has no font support built in: `No font support available.`
- A font that draws nothing at this size: `The text yielded no shape.`

For text that follows a curve, see **Arc text** under the generators.

## Images

**Place image** in the tool rail opens a file picker for `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp` and `.webp`, and drops the picture on the bed. Import in the top bar does the same for the wider list of design files.

An image only burns in a raster layer. What decides how it comes out of the machine is the fold **Image** in the panel on the right, which appears when an image is selected. It holds eight switches; the summary shows `{n} on` when any of them are, and **Clear everything** puts the image back as it came in.

What the switches do, in the order they sit in the panel:

- contrast and brightness, both on a scale from −127 to 127;
- gamma, as a factor between 0 and 5;
- automatic contrast, with a cutoff percentage;
- sharpening, with strength, radius and threshold;
- edge enhancement, on or off;
- halftone, with a sample size, an angle and an oversample factor;
- dithering, with a **kind** menu: Floyd-Steinberg, Atkinson, Jarvis-Judice-Ninke, Stucki, Burkes, Sierra3, Sierra2 and Sierra-2-4a;
- invert.

None of it touches the pixels you imported. The switches are a recipe that runs over the original again on every change, so pressing the same one twice does not do it twice, and switching something off really brings the image back. That is also why the panel can show you what is on.

Below the switches sits **DPI**, between 10 and 2000. It decides how finely a raster layer scans the image, and with it the burn time — it is the one number here that changes the job and not the picture.

### Cropping

Right-click the image and choose **Crop**. The menu says what happens next: `Then drag a frame over the image`. Drag a box on the bed and the image is cut to it. There is no other hint on screen while crop mode is on, so if you were expecting a frame with handles, drag the box.

The crop is part of the same recipe, so it is reversible and a second crop computes from the original rather than from the already-cropped result. **Undo crop** appears in the menu once an image is cropped.

### Tracing to vector

Right-click the image and choose **Vectorise** — `Turns the image into paths`. That is what you want for a scanned drawing you intend to cut instead of engrave: the paths appear beside the image, which stays.

### When it goes wrong

- A crop box dragged to nothing: `The crop box needs a width and a height.`
- A crop box beside the picture instead of over it: `The crop box falls outside the image.`
- A value outside a switch's range is refused by name, for example that contrast has to be between −127 and 127; DPI outside 10–2000 is refused the same way.
- Tracing depends on plugins that can be absent from an installation. When the tracer is missing, the refusal names which ones are available — and if the answer is none, tracing is not possible on that machine.

## Clipart from public collections

**Search clipart** in the tool rail opens a search across three collections: Iconify, Wikimedia Commons and Openclipart. Icons are the most usable material on a laser — closed outlines, no gradients — which is why Iconify comes first.

![The Search for clipart window: a search field holding "star", a Width (mm) field set to 60 and a Search button, three ticked source boxes for Iconify (iconen), Wikimedia Commons and Openclipart, a warning line saying Openclipart did not answer in time, with "The rest is there.", and a grid of star thumbnails. Each carries its title and licence — several "Apache 2.0 · source", one "CC BY-SA 4.0 · source", one "Public domain · source".](images/19-clipart.png)

Type at least two letters and press Enter or **Search**. **Width (mm)** is the size the drawing gets when you insert it; the tooltip on a result reads `Insert at {width} mm wide`. Clicking a thumbnail fetches it, scales it to that width and puts it on the bed.

Every result carries its licence, or `licence unknown`, plus a **source** link to the page it came from. The window says why that matters up front: `Searches public collections. What you find belongs to someone else: the licence is with every result, and it decides whether you may sell what you cut with it.`

At the bottom, `{n} shown` with **More results** beside it, or `that is all` when a collection has run out.

### What does not survive the trip

An SVG can hold things a laser has no notion of. The check runs at insert time, not at search time, and it reports rather than refuses. You get a note naming what is dropped — gradients, filters, masks, text (which does not become a path) and embedded pixels — and the drawing goes in without them.

A second note warns about weight: a drawing built from more than 400 separate paths makes a long job, and that is worth knowing before the machine starts rather than after.

### When it goes wrong

- A search that returns nothing: `Nothing found. English words usually give more results.` Before you have searched at all: `Type a word and press Enter.`
- One collection down while the others answer: `{source} {reason}. The rest is there.` — in the picture above, Openclipart did not answer in time.
- An SVG the engine cannot read at all is refused, with the notes about what it contained appended to the reason.
- Only the three collections are fetched. An address pasted from elsewhere is refused, with the advice to pick a drawing from the search window instead.

## Generators

**Generators** in the tool rail opens one window with eight tabs. Every tab is a small form on the left and, beside it, the shape that form makes.

![The Generators window over the canvas, on the Repeat tab. Eight tabs across the top: Repeat, Circle, Polygon, Box, QR code, Barcode, Arc text, Living hinge. The form holds Columns 4, Rows 3, Space X (mm) 5 and Space Y (mm) 5, with a teal button reading "Make 12 copies — 175 × 100.0 mm". To the right a preview panel shows the selected rectangle repeated in a 4 by 3 grid, with "175 × 100.0 mm 12 pieces" under it and the warning "This falls outside the sheet."](images/18-generators.png)

### The preview

The picture beside the form is not a drawing of the idea — it is the result. The engine runs the same calculation it will run for the real work and sends back the outlines in millimetres, so what you see is what gets burned, including where it lands on the sheet. It refreshes as you type, with a fifth of a second of rest so it is not recomputed per keystroke.

Under the shape sits its size as `{width} × {height} mm`, and the count in the unit that fits the thing: pieces for a repeat, panels for a box, modules for a QR code, bars for a barcode, slits and rows for a living hinge. If anything sticks out past the sheet edge you get `This falls outside the sheet.` — on a laser that is not a detail.

Two things it deliberately does not do. It does not blank out while you are halfway through typing a number: the last valid shape stays up with the reason above it (`Not complete yet: fill in the empty fields.` and `Below is your last valid shape.`). And for **Repeat** and **Circle**, which need to know what they are repeating, it falls back to a sketch of the fields marked `Sketch, not to scale` for as long as it does not have the shapes you picked, rather than repeating an invented shape that looks like yours and is not.

Two other lines you will meet there: `Type something and it appears here` before you have typed anything, `Calculating…` while it is being worked out, and `The engine cannot draw this.` when the answer comes back empty.

The primary button carries the outcome, so you can read what is coming before you commit: **Make 12 copies**, **Place around**, **Draw**, **Make panels**, **Make the hinge** or **Place**, each followed by the size or the piece count.

### Repeat

Copies the selection in rows and columns. Select the shapes first; without a selection the tab says `Select what should be repeated first.`

Fields: **Columns**, **Rows**, **Space X** and **Space Y**. The spacing is the gap *between* the shapes, not the pitch from one to the next — `The distance is the space between the shapes, because that is where the cut goes.`

Under them a tick: **Each copy takes the next name from the list**. Repeating a tag that reads `{name}` gives you twelve identical Annas otherwise, because a copy is a copy. With this on, copy one reads the next row, copy two the one after that, in reading order — which is how you fill a plank with twelve different tags and lay them out yourself. It needs a list; without one the tick is greyed with the reason, and asking anyway comes back as `No list is attached, so there is no next name to take. Import a list in the Series window first.` With a list but nothing variable in what you picked: `None of the shapes you are repeating has a placeholder in its text, so there is no name for the copies to take. Put a column into a text first.` See [Variable text](variable-text.md#more-than-one-on-a-sheet).

### Circle

Copies the selection around a centre point. Fields: **Count** (at least two), **Radius**, and the tick **Rotate along**, which turns each copy to face outward instead of keeping it upright.

The centre lies one radius to the left of the selection, so the original itself sits on the circle.

### Polygon

A regular polygon, and no selection needed. Fields: **Corners** (at least three), **Radius**, **Inner radius**, **Centre X** and **Centre Y**.

**Inner radius** is the one worth knowing: leave it empty and you get a plain polygon, fill it in and the same corner count becomes a star. **Corners** counts the corner points, not the star's points, so a five-pointed star is five corners and not ten.

### Box

Loose panels for a finger-jointed box, laid out on the sheet. Fields: **Width**, **Depth** and **Height** on one line, then **Material thickness**, then **Finger** and **Kerf**, and two ticks: **With a lid** and **Spread over sheets when it does not fit**.

Three things the tab tells you and that are easy to get wrong: the three sizes are **outside** sizes; the kerf is added to the teeth, because the laser takes material off both sides of the cut; and when the panels do not fit on one sheet the rest goes to a next sheet rather than off the bed. The button then reads `{parts} on this sheet, {sheets} sheets` instead of `{parts} pieces, fits on this sheet`.

With a lid ticked, the walls get teeth along their top edge for the lid to engage; without it, the top edge is straight.

### QR code

Fields: **Content** and **Size**. The code is made as filled areas, not as a picture, and the reason is on the tab: `A QR code as areas, not as a picture: engraved bitmaps often come out vague on wood, filled squares do not.` The preview draws it solid, because nobody can read a QR code made of separate little outlines.

### Barcode

Fields: **Content**, **Type**, **Width** and **Height**. Seven types are offered: `code128`, `code39`, `ean13`, `ean8`, `upca`, `itf` and `issn`. Like the QR code it comes out as areas.

EAN and UPC make demands on length and check digit. The tab says what happens when your content does not meet them: `if it does not add up the app says so instead of making a code that will not scan.`

### Arc text

Text bent along a circle, for a round sign or a lid. Fields: **Text**, **Centre X**, **Centre Y**, **Radius**, **Letter height**, the tick **Along the underside**, and a **Font** row that starts collapsed showing `Default` — open it and you get the same font picker as the text window, with the sample line in your own words.

One thing to know before you use it: the result is a path and no longer text. The tab says why — the engine would render the wording straight again at the next change and silently wipe the arc away. So set the words right first; afterwards you edit it as geometry.

### Living hinge

A field of slits that lets rigid sheet material bend. Cut enough short slits across a piece of plywood and the strips of material left between them twist instead of snapping, and the sheet rolls. The tab says which way: `A field of slits that lets rigid sheet material bend. The slits lie across, and a sheet bends around a line parallel to its slits, so this one curls from top to bottom. Turn the group a quarter afterwards and it bends the other way.` There is no direction field, because a rotation already exists.

![The Generators window on the Living hinge tab: the Pattern chooser set to Staggered rows, Slit length 8 mm, Gap in a row 3 mm and Between rows 2 mm, the line about what stays behind between them, and a preview of a dense field of short slits captioned with its size and the count of slits and rows.](images/28-hinge.png)

**Pattern** picks the slit shape: **Straight slits**, **Staggered rows** or **Wavy slits**. Staggered is the one to start with — every other row is shifted half a pitch, so the bridge in one row sits opposite a slit in the next and the sheet bends evenly instead of hinging on a few lines. Wavy slits put more cut length in the same span and bend more easily; the slit becomes two curves rather than a straight line.

Then three numbers, and they are the whole design of a hinge:

- **Slit length** — how long one slit is.
- **Gap in a row** — the material between two slits in the same row.
- **Between rows** — the distance from one row of slits to the next.

Beside the fields stands what those two gaps mean in wood: `Between two slits in a row 3.0 mm of material stays behind, and between two rows 2.0 mm. That bridge is what twists, and what breaks.` It says no more than that on purpose. How thin a bridge may be depends on the material, the thickness and how far you want to bend it, and a generator that pretends to know that is guessing with your plywood.

The area comes from one of two places. Tick **Fill the area of the selected shape** and the slits fill that shape — inside its outline, not inside the box around it. On a circle that means a round field of slits; on a rectangle the two are the same thing. Select a shape and a hole in it, and the hole stays empty, the way a fill would leave it. The tick reads **Select a shape first to use its area** when there is nothing selected. Untick it and you get four fields instead — **Left**, **Top**, **Width** and **Height** — and the field is placed on the bed where you say.

The count then comes out lower than the width and the pitch would predict, and the preview says why: `62 slits fell outside the outline of the shape and were left out; the field follows the shape, not the box around it.` Measured on a circle 60 mm across with 6 mm slits, 2 mm gaps and 3 mm rows: 160 slits fill its box, 132 fill the circle.

Two things to know about it. The outline is followed as a polygon approximation of whatever curve is really there — on a circle of 60 mm that is within a few hundredths of a millimetre of the arc, which is less than the width of the cut that follows it. And the field is geometry once it is drawn: resize or reshape the outline afterwards and the slits stay where they were put, exactly as they do when you type the area yourself.

Rows are laid out from the middle of the area outwards, so no row lands exactly on the boundary: a slit on the edge weakens the edge and hinges nothing. Along the row the field is tiled from the left and then clipped to the area, and the half slits that leaves at the edge of a staggered row are meant to be there — without them the stagger stops at the edge.

The result is one shape in a cut layer, named after the pattern it was made with, with every slit as a loose piece of it. It moves as one thing, and the laser cuts each slit once. The count under the preview reads `{n} slits in {rows} rows`; measured on a 60 × 40 mm area with a slit of 8 mm, a gap of 3 mm and 2 mm between rows: 120 slits in 20 rows for straight and staggered, 114 in 19 for wavy, which needs a little height for its crests.

### Focus test

Only on a machine whose Z axis the software can move. Elsewhere the tab is not there at all, and that is not tidiness: a focus board on a machine that cannot move its head would burn every mark at the same height — ten identical marks that look like an answer. The same flag decides this and **Drop per pass** in the layer panel, so a machine cannot offer one and refuse the other.

The focal point of a lens is a plane a few tenths of a millimetre thick, and where it lies depends on the lens, the nozzle, the material thickness and whatever the last person to touch the machine did. The board answers it by measurement: the same short line burned at a series of heights, with the height written under each one. Burn it, look for the thinnest and darkest mark, and set the head at the height beside it.

![The Generators window on the Focus test tab: Sweep start -2, Sweep end 2 and Marks 9, the
line about which way a plus moves the head, the step per mark, the size and position fields,
and a preview of nine short lines side by side captioned with the board size and the step in
height.](images/33-focus.png)

Three numbers make the sweep — **Sweep start**, **Sweep end** and **Marks** — and beside them stands what they come to per mark: `0.5 mm between two marks, over a sweep of 4.0 mm.` That step is the thing you are really setting and it is in none of the three fields, which is why it is spelled out; a board whose marks are a tenth of a millimetre apart cannot answer its own question, and you find that out after burning it.

Which way is which is written under the fields: `The numbers are offsets from the height the head is at when the job starts: a plus drops the head, a minus raises it. Afterwards it goes back to where it began.` They are offsets and not machine coordinates, because the height the head starts at is the one thing the software cannot know. The sign is the same convention as the drop per pass — one rule, not two.

Then **Mark length** and **Space between marks** for the size of the board, **Left** and **Top** for where it lands, and **Burn the height under every mark**, which is what makes the board readable a week later.

Every mark becomes a layer of its own. That is not tidiness either: the engine keeps one settings dict per layer, so a height per mark has nowhere else to live. What actually moves the head is a console step in the job between the marks, and it moves by the *difference* with the previous mark, with one move at the end that brings the head back to where it started.

Refused, in these words: fewer than two marks ("one mark compares nothing"), both ends the same, a sweep further than 20 mm, more than 30 marks, and steps closer together than 0.05 mm — "closer than you can see on the material. Use fewer marks or a wider sweep." A board that would fall off the bed is refused with both measurements in the sentence.

### When it goes wrong

The refusals come from the same calculation as the preview, so what you read while setting up is what you read if you press the button anyway.

- Repeat or Circle with nothing selected: `Choose what should be repeated first.`
- A grid of one cell, a negative gap, fewer than two copies for a circle, fewer than three corners for a polygon, or an inner radius that is not smaller than the radius — each refused in those words.
- Box, material too thick for the sizes: `The material is too thick for these outside sizes; the walls would touch each other.`
- Box, finger too narrow: `A finger narrower than the material is thick snaps off.` followed by the minimum in millimetres. Too wide: `The finger is too wide: three of them do not fit on an edge.`
- Box, a panel wider than the sheet: the message gives both measurements and asks for smaller outside sizes. A kerf outside 0–2 mm is refused as well.
- QR code without content, or too much of it: `This text is too long for a readable QR code.`
- Arc text that would wrap onto itself: `This text is too long for this radius; it would run over itself. Choose a larger radius or a smaller letter.`
- QR codes and barcodes lean on packages that can be missing from an installation. Then you get `QR codes need the segno package; install it beside the API.` or `Barcodes need the python-barcode package.`
- Living hinge, a slit as long as the area is wide: `A slit of 60 mm is as long as the 60 mm area is wide: that cuts the piece in two instead of bending it. Shorten the slit.`
- Living hinge, an area that has no room for two rows: `This area is 40 mm high; at 30 mm between rows that is not two rows of slits. Make the area taller or the rows closer together.` One row of slits is a row of slits, not a hinge.
- Living hinge, more slits than the cut plan can carry: `This comes to about 80400 slits; above 4000 the cut plan takes longer than the burn. Choose a bigger gap or fewer rows.`
- Living hinge with the area from a selection, but nothing selected: `Choose the shape whose area the slits have to fill first.` And if the clipping leaves nothing at all: `Nothing is left of this field inside the area.`
- Not a refusal but a warning under the preview, because whether it is fatal depends on your material: a gap of 0.4 mm or less gets `The bridges between the slits are 0.3 mm wide, and a CO2 cut is 0.1 to 0.3 mm wide itself: they burn away and the field falls apart.` Slit remnants at the edge shorter than half a millimetre are dropped and counted in a second line — that short, a cut frees nothing.

## Working on the geometry: the path operations

Right-click a shape and the middle of the menu holds everything that reshapes it. The same list feeds the **More** button in the action bar above the canvas, so you can reach it without the right mouse button. A greyed row always carries its reason in the tooltip — `Pick a shape first`, `Select at least two shapes`, `Another operation is still running`, `Requires a token`.

### Combine

The submenu **Combine** holds **Union**, **Difference**, **Intersection** and **Exclude**. It needs at least two shapes, and the tooltip states the price: `The result is one path; the shapes disappear`.

When it goes wrong: `That combination yielded nothing — do the shapes actually overlap?`

### Offset

**Edit path → Offset…** opens a small window. One field, **Distance**, in millimetres, with the direction spelled out beside the number, because a minus sign is the input and "inward" is the meaning: `{mm} mm {direction}`. The window explains the result — `A new path appears beside the existing one. The original shape stays.` — and the button repeats what you asked for before you press it.

This is the operation for kerf compensation and for a border round a shape. An empty or zero distance shows `Fill in a distance; negative is inward.` If the engine produces nothing: `The engine made no offset.`

### Simplify

**Edit path → Simplify** takes nodes out of a path without changing its shape. Worth doing on a traced image or a CAD export, where the point count can make a job much slower than the geometry deserves.

### Split

**Edit path → Split into separate shapes** takes a path made of several loose pieces apart. When there is something to split the row counts it — `Split into {n} shapes` — and the panel on the right says the same thing in full: `This shape consists of {pieces} loose pieces. An export from a CAD program is often one path; the pieces can only be clicked separately after splitting.`

Afterwards you get `{n} shapes — clickable separately.` A single-piece shape refuses with `This shape is a single piece`, and if you get that far anyway: `This shape consists of one piece; there is nothing to split.`

### Corners

**Corners…** opens a window with the drawing beside the numbers, because "5 mm" tells you nothing about how round that corner becomes.

Two styles, **Round** and **Chamfer**, plus a **Size** in millimetres. Which style you pick changes what the shape *is* afterwards, and the window says so:

- Round on a rectangle: `A rectangle stays a rectangle, so you can adjust the radius later.`
- Chamfer, or round on anything else: `This turns the shape into a path: width and height can no longer be changed separately afterwards. Undo brings it back.`

The button names both the count and the size, for example `3 shapes: Round the corners — 5 mm`.

When it goes wrong: corners it cannot do are skipped and counted — `{n} corners were skipped: the sides are too short for it, or an arc meets there.` When not one of them can be done: `Not one corner can be rounded or bevelled: no two straight sides meet there, or the size is too big for the sides. Choose a smaller size.`

### Fill

**Fill — for rastering** gives a shape an inside. Without it, a shape in a raster layer burns only its outline: `Without a fill a shape only rasters its outline`. With it: `A raster layer then burns the area instead of just the outline`. The row flips to **Remove fill** once the shape is filled.

Afterwards: `{n} shapes filled — a raster layer now burns the area.` A line has nothing to fill and is skipped with `{n} were skipped: a line has no inside.`

One thing an estimate will not tell you: filling does not change the time. A raster layer scans its bounding box line by line whether the shape is filled or not — only the result differs, which is exactly why an empty raster layer is so easy to miss.

### Hatch and wobble

**Edit path → Hatch** fills a shape with lines the head follows; **Wobble** makes the cut wander along its path. Both behave differently from the rest of this list: they are not a property of the shape but a layer of their own that refers to it, so they appear in the Layers tab. A shape that is part of one says so in the panel: `Part of effect: {label}`.

### Nest

**Edit path → Nest** slides the selected shapes close together to save material — `Pack the selection close together to save material`. It needs at least two: `Choose at least two shapes to nest.`

Two honest limits. It computes on bounding rectangles rather than real outlines, so two round shapes can end up further apart than strictly necessary — never overlapping, just not optimal. And a group counts as one thing: whatever belongs together moves as a whole and keeps its internal spacing exactly. That last one is not tidiness. A test board is a measuring instrument, and once its squares have been shuffled relative to each other, "row 3, column 5" means nothing.

The canvas menu has a related entry, **Put everything on the bed**, which nests the whole design — including what lies off screen and cannot be clicked.
