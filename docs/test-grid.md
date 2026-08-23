# Test grids: finding the settings for a material

A test grid is a board of small squares, each burned at a slightly different speed and
power. You burn one, look at which square came out right, and OpenKerf turns that square
into a saved setting for that material. This page follows the whole loop: planning the
board, what lands on the bed, burning it, photographing it, aligning the photo, and
reading off the square you want to keep.

## Why you burn one

Speed and power are not properties of a material, they are properties of your machine on
that material: the same 3 mm birch cuts at one setting on a tired tube and at another on
a fresh one. A number somebody else wrote down is a starting point, not an answer.

The board is also evidence. Two weeks later you no longer remember what "25 at 60" was
about, but a plank with the values engraved beside the squares still tells you. That is
why the caption is on by default, and why the photo stays attached to the setting it
produced.

## Opening the window

The **Test grid** window opens from the tool rail on the left, from the button of the same
name. Coming from the material library it opens with the material already filled in: each
material heading there carries a **Make a test grid** link, and the row menu of a single
setting has **Make a test grid for {material}**.

If the sheet you are working on already has a material and a thickness, both fields start
filled in — the board is about the plank that is in the machine, so those two are not a
question any more.

The window shows the four steps of the loop across the top: **Set up**, **Burn**,
**Photograph**, **Best square → preset**. Steps 1 and 2 are the wizard at the top of the
window; steps 3 and 4 are the block underneath it, headed **Steps 3 and 4 — photo and
preset**.

![The Test grid window over the canvas: the four numbered steps across the top, the form on the left with Material, Operation, Thickness, Square, Passes and the two axis choices, and on the right a preview of a four-by-four board with power percentages above it and speeds beside it, above the button "Draw the grid — 16 squares, 57.9 × 58.3 mm"](images/16-testgrid.png)

**Without a token.** A read-only session cannot draw a board. The window then says:

> Generating a test grid requires a token.

## Which quantity on which axis

Three quantities can be swept: **Speed** (mm/s), **Power** (%) and **Line spacing** — the
interval, in mm. Two of them go on the axes, **Rows, downwards** and **Columns, to the
right**; the third stays the same over the whole board and gets a field of its own,
labelled for instance *Speed (fixed, whole board)*.

The default is speed down and power to the right. Picking for the rows what is already in
the columns swaps the two, rather than refusing the choice.

Line spacing only takes part when you are rastering. With **Cut** and **Engrave · vector**
the head lays one line and there is no spacing between lines, so the option is not offered
for those operations. If you switch the operation back to cutting while the interval was
on an axis, that axis falls back to speed or power on its own.

**Passes** is deliberately not an axis. It applies to the whole board — it multiplies the
burn time of everything on it, and a board where each column had a different number of
passes is not a board you can read back. It goes on the caption instead, so you can still
place the plank in two weeks.

## The ranges

Each axis has its own block: **from**, **to** and **Steps** (in rows, or in columns).
The first and last value are exactly what you typed — that is the range you want to sweep.
The values in between are nudged to tidy numbers, so the board does not end up with a row
at 11.667 mm/s that you will never type again. When rounding would produce two identical
rows, the raw numbers stay.

**Suggest a range** fills from and to for speed and power from what the library already
knows about this material, thickness and operation. It then says what it based that on:

> Range suggested on the basis of 3 existing presets.

or, when there is nothing to go on:

> No presets for this combination yet; this is a broad starting point.

**When it goes wrong.** The board is refused, and the reason appears beside the preview:

- from higher than to — *The speed at 'to' has to be at least the speed at 'from'.*
- fewer than two steps — *The number of steps speed has to be at least 2 — otherwise you
  vary nothing.*
- power above 100 — *Power cannot go above 100 per cent.*
- a line spacing above 5 mm — *An interval above 5 mm is no longer an engraving.*
- too many squares — *25×20 cells is too many; keep it under 400.*

While you are typing, the range is briefly invalid — you raise "from" and it is higher
than "to" until you fix that too. The preview does not go blank then. The reason appears
above it with:

> Below is your last valid board.

## The size of the board

**Square (mm)** is the side of one square, **Gap (mm)** the space between two of them, and
**Passes (× per square)** how many times the head goes over each square.

A square of 8 mm with a gap of 2 mm and four steps each way gives a grid of 38 × 38 mm.
The board itself is larger than that, because the labels and the border burn too — the
preview reports the whole thing and says what the difference is:

> Of which 38 × 38 mm is squares; the rest is caption and border.

## What else goes on the board

Under **What else goes on the board** there are two switches:

- **Engrave the caption and axis labels** — on by default. The axis values are engraved
  beside the rows and above the columns, and the caption goes above that. Switch it off
  and the hint says why you would rather not: *Without a caption the board is a puzzling
  piece of wood in two weeks — and the axis values will not be on it either.*
- **Border around the board** — a line around everything, caption included. Off by
  default. *The border is a line around the whole board; it makes aligning the photo
  easier.*

The caption and the border are burned in a layer of their own, called **Board labels**, at
a speed and power you set yourself: **Caption: speed** and **Caption: power** (or *Border:* when only the border
is on). They start at 80 mm/s and 30%. That layer does not join the sweep — it has to stay
readable whatever the trial does — and on a material other than plywood the default can
burn straight through your board.

**Caption on the board** is your own line, up to 48 characters, for instance
*test back side*. OpenKerf engraves it with the material, the thickness, the operation,
which quantity is on which axis, the fixed quantity, the number of passes when it is more
than one, and the date. What you have already said yourself is not repeated: type
"3MM Acryl Engrave" and it will not add "Acrylic (extruded) · 3 mm · engrave" behind it.

The caption never makes the board wider than its squares plus the row labels. It shrinks
until it fits, and only breaks onto a second line when shrinking further would make it
unreadable.

## A board that says who it is, and a tile you can keep

Two more things a board can carry. Both were built this round, both are in the engine, and
**neither is on the form yet** — today they are asked for through the API, on
`POST /api/library/testgrids`, with `code_enabled` and `cutout_enabled`. And neither has
ever been burned: not one board with a code or a cut-out has come out of a machine, on any
material. The numbers below are measured on pixels and on the engine's own cut plan, not on
wood. Read them as a starting point, exactly the way you would read somebody else's speed
and power.

### The code, and what it is for

Every board has a name of its own — eight characters, minted when the board is planned, kept
for as long as the row exists. Boards that predate this round were given one too, so every
board in your library already has a name whether or not it is burned on the plank.

That name can be burned on the board as a QR code saying `OK1:7X4MQB2K`. When it is, the
same name goes on the end of the caption line in a form a person can read — `7X4M QB2K` —
so a board whose code is scuffed or badly lit can still be identified by eye.

The reason is a repair, not a feature. Of the thirty-two boards in the author's own library,
**eleven are physically indistinguishable from another one** — same material, same square
size, same sweep, burned minutes apart. By the time the wood is off the machine, filing the
photograph is guesswork, and guessing wrong writes somebody else's numbers into a setting
that then carries the wrong photograph as its evidence. A board that says who it is takes
the guess out: photograph it, and the picture finds its own row.

The characters are Crockford's base32 — the alphabet without I, L, O and U, because those
are precisely the ones somebody mistypes off a plank, and the line printed in the caption is
meant to be read back by a person.

### How big it has to be, and why

The default is **18 mm** square, quiet zone included. That is not a round number picked for
looks:

- A board name is always 21 modules of QR, **29 with the four-module quiet zone** the
  standard asks for — measured over 300 minted names, always exactly that, so the footprint
  of a code never changes.
- 18 mm over 29 modules is a **0.62 mm module**, which clears the rule of thumb that a
  module wants to be at least three kerfs wide.
- Of those 18 mm, 4.97 mm is quiet zone and the pattern itself is 13.03 mm. That margin is
  what keeps the caption, the squares and the rim out of the pattern — and it is not what
  makes the code readable in a frame, which an earlier version of this page claimed. On a
  simulated photograph of a code with **nothing** around it, no quiet zone never decoded
  (0 of 20 at 3, 6 and 12 pixels per module) while two modules and four both read 20 of 20;
  on a photograph of the same code **on a plank**, even no quiet zone read 20 of 20,
  because the unburned wood around it is the quiet zone.

How big it has to be in the *photograph* was measured on a simulated one: the code rendered
from the millimetres the laser gets, stamped on a 300 mm plank with the board's own sixteen
squares beside it, turned 5°, blurred, speckled and saved as JPEG at quality 85 — forty
different names at each size, read back through the same two decoders and the same retry the
app uses. Rendering it instead through the 167 dpi bitmap the machine really rasterises
moves none of the rows.

| The photograph is | Pixels per module | Names decoded |
| --- | --- | --- |
| 1200 px across | 2.5 | 0 of 40 |
| 1600 px across | 3.3 | 16 of 40 |
| 2000 px across and up | 4.1 and up | 40 of 40 |

Any phone takes a 2000 px picture. What does *not* work is the 1600 px copy that travels
with a contribution — so a code is read off the upload, never off a downsized copy.

The blur is what decides those bottom two rows: leave it out and 1200 px decodes as well.
That is worth saying because an earlier version of this page printed a far kinder pair for
them (34 and 36 of 40), measured without it — which describes a screen and not a plank.

Which decoder matters as much as the size: on the same photograph the plain OpenCV detector
read 1 of 20 where the Aruco detector read 19 of 20, so OpenKerf asks Aruco first and keeps
the plain one as the fallback for an older OpenCV. It is the photograph that defeats the
plain detector and not the board's own dark squares — take the sixteen squares out of the
picture and it reads no better; take the blur, the tilt and the JPEG out and it reads every
one.

Below 14 mm the code is drawn with a warning — *A 13 mm code has 0.45 mm modules;
photograph the board from close by, or make the code bigger.* — and below 12 mm it is
refused outright:

> A board code smaller than 12 mm cannot be read back; 11 mm was asked for.

A code that cannot be read is not a smaller version of the feature; it is burn time and a
board that still cannot say who it is.

### Where it goes on the board, and what it costs

Bottom right, outside the squares, in a strip the board grows for it: the code plus a 2 mm
gap, so 20 mm of extra board at the default size. Growing the board rather than fitting the
code inside it is what makes the bed check, the frame and the cut-out cover the code without
being told about it. Bottom right because the caption and both sets of axis labels are up in the
top-left corner, which makes it the only corner with nothing else burning near the quiet
zone, and because it is outside the block of squares you drag the four alignment handles
onto.

It burns in a raster layer of its own, called **Board code**, at 167 dots per inch and at
the caption layer's own speed. Both of those are pinned rather than settable, and the reason
is arithmetic: at the engine's default 500 dpi the same code costs 46.4 s, which nearly
doubles a small board. At 167 dpi — 0.15 mm a line, about four overlapping lines across a
0.62 mm module — it is 15.8 s.

It has to be a raster layer. An engrave layer traces outlines and never looks at a fill, so
the same 212 filled modules come out of the machine as 212 little outlines with unburned
wood inside each one, and nothing on earth reads that. Measured through the engine's own
plan: one raster object against 848 cut objects. On an engine with no rasteriser at all the
code is refused rather than drawn:

> This engine cannot burn a raster layer, so it cannot burn a board code either. Leave the code off, or install a rasteriser.

Measured on a four-by-four board through the real cut plan: **56.9 s and 17 layers** plain,
**73.8 s and 18 layers** with the code.

A board of small squares can run out of room for it, and that is said while the numbers are
still on screen rather than after the button:

> A 18 mm code does not fit beside 12 mm of board; use bigger or more squares, or a smaller code.

### Reading it back off a photograph

With a code on the board, a photograph does not need to be told which board it is of. There
is a route that takes a picture with no board named — it decodes the code and files the
picture against the board it names. And the ordinary per-board upload now refuses a
photograph whose code names a *different* board of your library:

> The code in this photograph says board 7X4M QB2K; you picked R8KA C1HX. File it under 7X4M QB2K, or pick that board here.

That is the mix-up the whole thing exists for, and it is the one mistake that cannot be
repaired later: the picture would sit under a row it is not of, and every setting drawn from
it would carry it as evidence.

Three more answers, because each sends you somewhere else: no code in the picture — *No code
was found in this photograph. Choose the board it belongs to yourself, or photograph the code
more squarely.*; a code this library does not know — *The code in this photograph says board
7X4M QB2K, and this library holds no board of that name. It belongs to another library, or
the picture caught a code that is not a board.*; and two boards in one frame — *This
photograph holds the codes of more than one board (7X4M QB2K and R8KA C1HX). Photograph one
board at a time, so the picture is evidence for the board it is filed under.*

Reading a code needs OpenCV, which is not part of the engine's own installation. Without it
the board still burns its code and everything else still works; only the reading back is
gone, and it says so: *Reading codes from photographs needs OpenCV. Install it beside the
engine with 'pip install opencv-python-headless'. Choose the board yourself for now.*

A code that reads back but names nothing in this library is deliberately left alone: eight
characters of that alphabet is not a rare thing for a stranger's QR sticker to survive, and
blocking a perfectly good picture over one in the corner of the frame would be worse than
ignoring it.

One thing the printed name cannot do yet: the board picker in step 3 does not search on it,
so with no camera and no OpenCV you are still choosing the board off its date, material and
operation the way you always did.

![The bed with a test board drawn on it: four rows of four squares with the power percentages above the columns and the speeds beside the rows, and the caption across the top — "Cut trial", the material, the thickness, the operation, which way the two axes run, the date, and on its own last line the board name 7X4M QB2K. Below the squares, at the bottom right of the board, a QR code.](images/41-board-code.png)

### Cutting the tile loose

The other thing a board can carry is a cut around itself, so the finished board comes out of
the sheet as a tile you keep — flat, photographable, filable in a drawer beside the others.

What it draws is one rectangle **4 mm outside everything else on the board**, in a cut layer
of its own called **Test board cut-out**. Four millimetres and not the two the engraved
border uses, because the engraved border *is* the board's outer box — a cut at the border's
own padding would run along the frame. Four is also a rim you can hold, and one that survives
the char of its own cut.

That margin is what "does the board fit on the bed?" is now measured on. It has to be: on the
default form the board's own left edge sits 0.4 mm from the edge of the bed, so a cut-out
asked for there would run 3.6 mm off the bed while every number on the form said the board
fitted. Without a cut-out the two rectangles are the same and nothing changes.

**The tile hangs on four tabs until you snap it out.** Four gaps of 2 mm, one in the middle
of each side, through the engine's own bridge mechanism — so the cut plan, the time estimate
and the stream to the machine all get the gaps for free. They are not optional, and that is
the point of the layer order: a tile that comes free while the sweep is still running
shifts, and the rest of the squares then burn on a moving target. That is a board you cannot
read and material you cannot get back.

For the same reason the cut layer is created **last**, so it burns last — and it is moved to
the end again every time another board asks for one, because creation order alone gets a
*second* board wrong: board one's tile would come free while board two is still being
engraved.

The rim is cut with a cut setting from your own library, for this material, this thickness
and this machine — the one you used most recently. It is refused when there is none, rather
than guessed:

> There is no cut setting for this material

with the thickness named when there is one, and the thicknesses you *do* have listed after
it. Guessing here would cut the rim at a speed nobody has ever burned, on the very plank
whose purpose is to find out what that speed is. A cut setting for another thickness is not
offered either: half-cutting the rim leaves the tile in the sheet with a crack line through
it, which is worse than not cutting at all. Cutting loose also needs a material at all:
*Cutting the tile loose needs a material, so its cut setting can be looked up.*

Measured on the same four-by-four board: **109.9 s and 19 layers** with both the code and
the cut-out, against 73.8 s with the code alone and 56.9 s with neither. A rim is not free.

One thing worth knowing before you use it. On a loose tile the most obvious rectangle in the
photograph is the tile's own edge, roughly 20 mm outside the squares — and dragging the four
alignment handles onto *that* puts every square in the wrong place without a word of
complaint. So a board you intend to cut loose is a board that wants a code on it.

![The bed with a test board drawn on it and a rectangle around the whole board, four millimetres clear of it, with a small gap in the middle of each of its four sides. In the Layers tab beside it three layers, in burn order: the one holding the caption and the axis labels (named "Board labels" on screen), then "Board code", and last "Test board cut-out" at 12 mm/s and 65% — the cut setting looked up from the library rather than guessed.](images/42-board-tile.png)

## Where the board lies

**Measure the position from** offers **The top-left corner of the board** or **The centre
of the board**. On a fresh plate the corner is handier; on an offcut you know where the
middle of your piece of wood is, not where the corner of a grid you have not seen yet
should go. The two fields below it change name with the choice: **Start X** / **Start Y**,
or **Centre X** / **Centre Y**.

Both refer to the whole board, captions included. That matters, because the row labels are
engraved to the left of the squares and are as wide as their longest value — at
three-digit speeds a good 17 mm.

**When it goes wrong.** If the board starts off the bed on the left or the top, the
preview says so, with the numbers you need to fix it:

> The board starts at -3, 20 mm, and that is outside the bed. The row labels need roughly
> 17 mm on the left. Move the start point to the right or downwards, or switch the caption
> off.

If a second board would land on the first, which is what happens when you draw twice
without moving anything:

> This board falls over grid #32, which is still on your sheet. Move the start point along.

And if the board runs off the bed to the right or below, drawing is refused outright — the
head cannot get there at all.

## Reading the preview

The panel on the right shows the board as it will come out: the number of squares, the
size of the whole board, the burn time, and a picture with the axis values where they will
be engraved.

Darker means more burning. The legend underneath names the axes, the fixed value, and
which corner goes deepest — worked out from the values, not assumed, because with freely
chosen axes it can be any corner:

> Rows: speed in mm/s. Columns: power. Interval fixed at 0.1mm. Darker is more burning —
> top right goes deepest.

The burn time is worth a look before you press the button:

> Burn time roughly 3 min 20 s, without the captions.

With line spacing on an axis that number can multiply quietly: a row at 0.05 mm lays six
times as many lines as a row at 0.3 mm, and nothing else on the form shows that.

## Recipes: settings you keep

Two ways of not filling the same form in every week.

**Last time.** Choose a material and OpenKerf fills the form with the settings of your
previous board for that material:

> Settings carried over from your previous grid for this material (20 Aug, #32). Feel free
> to adjust them.

**Recipes**, at the top of the window, are named settings — for the case where one material
needs two of them, cutting beside engraving. Pick one from the **Recipe** list and the form
fills; **Save this…** opens a name field (*Name, e.g. birch 3 mm cut*) and **Remove**
throws the chosen one away. A recipe holds everything on the form except the caption, which
belongs to one board. With a material chosen it belongs to that material and a recipe of
the same name is overwritten; without one it becomes a recipe for all materials.

## Drawing it, and burning it

The main button names what it is about to do: **Draw the grid — 16 squares, 57.9 × 58.3 mm**.

Without a material it reads **Draw it anyway, without a material** and stays an ordinary
button rather than the highlighted one, with the warning above it:

> Pick a material. A preset is a statement about one particular laser on one particular
> material — without a material the burned board yields nothing later.

The warning also closes the gap: a field beside it (*New material, e.g. birch plywood*)
and **Create and choose** add the material without leaving the window.

Once the board is drawn:

> Grid #33 is on the bed — 16 squares, as one group in your design. Check the frame first,
> burn it after, and come back for step 3.

Two buttons sit under that message, in that order: **Show frame** sends the head round the
outline of the work with the laser off, so you can see whether your plank lies where the
board is going to be, and **Start job** puts the board in the queue.

> The head is tracing the outline of the bed. Is your board in the right place?

> The job is in the queue. Stay with it until the board comes out of the machine.

**Set up another grid** puts you back at the settings for the next board — it does not draw
straight away, because a second board would fall on the first.

**When it goes wrong.** Starting is refused when part of the board is off the bed:

> 2 shapes lie outside the bed — the head does not reach there. Set Start X or Start Y
> higher and draw the grid again.

Off the sheet is a warning rather than a block — the head gets there, there is simply no
material:

> Careful: One shape falls outside the sheet: there is no material there.

## What lands on the bed

The board is one group on your sheet, with each square in a layer of its own — that is what
makes the sweep possible, because every square needs its own speed and power.

![The bed with a burned-in test board drawn on it: four rows of four red squares, the power percentages 40%, 55%, 75% and 90% engraved above the columns, the speeds 8, 12, 16 and 20 mm/s beside the rows, and above it the caption "Acrylaat (gegoten) — cut speed v / power > 2026-08-21"](images/17-testgrid-board.png)

In the **Layers** tab the whole board is one row, **Test grid #33**, with
*16 cells · speed and power are fixed* underneath. The **+** beside it unfolds the
squares, each with its own tick box and its speed and power, so you can leave part of the
board out of the job. **Remove grid from the design** takes the group and all its cell
layers off the sheet; the stored grid stays, with its photo and everything that came out of
it. Throwing all layers away leaves the board alone as well — the confirmation says
*Test grids stay.*

## Photographing the board

Step 3 and 4 are in the block below the wizard. Pick the board from the list — each line
carries the date, the material and the operation, followed by *· with photo* or
*· waiting for a photo*, so three trials on the same material stay apart.

A board without a photo says:

> Burn this grid and photograph the board. Straight from above, the whole board in frame —
> you align the corners yourself afterwards.

**Add a photo** takes one from the camera or from a file. On a phone the shot itself is
easier: open OpenKerf on it, and the boards waiting for a photo are listed under
*3 test grids are waiting for a photo*, each with a **Take a photo** button. After the
upload the phone says:

> Photo saved. You get the preset out of it on the desktop.

**When it goes wrong.** An empty file or a failed upload gives *Saving the photo failed.*
Taking another shot is **Another photo**, which replaces the one that is there.

## Aligning the photo on the board

A photo of a plank is never a tidy crop — you stand at an angle over the machine, and the
board is half in frame. So the overlay of squares has to be told where the board is:

> Drag the four corners to the corners of the burned grid

Four round handles sit on the photo, one per corner. Drag them onto the corners of the
burned grid — the outermost corners of the squares, which is where the border comes in
handy. The overlay follows the perspective, so a board photographed at an angle still gets
its squares in the right place. The handles also take the arrow keys, in small steps, and
shift for larger ones.

**Aligning done** puts the overlay to work. The alignment is stored with the board and not
with the browser, so you can align on the desktop and point out the best square on the
tablet beside the machine. A fresh photo starts in aligning mode, because that is the first
thing that has to happen.

**When it goes wrong.** *The alignment could not be saved.* — or, with the server
unreachable, *The alignment could not be saved — no connection.* The corners are then still
where you put them on screen, but they are not stored.

## Reading off the best square

With the overlay in place, the readout in the corner of the photo says:

> Tap the square that turned out best

Point at a square and it tells you what you are looking at — *row 2, column 3 · 12 mm/s ·
75%* — so you never choose blind. Tapping picks it; tapping again lets it go. Picked
squares appear as chips under the photo, and **No square chosen yet** stands there while
there are none.

**Make presets from 2 squares** saves them. One square gives **Make a preset from 1
square**.

> 2 presets saved with Acrylaat (geëxtrudeerd). You will find them in the material library.

The squares a setting has already come out of stay marked on the photo, with the line
**Became a preset:** and a chip per square underneath. Pointing at a chip lights the square
up on the photo — *— pointing at it highlights the square on the photo.*

**When it goes wrong.** Saving is refused without a material on the board:

> This grid belongs to no material, so no preset can come out of it. Link a material when
> generating the next grid.

A failure on the way out gives *Making the preset failed.*

## What the preset carries with it

The setting that comes out of a square is not a bare speed and power. It carries the
material, the thickness, the operation, the machine it was burned on, the number of passes
and the line spacing — burn it again with one pass where the square had two and you notice
that on material.

It also carries where it came from. In the material library it wears a green **Verified**
badge, and its detail lines read *Verified — burned and judged on a test grid*, the machine
it was made on, and the board itself: *Test grid #16 · burned last week*. Beside that sits
the photo of that board with the square outlined:

> The outline marks the square at row 2, column 2 — that is where these values come from.

If the board was never aligned, the outline is a guess and says so: *The alignment of this
photo has not been set, so the outline is approximate — align the grid for an exact mark.*
Without a photo there is nothing to show: *There is no photo of this grid yet. Without a
photo there is nothing to read the choice off.*

![The material library with a setting unfolded: 3 mm, Cut, 125 mm/s, 45%, a green Verified badge, the lines Source "Verified — burned and judged on a test grid", Machine KH-5030, Test grid "#16 · burned last week", Air assist on, and to the right the photo of the burned board with one square outlined](images/15-library-preset.png)

The other badges say the opposite in one word, and what each of them means is in
[The material library](library.md#where-the-numbers-come-from). That is the point
of the whole loop: to end up with the green one.

## A raster grid on a server that cannot raster

Sweeping the line spacing means rastering, and rastering means turning an area into laser
lines. Not every engine can do that on its own: in MeerK40t that converter lives in the
wxPython interface, and a server running without it silently throws the shapes of a raster
layer away during planning. The board then comes out of the machine blank — not faint,
blank — and the time estimate for it reads zero.

OpenKerf carries its own converter for exactly this reason, so on most servers a raster
board burns. Where it is missing, the wording is:

> This server cannot burn raster layers. The converter that turns a raster area into laser
> lines lives in the wxPython version of the engine and is missing here. A raster board
> comes out of the machine blank. Choose Engrave · vector or Cut, or burn this grid from the
> wxPython UI.

The same sentence appears in the pre-flight of the Job panel for an ordinary design, naming
the layers it applies to — see [Burning](job.md#the-layer-table). If you meet it, either
sweep speed against power in **Engrave · vector** or **Cut**, or burn that particular board
from the wxPython interface.
