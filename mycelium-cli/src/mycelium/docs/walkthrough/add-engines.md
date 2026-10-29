# 4. Add the room's engines

Engines are helpers that run on the hub. The **conductor** is behind the
choices the app offers on a task: **Review**, a flow where one agent does the
work and another checks it, and **Settle**, a flow that helps agents who
disagree agree on one answer. A new room doesn't have it, so add it now.

Open **Members**, press **Add** and choose **Engine**. Pick **conductor** and
press **Add to room**. Keep the handle the dialog fills in, `conductor`,
because Review and Settle call the engine by that name.

Engines do nothing until a task asks for them. The conductor never needs a
model, since the agents taking part do the thinking. Other engines, such as
personas and the synthesizer, do. If you skipped the model in step 1, add it in
**Settings → Model**. See [Models](#models).
