# Telegram UX Improvement Plan

This plan outlines the enhancements to the Telegram bot user experience based on user design choices.

---

## 1. Real-Time Batch Progress Stepper
When you send one or multiple words at once, the bot will post a **single, unified progress message** that updates in real-time as the worker advances through the sub-steps:

### Step-by-Step Progress States
For each word in the batch, the bot displays its active status using emoji steppers:
* 💤 `In queue...` — Job is waiting in the Redis/ARQ queue.
* 🧠 `LLM: Generating meaning & examples...` — Worker is calling Gemini.
* 🔊 `TTS: Synthesizing voice audio...` — Worker is calling Azure Speech to generate MP3 clips.
* 📥 `Anki: Saving card & media...` — Worker is calling AnkiConnect to upsert the card.
* ✅ `Added successfully!` — Card created and synced.
* ♻️ `Rewritten!` — Existing card updated.
* ❌ `Failed: <Error details>` — Processing failed.

### Real-Time Update Example (Intermediate State)
```markdown
⏳ **Processing 3 words...**

* `repremend` — 🔊 TTS: Synthesizing voice audio...
* `dejavu` — 🧠 LLM: Generating meaning & examples...
* `dominion` — 💤 In queue...
```

---

## 2. Rich Card Preview
Once all words in the batch finish processing, the progress message is replaced in-place by a rich, formatted Markdown card preview:

```markdown
✅ **Batch Processing Complete**

---
**1. repremend** (noun)
* **Meaning**: දෝෂාරෝපණය කරනවා / අවවාද කරනවා
* **Definition**: A formal expression of disapproval.
* **Examples**:
  1. *He received a severe reprimand for his behavior.*
  2. *The officer was given a written reprimand.*

---
**2. dejavu** (noun)
* **Meaning**: පෙර දුටු බවක් දැනීම
* **Definition**: A feeling of having already experienced the present situation.
* **Examples**:
  1. *I had a strong sense of deja vu when I entered the room.*
```

---

## 3. Inline Action Buttons
Each completed card in the summary will have inline buttons attached underneath it, enabling direct modification from Telegram:

* `[ ✏️ Edit Meaning ]`
* `[ 🔄 Regen Examples ]`
* `[ 🗑️ Delete Card ]`

---

## 4. Interaction Flows

### A. Edit Meaning (Reply-to-edit flow)
1. User clicks `✏️ Edit Meaning`.
2. The bot enters an input-awaiting state for that card and edits the status message in-place: *"Reply to this message with the new Sinhala meaning..."*
3. User replies with the text of the new meaning.
4. The bot:
   * Validates the input.
   * Updates the `Sinhala Meaning` field in the Anki database via AnkiConnect.
   * Triggers a background sync.
   * Quietly updates the original card preview message in-place with the new meaning, restoring the action buttons.

### B. Regenerate Examples
1. User clicks `🔄 Regen Examples`.
2. The bot edits the message in-place to show `⏳ Regenerating examples...`.
3. The worker:
   * Queries Gemini for new examples.
   * Synthesizes new audio files using Azure Speech (region: `eastus2`).
   * Updates the card and media via AnkiConnect.
   * Triggers a background sync.
4. The bot quietly updates the preview message in-place.

### C. Delete Card
1. User clicks `🗑️ Delete Card`.
2. The bot deletes the note from Anki via AnkiConnect and triggers a background sync.
3. The bot quietly updates the message in-place to:
   ```markdown
   🗑️ **Deleted**: `repremend`
   ```
   (All action buttons are removed).
