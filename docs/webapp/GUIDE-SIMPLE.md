# What We Built — Explained Simply

This explains the same work as `TECHNICAL.md`, but in plain English.
No computer jargon. If a word needs explaining, it's explained right there.

---

## The big picture

There's a tool called **Lakebridge**. It moves data and database code from
one company's system (like Redshift or Starburst) into Databricks, which
is a different system. Right now, Lakebridge only works by typing commands
into a black terminal window. That's hard for most people.

So we're building a **website** that does the same job, but with buttons
you click instead of commands you type.

---

## The two halves of the website

Think of a restaurant. The **frontend** is the dining room — what the
customer sees and touches. The **backend** is the kitchen — where the
real work happens, out of sight. Our website has both:

- **Frontend**: the web page you'd actually look at and click on.
- **Backend**: a program running quietly that does the real work — talking
  to databases, running Lakebridge, moving data.

---

## The rule we never broke: show what's real

At every step, we tested things for real. We connected to real databases.
We ran the real tool. We showed real results — including when something
went wrong. We never faked a screenshot or pretended something worked when
it didn't.

---

## Step by step, what we did

### Step 1 — Teach the backend to run Lakebridge safely

We built the "kitchen" — code that can safely run the Lakebridge tool.
"Safely" matters because a website should never let a stranger type
something that tricks the computer into running a dangerous command. We
built a strict list of exactly which Lakebridge actions are allowed, and
nothing else gets through.

**A real problem we hit:** Lakebridge needs a program called Java to do
some of its work. The Java on this computer wasn't easy to find
automatically — kind of like a tool that's in the garage, but not in the
toolbox where you'd expect it. We had to point the computer straight at it.

### Step 2 — Add more buttons, and don't lose data

We added two more Lakebridge actions, and made sure that if the website's
"kitchen" program restarts, it doesn't forget everything it did before —
like a to-do list that survives even if you close the notebook and open
it again.

**A real problem we hit:** one Lakebridge action quietly asks "want to
open this in your browser?" and waits for someone to answer. Since nobody
was there to answer, it just got stuck. We taught it to automatically say
"no" so it can keep going on its own.

### Step 3 — A first try at the website (rejected)

We built a simple page with four buttons. But then it became clear the
real goal was much bigger: browsing real company databases and
drag-and-dropping things to move them over. Four plain buttons weren't
close to that. So we set it aside — kept the useful parts, and started
planning something bigger.

**Something important happened here:** while planning the bigger version,
real database passwords were typed into the chat by mistake. That's not a
safe place for passwords to live — chat messages get saved. We
immediately moved them to a locked, private file that never gets shared or
saved to the project's history. **But the passwords should still be
changed**, since they were visible for a little while.

### Step 4 — Actually connect to real databases

We connected the backend to a real Redshift database and a real Starburst
database — both real company-style databases, not pretend ones. We could
now ask "what tables exist in here?" and get real answers.

We found that the Redshift database had 7 real tables, but no special
custom functions yet. So we created three simple ones for real, so there'd
be something worth practicing on:
- One that counts how many days until an event happens
- One that labels a ticket price as cheap, normal, or expensive
- One that adds up sales for each venue

### Step 5 — Actually move things over

This is the big one. We learned something important: **Lakebridge only
converts code — it doesn't copy the actual data (the rows in a table)**.
That's like a translator who can translate a recipe into another
language, but won't go to the store and buy the ingredients for you. So we
had to build a second, separate piece just for moving the real data.

**Four real problems we found and fixed, without hiding any of them:**

1. One way of asking Redshift for a function's details just doesn't
   exist. We found another way to get the same information.
2. We *thought* Starburst could only tell us a function's name and not
   what it does inside. **That turned out to be wrong — see the G18
   section near the end of this guide.** We had only tried one way of
   asking. A different command hands over the whole thing, and the app
   now shows the real contents.
3. One setting needed an exact word from a specific list, and "Starburst"
   wasn't on the list. We picked the closest match and were upfront about
   it being a guess, not a perfect answer.
4. **The biggest one:** one Lakebridge command can fail and still tell the
   computer "everything's fine!" We caught this because we didn't just
   trust it — we double-checked by looking at what it actually printed,
   and by watching the real job it started until it truly finished.

**We also found a real mistake in Lakebridge itself** — it converted one
of our functions incorrectly (it was supposed to handle words up to 20
letters long, but the converted version only allows 1 letter). We didn't
fix or hide this — we wrote it down and built a check that will notice if
a future version of Lakebridge fixes it.

**Real proof it works:** we copied 5 real rows of data from the source
database to the new Databricks table and checked every single value
matched exactly — not just "same number of rows," but the actual names
and numbers were identical.

---

## What's happened since (all done now)

- Built the real visual page — you can look inside both databases and
  drag things onto Databricks to move them.
- Added moving a whole group of tables at once (a whole schema), not
  just one at a time.
- Fixed a real problem: the "reconcile" button used to say "done" the
  moment it started a check, not when the check actually finished.
  Now it waits for the real answer. Added a page showing everything
  this app has ever done, all in one list.
- Had two safety/usability checks done for real. One found a real
  security hole (a sneaky table name could have deleted real data) —
  found it, tried the trick, proved it worked, then fixed it and proved
  the fix worked too. The other found buttons that couldn't be used
  with just a keyboard, and fixed those.
- Added a chat box: type what you want in plain English, it shows you
  exactly what it's about to do, and waits for you to say "yes" before
  doing anything for real.

## What we built next: our own fast Starburst path (done)

The Starburst side used to borrow a Databricks AI helper to convert
table shapes, and it could take several minutes and sometimes didn't
finish — annoying for a live demo. There was also no way to move
Starburst's actual table *data*, only its shape.

We built our own faster way to convert Starburst table shapes — done
entirely in our own code, no more waiting on the AI helper — and a real
way to copy Starburst's actual data over too, which didn't exist before.
The old slow method is still in the code, just hidden from the buttons,
in case we want it again later.

**Two real mistakes found and fixed while checking this, by someone who
didn't write the code:** first, the results screen was mislabeling every
new fast conversion with the old slow method's name — the work was
correct, but the label lied about which method did it. Second, clicking
"convert" on a real Starburst view (views are different from tables —
a view is more like a saved question than a real storage box) caused a
real error, because the app was treating every Starburst item as if it
were a table. Both were caught by actually clicking the real buttons in
a real browser, not just reading the code, and both are fixed and
re-tested now.

**What we're honest we can't do:** copy the actual code inside a
Starburst-defined function, or copy stored procedures — Starburst
doesn't have stored procedures at all, and it won't show us a
function's inner code no matter how we ask, only its name. Rather than
fake it, the app just says so.

**A third mistake, found after real use:** someone using the app said it
still felt slow when dragging a Starburst table over, even after the
fixes above. Turned out that was true — a real bug, not just something
that needed a page refresh. The new fast button worked fine, but
actually dragging a table (instead of clicking the button) had been
left connected to the old slow method by mistake. We found this by
testing a real drag, not just clicking the button, fixed the wiring, and
tested a real drag again to prove it now takes seconds instead of
minutes. Lesson for next time: when we add a new button next to an old
drag-and-drop action, we have to test the drag too, not just the button.

## What we fixed after that: five more real problems, found by really using it

The person using this app pointed out five real problems, and said
plainly: don't just tell me it's fixed, actually test it.

1. **Switching tabs kept reloading everything.** Look at a Redshift
   table, switch to another tab, come back — it used to fetch the whole
   list all over again, instead of remembering what it already showed
   you. We fixed it so the app remembers, like a real database tool
   does. We proved it by watching the actual network traffic: switch
   away and back, and no new request fires.
2. **We added a refresh button.** Since the app now remembers what it
   already loaded, we needed a way to say "check again, something might
   have changed" — a small refresh icon, and also a right-click menu,
   on every folder in the tree. Only that one folder refreshes, not the
   whole tree.
3. **We built a real window into Databricks.** Before, the app could
   only send things TO Databricks — it never showed you what was
   already there. Now there's a real "Databricks" tab that looks inside
   for real, showing real tables that were really moved there.
4. **You can now see the actual migrated data**, not just "it worked."
   Click "view data" on anything that copied real rows, and you see the
   real rows — in the Databricks tab, and also next to the migration
   record itself.
5. **The chat box now understands Starburst too**, not just Redshift.

**While checking our own work extra carefully this time, we found three
more real mistakes and fixed all of them:**
- The new information about "where did this data end up in Databricks"
  was being calculated correctly, but the website was accidentally
  throwing it away before showing it to you. Fixed.
- Right-clicking to refresh only worked if you clicked exactly on the
  tiny icon — clicking anywhere else on the folder's name did nothing,
  even though that's the natural place to click. Fixed so the whole row
  responds.
- The "view data" button only showed up in one of the two places you'd
  look for it (today's session), not in the full History list where you
  can look back at everything ever done. Fixed so both places show it.

Every one of these was found by actually clicking through the real app
and checking the real network traffic — not by reading the code and
assuming it worked.

## What we added to the chat box: clickable shortcuts for real things

The chat box is now called **AI Command**, and next to it there's a list
of small clickable buttons — one for each real thing in the source
databases (a "chip" is just a small rounded button with a name on it).
These aren't a made-up list typed into the code: the app asks the real
databases what's actually in them and builds the buttons from the answer.

**Clicking one does not immediately move anything.** It simply types a
sentence for you — the exact same sentence you could have typed
yourself — and sends it through the normal path: the app shows you the
plan, asks you to confirm, and only then does the real work. There is no
shortcut around the "are you sure?" step, and there was never meant to
be. We checked this two ways: by following the code from the button all
the way to the send function (it's the same one typing uses), and by
actually clicking it in a real browser and watching the confirmation box
appear.

We also taught the chat box a new instruction: "move this table **and**
its data" — one sentence that does both the table's shape and the rows
inside it. It only accepts tables and views, because functions and
stored procedures don't have rows to copy in the first place.

**A real bug we only found by clicking the buttons:** the sentence the
button wrote was "migrate public.venue and its data". But the Redshift
half of the chat box only understands the schema (the folder a table
lives in) when you say it in words — "in schema public" — not when you
stick it on the front with a dot. The Starburst half *does* understand
the dotted form. The two databases genuinely have different rules for
how names are read. So every Redshift button quietly looked in the
default folder and got refused. Fixed by having the button write
"migrate the venue table in schema public and its data" instead.

## We rebuilt the whole look of the app

The old app was a light-coloured page with a row of tabs across the top.
It's now a dark console-style app:

- A narrow strip of icons down the left side to switch between sections:
  Migrations, AI Command, Intelligence, Unity Catalog, and Logs.
- A **Data Explorer panel that stays put** — the tree of databases no
  longer disappears when you switch sections.
- A main area with a slim bar across the top.

Dark is what you get by default. There's a light-mode switch that works,
and it remembers your choice next time you open the app — and it wins
over whatever your computer's own dark/light setting says, in both
directions.

We also wrote down the rules for how the app should look in a new
document (`docs/webapp/DESIGN-SYSTEM.md`), and put every single colour
in one file (`frontend/src/theme.css`). Nothing anywhere else is allowed
to write a colour directly.

**A real structural problem we fixed:** the three database trees
(Redshift, Starburst, Databricks) used to be built **twice** — once on
the explorer page and once again in the chat sidebar. Two separate
copies, each asking the databases for the same information, each
remembering separately which folders you'd opened. Now there's exactly
one copy, in one place. That's why the explorer keeps its opened folders
when you move between the Migrations and AI Command sections.

The Unity Catalog section on purpose does **not** show a second copy of
the Databricks tree — that was tried, and caught and rejected during
checking, because it would have re-created the exact duplication we'd
just removed. Instead it shows a real list of catalogs with the
migration destination marked, plus a button that opens Databricks inside
the one real tree.

Other changes in this rebuild:

- All the little text symbols used as icons were replaced with proper
  drawn icons, hand-written into the app itself. We did not add any
  outside package to do this — this project's rule is not to pull in
  code we haven't verified.
- The pipeline picture (what happens to your table on the way over) was
  rebuilt as three circles — source, converting, destination — each
  showing its own status.
- The Databricks tree caught up with the others: you can now open a
  table to see its columns, and view the code inside a Unity Catalog
  function. Two things we learned the hard way while building this:
  asking Databricks to list functions fails outright unless you first
  tell it which catalog you're working in; and the obvious command for
  "show me this function's code" returns everything *except* the code.
  Only one particular system table actually has it.
- Starburst views now have a preview button too (before, only tables
  did). Starburst functions still won't show us their inner code — that
  genuinely isn't available from Starburst, and the app says so rather
  than faking it.
- **Fixed a real lie in the pipeline picture:** when you asked the chat
  box to move a table and its data, the last step said "Writing target:
  Skipped" even though the rows had actually been written. Checked live
  after the fix: it now says "writing target: DONE" with "rows copied:
  10".

### Two bugs that only showed up in a real browser

1. When you hide the data panel, the app used to go completely blank.
   The reason: the page is laid out in three columns, and hiding one of
   them doesn't automatically shrink the layout back to two — the main
   column ended up with no width at all.
2. In the top bar, the title and the status badge both take up exactly
   as much room as they need, so on a narrower window they overlapped
   each other instead of moving to separate lines.

Neither of these was caught by the automatic code checks or by building
the app — both look perfectly fine to a computer. Only opening it in a
real browser showed them.

### How we know this is done

109 automatic backend checks pass, and both frontend build checks come
back clean. On top of that, someone independent went through the whole
thing again from scratch and **rejected it the first time** — for two
real reasons: the Databricks tree was still being built twice (in the
new Unity Catalog section), and 13 colours had been written directly
into a stylesheet instead of coming from the one colour file. The worst
of those painted a Redshift item blue, which contradicts the rule that
each system keeps one colour everywhere. Both were fixed and checked
again.

## Tidying up the new look, and one bug where the app made something up

After looking at the rebuilt app, the person using it asked for several
changes, and while making them we found a mistake that matters more than
all the layout work put together.

### Moving things around

- **The database list moved.** It used to sit in the app's outer frame,
  next to everything. Now it lives inside the Migrations section. It's
  still built only once — that was the whole point of the earlier
  clean-up and we didn't undo it. The AI Command section doesn't grow a
  second copy of the list; it has the little clickable name buttons
  instead.
- **Two sections were taken off the left-hand strip of icons:
  "Intelligence" and "Unity Catalog."** They are *hidden*, not deleted.
  Their code is all still there, the sections are still loaded, and
  turning either one back on means deleting a single name from a short
  list in one file. The Logs section still opens the Intelligence
  section when you click through to see a job's detailed log.
- **The Logs filter buttons were stacked on top of each other instead of
  sitting in a row.** These are the All / Run / Migration / Batch
  buttons, each showing a count. The reason: they were borrowing a
  styling label ("batch-toolbar") that another part of the app — the
  batch card in Migrations — had later redefined to mean "stack these
  vertically." Two unrelated things sharing one label, and one of them
  changed the meaning. Fixed by giving the Logs filters their own label
  so they no longer share. They now sit in a horizontal row of little
  count cards.

### The chat box used to look frozen

Before, while the chat box was working, almost nothing on screen changed.
While it was working out a plan, the only clue was the wording on the
send button. And while it was *actually doing* the migration, the code
never even marked itself as busy — the typing box stayed enabled and all
you got was a motionless grey line saying "Executing…". If a check on
progress failed, that failure was quietly thrown away and you were never
told.

Now: a moving indicator appears right in the conversation, the app
properly marks itself busy while executing, and a **counter ticks up the
seconds**. That last part matters because a real migration takes 20 to 40
seconds — long enough that a motionless label genuinely reads as "this
thing has crashed." And if progress checks keep failing, it now says so
honestly instead of hiding it. The animation switches itself off if your
computer is set to reduce motion.

### The bug where the app made something up

This one is worth reading carefully.

The code contained a claim: that Starburst has no way to show you the
code inside one of its functions. Acting on that claim, whenever anyone
looked at a Starburst function the app displayed a placeholder saying the
function's insides couldn't be recovered.

**That claim was false for this server.** There is a command
(`SHOW CREATE FUNCTION`) that returns the complete, real code — it works
here, and always did. So the app had been showing invented text in a
place where the real thing was available all along.

Fixed: the app now runs the real command and shows the real code. The old
approach — rebuilding a rough outline of the function from its name and
argument types — is kept only as a genuine backup, and when it's used it
now says clearly that what you're looking at was reconstructed, not the
real source.

The wider lesson: one command gave less information than we hoped, and
that got turned into a sweeping statement about what the whole system can
do — and that statement was then used to justify showing made-up content
to a user. Note that some earlier text in these documents said the same
false thing; it's corrected now.

### Real practice routines, and buttons for them

We created some real things to practise on, using a small script:

- In Redshift: a stored procedure that joins the real customers and
  orders tables, and a simple function.
- In Starburst: a simple function.

**We did not create a Starburst stored procedure, because Starburst
doesn't have them at all.** Asking it to create one fails immediately at
the grammar level — it doesn't just refuse, it doesn't even recognise the
word, and it replies by listing what it *would* have accepted there
(branch, catalog, function, materialized, or, role, schema, table, view).
This isn't a permission problem or an out-of-date version. The feature
does not exist.

The clickable name buttons next to the chat box now include these
routines as well as tables. They behave differently on purpose:

- Clicking a **table** button writes the "move this" sentence, as before.
- Clicking a **routine** button shows you that routine's **real source
  code** in the conversation, and does nothing else.

There is deliberately **no "create it in the destination" button** for
routines. That was an explicit decision by the person using the app, not
an oversight.

### Why tables are easy to move but routines are harder

Someone asked this directly, so here's the honest answer:

- A table definition is just a list of column names and their types.
  Converting that is mechanical — you swap each type for the matching one
  and you're done.
- Simple **functions** are *not* blocked. Databricks does let you create
  them, and one already exists in the destination. What's different is
  the way they're written down: Redshift wraps the body in a special
  `$$ ... $$` marker and refers to its inputs by position ("the first
  one", "the second one"), while Databricks writes a single `RETURN`
  expression and refers to inputs by name. That's a translation job, not
  an impossibility.
- **Stored procedures** are the genuinely hard case, and only Redshift
  has any. Their body is a small program — it has begin/end blocks,
  if-statements and loops, and it can create and change tables from
  inside itself.
- One thing we deliberately are **not** claiming: whether the destination
  Databricks warehouse accepts stored procedures at all. We didn't test
  it, so we don't say.

### A crash we caught before it hit anyone

The web page's description of what Starburst sends back said one field
(the list of a function's argument types) was a list. The backend
actually sends it as ordinary text. The page then tried to join that
"list" together with commas — an operation that only works on a real
list — which would have crashed the moment anyone opened the functions
folder in the tree. The page was simply wrong about its own data. Fixed
by correcting the description and using the text as text.

---

## What we've been asked to do next (not built yet)

Everything here is a **list of requests**, written down so it isn't forgotten.
None of it works yet.

- **Move the object list into the menu.** Right now the list of database
  objects sits in its own column. It should instead live inside the left menu,
  tucked under "Migrations", and open and close like a folder.
- **Stop showing previewed data inside that list.** When you click the eye icon
  to look at data, it should open in the **middle of the screen**, not squeezed
  into the bottom of the narrow list.
- **Only show the progress diagram once.** At the moment the same
  source → converting → destination diagram appears twice on the page.
- **Tidy the buttons.** The "batch migrate schema" button should sit apart from
  the individual schema it belongs to, with the refresh button next to it, and
  the three small buttons on each table should sit on one line instead of
  wrapping.
- **Use the same wording on both sides.** Redshift's button says "migrate" and
  Starburst's says "migrate (fast)". They should match.

**The bigger request:** when you click the eye icon, you should get a clean view
in the middle of the screen with two parts you can open and close separately —
the **SQL**, and the **actual table data** with scrollbars both across and down.
It has to look neat and move smoothly, and it must not get in the way of
dragging and dropping.

**The demo we're aiming at:** open the app, open the object list in the menu,
drag something onto the drop zone, watch the progress, and then see the original
SQL and data alongside what ended up in Databricks. Then do the same thing from
the chat box by clicking a suggestion chip.

### A question that came up, answered here

**What's the difference between "migrate" and "copy data"?** They are not the
same thing at all:

- **"migrate"** only **translates the SQL** into the Databricks dialect and
  shows you the result. It doesn't build anything and doesn't move any rows.
- **"copy data"** actually **creates the real table in Databricks and copies the
  real rows into it**, then counts them to check.
- **Dragging and dropping** a table does **both** at once.

The "(fast)" on the Starburst button is there only because Starburst has two
ways of translating — a quick one we wrote ourselves and an older, slower one.
Redshift only has one way, so its button has no extra word. That's the only
reason the two buttons read differently, and we've been asked to fix it.

### One thing still to decide

Should the chat box also list objects **already sitting in Databricks**, just to
look at? Nothing would ever be migrated backwards — moving only ever goes from
the source systems into Databricks. It may simply repeat what you already see
after a migration finishes. We owe a recommendation rather than just building it.

## AI mode in the chat, and "you already migrated this"

**Two things changed.**

### 1. The chat can now understand ordinary English

Before, the chat only understood a fixed set of phrasings. Say it a slightly different way and it
would shrug. Now there's a fourth method: if the built-in rules can't work out what you meant, an AI
model reads your sentence and works it out.

So all of these now work, and none of them did before:

- "can you bring the customers table over from redshift along with all of its rows please"
- "push the orders table and everything in it into the lakehouse"
- "I'd like the f_customer_tenure routine moved across to databricks"

**It is switched off until you switch it on.** In `backend/.env` you set `LLM_ENABLED=true`, choose a
provider (Anthropic, OpenAI or DeepSeek), and paste an API key. With it off, nothing is sent anywhere
and the chat behaves exactly as it always did.

**It can't wander off-topic.** The AI is never asked "what should I do?" — it's asked to pick one
action from a fixed list (migrate this, copy that, preview this). There's no option on that list for
answering a general question, so it can't. Tried and confirmed against the real model: asking for the
weather, the capital of France, a poem, or telling it to ignore its instructions and drop all tables
— every one refused, and nothing was migrated.

It also can't invent objects. Whatever name it comes back with is looked up in your real Redshift and
Starburst before anything happens. "Migrate the unicorn table" is refused, because there is no
unicorn table.

And nothing runs without you confirming it. The AI only *proposes*; the confirm dialog still appears
exactly as before.

### 2. It tells you when something is already migrated

If you try to migrate an object that's already in Databricks, it says so instead of quietly doing the
work again. There are two different messages, because there are two different situations:

- **"Already migrated."** — for `migrate`. Nothing was created, nothing changed.
- **"Already migrated — rows refreshed."** — for `copy data` and drag-and-drop. Copying data means
  replacing everything with a fresh copy, so it *did* do something: your rows are now up to date.
  Skipping would have left you with stale data, which is the opposite of what copying is for.

This applies everywhere — the migrate button, copy data, drag-and-drop, batch select, batch migrate
schema, and the chat.

## Why there are now two copies of this project

You may notice two folders:

- `databrick-proj-migrate` — the original
- `databrick-proj-migrate-paid` — this one

**Nothing is broken.** Here's what happened.

The Databricks account we were using is on a free plan, and free plans have a daily limit on how many
queries you can run. We used it up — a lot of real migrations plus several full test runs. Once that
limit is hit, everything Databricks-related stops working until the next day.

So we're pointing this copy at a **paid** Databricks workspace instead, which doesn't have that limit.

**The original folder still works and is untouched.** Once the daily limit resets, you can go straight
back to it. Nothing was moved or deleted — this is a copy, not a relocation.

### Why copy the folder instead of just changing a setting?

Fair question, and it depends entirely on one thing: is the paid warehouse in the *same* Databricks
workspace, or a different one?

- **Same workspace** — genuinely two lines in a settings file. No copy needed.
- **Different workspace** — the login details change, the place we put migrated tables changes, the
  file storage area changes, the Lakebridge tool has to be installed there, and the reconcile job has
  to be registered again.

The paid workspace turned out to be a different one, so we made the copy. That way, if anything goes
sideways, the working original is still sitting there.

### What has NOT changed

Redshift and Starburst — where your data comes *from* — are exactly the same. Only the destination
moved. Everything you've seen the app do still works the same way.

### What's needed before this copy can run

1. The connection address of the paid warehouse (found in Databricks under SQL Warehouses →
   Connection details).
2. A login profile for the new workspace, which involves a token — that has to be set up by you, not
   by the assistant.

There's a full checklist in `WORKSPACE-MIGRATION.md` in this folder.

---

## The paid workspace is now live (2026-08-02)

The second Databricks account is connected and working. Everything you can do in the app — migrate
an object, copy its data, run a batch, ask the AI chat to do it — has been run against it and
checked.

**What's in the new account now:** a catalog called `lakebridge_demo`, three schemas inside it, a
storage area ("volume") holding a real CSV file and a real Parquet file, five small tables with real
rows, and two functions. All of it was created by a script you can safely re-run — it skips anything
that already exists.

**Signing in.** We used a browser sign-in rather than a password or an access key, so there is no
secret written down anywhere in the project. If the app ever says it can't authenticate, sign in
again:

```
databricks auth login --host https://<workspace>.cloud.databricks.com --profile lakebridge-paid
```

**Two things that will waste your time if you don't know them:**

1. The app's two halves only talk to each other on specific ports — the back end on 8811, the front
   end on 5173. On any other port the app says "ADAPTER UNREACHABLE", which looks like a broken
   connection but is really just the wrong door.
2. The *original* project folder can leave its own copies of these programs running. They answer on
   the same ports and look identical, so you can end up testing the old code without noticing. It
   happened during this work. If something looks wrong, check which folder is actually running.

**Something we found and fixed:** the first time you migrated a table *with* its data, the app said
"already migrated" even though it had never been migrated before. It was confusing itself — it
created the table, then looked, saw the table it had just made, and assumed someone else made it
earlier. It now checks before it starts, so the message is only shown when it's true.

**The original folder still works and is untouched.** Go back to it whenever the free account's
daily limit resets.

---

## Getting it to run somewhere other than this laptop (2026-08-02)

To demo from GitHub Codespaces, four things had to change. None of them alter how it behaves here.

**The one that would have broken the demo outright:** the app's screen used to look up the back end
at "this computer". That's fine when it's your computer. But when someone else opens your link,
"this computer" means *their* laptop — where nothing is running. The page would load and nothing
would work. The address is now a setting, so it can point at the real server.

**The other three:** the back end now accepts connections from the demo address (before, only from
this laptop); sign-in works without the usual settings file, which a fresh cloud machine doesn't
have; and there's a setup file that prepares a cloud machine automatically.

**We tested it properly.** We ran the whole app on two unusual ports at once — deliberately not the
normal ones — to imitate the cloud setup, and migrated a real object through it. That's the same
thing that failed before, so passing it is real evidence rather than a hopeful guess.

**One honest caution:** a "public" link in Codespaces has no password. Anyone with it can drive the
app, and the app creates real things in Databricks and spends real money on the AI key. We'd share
it with named people instead.

**Something we found while testing:** if you asked it to copy a table that doesn't exist, it
complained about broken syntax instead of saying "that table isn't there". Confusing, and it was
writing a nonsense query. Fixed — it now says the real reason.

---

## A few important fixes, and a new "testing" button (2026-08-03)

**The app could quietly talk to the wrong account.** Depending on which file the program loaded
first, it sometimes used the settings for the *old* Databricks account instead of the new one. The
error message blamed the password, which sent us looking in completely the wrong place. Now the
settings are always loaded first, before anything else can read them.

**A test was carrying a real password.** We have tests that check passwords never leak out of the
app. Awkwardly, those tests had the real password typed into them — so the file meant to prove
passwords stay secret was the one about to reveal one. They now read the password from the settings
file at the moment they run, which checks the same thing without writing it down.

**The code is now on GitHub.** It was published from a separate copy, so your own files kept all
their real details while the public version has them replaced with placeholders. Passwords, keys and
private notes were left out entirely. GitHub itself blocked our first attempt because a *fake*
password in a test looked real to its scanner — there was an "ignore this" button, and we didn't
press it. We changed the fake value instead.

**New: a "testing" button** in the left menu. It clears out the practice objects in Databricks,
keeping one from each source plus one important helper, so the next thing you migrate is obviously
new rather than lost in a pile from earlier runs.

Two things about that button worth knowing. It only appears when you start the app in testing mode —
during a demo it isn't there at all, so it can't be clicked by accident. And pressing it doesn't
delete anything straight away: it first shows you a list of exactly what will be removed and what
will be kept, and only the confirm button actually does it.

---

## Right-click, a wider panel, and a migration bug that wasn't what it looked like (2026-08-10)

### Right-click now does something useful

Before, right-clicking anywhere in the object explorer offered exactly one thing: "Refresh". Every
real action lived as a small button on the row itself — easy to miss, and often scrolled out of
sight.

Now right-click gives you the same actions, wherever you are:

- right-click a **schema** → Refresh, Batch migrate schema
- right-click a **table** → Migrate, View data, Copy data
- right-click a **function or procedure** → Migrate, View source
- right-click something in the **Databricks** panel → View data only. Databricks is the
  destination, so the app never writes to it from a right-click menu.

Worth saying plainly: **nothing was taken away.** Every button that was there before is still
there and still works exactly as it did. Right-click is simply a second route to the same place.

### You can drag the left panel wider

Object names get long. A full name like
`lakebridge_demo.g3_migrations.redshift_demo_fast_test_orders` didn't fit in the panel, so the end
of it was just cut off.

There's now a thin handle on the edge between the left panel and the main area. Drag it right to
widen the panel and read the whole name; drag it left to give the main area more room. It remembers
the width you picked, even after you close the browser and come back. You can also nudge it with
the arrow keys, and double-click the handle to snap it back to normal.

The horizontal scrollbar that was already there is untouched and still works — the two do different
jobs. The scrollbar is the right tool when one single row happens to be unusually long. Dragging
the panel wider is the right tool when a whole schema is full of long names and you'd otherwise be
scrolling every row, one at a time.

### Migrations broke, and the cause was not the obvious one

For a while, migrating anything failed with a long red error. It looked exactly like "Databricks is
down" — but nothing was down. Browsing Redshift, Starburst and Databricks all worked perfectly the
whole time, which is what made it confusing.

Here's the simple version. The app has two different ways of talking to Databricks. The part that
*browses* used a password-style key that was perfectly fine. The part that *migrates* goes through
a separate Databricks tool, and that tool insisted on using a different, older login — one that had
quietly expired — while ignoring the good key sitting right next to it.

The fix was to tell that tool explicitly which key to use. Migrations work again, and we checked it
by actually migrating a real table rather than trusting the tests.

**One test is still failing, on purpose.** It covers "reconcile" — a feature that compares two
tables to confirm a migration copied everything across correctly. Its helper job was set up in the
old workspace and was never re-created in the new paid one, so the test has nothing to run against.
Reconcile isn't part of the demo, so we deliberately left it alone rather than half-fixing it.

### Folding away cards you're done with

Run a few batch migrations, or ask the assistant a few things, and the page gets long. Each result
card is tall, so the one you actually care about ends up somewhere off the bottom of the screen.

Every batch card and every plan card now has a small arrow button in its top-right corner. Click it
and the card folds down to a single line; click it again and it comes back. Nothing is lost —
folding only hides it from view.

One deliberate detail: a folded batch card still shows its real numbers, including any failures. So
a batch where something went wrong still says so plainly (`6/16 settled — 6 ok, 0 failed`) even when
it's collapsed. Hiding a failure behind a tidy summary is exactly the sort of thing this project has
refused to do everywhere else, and folding is no exception.

### Turning off the meter: making the Redshift cluster throwaway (2026-08-12)

One of the three systems this app reads from — Amazon Redshift — costs money simply for existing.
It charges while it is switched on, and it *still* charges for storage even when it is paused. If a
demo slips by a week, that is a week of paying for a database nobody is looking at.

So we made it disposable.

Everything the demo needs from Redshift — the tables, every row in them, and all the little
functions — is now saved as plain SQL files kept alongside the code. That means the cluster can be
deleted completely. When the next demo comes round, you create a fresh one, run a single command,
and about a minute later the source data is back exactly as it was. Nothing is paid for in between.

It is a small amount of data on purpose: 7 tables, 39 rows in total, 5 functions and 1 stored
procedure, across the two demo schemas. Small enough to restore in seconds, real enough to migrate.

**We generated those files from the real database rather than writing them by hand.** That matters:
a hand-written copy slowly stops matching reality, and you only find out when it fails in front of an
audience.

**And we actually tested the restore, rather than assuming it would work.** That was worth doing,
because it failed the first time — and would have failed in front of you. Redshift refuses to create
a function unless you tell it one extra detail about how the function behaves, and the code that
produced our SQL did not include it. **All five functions would have been missing.** Reading the
files would never have revealed it; only running them did. It is fixed, and the whole thing has now
been rebuilt from scratch on a real cluster and checked end to end — every table, every row count,
and every function called to confirm it returns the right answer.

**One thing you have to do by hand.** When you create a new cluster, its address changes, so the app
needs to be told the new one (a single line in a settings file) and restarted. Skip it and the app
reports a confusing "Server refuses SSL" error, which is the same unhelpful message it gives when
the cluster is merely paused — it almost never has anything to do with SSL.
