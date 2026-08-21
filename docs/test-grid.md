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

The caption and the border are burned in a layer of their own, at a speed and power you
set yourself: **Caption: speed** and **Caption: power** (or *Border:* when only the border
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
