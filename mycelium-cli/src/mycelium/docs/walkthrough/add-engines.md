# 4. Add the room's engines

Engines are helpers that run on the hub. Two of them are behind choices the app
offers on a task. The **conductor** runs **Review**, a flow where one agent
does the work and another checks it. The **aligner** runs **Settle**, a
negotiation that helps agents who disagree settle on one answer. A new room has
neither, so add them now.

Open **Members**, press **Add** and choose **Engine**. Pick **conductor** and
press **Add to room**. Do the same for **aligner**. Keep the handles the dialog
fills in, `conductor` and `aligner`, because Review and Settle call the engines
by those names.

Engines do nothing until a task asks for them. They only need a model when they
have to think, which the aligner does and the conductor never does. If you
skipped the model in step 1, add it in **Settings → Model**. See
[Models](#models).
