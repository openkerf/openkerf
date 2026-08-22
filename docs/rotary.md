# Burning on a cylinder: the rotary

A rotary is a chuck or a pair of rollers that stands in the bed and turns the
workpiece under the head. Y stops being a distance across the bed and becomes
rotation around the object — and the *number* stays the same. That is the whole
convention of this page, and it is worth reading twice, because the other
convention exists too and is a good way to ruin a mug:

> "A rotary turns the workpiece under the head, so the height of your drawing
> becomes rotation around the object instead of distance across the bed. A
> millimetre stays a millimetre on the surface: what you draw 30 mm tall comes off
> the cup 30 mm tall."

So the bed on your canvas does not become one revolution. A 30 mm logo is 30 mm of
surface, whatever the diameter, and the ruler, the context panel and the
pre-flight all keep saying 30 mm. What the diameter is for is the check in the
other direction: how far round does 30 mm get you, and does a design that is
taller than the circumference burn over its own beginning.

> **Nothing on this page has been driven on a rotary.** There is none on the
> computer these pages were written on. Everything that could be measured without
> the hardware has been — the scale really does reach the cutcode, homing really
> is refused, the settings really do survive a restart — and it is listed at the
> foot of the page, separately from the part that is still a written expectation.
> The numbered list under [At the machine](#at-the-machine-the-first-ring) is that
> expectation: an order of work with the number to expect at each step.

## Where it lives

A rotary is bolted into one particular bed, so it belongs to the machine and not
to the design: **Machine → Your machines**, and then **Rotary** on the row of the
machine it is fitted to. Same row as **Settings** and **Export the profile**.

Nothing on this page changes anything until you press **Save the rotary**. Typing
a diameter puts nothing in the next job; the sentences under the fields tell you
what *would* happen.

![The Rotary page for the machine KH-5030. "Burn on a cylinder" is ticked; under "Kind of rotary" the choice is "Chuck — I know the diameter" with a diameter of 80 mm and the line "Once round is 251.33 mm."; under "Y scale" the choice is "A factor I fill in" with 1.036269, "Y goes into the machine multiplied by 1.036." and "A shape 100 mm tall burns 103.6 mm around the object."; then a "Save the rotary" button and the block "Calibrate from a burned line" with 100 mm asked for, an empty measurement, and the note that it was last calibrated on 100 mm asked for and 96.5 mm measured. At the bottom three blocks: "What changes on the machine", "What this deliberately does not do", and "At the machine: the first ring" with ten numbered steps.](images/30-rotary.png)

**On a machine that has its own rotary** the page says one sentence instead of a
form: "This machine brings MeerK40t's own rotary along, and that one stays in
charge. Set it up in the machine's own settings; OpenKerf leaves it alone here."
That is not a limitation but a rule: the engine hangs its own rotary on a
lhystudios, grbl, balor, newly or moshi device, and two rotaries correcting the
same axis is worse than one. On a Ruida the engine's rotary is never loaded, and
that is the machine this was built for.

## The settings

**Burn on a cylinder** is the switch. Under it: "Switch this on once the rotary is
in the bed and the workpiece turns freely." Switch it on when the rotary is really
there, not in advance — while it is on, OpenKerf refuses to home, and that
refusal is the point.

**Kind of rotary** is a question about what you can measure, not about the
hardware:

| Choice | What it asks for | Why |
|---|---|---|
| **Chuck — I know the diameter** | "Diameter of the object" | "Measure it with calipers at the height where the design goes; a mug tapers." |
| **Rollers — I know the circumference** | "Circumference of the object" | "Mark a line, roll the object round once, and measure how far it travelled. On rollers this is more reliable than the diameter, because they slip." |

Either way the page answers with the one number you will need at the machine:
"Once round is 251.33 mm." for a chuck of 80 mm. That is π × d, and it is what
tells you whether a design fits round the object.

**Y scale** is a *calibration*, not a conversion. Three sources:

| Source | When |
|---|---|
| **No correction — the controller does the conversion** | The normal case on a Ruida whose own rotary page is set up. Leave it here. |
| **A factor I fill in** | Something is a percent or two out, and you have measured it. |
| **Computed from the two motors** | You know the steps per millimetre of the flat bed and of the rotary, and want the ratio worked out. |

The explanation on the page is the reason the first one is the default: "The scale
corrects a rotary that turns a little too far or not far enough. Leave it at 1
when the controller already converts Y to rotation itself, because two corrections
multiply." A controller that already converts *and* a factor of 1.036 here is a
job that is 3.6 % out and looks fine on screen.

Whatever the source, the page says what it means in two ways — as the factor, "Y
goes into the machine multiplied by 1.036.", and in the terms of the thing you
drew, "A shape 100 mm tall burns 103.6 mm around the object." The second one is
the one to read: 1.0363 says nothing on its own.

**When it goes wrong.**

- A factor far from 1 is not a calibration any more, and the machine refuses it:
  "A factor between 0.5 and 2 is a calibration; anything beyond that is a resize
  and the machine refuses it."
- A chuck without a diameter, or rollers without a circumference, are refused with
  what to do about it: "A chuck rotary needs the diameter of the object, measured
  with calipers." and "A roller rotary needs the circumference of the object: mark
  a line, roll it round once, and measure."
- "Computing the Y scale from the motors needs both numbers: the steps per
  millimetre of the flat bed and of the rotary."
- With no machine chosen there is nothing to set up: "There is no machine
  selected, so there is no rotary to set up."

## Calibrating from a burned line

The block **Calibrate from a burned line** is the honest way to a factor: burn a
line of a length you know, measure what came out, and let the page do the
division.

> "Burn a line of a known length around the object, measure what came out, and
> fill both in. Calibrating again later builds on what is set now instead of
> starting over."

Fill in **Length I asked for** and **Length I measured**; the page previews the
result ("That gives a factor of 1.0363.") before you press **Use this factor**.
100 mm asked for and 96.5 mm measured gives 1.0363 — the burn came out short, so Y
has to go in a little larger.

That it *builds on* what is set is the part worth remembering. Calibrate again on
a factor of 1.0363 with 100 mm asked for and 99.5 mm measured and you get 1.0415,
not 1.005: the second measurement was made through the first correction. What was
used last stays on the page — "Last calibrated on 100 mm asked for and 96.5 mm
measured, giving 1.036." — so a factor is never a number without a story.

**When it goes wrong.** One length on its own is not a measurement:
"Calibrating needs both lengths: what you asked the machine for and what you
measured on the object."

## What changes on the machine

Four things, and the page lists them where you set the rotary because they are
consequences and not settings.

- **Homing is refused.** "Homing is refused while the rotary is on: the head would
  drive into it. Take the rotary out first, or confirm that the bed is clear." A
  chuck stands exactly where the gantry wants to go. Pressing **Home** in the Job
  tab opens the question **Home with the rotary fitted?** instead of moving
  anything — see [Burning](job.md#homing-with-a-rotary-in-the-bed).
- **The frame means something else.** "The frame still traces a rectangle, but its
  height is rotation: you see the object turn under a head that stays where it
  is." So **Show frame** still works, and it no longer tells you whether the work
  fits *across* the bed.
- **The pre-flight says so.** "Before every start the pre-flight says that the
  rotary is on and by how much Y is scaled." One line above the start button, every
  time.
- **The scale counts from the machine zero.** "The scale counts from the machine
  zero, so a shape further up the drawing also lands further along. Put your work
  near the top of the sheet and burn the calibration line in the same place." This
  is the engine's own arithmetic, not ours: the whole coordinate system is scaled,
  so a shape at Y = 200 mm moves by 200 × (factor − 1), and a shape at Y = 10 mm
  hardly moves at all.

## What this deliberately does not do

> "Nothing is written into the controller. A Ruida keeps its own rotary page, and
> on a GRBL machine OpenKerf does not touch $101 at the start of a job — that is
> firmware, and this machine is a Ruida."

There is no rotary opcode in the Ruida job format at all, so this could not be
written from the engine even if we wanted it. Which is why the order of work below
starts on the controller's own panel: that conversion is its job, and ours is the
correction on top of it.

> "The feeder, the dual laser and galvo mode are not part of this either."

Neither is cylinder correction — burning on a cone or correcting for the curve of
a flat-ish surface. That is a different transformation and it is not built.

## At the machine: the first ring

This is the list to work through the first time, and it is in the app as well as
here: the same ten steps stand at the foot of the Rotary page, because the person
who needs them is standing at the laser with that screen open, not reading a
handbook on another floor.

> "Whether a burned ring comes out round and the right size cannot be tested
> without the hardware, so nothing below has been driven by us. This is the order
> to do it in, and the number to expect at each step."

Before you start: the workpiece must turn **freely**, with nothing touching the
head or the bed; have calipers and a flexible tape or a strip of paper to measure
the circumference with; and work at low power. Every step below is a measurement,
not a product.

1. **Fit the rotary**, put a straight-sided tumbler in it, and switch the laser
   off at the key. Move the head by hand to the middle of the object.
   *Expected:* the object turns freely and the head touches nothing.
2. **Set the rotary up on the Ruida's own panel** — pulse per rotation and
   diameter. *Expected:* the controller converts Y to rotation. Ours stays at 1 as
   long as it does the work; two corrections multiply.
3. **In OpenKerf:** switch **Burn on a cylinder** on, fill in the diameter, leave
   the scale at *No correction*. *Expected:* the page reports the circumference —
   at d = 80 mm that is **251.33 mm**.
4. **Press Home** in the Job tab. *Expected:* the question **Home with the rotary
   fitted?** appears and nothing moves. Do not go through it. This is the safety
   part of the feature: without the question the head drives into the chuck.
5. **Draw a rectangle 100 mm tall and 10 mm wide**, put it in a cutting layer at
   low power, and read the pre-flight. *Expected:* "The rotary is on: a chuck of
   80 mm, Y scaled by 1." above the start button.
6. **Burn it.** Then measure with a flexible tape how far the burned line runs
   *around* the object. *Expected:* something near 100 mm. More than 10 % out and
   you stop here: the controller's own setting is wrong, and calibrating on top of
   a wrong conversion only hides it.
7. **Calibrate:** 100 asked for, what you measured. *Expected:* a factor of 100
   divided by your measurement — 96.5 mm gives **1.0363** — and the page then says
   "Y goes into the machine multiplied by 1.0363." and "A shape 100 mm tall burns
   103.6 mm around the object."
8. **Burn the same rectangle again and measure again.** *Expected:* within half a
   millimetre of 100 mm. Worse than that, calibrate once more; it builds on the
   first factor.
9. **Burn a ring all the way round:** a rectangle as tall as the circumference the
   page reported (251.33 mm at d = 80). *Expected:* the end meets the beginning. A
   gap or an overlap means the **diameter** is wrong, not the factor — the factor
   was proved in step 8.
10. **Write the factor down beside the machine**, with the diameter next to it. It
    belongs to this rotary with this object; a different diameter is a different
    measurement.

### When the ring comes out wrong

| What you see | What it points at |
|---|---|
| A spiral: the end lies beside the beginning instead of on it | The object is not straight in the rotary, or it tapers. Measure the diameter at the height the design goes. |
| Everything is short or long by the same proportion | The factor. Step 7. |
| Short *and* skewed | The object is slipping in the chuck or on the rollers. Clamp first, measure after. |
| The head drives into the rotary | Something homed. Switch the rotary on in the app the moment it goes into the bed; then homing is refused. |
| The right size, in the wrong place | The scale counts from the machine zero, so a shape further up the drawing lands further along. Lay the work where you burned the calibration line. |
| Corrected twice as much as it should be | Double compensation: the controller converts *and* our factor is not 1. Set the scale to *No correction* and calibrate again. |

## What is proved, and what is not

The line between the two is the point of this page, so here it is as a table.

| Proved without a rotary | How |
|---|---|
| The scale reaches the cutcode the spooler gets — not just the drawing | A rectangle 30 × 20 mm at 10,10 with factor 1.036269: Y goes from 10000…30000 to 10363…31088 native units (a height ratio of 1.036250; the rest is rounding to whole units at 2580.118 per mm) while X stays 10000…40000 |
| Switching it on and off is visible in the cut path | Over real HTTP: the path came out at y 10.0…30.0 mm, with the rotary on 10.36…31.09 mm, and 10.0…30.0 again after switching off |
| Homing is refused, `physical_home` included, and `force` is the way through | The API answers 409 with the code `rotary.homeWhileActive` |
| The settings survive a restart of the server | They are written to the machine's own configuration at once, not at shutdown |
| The pre-flight says it before every start, with the diameter and the factor in the sentence | |
| Calibrating builds on what is set | 100 / 96.5 gives 1.036269, and 100 / 99.5 after that gives 1.041477 — not 1.005 again |

| Not proved, and not claimed |
|---|
| That a burned ring comes out round and to size |
| That one calibration factor also holds for a second diameter |
| Whether counting the scale from the machine zero is a nuisance in practice |

Those three are what the ten steps above are for. Until somebody has run them on
a real machine, this feature is honest arithmetic with an untested end.
