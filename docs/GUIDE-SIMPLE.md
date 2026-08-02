# Lakebridge, Explained Simply

**What we did on 27 July 2026, in plain English.**

You do not need to be a programmer to read this. Every technical word is explained
the first time it appears.

---

## The short version

We installed a tool called **Lakebridge** on a Mac, connected it to a Databricks
account, and tested whether it really works. It does. We also found **two genuine bugs**
in the tool itself, and worked around both.

Think of it like buying a translation machine, setting it up, and then testing it with
real documents to see if the translations are any good — and finding two places where
the machine gets confused.

---

## First, some words explained

| Word | What it means |
|---|---|
| **Databricks** | An online service where companies keep and analyse large amounts of data. Like a giant, very powerful spreadsheet system that lives on the internet. |
| **SQL** | The language people use to ask questions of data. "Show me all customers in Asia" written in a way computers understand. |
| **Snowflake** | A competitor to Databricks. Another place companies keep data. |
| **Migration** | Moving your data and your questions from one system to another — for example from Snowflake to Databricks. |
| **Lakebridge** | A free tool from Databricks that helps with that move. |
| **Terminal** | A text-only window where you type commands instead of clicking buttons. |
| **Catalog / Schema / Table** | How data is organised, like Cabinet → Drawer → Folder. |

---

## Why Lakebridge exists

Imagine your company has 5,000 questions written in "Snowflake language", and you want
to move to Databricks. The two systems speak *similar* languages, but not identical
ones — like British English and American English, but with more differences.

Rewriting 5,000 questions by hand would take months. Lakebridge does four jobs:

| The tool | What it does | Everyday comparison |
|---|---|---|
| **Profiler** | Looks at everything you have and estimates the work | A surveyor measuring a house before you move |
| **Analyzer** | Reads your questions and flags the tricky ones | A proofreader marking difficult passages |
| **Transpiler** | Rewrites the questions into the new language | The actual translator |
| **Reconciler** | Checks the data matches after the move | Counting your boxes at the new house to make sure nothing was lost |

---

## What we found before starting

Before installing anything, we checked what the Mac already had. Think of it as
checking your toolbox before starting a job.

| What Lakebridge needs | Did the Mac have it? |
|---|---|
| Python (a programming language) version 3.10 or newer | ⚠️ Only had 3.9 — **too old** |
| Java version 21 or newer | ❌ **Missing completely** |
| The Databricks command tool | ❌ **Missing completely** |
| Internet access to three websites | ✅ Yes |

So three things were missing. We installed them one by one.

---

## Step 1 — Installing the Databricks tool

We tried to install it, and got stopped:

```
Error: Refusing to load formula databricks/tap/databricks from untrusted tap
```

**What that means:** the Mac's software installer was being cautious. It was saying
"I don't recognise where this software comes from — are you sure?"

**Why it happened:** the software comes from Databricks' own official source, but the
installer requires you to say "yes, I trust this" the first time.

**The fix:** one command to confirm we trust it.

```bash
brew trust databricks/tap
brew install databricks
```

**Result:** worked. Version 1.9.0 installed.

---

## Step 2 — Installing Java

This one failed too:

```
sudo: a terminal is required to read the password
sudo: a password is required
```

**What that means:** this version of Java wanted to install into a protected part of
the Mac, so it asked for the computer password. But nobody was there to type it.

**The fix:** there are two versions of Java available — one that needs a password and
one that does not. We used the one that does not.

**Result:** Java 21.0.12 installed, no password needed.

**The lesson:** when software asks for a password, check whether there's a version that
doesn't need one. Often there is.

---

## Step 3 — Connecting to the Databricks account

Instead of typing a password or a secret key, we used a method where a browser window
opens, you click "approve", and the connection is made.

**Why this way?** Because no password or secret code is ever typed, stored, or visible
to anyone. It is the safer method.

**Result:** connected successfully as you@example.com.

While connected we looked around the account and noticed something important:

> **The account has no "clusters" — only one small "serverless warehouse", and it was
> switched off.**

A **cluster** is a group of computers rented by the hour to do heavy work. A
**serverless warehouse** is a simpler, automatic version of the same thing.

This one detail caused a problem later. Keep it in mind.

---

## Step 4 — Installing Lakebridge itself

This worked first time. Version **0.14.2** installed.

One small thing we had to be careful about: the Mac's default Python was version 3.9,
which is too old. We pointed Lakebridge at a newer Python (3.12) so it wouldn't pick
the wrong one.

---

## Step 5 — Setting up the translators

Lakebridge asked us a series of questions. Here is what we answered and why:

| Question | Our answer | Why |
|---|---|---|
| Which system are you moving from? | Snowflake | That's what our test files were written in |
| Where are your files? | The samples folder | |
| Where should results go? | The output folder | |
| Check the results against the live system? | **No** | Checking needs the warehouse switched on. It was off, so this would have failed |

**Result:** two translators installed — **Bladebridge** and **Morpheus** — supporting
11 different source systems.

---

## Step 6 — The Analyzer refused to run

This was the biggest problem of the day.

```
OSError: [Errno 86] Bad CPU type in executable
```

**What that means in plain English:** modern Macs use a different type of chip
(called Apple Silicon) than older Macs did (Intel). Software built for the old chip
won't run on the new one — unless you install a translator called **Rosetta 2**.

Lakebridge's Analyzer was built **only for the old Intel chip**. This Mac has the new
chip and did not have Rosetta 2 installed. So the Analyzer simply could not start.

**How we proved it** (rather than guessing):

- We asked the Mac what type of program the Analyzer was → "Intel only"
- We asked what type of chip the Mac has → "Apple Silicon"
- We checked if Rosetta 2 was installed → "No"

Three checks, one clear answer.

**The fix:** install Rosetta 2. This is a one-line command that needs your computer
password, so the user ran it themselves.

During the install, this appeared:

```
Package Authoring Error: 122-10397 ...
Install of Rosetta 2 finished successfully
```

**Was that an error?** No. The first line is a harmless cosmetic complaint inside
Apple's own installer. The last line is the one that matters: **finished successfully.**

**Result after the fix:** the Analyzer ran perfectly. It read our four test files and
correctly identified what each one does and how complicated it is — all rated "LOW"
complexity, which was correct.

**This is not your fault or a setup mistake.** It's a genuine oversight by whoever
packaged Lakebridge. Anyone with a modern Mac will hit it.

---

## Step 7 — The translation test

We gave Lakebridge four Snowflake files and asked it to translate them.

**Result: 4 out of 4 translated, with zero failures.**

Here are some things it got right — the left column is Snowflake's way of saying
something, the right is the Databricks way:

| Snowflake says | Databricks says | Correct? |
|---|---|---|
| `NVL` | `COALESCE` | ✅ |
| `IFF` | `IF` | ✅ |
| `DATEADD` | `DATE_ADD` | ✅ |
| `OBJECT_CONSTRUCT` | `STRUCT` | ✅ |
| `FLATTEN` | `VARIANT_EXPLODE` | ✅ |

These are all different words for the same ideas. Like "lift" and "elevator".

### But we found a real bug

In one file, Lakebridge produced broken output. The original said:

```sql
payload:user.id
```

Meaning: "get the user's ID". Lakebridge turned it into:

```sql
payload/* SESSION_USER() */.id
```

That is **broken**. The word `user` got mistaken for a special command, and the tool
replaced it with a note-to-self instead of translating it.

**Why this is dangerous:** Lakebridge only marked this as a *warning*, not an error.
If nobody reads the warnings, broken code goes into production and fails later.

### We proved exactly what causes it

Rather than guess, we ran a test with four almost-identical lines, changing only one
word each time:

| The word used | Did it break? |
|---|---|
| `user` | ❌ **Broke** |
| `customer` | ✅ Fine |
| `table` | ✅ Fine |
| `device` | ✅ Fine |

Only the word `user` breaks it. Even `table`, which is also a special word in these
languages, works fine.

**What to do about it:** if your data uses the word "user" as a label, check those
lines by hand after translation. Search the output for `SESSION_USER()` to find them.

---

## Step 8 — "Do I need a new workspace?"

A fair question. The answer is **no** — and for two separate reasons.

**Reason one: it isn't possible.** This type of Databricks account does not allow
creating new workspaces. We checked, and got a clear "not found" response.

**Reason two: it wouldn't help even if it were possible.**

This is the surprising part. You might expect a new workspace to give you a clean,
separate space. It doesn't. Databricks stores all your data organisation in one shared
place per region. A new workspace would connect to that **same shared place** and see
**exactly the same data**.

> **The useful comparison:** a workspace is like a new office building. A catalog is
> like a new filing cabinet. If you want your files kept separate from everyone else's,
> you need a new *cabinet* — moving to a different building doesn't help, because
> everyone still shares the same filing room.

So we created a new catalog instead. That gave complete separation, took five minutes,
and worked.

---

## Step 9 — Loading data from three file types

We tested loading three common file formats.

| Format | Worked directly? | What happened |
|---|---|---|
| **CSV** (plain text spreadsheet) | ✅ Yes | Loaded 20 rows immediately |
| **Parquet** (compressed data file) | ✅ Yes | Loaded 50 rows immediately |
| **Excel** (.xlsx) | ❌ **No** | Databricks cannot read Excel files at all |

### The Excel problem

We tested it rather than assuming:

```
Failed to find provider for xlsx
```

**In plain English:** Databricks simply has no ability to open Excel files. It handles
CSV, text, and several data formats — but not `.xlsx`.

**The fix:** convert the Excel file into a format Databricks understands first, then
load it. We did that, and the 15 rows loaded fine.

**Practical advice:** if your company sends data as Excel files, plan for a conversion
step. It's not difficult, but it must be built into the process — Databricks won't do
it for you.

### Proving the data was really usable

Loading data is one thing; being able to *use* it is another. So we asked a question
that required combining all three files at once — customers (from CSV), products (from
Excel), and orders (from Parquet):

| Region | Brand | Orders | Revenue |
|---|---|---|---|
| APAC | Globex | 14 | 19,383.45 |
| APAC | Acme | 9 | 11,630.45 |
| AMER | Initech | 6 | 8,810.05 |

It worked. All three formats combined correctly into one sensible answer.

---

## Step 10 — The checking tool, and the problem it hit

The Reconciler is the tool that proves nothing was lost or changed during a migration.

Setting it up went well at first. It created six record-keeping tables, a storage area,
and two dashboards.

Then, at the very last step:

```
InvalidParameterValue: Only serverless compute is supported in the workspace.
```

**In plain English:** Lakebridge tried to book the old-fashioned kind of computer
(a "cluster") to do the checking work. But this account only allows the newer automatic
kind. The account refused the booking.

Remember Step 3, where we noticed there were no clusters? This is that detail coming
back.

**Everything else had worked** — all the record-keeping was in place. Only the "worker"
was missing.

---

## Step 11 — Building the missing worker

We solved it by reading Lakebridge's own instructions — literally opening up the tool's
internal code to see exactly how it builds that worker — and then building an identical
one, changing only the part that asks for the old-fashioned computer.

**An analogy:** the tool kept ordering a petrol car in a city that only allows electric.
We read its order form, copied it exactly, and ticked "electric" instead. Everything
else — the destination, the driver, the luggage — stayed identical.

**Result:** worker created successfully.

The first run then failed for a completely different reason: we hadn't told it *which
tables to compare*. That is a separate file that the setup wizard does **not** create
for you — you have to write it yourself. This is not explained clearly in the
documentation, and is worth knowing in advance.

---

## Step 12 — The final test, and the best result of the day

Here is the most important part.

Anyone can run a checking tool against two identical tables and get "everything matches".
That proves nothing — a broken tool would give the same answer.

So instead we **deliberately damaged** a copy of the data in four specific ways, then
asked the Reconciler to find them without telling it what we'd done:

| What we deliberately broke | Did it find it? |
|---|---|
| Changed one customer's **name** | ✅ Found it |
| Changed one customer's **region** to "ANTARCTICA" | ✅ Found it |
| Added £999.99 to one customer's **balance** | ✅ Found it |
| **Deleted** one customer entirely | ✅ Found it |

**Four faults planted. Four faults found. Nothing missed. Nothing wrongly flagged.**

The check took about 31 seconds.

**This is the result that matters.** It proves the tool doesn't just run — it genuinely
does its job correctly.

---

## The overall verdict

| What we tested | Result |
|---|---|
| Installing everything | ✅ Works, after fixing three missing pieces |
| Connecting to Databricks | ✅ Works |
| Analyzing existing code | ✅ Works — **but needs Rosetta 2 on modern Macs** |
| Translating Snowflake → Databricks | ✅ Works well — **one bug with the word "user"** |
| Loading CSV files | ✅ Works |
| Loading Parquet files | ✅ Works |
| Loading Excel files | ⚠️ Needs a conversion step first |
| Creating organised storage | ✅ Works |
| Checking data after migration | ✅ **Works perfectly — 4 out of 4 faults caught** |

**Bottom line: Lakebridge works and is worth using.** Two rough edges exist, both
have workarounds, and both are now documented.

---

## Things to remember

1. **On a modern Mac, install Rosetta 2 first.** Otherwise the Analyzer will not start
   and the error message will not tell you why.

2. **Check anything containing the word "user" by hand** after translation. Search for
   `SESSION_USER()` in the output.

3. **Excel files need converting first.** Build this into your process.

4. **You do not need a new workspace.** A new catalog gives you the separation you want,
   and takes minutes instead of an approval process.

5. **On accounts without clusters,** the checking tool needs the manual setup described
   in the technical document. It works — it just isn't automatic.

6. **Always test a checking tool by breaking something on purpose.** If it doesn't
   notice, it isn't protecting you.

---

## Two things worth telling Databricks

Both of these are faults in the tool, not in your setup, and both would affect other
people:

- **The Analyzer only works on old Mac chips.** Anyone with a Mac bought in recent
  years will hit this.
- **The checking tool cannot set itself up on newer account types.** It asks for a kind
  of computer those accounts don't offer.

---

## Where to find more

- **`docs/TECHNICAL.md`** — the full version with every command and its exact output
- **`docs/session-report.html`** — an interactive page you can click through
- **`docs/PLAN.md`** — what we planned before starting
- **`docs/RESULTS.md`** — the results checklist
- **`docs/UC-SANDBOX.md`** — details of the storage we created
- **`docs/RECONCILE.md`** — details of the checking tool
- **`logs/`** — a timestamped record of all 30 steps
