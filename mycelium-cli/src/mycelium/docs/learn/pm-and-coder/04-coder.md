# Bring in the coder

The coder is a second agent in the same room. The easiest way to start one is
from the app: open the room's members panel, choose **Add**, pick a coding
agent on your machine, and name it `coder`. It starts in the folder you
choose, which should be a checkout of the repository you're working on.

Your machine asks before it starts anything the app asked for, so say yes
there.

The coder doesn't need much of a brief. Something like this is enough:

```bash
mycelium memory set agents/coder/notes --body "You're the coder. @pm holds the task and reviews your work. Do one piece at a time, and say what you did and how you checked it."
```
