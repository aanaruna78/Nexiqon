# Quickstart

This takes you from an empty organization to an assistant that answers questions on your website,
with citations. It takes about fifteen minutes.

**Where things are in Studio:**

- **The home page is the assistant.** Everyone in your organization lands there: they pick an
  assistant, ask, and get answers with their sources. Past chats are listed on the left.
- **Admin** (top right; for owners, admins and editors) is where you build and run assistants
  and administer the organization. The steps below all happen there, and **Admin → Get started**
  walks you through the same four steps.
- **Settings** (the account menu) holds your own preferences: theme and language.

## 1. Choose what your assistant is for

In Studio, open **Domain Packs**. A Domain Pack holds an assistant's field knowledge: the words your
users use, what they ask for (intents), the instructions, the guardrails and the workflow.

- Start from a ready-made pack, such as **SaaS Knowledge Assistant** for product questions,
  account lookups and handover to support.
- Or create a blank pack and fill it in later ([Domain Packs](domain-packs.md)).

## 2. Add what it answers from

Open **Knowledge → New collection**. A collection groups related content, with one model, one
sensitivity level and one set of access rules.

- **Upload files:** PDF, Word, Markdown, HTML, text, CSV or JSON. Every file is virus-scanned
  first.
- **Or connect a source:**
    - **Website crawler:** your documentation site;
    - **S3 bucket**;
    - **Git repository**.

  Choose a sync schedule; only changed content is processed again.

Documents appear as **Ready** when they are indexed. If one **needs attention**, its row says why
and what to do.

## 3. Create the assistant and ask it something

Open **Assistants → New assistant**:

1. Give it a name and pick the pack and the collections.
2. Choose **Create and test**. It goes live in the **dev** environment at once.
3. Ask a question in the **Test** tab.

Each answer cites its sources. Choose **Inspect** to open the **Answer Inspector**: what was
understood, which passages were found and used, which checks ran, and what it cost.

If the assistant cannot back an answer with your documents, it says so rather than guessing. To
correct an answer, choose **Fix**:

- teach the right answer;
- take an outdated page out of answers;
- save the question to a test set, so later versions are checked against it.

## 4. Put it on your website

On the assistant's **Widget** tab:

1. List the websites allowed to use it, for example `https://www.example.com`.
2. Choose **Create widget key**, and copy the embed code. It looks like this:

```html
<script type="module" src="https://<studio>/widget/nexiqon-chat.js"></script>
<nexiqon-chat agent="support" api-base="https://<gateway>" api-key="nxq_..." locale="en"></nexiqon-chat>
```

The widget key is safe on public pages: it works only from the websites you listed, only for this
assistant, and each visitor sees only their own conversations. The widget is under 20 KB, follows
your pack's colours and words, works in light and dark mode and right-to-left languages, and
meets WCAG 2.2 AA.

## Next steps

- **Release safely.** Changes are saved as drafts and released as versions. With **Safe publish**
  (the assistant's **Quality** tab), a version goes live only after it passes its test set.
- **Ask it yourself.** Open the home page, pick the assistant and ask. Admins can open
  **Inspect** on any answer.
- **Review conversations.** **Conversations** shows what people asked. Handed-over conversations
  wait in a queue for your team.
- **Watch quality and cost.** **Insights** shows the answer rate, content gaps (questions to write
  documentation for) and monthly budgets.
- **Connect your systems.** **Actions & integrations** imports an OpenAPI description as tools.
  Tools that change data always ask the user to confirm.
- **Call the API from your servers** with a server key ([API reference](api/index.md)).
