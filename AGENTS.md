# Gradescope CLI

We are building a CLI for gradescope. We want to be able to sign into
gradescope using GRADESCOPE account parameters. There should be a TUI
interface to browse assignments and view due dates, as well as some 
way to submit files to gradescope (usually code).
I should be able to track autograder progress, and leaderboard stats.
Additionally to a TUI, we want a CLI to just submit to gradescope, 
interact with the assignments.

Roughly follow a planned structure, we will be trying to keep commit 
sane and readable.

## Dev tools and style
ruff for formatting, mypy for type checking. Write type-hinted python 
code. Write tests if needed. 
