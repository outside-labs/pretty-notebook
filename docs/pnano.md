# pnano (unsupported)

> [!WARNING]
> **0.9 status:** the `pnano.app` and `ppnbp.app` protocol handlers are experimental and unsupported. Do not install or register them as part of a supported 0.9 setup. Their scripts do not safely validate URL input.

**pnano** ("protocol-ed nano") is ultimately a non-nano name to call some monkey patch that handles for the (unused) URI protocol namespace of ```nano://``` to open files directly to the nano text editor. (e.g. as written for macos, when clicking ```nano:///Users/alice/hello.py```, ```hello.py``` will be opened in ```nano``` to the second (to the right) pane in a split-pane iTerm2 window (closed/->reopened).

Why? 
- (a) vim has a [wiki](https://vimwiki.github.io/) system.
- (b) emacs has a [wiki](https://github.com/caiorss/org-wiki) system.
- (c) [nano](https://www.nano-editor.org/) *doesn't* have a wiki system.

... 
- Modern terminal emulators can handle clickable links (e.g. [GNOME](https://unix.stackexchange.com/questions/112267/create-clickable-links-in-terminal#437585)). 
- [Rich](https://github.com/willmcgugan/rich) is a Python library that can handle rendering [markup links](https://rich.readthedocs.io/en/latest/markup.html?highlight=link#links) to terminals that support them. 
- [iTerm2](https://iterm2.com/) is a terminal emulator for macos that can handle clicks to links, and has an [Applescript API](https://iterm2.com/documentation-scripting.html) -> ... 
- iTerm (and the like) will open clicked links to the default Application that handles a protocol :
- (e.g. ```https``` -> https://github.com/,  URL, to default browser)
- (e.g. ```file``` -> ```file:///Users/alice/hello.txt```, [file URI scheme](https://en.wikipedia.org/wiki/File_URI_scheme), to default app) 
- ... 

--- 

a wiki-linked .md file (e.g. 

```sh
% cat notebook/INDEX.md

mocs:
- [[SCHOOL]]
- [[PROJECTS]]
- [[WORK]]
- [[LIFE]]
```
), 

With [pnbp](https://github.com/wispsy/pretty-notebook/blob/main/docs/pnbp.md),

```sh
% pnbp pprint -n index
# ...
```

on ```pnbp pprint -n mynote```, before rich [Markdown](https://rich.readthedocs.io/en/stable/markdown.html) handling, every internal **\[\[link\]\]** is converted to **\[link\]\(pnbp:///path/to/notebook/mynote.md\)** and a frame is added to the pretty print-out w/ : 

MENU : 
--->: refresh - re-print the current note (e.g. on update)
nano: mynote - split-pane and open the currently printed (`-n`) note to ```nano```
nano: new note - split-pane to a new (incremented, default name) .md note on path

if the markdown wasn't being marked-up and rendered, it would look like this e.g. :

```sh
% pnbp pprint -n "INDEX.md"

MENU :
--->: [refresh](pnbp:///Users/alice/notebook/INDEX.md)
nano: [INDEX](nano:///Users/alice/notebook/INDEX.md)
nano: [new note](nano:///Users/alice/notebook/new2.md)

--- 

mocs:
- [SCHOOL](pnbp:///Users/alice/notebook/INDEX.md)
- [PROJECTS](pnbp:///Users/alice/notebook/PROJECTS.md)
- [WORK](pnbp:///Users/alice/notebook/WORK.md)
- [LIFE](pnbp:///Users/alice/notebook/LIFE.md)


--- 

MENU :
--->: [refresh](pnbp:///Users/alice/notebook/INDEX.md)
nano: [INDEX](nano:///Users/alice/notebook/INDEX.md)
nano: [new note](nano:///Users/alice/notebook/new2.md)

% # ...
```

Every internal link (e.g. ```[[LINK]]```) within the content of the current pretty printed note (e.g. as `LINK`) being redirected to ```pnbp://```, on click, will call ```ppnbp.app```, -> iTerm's current window (the one you clicked in) is instructed to ```clear ``` (fully) and then ```pnano pprint -n "LINK.md"```. This "refreshes" the window to the exclusive content of the newly clicked note (so that any scrolling instance only holds the current note context).

--- 

All in, you can achieve something to the effect of using a split-pane markdown editor in the terminal; viewing (and moving through the wiki-link .md system) with the rendered content on the left: 

![left](https://github.com/wispsy/pretty-notebook/blob/main/docs/pnano_left.png)

while making edits in nano on the right:

![right](https://github.com/wispsy/pretty-notebook/blob/main/docs/pnano_right.png)


---

The macOS URL-handler setup is intentionally omitted while these apps are unsupported.
