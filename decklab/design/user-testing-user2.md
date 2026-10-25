# User testing with User2: session checklist

The prepared checklist for story **E11-S28** in [stories.md](stories.md): Matt watches User2 (member, own space `user2`) do everyday jobs in Deck Lab, to find where the navigation, wording or feedback needs to be clearer. Written 2026-10-17 from the code as it stood then. Recheck the "where it is" notes against Deck Lab on the day, because features may have changed.

Print sections 1 to 6. Section 3's boxed **For Matt (don't read out)** notes are only for Matt: don't read them out, and don't use them to coach. Read aloud only the quoted prompt after each task's bold name.

## 1. Purpose and opening script

Deck Lab is the thing being tested. User2 is not. He is an experienced Magic player, so every task assumes he knows the game, and terms such as creature, vigilance, mana value and colour identity need no explaining. When a task goes wrong, that tells us about Deck Lab. Ask him about his device and what he needs. Don't guess them.

Say something like this:

> "I'm testing Deck Lab, not you. If something's hard to find or doesn't make sense, that's Deck Lab's fault, and it's exactly what I want to find out. I'll give you a few jobs to do. Please try them your own way, and say out loud what you're looking for and what you expect to happen. I'll mostly keep quiet and take notes, even when you're stuck, so I can see where it goes wrong. You can ask for help or skip a job at any time. Nothing you do will break anything, and we'll put back anything you don't want to keep."

## 2. Before the session

**Confirm these with User2** (ask him; don't fill them in from assumptions):

- Device he usually uses, model if he knows it: ______________________
- Browser he usually uses: ______________________
- Does he use Home Screen icons for websites, or want to? ______________________
- Glasses, text size, a stylus or anything else that helps him: ______________________
- Where he'd like to do it, and whether he's on Wi-Fi or mobile data: ______________________

Once his device is confirmed, cross out the device notes in section 3 that don't apply to it, and write his device's word (phone, tablet, computer) into the T1 prompt.

**Check access, without signing in as him:**

- His email is in his `decklab/config.json` profile, and the same address is allowed by the Cloudflare Access policy for decklab.example.com. If it's missing from either, he gets the Access page or "Your login has no Deck Lab profile".
- He can get to that mailbox on the device he'll use. The one-time code arrives by email.
- Test over the tunnel (https://decklab.example.com), not the home Wi-Fi address. At home there's no sign-in: anyone can pick any person on "Who are you?".
- Settings, Simulations, **Who can start them**: note what it's set to, since the Forge messages in T5 and T10 come from it.

**Agree cleanup with User2 before any edits.** Every save is real and goes into the database and the Activity page.

| Task | Option A: throwaway | Option B: a change he wants to keep | How to put it back |
|---|---|---|---|
| Deck change (T5) | A test deck in his space, status `idea`, with a title that says so, such as "Test deck (to delete)". Best made by User2 himself with **New deck** on Decks, as a warm-up. If Matt makes it beforehand (with his agreement): `python -m decklab.db deck new casual <slug> --space user2 --from FILE`, its text with an empty owned-vs-needed table, then `deck tables user2/casual/<slug> --reprice --apply`, since a deck without that table blocks his space's table refreshes | A real change he's been meaning to make to one of his decks | Afterwards, the deck's More, **Retire deck…** (only for a deck that isn't built). History keeps every revision. |
| Collection quantity (T6) | One fewer or one more of a card, then change it back | A count that really is wrong | Set the count back in the same sheet. Going to 0 means **Remove…** instead. |
| Wishlist (T7) | A card he doesn't want | A card he does want | Remove it from the Wishlist (it has an Undo). |
| Game (T8) | A practice record, cancelled with **Undo** before the 8-second toast runs out. He must stay on the page until he has tapped Undo: locking the phone or leaving the app while "Saving the game…" shows saves it at once, and it can't be undone | A game he really played (safer) | I found no way to delete a saved game on the page. Agree beforehand which it is. |

Agreed: ______________________________________________

**Note the app version.** Before the session, open Settings, **About Deck Lab** (only Matt can see this) and copy the `Server <commit>` value into the session header. Deck Lab has no version number: the git commit is the version. Also check there's no restart or reload warning.

**Have ready:**
- This checklist printed, a pen, and a clock or phone timer.
- The test deck, if you chose option A.
- His device charged.

## 3. Tasks

Read only the prompt. Let him choose the cards, decks, colours and numbers wherever he can. Don't look through his collection or decks beforehand to choose them for him. You can reorder, drop or reword the tasks to fit what he actually wants to do and what's working on the day. The tasks marked *(adapt)* depend most on that.

**T1. Sign in.** "Open Deck Lab on your [device] and get in."
Success: Deck Lab opens on Decks, with the "User2's decks" button. Afterwards, confirm it yourself: tap the avatar (his initial, top right) and the menu says "Signed in as User2". The top bar shows only his initial.
> **For Matt (don't read out):** sign-in is Cloudflare Access: his email, then a one-time code by email, which means switching to his mail app and back. The login lasts about a month. A Home Screen icon opens Deck Lab like an app: if he uses an iPhone or iPad with Safari, Share, Add to Home Screen; if Android with Chrome, the ⋮ menu, Add to Home screen or Install app; on a computer, skip the Home Screen part. Untested: signing in, then adding the Home Screen app, then coming back, has never been tried through decklab.example.com. A Home Screen app may keep its own cookies (iOS does), so he may have to enter a code again inside it. If that happens, record it, but it isn't his mistake.

**T2. Find one of your decks.** "Find one of your decks, any one you'd like to look at, and open it."
Success: that deck's own page is open.
> **For Matt (don't read out):** Decks (`#/library`) opens on "User2's decks". "All decks" also shows everyone else's. Filters are Format, Status, "Planned list availability" and a sort; on a phone they're behind **Filter**. If the deck is missing cards, tapping its tile opens its Cards tab filtered to Missing (the "Missing" chip is selected); "All" shows the rest. Unsupported: searching decks by name. Record it as an unmet need if he looks for one.

**T3. Read a card's rules.** (a) "Pick a card in that deck and read me what it does." (b) "Now think of a card you know you don't own, look it up, and tell me what it does." (Or name a card yourself and first ask him whether he owns it. Don't check his decks beforehand.)
Success: he reads out the card's rules text and explains it.
> **For Matt (don't read out):** tapping a card picture opens the viewer, and its **Text** button shows the Oracle text. For (a): the deck page's **Cards** tab, which may be showing only the missing cards (see T2). For (b): the only way is the Wishlist's "Find a card to add" search, or the editor's Add cards search. Unsupported: Scryfall rulings, a link to Scryfall, and a page just for looking up any card. Record these as unmet needs.

**T4. Owned versus missing.** "Could you put this deck together from your cards today? If not, how many cards are missing? Name one of them."
Prefer a deck of his that isn't built: for a built deck the banner answers it outright, so adapt the prompt (for example, a deck he hasn't put together yet).
Success: he gives the right count and names a card that really is missing (check it in the Cards tab's Missing filter; the banner names no cards).
> **For Matt (don't read out):** the banner under the title says "N missing, about A$X" (plus "· N held by other decks" when other decks hold copies; those count as missing), with **Show missing**; or "Ready to build: you have every card" (not built), "Every card is here" (built), "Ready once N cards arrive", or "Whether you have every card couldn't be worked out". If he opened the deck from its library tile, the Cards tab may already be filtered to Missing (see T2), so he may have seen the answer already. The Cards tab has All / Missing / On the way / In other decks chips, and missing cards are greyed out. "On the way" never applies to his space. There may be a "Planned list | Play-now list" switch, with an **i** button.

**T5. Change a deck and check it stuck.** *(adapt)* "In [the test deck / the deck you chose], swap one card for another, save it, and then show me that Deck Lab kept the change."
Success: a "Saved …" message, and the change is still there after he leaves the deck and comes back, or in its History.
> **For Matt (don't read out):** **Edit** on the deck page. A phone gets the Quick edit; a tablet or computer gets the full editor, with **Add cards**, **Save** and **▾ Save & view deck**. History is under the deck page's More. He sees no Played by, Sleeves or Deck box fields; that's expected. "Test this change" needs a Forge run; who can start one follows Settings, Simulations, **Who can start them** (checked in section 2). While it's admins only, only Matt can.

**T6. Update your collection.** *(adapt)* "Say you've found another copy of one of your cards, or lost one. Change your collection to match."
Success: the count shown for that card changes to the new number.
> **For Matt (don't read out):** Collection, **Find cards** (search "Name or rules text"), tap the card, **Edit copies**, then a printing's **Edit**, the Copies − / + buttons and **Save**. The Card list tab works too. Copies go from 1 to 9999; 0 means **Remove…**. A note about decks' tables being out of date is expected.

**T7. Add to your wishlist.** "Add a card you'd like to own to your wishlist."
Success: the "… is on your wishlist" message, and the card shows on the list.
> **For Matt (don't read out):** the Wishlist is under More. "Find a card to add" needs at least 2 letters, then **Add**. It searches by name only.

**T8. Record a game.** *(adapt)* "Record [a game you played recently / a practice game we'll cancel] with one of your decks."
Success: "Game saved." and the game shows under Played games. For a practice record, he cancels it with **Undo** instead, staying on the page until he has tapped it.
> **For Matt (don't read out):** Game log is under More, or on the deck page's More. One of the decks must be his; the opponent's deck can be anyone's, and that list is long. The other player defaults to "Opponent", which can be renamed under More details. The buttons are "User2 won", "Opponent won" and "Draw", and a "Saving the game…" toast with Undo shows for 8 seconds. If he locks the phone or leaves the app while it's showing, the game is saved at once and can't be undone. For a practice record, ask him to stay on the page until he has tapped Undo, or prefer option B (a real game).

**T9. Search with a filter.** "Find your creatures with vigilance. Now narrow that to a colour of your choice. Now just one mana value, you pick." Optional: "Now find creatures with vigilance that you don't own yet."
Success: he gets a grid of his creatures with vigilance in his chosen colour, then his chosen mana value, and judges whether they fit (an empty grid is fine when that's the right answer).
> **For Matt (don't read out):** Collection, Find cards: type `vigilance` in "Name or rules text", then set Type to Creature, plus Colour and Mana value. On a phone these are behind **Filters**. The text match is a substring, so cards that give vigilance show too, and he can judge those. Colour is one colour at a time, and mana value is an exact number, with no "3 or less". **Unsupported:** searching all cards by rules text or keyword (the editor and Wishlist searches match names only), so the optional step can't be done. Watch what he tries, record it as an unmet need, and then say it isn't there.

**T10. His own job.** *(adapt)* "Is there something you'd want Deck Lab for that we haven't done? Have a go at it."
Success: whatever he says it is. Write it down before he starts.
> **For Matt (don't read out):** if it's a Forge matchup, he'll see "Only Matt can start simulations right now. Saved results still show." That's expected while **Who can start them** is admins only (checked in section 2); record whether the wording makes sense to him. Shopping, Sleeves & boxes, Build decks and Settings are hidden from him.

**T11. Come back later.** "Close Deck Lab completely, then get back into it the way you would tomorrow." (Use the Home Screen icon if he added one.)
Success: he's back in, on Decks with the "User2's decks" button, with or without a new code. Afterwards, tap the avatar to confirm "Signed in as User2".
> **For Matt (don't read out):** within the month he should go straight in. Write down whether it asked for a code, and where (in the browser or the Home Screen app).

## 4. Observation rules

- **He tries first.** Before a task, ask "Where would you look?" or "What do you expect to happen?" Then stay quiet. Wait at least a minute of real searching before you offer help.
- **Think aloud.** If he goes quiet, ask "What are you looking for now?" Don't ask "Did you see the button?"
- **Help in steps**, and write down which step you gave: (1) "What would you try next?", (2) a hint about the area ("It's somewhere under More"), (3) showing him. Showing him means the task counts as **with help**.
- **Outcome codes:** **U** unaided, **H** with help (write down which step), **N** not completed (he gave up, or you stopped it).
- **Write what you saw separately from what he said.** On each task's "Observed" line in section 5, tag each item:
  - `[hesitation]`: a pause of more than about 10 seconds, or "hmm"
  - `[wrong turn]`: he opened the wrong page or used the wrong control
  - `[wording]`: a label or message he misread or asked about
  - `[error]`: an error message, or something broke
  - `[device]`: zoom, a mis-tap, or the keyboard getting in the way
  Record each item with where it happened (page, control, the exact message).
- **His words:** quote them exactly, in quotation marks. Mark a paraphrase **(paraphrase)**.
- **Don't defend Deck Lab** or explain how it's meant to work until the task is over.

## 5. Notes

**Session (record once):** Date ________ · Device and browser ________________ · Home Screen app used? ____ · App version (Settings, About Deck Lab, `Server`) ________ · Over decklab.example.com or home Wi-Fi ________ · Cleanup agreed (section 2) ____

One block per task, with room to write under each line. Leave every result blank until it has been observed. Start each task on its own half-page if you can.

**T1 Sign in: opens on Decks with "User2's decks"; avatar menu says "Signed in as User2"**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T2 Find a deck: its deck page is open**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T3a Card in a deck: reads the rules text**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T3b Card not owned: reads the rules text**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T4 Owned vs missing: right count, names one (checked in the Missing filter)**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T5 Deck change: saved, still there afterwards**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T6 Collection count: new number shows**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T7 Wishlist: message, and the card listed**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T8 Game: "Game saved." and listed (or undone)**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T9 Vigilance + colour + mana value: right grid**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T9 optional, unowned vigilance: unmet need expected**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T10 His own job: ________**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**T11 Come back later: back in on Decks; avatar menu says "Signed in as User2"**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**Extra task: ________**

- Outcome (U / H + help step / N): ____
- Observed (tagged, with where):<br><br>
- Help needed:<br><br>
- His words (quote, or labelled paraphrase):<br><br>
- Impact (blocks / needs help / minor friction): ____
- Follow-up (story id, new story, or none): ____

**Unmet needs he mentioned or ran into** (features that aren't there): ____________________________

**Praise and what worked** (keep these, so they aren't lost in later changes): ____________________________

## 6. Closing questions

Ask these, and write down his answers in his words:

1. "What was confusing, or harder than it should have been?"
2. "What felt easy?"
3. "What did you expect to find that wasn't there?"
4. "Would you use this on your own, without me there? For what?"
5. "Anything else you'd change?"

Thank him, put back whatever the cleanup agreement says, and check that it's been put back.

His answers come from one participant. Weigh them as one person's experience, not as what every member will do, and look for the same problem in other evidence before redesigning around it.

## 7. After the session

- **Prioritise by impact:** first "blocks", then "needs help", then "minor friction". Within each group, put problems that hit several tasks or pages first.
- **Link each problem** to an existing story in [stories.md](stories.md) (search for the page or feature) or write a new `missing` story under the `space-members` persona. Unmet needs become stories too, even if the answer is `not wanted`. Keep praise as evidence alongside the stories it supports.
- **Add actionable work to [TODO.md](../../TODO.md)** as rows pointing to those stories. E11-S28 stays open until the session and this review are done.
- **Check assumptions:** anything User2 confirms or corrects about the `space-members` persona in [personas.md](personas.md) becomes a dated fact, as the README's "Using and keeping it up to date" says.
- **Privacy.** This folder is committed and the members can read it. Under privacy by default, User2's data is his:
  - Never record his cards, deck names or lists, games, opponents or wishlist entries in anything committed. Write "a deck of his", "a card he owns" or "his chosen colour" instead.
  - Ask him first before sharing any example in his words, or leave it out.
  - Settings' Visits page lists the titles of decks he opened. Don't copy them.
  - Keep the filled-in sheet itself on paper or outside the repo. Commit only a redacted summary of the findings (problems, where they happened, impact, quotes he agreed to), dated, next to this file or in the stories it changes.
