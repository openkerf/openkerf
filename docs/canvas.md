# The bed: drawing, selecting and sheets

The bed is the large drawing area in the middle of the window. It shows your machine's
work area to scale, the sheet of material lying in it, and everything you have drawn or
imported. This page covers the tools on the left, how you pick things up and change them,
how the view moves, and how sheets work.

![An empty bed with rulers in millimetres along the top and left, the tool rail on the left, and the words "Empty bed" in the middle](images/05-canvas-empty.png)

A fresh bed says **Empty bed**, with "Use Import in the top bar for an existing design, or
pick a shape on the left and click the bed." That block disappears as soon as there is
work on the bed, and also while a job is running.

## What is drawn on the bed

- The **bed rectangle**, at the size of your machine's work area, with its measure beside
  the top right corner: `bed 500 × 300 mm`.
- **Rulers** in millimetres along the top and the left, with `mm` in the corner between
  them. Zero is the corner of the bed. The scale runs on past the bed as well, in lighter
  figures and with negative numbers to the left of and above it, so you can read off how
  far a shape lies outside the work area. A band on the ruler marks how far the bed
  reaches. While you move the pointer, a coloured tick on both rulers follows it.
- A **grid**, at the same step as the ruler, with a finer subdivision that disappears when
  it would fall too close together.
- The **sheet** — the piece of material you put in — as a dashed rectangle in the top left
  corner of the bed with its name in the corner, whenever it is smaller than the bed.
- The **origin mark** at 0,0: two short arrows marked X (to the right) and Y (downwards),
  the directions the machine counts in. This mark never moves.
- If you have set a zero point of your own, a small cross marked `0`, and a dotted frame
  showing where the work will land, labelled **burns here**.
- The **laser head**, as a circle with a crosshair through the whole bed. Its position is
  read out as "Laser head at 120.5 by 80.0 millimetres", or "Position of the laser head
  unknown" when the machine does not report it.

## The tools on the left

The rail on the left holds eight tools; one is active at a time.

| Tool | What it does |
| --- | --- |
| **Select** | The resting state: pick things up, move, scale, rotate. |
| **Nodes — pick a shape first, then drag the points** | Drag the points of one shape, add and remove them, and bend a straight piece into a curve. |
| **Rectangle** | Click the bed and a 20 mm square is placed there. |
| **Circle** | Click the bed and a circle 20 mm across is placed there. |
| **Line** | The first click sets the start, the second the end. The line follows the pointer in between. |
| **Point — one spot, for a Dots layer** | One click, one spot, and no size to give it. It lands in a **Dots** layer — the only kind that burns a point — and the tool stays in hand, because points are placed in rows for perforating or for drill marks. Escape or the Select tool ends it. |
| **Pen — click points, Enter finishes** | Click for a corner, press and pull for a curve. Enter or a double-click finishes it open; clicking back on the first point closes it; Escape throws away what you had. |
| **Text** | Click the bed and the **Place text** window opens, with the text itself, **Height (mm)**, **Letter spacing** and **Alignment**. |
| **Measure** | Two clicks; the distance in millimetres stays on the bed until you start again. |

Below the tools sit **Place image** and the buttons that open a window of their own:
**Generators — grid, circle, polygon, box, QR**, **Search clipart in public collections**,
**Test grid**, **Series — one design burned once per row of a list** and the material
library.

Placing a shape snaps just as dragging does, so a new rectangle lands on the grid line you
put it on and not 3.7 mm beside it.

**When it goes wrong.** Every tool except Select needs an edit token. Without one the
button is dimmed and its tooltip reads, for example, "Rectangle — requires a token".

## Selecting: an outline is a line, not a surface

This is the part that surprises people who come from a drawing program.

The way a laser cutter works, an **outline is a line**. So you click a shape's contour, not
its middle. The inside of a rectangle is not clickable, and that is on purpose: anything
you draw *inside* that rectangle — a hole, a label, a part nested to save material — stays
reachable instead of being swallowed by the shape lying over it. There is a hit zone a few
pixels wide around the contour, so you do not have to hit a hairline exactly.

A **filled shape is caught on its face**. For a filled shape the surface is the work — that
is what a raster layer burns — so clicking anywhere on it selects it. Images work the same
way: the whole picture catches the click.

![A circle selected on the bed, with a dashed frame around it, square handles on the corners, a round rotation handle above it and its measure underneath](images/07-selection.png)

Other ways to select:

- **Drag a box** over the bed with Select active. Everything the box *touches* is selected;
  you do not have to enclose a shape completely. Hidden shapes are left out.
- **Shift+click** adds a shape to the selection, or takes it out again.
- **Escape**, or a click on the empty bed, clears the selection.
- A shape can also be reached with the keyboard: tab to it and press Enter or space.

### A pile under the pointer

Shapes lie on top of each other more often than you would think — a copy that did not
move, a cut-out over its panel, two rectangles of the same size.

A plain click takes the top one. **Alt+click walks down the pile**: whatever is selected
now, the next one below it is taken, and from the bottom it starts again at the top. Where
you are is said in words beside the selection count above the bed: "Shape 2 of 4 under the
pointer — Alt+click for the next." That line disappears again after a few seconds.

![The right-click menu on the bed, opened over overlapping shapes, with a submenu "Under the pointer" listing numbered shapes with their measures](images/08-under-pointer.png)

If you would rather look than click through, **right-click** the shape. The menu then opens
with **Under the pointer** at the top: a numbered list, top shape first, of everything under
the cursor, with the measure behind each name — `2. Rectangle · 60 × 40 mm`. The numbers are
the same ones the Alt+click line counts with, and the row of the shape that is selected now
carries a tick. Pick a row and that shape is selected. The list only appears when there is
really something to choose between: with one shape under the pointer it is left out.

## Changing what you have selected

The selection is a dashed frame, drawn a few pixels clear of the shape so the layer colour
underneath stays readable. Its measure stands underneath it, live: `60.0 × 40.0 mm`.

- **Move**: drag anywhere inside the frame. Or use the arrow keys — 0.1 mm a press, 1 mm
  with shift held.
- **Scale**: drag one of the four corner handles. The opposite corner stays put.
- **Rotate**: drag the round handle on the stem above the frame. Hold shift and it locks to
  steps of 15 degrees. A turn of less than half a degree is treated as a tremble and
  ignored.
- **A line** has no corner handles: you grab it by its two end points, and the length in
  millimetres shows while you drag.
- **Nodes** puts the shape's own points on screen; drag one and the shape follows. It does
  more than dragging — see [Curves, points and pieces](#curves-points-and-pieces) below.

Only one command goes to the engine, when you let go. Until then what you see is a preview,
shape and all.

**When it goes wrong.** The Nodes tool says why nothing is happening, in a line under the
bed:

- "Nodes works on one shape. Click one on the bed."
- "Nodes works on one shape at a time; 3 are selected. Click just one of them."
- "This shape has no loose points. Make it a path first with Combine, in the panel on the
  right."
- "The nodes of this shape could not be read. Try clicking it again; if it keeps failing, the
  engine is not answering." — the shape may well be editable; this one says the question
  itself did not get an answer, which is a different thing from a shape that has no points.

## Locking a shape

The shapes you must not touch are the ones you touch by accident: an alignment mark, an
outline you drew round the material, a jig you re-use every week. One drag box over the bed
takes them along with everything else, and you see it when the part comes out 3 mm off.

**Lock** (⌘L, or the row in the right-click menu) stops that. A locked shape draws no corner
handles and no rotation stem, and it does not move when you drag it. The panel on the right
says so, with the way back in it:

> **LOCKED** — Protected from moving, sizing and deleting. Its layer, colour and bridges can
> still be changed.

![A locked rectangle selected on the bed: the dashed selection frame with its measure
underneath, no corner handles and no rotation stem, and in the panel on the right the heading
LOCKED with the sentence about what a lock protects and an Unlock button.](images/31-lock.png)

That line is the whole rule, and the second half is deliberate. A lock protects **geometry
and existence** — moving, scaling, rotating, mirroring, aligning, combining, offsetting,
corners, simplifying, effects, editing text, deleting, and cutting to the clipboard. It does
not protect **what the shape is for**: you can still put it in another layer, give it a
colour, a fill or bridges, and you can still copy or duplicate it. A locked alignment mark
that could not be given a layer would be a lock that stops you working rather than one that
stops an accident.

Two more things worth knowing:

- A selection with one locked shape in it refuses **as a whole**: "1 of the 2 shapes you
  picked are locked, so nothing was moved." Doing it to the loose ones and saying so
  afterwards would leave a half-moved drawing and no way back except undo.
- The copy of a locked shape is not locked itself — otherwise every duplicate would have to
  be unlocked before you could place it, which is the opposite of what duplicating is for.

The flag is the engine's own, so a design locked here opens locked in MeerK40t's own
interface as well.

## What a shape does in a series

A **series** burns one design once per row of a list — fifty keyrings with fifty names on
them. Two things a shape on the bed can carry belong to that, and both are on the shape
rather than in the list, because they are properties of your drawing.

**A text can read from the list.** Put a column name in curly brackets — `{name}` — and the
text says something different on every plate. Right-click the text and the menu has **Insert
a column**: one row per column of the list, labelled with the column's own name. With exactly
one column there is no submenu and the row *is* that column, reading **Insert {column}**;
with no list attached the row is greyed and says why — "No list is attached in the Series
window".

The panel on the right then carries two lines instead of one: the text as you typed it, in
quotation marks, and under it what it comes out as for the plate that is next — "For the burn
now on the bed this reads “Anna”." The two are different facts. The first says which column
the tag reads; the second says what the machine is about to cut.

**A shape can burn only once.** A jig frame is cut on the first plate and then holds the rest
of them in turn, so right-click it and choose **Burn only once** — "In a series this shape
burns on the first plate only — a jig frame, or the pockets the pieces sit in". The same row
reads **Burn on every plate** on a shape that already carries the mark: "This shape goes onto
every plate of the series again". The mark can be set before there is any list, it travels in
the project file, and outside a series it withholds nothing.

The window itself, the list and the run at the machine are on [Variable
text](variable-text.md).

## Shapes lying on top of each other

A duplicate is the one mistake in a drawing you cannot see. Two identical rectangles at the
same place look like one rectangle, and the laser cuts the line twice: on thin material the
second pass scorches the edge, on thick material it simply costs the time. They arrive by
themselves — an SVG exported twice, a paste that landed back where it came from, an import on
top of work that was already there, a generator run twice with the same numbers.

**Remove duplicates…** looks for them. It is in the right-click menu on a shape (then it
searches the selection) and in the right-click menu on the empty bed (then it searches the
whole sheet). It opens **Shapes lying on top of each other** with the count first:

> 3 shapes lie on top of another one, in 2 places. Removing them leaves the one that was
> there first in each place.

![The window "Shapes lying on top of each other": the sentence counting three shapes in two
places, the line about a duplicate burning twice, and the buttons Cancel and Remove
3.](images/32-duplicates.png)

Looking and removing are two steps on purpose, because removing changes nothing you can see:
the drawing looks identical afterwards, so the number in the question and the number in the
note ("3 duplicates removed.") are the only evidence you get. With nothing to remove it says
so — "No two shapes in this design lie on top of each other." — and offers no button.

What counts as the same shape is what the laser cannot tell apart: the same kind of shape,
and the same points rounded to a tenth of a millimetre. That tolerance is a decision —
exports round differently, and two outlines 0.02 mm apart are one line as far as a 0.2 mm
kerf is concerned. The layer and the colour are deliberately *not* part of the comparison:
two identical outlines in two layers burn twice, which is exactly the mistake being looked
for. Shapes without an outline to compare (an image, a group) are counted as not compared and
the dialog says how many.

The shape that was there first stays, which in a drawing means the one you had before the
import laid a copy on top of it. A locked shape always stays, whatever its place in the
order: a lock says "do not touch this", and that has to win over "the first one stays".

## Curves, points and pieces

A laser cuts curves as happily as straight lines, and two tools put them on the bed without
an import: the **Pen** draws them, the **Nodes** tool changes them afterwards.

![A path with a curved piece on the bed, the node tool active. The points sit on the line as
round knots, one of them filled to show it is in hand, with a square handle on a tether
beside it. The right-click menu on that node offers "Add a node here", "Make this piece
straight" and "Remove this node".](images/27-nodes.png)

### Drawing one with the pen

**Click for a corner, drag for a curve.** That is the whole of it, and it is the same
gesture Illustrator and Inkscape use: a plain click puts a corner point down, while pressing
and pulling away from the point drags out a handle and the line arrives there bent. The
handle you pull is mirrored on the other side of the point, so a curve runs smoothly through
it rather than kinking.

Four screen pixels of movement is the line between the two. Below that a press is a click,
because a finger on a trackpad moves a pixel or two between pressing and letting go, and at
two pixels every corner came out slightly bent.

The hint under the bed says what the keys do while you are drawing: "Click for a corner,
drag for a curve. Enter finishes the line, Backspace takes back the last point, Escape
stops." A double-click finishes it too. Clicking back on the first point closes the shape.

The line you see while drawing is computed from the same numbers that are sent when you
finish, so the preview is not an impression of the result — it is the result.

Snapping applies to the points and not to the handles. A point lands on the grid or on a
neighbour's edge like anything else you place; a handle is a direction rather than a place,
and snapped to the grid a curve would jump between the few tangents the grid allows. For the
same reason Alt does not pan the view while the pen is in hand: there it means "this one
point does not snap".

### Changing one with the Nodes tool

Pick **Nodes** and click a shape. Its points appear on the line as round knots. Clicking a
knot takes it **in hand** — it fills in — and that is what the operations below act on,
because removing a node has to know which one you mean. A node can also be reached with the
keyboard: tab to it and press Enter or space.

The hint under the bed is the short version: "Double-click the line to add a node. With a
node in hand: Delete removes it, Shift+U curves the piece after it, Shift+L straightens it."

Right-click a node and its three rows stand there in full:

- **Add a node here** — "Halfway along the piece after this node. A double-click on the line
  puts one exactly where you click."
- **Make this piece a curve** — "The line stays where it is and gets a handle to pull it
  with." On a piece that is already curved the row reads **Make this piece straight**
  instead.
- **Remove this node** — red, and at the bottom of the menu.

A curve is carried by the **piece between two points**, not by a point, which is why the
rows say "this piece" and why a handle appears on a tether beside the knot rather than on
it. Handles are drawn as squares and knots as circles: the two lie close together and mean
different things. Only the pieces touching the node in hand show their handles — on a path
of fifty points, every handle at once would put a hundred squares on the bed.

Dragging a handle bends the piece live, and the line follows the handle rather than waiting
for the server to answer.

**When it goes wrong.** A greyed row in the node menu says why:

- "Click a node on the shape first" — nothing is in hand yet.
- "This is the last node; there is no piece after it" — the end of an open line has nothing
  leaving it, so there is nothing to bend or to divide.
- "A closed shape needs three nodes" and "A line needs two nodes" — removing this one would
  leave no shape behind.

One thing to know before you start: giving a rectangle or an ellipse an extra node turns it
into a path. Measured on a 60 × 40 mm rectangle, adding one node left a path of five points
where a rectangle had been. That is the same trade the chamfer makes — width and height can
no longer be set separately afterwards — and undo brings it back.

## Bridges: keeping the part in the sheet

Cut a shape all the way round and the part drops. It drops while the head is still moving,
so the last millimetres of the cut land beside the line, and on a small part it drops into
the machine. Every cutter therefore leaves a few **bridges** — small gaps in the cut that
hold the part in the sheet until you push it out by hand.

![A rectangle on the bed with four visible gaps in its outline, and the Edit panel on the
right open on Bridges: the tick "Leave gaps in the cut", a Number of 4 and a Length per
bridge of 2 mm, with the read-back sentence underneath.](images/26-bridges.png)

The quick way is the right-click menu: **Add bridges (4 × 2 mm)** — "Small gaps in the cut,
so the part stays in the sheet instead of dropping into the machine". Four of 2 mm is one
per side of a rectangle, so the part hangs on four corners instead of tipping on one. The
same row reads **Remove bridges** on a shape that has them: "The cut closes again and the
part comes loose". The keyboard shortcut is in [Reference](reference.md#bridges).

The two numbers are in the panel on the right, under **Bridges**, because they are values
you set and read back:

- the tick **Leave gaps in the cut**;
- **Number** — how many, spread evenly along the contour. They stay spread when you resize
  the shape.
- **Length per bridge** — in millimetres.

The two fields are independent: typing a length leaves the number as it was, and the other
way round.

Underneath stands what you have actually asked for, in millimetres of contour: "4 gaps of 2
mm, spread over a contour of 200 mm. What is left to cut is 192 mm." With several shapes
selected that are not all the same size, the sentence quotes the tightest of them, because
that is the one that runs out of contour first. And when the bridges sit at places of their
own rather than evenly: "At 10, 40 and 70 percent along the contour, each 2 mm long."

**The gaps are drawn on the bed.** The outline is shown with the bridges cut out of it,
because that is what the machine will cut — a value you cannot see is a value you cannot
check. A fill stays whole, though: a raster layer burns the area, and an area with four
notches in its outline is not what happens.

**When it goes wrong.**

- Not every kind of shape can carry them. On a line, a text or an image the panel says so:
  "This shape carries no bridges. They work on a rectangle, an ellipse, a polyline or a path
  — not on a line, text or an image." The menu row is greyed with the short version, "A line,
  text or an image carries no bridges".
- Bridges only mean something to a cut. In an engrave or raster layer the panel keeps the
  fields but adds: "This shape is not in a cut layer, so the gaps change nothing yet. They
  only matter to a cut."
- Too much bridge for the contour is refused, with the arithmetic in the sentence. Measured
  on a 60 × 40 mm rectangle, four bridges of 30 mm came back as "4 bridges of 30 mm take 120
  mm of the contour of meerk40t:7, and that contour is 200.0 mm long; at most half of it may
  be bridge. Use fewer or shorter bridges." The shape is named by the label you gave it, and
  by its internal name where you gave it none. With more than one shape selected the sentence
  also says how many of them would have been fine, and it names the tightest one — on a
  nested sheet of forty parts, knowing that one of them is too small does not tell you which.
- More than 200 in one contour: "More than 200 bridges in one contour is not a cut any
  more." At that point the outline is a dotted line.
- A mixed selection where the shapes carry different bridges says so before you overwrite
  them: "These shapes have different bridges. Setting a number here gives them all the
  same."

## Stencils: bridging what would fall out

Cut a design **out** of a sheet and the material and the opening swap places. The inside of
an **O** is then no longer part of the letter but an island of cardboard floating in the
opening, held by nothing: it drops on the bench, or into the machine halfway through the
job. That is what a stencil font solves by drawing the letters with the bridges already in
them — and it is what **Make a stencil…** does to any shape.

Select the shape — or all the shapes, if the design is drawn as separate outlines nested in
one another — and take **Make a stencil…** from the right-click menu. The whole selection is
looked at together, because whether a ring is one path with two contours or two shapes drawn
inside one another is a drawing decision and not a stencil one. The window says what it found
before you set anything, because the numbers only mean something together:

> 4 islands would fall out. 8 bridges go in.
> The shortest bridge has to span 3.6 mm — that is the thickness of the material at its
> narrowest.

![The word OpenKerf on the bed as outlined lettering, cut as a stencil: the counter of the O, of the p and of both e's each hang on two bridges. Each bridge is a break in the inner line, a break in the outer line at the same place, and two short cuts across the letter's stroke joining their ends, so the bridge stands out as a little tongue of material. The n, K, r and f are untouched, because nothing in them would fall out.](images/45-stencil.png)

Two settings, and both are worth understanding rather than accepting:

- **Bridge width** — how much of the cut is left uncut, in millimetres. The default is 3 mm.
- **Bridges per island** — two by default, because one is a hinge: an island on a single
  bridge swings aside under the air assist and under a spray can.

The crossing figure beside them is the one that decides whether the width is sane. On 60 mm
Arial lettering the stroke of an **O** is 3.6 mm, so a 3 mm bridge is very nearly the whole
thickness of the letter — and the window says so: *The bridge is wider than the gap it
spans, so it will look like a solid block rather than a bridge.*

**What a bridge is here, and why it is four cuts.** A gap in the island's own outline would
join it to the opening, and an opening is a void — so a bridge starts as a *pair* of gaps,
one in the island and one in the contour around it, facing each other. That is not enough on
its own: with only those two, the ring between the contours is still attached to the sheet at
one gap and to the island at the other, and nothing comes out at all. So the bridge is
completed by **two short cuts across the opening**, joining the ends of the two gaps. Those
are the sides of the bridge. With them the ring is bounded all round and drops out, and the
strip between the two crossing cuts — cut on neither long side — holds the island to the
sheet.

That is also why the app looks for the shortest crossing: a short bridge is the strongest and
it costs the least of the sprayed edge.

**A stencil makes the cut longer**, which is the opposite of what ordinary bridges do.
Measured on "OpenKerf" at 40 mm with 2.5 mm bridges: 970.4 mm of contour before, 980.0 mm
after — 40 mm of gaps taken out, and sixteen crossing cuts of about 3 mm put in.

**It is written into the shape**, not kept as a setting on it. Rounding a corner works the
same way: the path is replaced, one undo puts it back, and what you see on the bed is what
the machine cuts. Bridges the shape already carried disappear with it, because the gaps are
in the path now and applying both would take them out twice.

**One thing a bridge cannot be, and where the app says so.** A gap has to fit inside the
contour it sits on, because the engine's gap machinery measures along the whole path of a
shape and wraps at its end — it has no notion of a separate contour. A gap centred a
millimetre and a half from the end of one contour therefore spills onto the next one, and in
a word the next contour is the next letter: the crossing cut is then drawn across the word
and a nick is taken out of a letter that was never part of the bridge. So a bridge keeps one
bridge width clear of both ends of its contour, and a counter smaller than about two bridge
widths has nowhere to put one. When that happens the window says it, because it is the one
fault here that cannot be seen on the drawing — the shape looks finished and the island
still drops out:

> One island is too small for a bridge of this width and will fall out. Try a narrower
> bridge.

**When it goes wrong.**

- A single-stroke typeface has no inside, so nothing in it can fall out and there is nothing
  to bridge: *"9 of these contours are open lines rather than outlines, so nothing in them
  can fall out. A stencil needs an outline typeface; a single-stroke one draws letters with
  strokes and has no inside."* Place the text again in an outline typeface from the font
  picker. (Measured: the word "Stencil" is ten contours in the engine's built-in Hershey
  font, of which nine are open; in Arial it is nine closed ones.)
- A shape with no holes needs no bridges, and says a different thing: *"Nothing in this
  shape would fall out: there is no part of it that the cut would set loose. It needs no
  bridges."*
- A bridge under 0.6 mm is refused — a CO₂ cut is 0.1 to 0.3 mm wide itself, so it would
  burn away and the island would fall out anyway.
- Too much bridge for the contour is refused with the arithmetic, exactly as it is for
  ordinary bridges.

**Nothing has been cut out of cardboard yet.** The geometry is exact and the window says so
too: 3 mm is a starting point, not a measurement. How narrow a bridge may be before it tears
under a spray can is a thing you find on a scrap.

## Snapping, and what Alt does to it

While you move, scale, draw or drag a point, things lock onto their surroundings: the grid,
the edges and centre lines of the other shapes, the edges and the middle of the bed, and
the edges and the middle of the sheet. Left, right, top and bottom are decided
independently, so a shape can line up on the left with one neighbour and on the top with
another.

You see **what** it locked onto: a guide line appears, running from the shape you are moving
to the thing it lined up with, with a short word beside it — `grid`, `edge`, `centre`, or a
word for the bed or the sheet edge. A grid, bed or sheet line has no counterpart and runs
across the whole bed.

The reach is nine screen pixels, not a fixed number of millimetres. Zoomed in to 400% the
snapping is four times more precise by itself, which is what you want when you are aiming.
When the fine grid is too close together to see, snapping uses the main step only — locking
onto a line that is not drawn is a riddle.

**Alt inverts it for one movement.** With snapping on, holding Alt lets you place something
freely; with snapping off, holding Alt turns it on for that one drag. The magnet button in
the zoom bar bottom right switches it for longer, and remembers your choice between
sessions. Its tooltip says which way it stands: "Snapping is on — hold Alt to skip it for
one move" or "Snapping is off — hold Alt to use it for one move".

Alt has two other jobs on the bed, and they do not clash: Alt+click on a shape goes deeper
into the pile (that is a click without movement), and Alt+drag on the empty bed pans the
view.

### Right-click on the empty bed

A right-click on a shape is about that shape; a right-click on empty bed is about
the view and the whole design. It gives, in this order: **Paste here** ("The
top-left corner lands where you clicked"), **Select all** and **Clear selection**;
then, under the heading **View**, the four zoom states — **Fit everything in
view**, **To the selection**, **The whole bed** and **100 % — actual size**; then
two switches, **Snap to grid and shapes** and **Layer numbers next to the
shapes**; then **Remove duplicates…**, which searches the whole sheet (see [Shapes lying on
top of each other](#shapes-lying-on-top-of-each-other)); and at the bottom **Put
everything on the bed**, which pulls the whole design back inside the bed, "Including what lies off screen and cannot be
clicked". That last one is the only way to reach a shape you have dragged out of
sight and can no longer click.

A group of rows on that menu is not about the view at all: the doors to the five
workspaces. **Show cut path** (⌥P) opens the window that walks through the job in
the order the machine will burn it — here as well as in the pre-flight, because
this is where you are while you are still drawing; see
[Burning](job.md#the-cut-path). Under it stand **Set up a series** (see [Variable
text](variable-text.md#the-series-window)), **Material library**, **Test grid**,
**Generators** and **Search clipart**. Each of them is the second door to a button
on the tool rail, and the one you find while you are already right-clicking the
bed. What you do in those windows is a write, so all five are greyed out with
"Requires a token" when this session may not write.

Every row, with its shortcut and the reason it can be greyed out, is in
[Reference](reference.md#right-click-on-the-canvas).

## Moving the view

![A bed with several drawn shapes, layer numbers beside them and the zoom bar in the bottom right corner](images/06-canvas-drawn.png)

- The **wheel** zooms, towards the point under the cursor.
- **Hold space** and drag to pan; the cursor becomes a hand. The middle mouse button and
  Alt+drag do the same.
- The **zoom bar** bottom right has minus, plus, the current scale as a percentage, and a
  **Fit** button ("Fit everything in view (3)").
- The percentage is a real scale: at 100% a 10 mm line on the bed is 10 mm on your screen.
  Click it and a menu offers **Fit everything in view**, **To the selection**, **The whole
  bed** and **100 % — actual size**, plus fixed steps of 25, 50, 100, 200 and 400 %.
- On the keyboard: `3` fits everything, `2` goes to the selection, `0` shows the whole bed,
  `1` is actual size, `+` and `-` step in and out. "To the selection" falls back to fitting
  everything when nothing is selected, so the key always does something sensible.

## Layer numbers beside the shapes

Each shape is drawn in the colour of the layer it belongs to, and beside it stands that
layer's number — the same number as in the layer list and in the pre-flight. Colour alone is
not enough to tell ten layers apart, especially not on a 1.2 pixel line or for a
colour-blind eye, so the number is the safety net.

The number is left off shapes too small on screen to carry it, because fifty figures make
the bed unreadable; zoom in and they appear. What you have selected yourself always gets
its number, at any zoom level.

The button with the numbered-lines icon in the zoom bar turns them off and on. Its tooltip
says "Layer numbers next to the shapes are on" or "… are off".

Two other renderings you will meet: a shape in **grey dotted** lines is in no layer at all
and will not be burned; a shape drawn **thinner and half transparent** is in a layer that is
set not to burn.

## While the machine is working: the head trace

During a job the path the head really travelled is drawn on the bed as one thin line under
your design, with the last stretch brighter — that is where it is now. Around the head
marker a ring fills up with the progress.

It is a trace, not a kerf. The machine reports where the head is, not whether the laser was
on, so the jumps between shapes are in the line as well. A strip under the bed says so in
words: "Trace of the head — measured, including the jumps between shapes." followed by
"62% shows as a ring around the head."

## Off the bed, off the sheet

A shape that crosses an edge lights up on the bed with a glow under it, and a strip under
the bed says what is wrong. Two different problems, two sentences:

- "One shape lies outside the bed — the head does not reach there." (or "3 shapes lie …")
- "One shape lies outside Sheet 1 — there is no material there."

Shapes that are not going to be burned anyway — in no layer, or in a layer set not to burn
— are left out of this count. A false alarm teaches you to ignore the real one.

If the **sheet itself** is bigger than the bed, that is not a mistake but a way of working.
The strip then reads "This sheet is larger than the bed." with a button, **Burn in tiles?**

![A sheet larger than the bed, divided into tiles with seam lines and registration marks](images/23-tiling.png)

## Sheets

A sheet is the piece of material you put in the machine — not the bed. A project can hold
several, and each is a document of its own: what you see on the bed is exactly what gets
burned.

![The sheet bar above the canvas with several sheet tabs, each showing a name and a size, and a plus button at the end](images/21-sheets.png)

The row of tabs above the bed is the sheet bar. Each tab carries the sheet's name and its
size (`300×200`); hovering adds the material, if one is filled in. Click a tab to switch to
that sheet. The **+** at the end adds one ("Add a sheet").

Click the tab you are already on and a small editor opens under it, with:

- **Name**
- **Width** and **Height** in millimetres
- **Material** — the button shows the material and thickness of this sheet, or "not filled
  in". It opens the same material window as the chip in the top bar; the choice is made in
  one place only.
- **Remove the sheet**, and **Done** to close the editor.

**When it goes wrong.** Removing a sheet that has work on it asks first: "Sheet 2 holds 7
elements. Removing it throws that work away — this cannot be undone.", with the button
**Remove the sheet and 7 elements** beside Cancel. The count is asked of the server at that
moment, not read off the screen, so a sheet you have just switched to is never mistaken for
an empty one. An empty sheet goes without a question. The last sheet cannot go at all — the
button is dimmed and reads "A project has at least one sheet".
