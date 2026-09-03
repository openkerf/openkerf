# Plates larger than the bed

A plate of 900 mm does not fit in a 500 mm machine, but the work on it can still be
burned: in tiles, one part at a time, sliding the plate along in between. OpenKerf
splits the design into tiles with an overlap, burns two alignment marks in that
overlap, and uses those marks to work out where the plate lies after you have moved
it. This page walks through that from the first offer on the screen to the last tile.

You need a plate that is longer or wider than your bed, and hands free to move it —
this is a procedure you carry out at the machine, not one you start and walk away from.

## The offer, when the sheet is bigger than the bed

Give the sheet the size of your material — the sheet tab above the canvas holds
**Add a sheet** with **Name**, **Width** and **Height**, and an existing sheet can be
resized the same way. As soon as the sheet is larger than the bed, the strip under the
canvas says:

> This sheet is larger than the bed.

with a button beside it, **Burn in tiles?**. That one button does two things: it
switches tiling on for this sheet and it starts the run straight away.

![The work area with a 900 by 280 mm sheet on a 500 by 300 mm bed. The left part of the sheet is drawn normally, the right part is dimmed, a dashed seam line runs down between them, and a circle-with-cross mark numbered 1 sits above the seam and one numbered 2 below it. Under the canvas a strip reads "This sheet is larger than the bed." with a button "Burn in tiles?".](images/23-tiling.png)

The division is worked out, never stored. Change a shape, the sheet size or the
machine, and the seams and marks are recalculated. So you can keep drawing while the
tiling is on.

**When it goes wrong.** A plate that is too big in *both* directions is refused, with
the reason: "This plate is larger than the bed in both directions. Dividing in two
directions is not possible yet: every seam would then have its own marks and its own
order. Cut the plate to bed height first, or take a narrower plate."

## What the layout shows you

On the canvas the tile whose turn it is now is drawn at full strength. Tiles still to
come are dimmed; tiles already burned are dimmed a little less, so you can see at a
glance what is down and what is still coming. The seams are dashed lines.

At each seam sit two marks, drawn as a circle with a cross in it and a number beside
it — 1 and 2. The cross is the point you aim at, the circle gives that point an edge
you can see, and the number is there because two identical circles on a plate are
otherwise impossible to tell apart. The number on screen is on the same side of the
circle as the number that gets burned into the plate.

The seam does not sit blindly in the middle of the overlap. Within the overlap strip
OpenKerf shifts it to where it cuts through the fewest shapes, so a seam through the
middle of a shape is avoided when there is room to avoid it. What still crosses a seam
is genuinely cut in half and burned as two halves that meet.

The overlap is 25 mm, the margin kept free along the bed edges 10 mm, and a mark 8 mm
across. Those are the values a sheet starts with, and all three are on the sheet
itself: click the sheet tab under the top bar a second time and the sheet editor
opens, with **Larger than the bed** under the width and the height — *Margin (mm)*,
*Overlap (mm)*, *Marker (mm)*. They belong to that one sheet, like its size and its
material.

The refusals below are about those three numbers, which is why they ask you to make
the overlap larger: that is now something you can do.

**When it goes wrong.** An image cannot be cut in half, so it has to fall inside one
tile: "… lies across the seam between two tiles. An image cannot be cut in half: move
it so that it falls within one tile, or make the overlap larger." And if the overlap
strip is too crowded for two marks, the run does not start at all: "There is no room in
the overlap strip for two alignment marks that lie clear of the work. Make the overlap
larger, or move a shape away from the seam."

## The run, in the Job tab

Once the run is going, the panel on the right, under **Job**, leads it. It shows one
step at a time, because that is how you carry it out.

At the top: **Tile 1 of 2**, a row of tile numbers with a tick behind the ones that are
done, and a line you should read once:

> The zero point you set does not apply now: the marks decide where the burning happens.

**Stop the run** ends it. The tiles you already burned stay on the plate, of course;
what stops is the bookkeeping.

## The first tile: lay the plate and tap the corner

There are no marks on the plate yet, so the first tile is aligned on the plate itself.
The panel says:

> Lay the plate so its top-left corner can sit under the head. Jog to it and press Here.

Jog the head with the arrows in the panel until it is over that corner, then press
**Here · corner of the plate**. OpenKerf takes the head position at that moment as the
plate's corner. With one point there is no angle to measure, so it works with a plate
lying square — that is why the first tile is worth laying carefully against a fence or
rail.

When the alignment holds, the panel says **Aligned**, and two buttons appear:
**Burn this tile** and **Tile done, next**.

**When it goes wrong.** If the machine reports no position, tapping cannot mean
anything: "This machine reports no position, so Here does not know where it is."

## Burning a tile

**Burn this tile** sends only what falls inside this tile's burn area, plus the
alignment marks of the seam ahead of it, as one job. The marks are burned as an engrave
at a modest setting: they only have to be visible, and burning them hard makes their
edge vaguer to aim at and can cut through thin material.

Before anything moves, the tile is checked against the bed *with the correction applied*
— marks included, because those sit in the overlap outside the burn area and are still
burned.

**When it goes wrong.**

- Not aligned: "This tile has not been aligned yet. Tap the two marks first, otherwise
  the machine does not know where the plate is." This is the refusal you will meet most,
  and it is the whole point of the feature: without a measured position the machine would
  burn the tile where the drawing says, not where your plate actually lies.
- Sticking out: "After the correction this tile falls 4.2 mm outside the bed. Lay the
  plate straighter or a little further in and tap again."
- Already burned: "This tile has already been burned. Burning it again means the laser
  goes over work that is already there — only do that when the previous attempt was
  aborted. Confirm to carry on." A **Burn it again anyway** button then appears beside
  the others — deliberately not the primary one.

## Move the plate, then align with two taps

When a tile is done, press **Tile done, next**. The alignment lapses at that moment:
the plate is about to move, so what was measured no longer says anything.

The panel now tells you how far to go, for instance:

> Shift the plate 142 mm up, until the two marks can sit under the head.

For a plate that is too tall the shift is upwards; for one that is too wide the app says
left. Slide the plate, keeping it against the same fence, until the two marks from the
previous tile are inside the machine.

Then you tap twice. The panel names the mark by its number, the same number that is
burned next to the circle:

> Jog to mark 1 and press Here.

Press **Here · mark 1 of 2**, jog to the other circle, press **Here · mark 2 of 2**. Two
points give both the shift and the angle. From those OpenKerf works out how the plate
lies and rotates the tile to match, and reports what it measured:

> Aligned · 0.42° off square · 0.3 mm deviation

The deviation is a check, not a correction: the distance between two burned marks cannot
change, so if the measured distance differs, something was tapped wrong. The scale is
never adopted from your taps.

**When it goes wrong.**

- Tapped the wrong circle, or the same one twice: "These two points lie 12.4 mm further
  apart than the marks I burned. Did you tap the right mark?" and "The two tapped points
  lie on top of each other."
- Really askew, or a mixed-up pair: "The plate would lie 5.1° askew. That is more than a
  plate *can* lie askew without you seeing it — the wrong mark was probably tapped. Lay
  it straight and tap again." Anything over 3° is refused.
- Refreshing the page between the two taps loses the first one. The panel warns while a
  tap is held: "Refresh the page and you start tapping the marks again. The marks
  themselves simply stay where they are."

Repeat: align, burn, next, move, align. After the last tile the run closes itself.

## When the design changes halfway

A run of a 900 mm plate is hours of work and survives closing the app — but only as
bookkeeping. The measured position of the plate never survives a break, by design: a
stored alignment is an assumption about where your plate lies, and that is exactly what
you must not trust after walking away. You tap the marks again.

If the design or the plate size changed since the run began, the panel says so in
amber and refuses to burn or align:

> The design or the plate has changed since this run began. The tiles already burned
> belong to the old design; carrying on would give you half old and half new.

Start a new run, or undo the change. The same happens when the sheet the run belongs to
is no longer the active one: "The sheet this tile run belongs to is gone or is no longer
active. Choose that sheet again, or stop the run."

And if tiling was switched off for the sheet in the meantime: "Tiles are switched off
for this sheet. Switch them on at the plate size."

## Advice from the plate

Two things worth doing before you put good material in.

Run the whole procedure once on scrap, or with the lid open and the laser unable to
fire, so you see the head go to the marks and the plate slide the distance the panel
names. And keep the plate against one fixed edge all the way through: the marks correct
a small rotation, but they refuse a big one, and a plate that walks away from its rail
between tiles is the fastest way to that refusal.
