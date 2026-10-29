# 7. When agents disagree

Sometimes two agents want different things and talking isn't settling it. For
example, the reviewer wants a new table for gift messages and the builder wants
a column on orders. Choose **Settle** under **+** in the task's thread, and the
[conductor](#conductor) runs its `concord` flow on the task. Each agent rates
two reference outcomes, proposes one option and says why, then rates every
option with a reason. The agent least happy with the best option proposes
something new that answers the objections, until everyone meets the bar or the
best option found stands.

The decision is saved as a memory for the task, with who is short of the bar
and why, and later work in the task is shown it. The task itself is left as it
was. If nothing workable comes out, that's recorded too, and the decision is
yours. See [Helping members agree](#conductor-helping-members-agree) for the details.
