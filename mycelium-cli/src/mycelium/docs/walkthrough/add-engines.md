# 4. Add the room's engines

Engines are helpers that run on the hub. Two of them are behind choices the app
offers on a task: the **conductor** runs **Review**, a flow where one agent
does the work and another checks it, and the **aligner** runs **Settle**, a
negotiation where agents that disagree settle on one answer. A new room has neither, so add them now.

Open **Members**, press **Add**, choose **Engine**, pick **conductor**, and
press **Add to room**. Do the same for **aligner**. Keep the handles the dialog
fills in (`conductor` and `aligner`): Review and Settle call the engines by
those names.

They do nothing until a task asks for them, and they need a model only when
they think: the conductor never does, the aligner does. If you skipped the
model in step 1, add it in **Settings → Model**. See [Models](#models).
