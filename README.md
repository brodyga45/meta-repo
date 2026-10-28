# meta-repo

A small CLI that renders a directory tree by executing embedded Python blocks.
All blocks share a `memory` variable. Python 3.11+, no runtime dependencies.

## Why a metarepository?

A metarepository is source for a repository: its files are **meta-text** that
produces ordinary text. It lets the source follow **logical relationships**
rather than the formats of generated files: define a shared entity once, keep
its related configuration together, and render its different representations
wherever JSON, YAML, or other files need them. Python provides objects,
functions, loops, and composition; directory priorities and shared `memory`
make definitions available to later consumers. The output stays ordinary files.

This organization goes hand in hand with **verifiable refactoring of text**.
You can substantially reorganize a metarepository, extract entities and
abstractions, and remove duplication, then build the old and new versions and
verify that they produce exactly the same repository: the same paths and
output bytes. Together, logical organization and reproducibility let you
improve how a repository is expressed while checking that its result is
unchanged, separately from intentional changes in generated behavior. This
equivalence check is why rendering should avoid external effects and implicit inputs.

## Install

```sh
pipx install git+https://github.com/brodyga45/meta-repo.git
```

Or install from a local clone:

```sh
python3 -m pip install .
```

## Run

```sh
meta-repo SOURCE DESTINATION
meta-repo SOURCE DESTINATION --descending
meta-repo --help
```

`DESTINATION` must be a new directory outside `SOURCE`. The source tree is
unchanged, and the output tree is published only after processing succeeds.
You can also run the CLI as `python3 -m meta_repo`.

## Meta-files

A meta-file starts with exactly this first-line format:

```text
!#meta[A][B][n]
```

`A` and `B` are opening and closing delimiters; `n` is an integer priority.
The delimiters cannot contain square brackets or line breaks. They must be
nonempty, distinct, and neither can be a prefix of the other.

Delimiters are chosen per file, so meta-text can coexist with XML, JSON, YAML,
any programming language, or other text. Choose markers that do not conflict
with that particular file's contents; even files of the same format can use
different delimiters when convenient.

For example, `00-init.txt`:

```text
!#meta[<py>][</py>][0]
<py>
memory["name"] = "world"
memory["items"] = ["alpha", "beta"]
return ""
</py>
```

And `10-report.txt`:

```text
!#meta[<py>][</py>][10]
Hello, <py>return memory["name"]</py>!
<py>
return "\n".join(f"- {item}" for item in memory["items"])
</py>
```

The second output file contains:

```text
Hello, world!
- alpha
- beta
```

Each block must `return` a string. That string replaces the entire block,
including its delimiters. The meta-file header is removed as well.
A first line that does not match the header format is ordinary content.

## Directory parameters

A file named exactly `!#meta` can specify parameters for its directory:

```text
[<py>][</py>][5]
```

Files without their own header use these delimiters and priority. A file's
own header overrides all directory parameters.

Alternatively, `[5]` sets only the priority; files without a header remain
ordinary files. Missing or unrecognized directory parameters provide no
defaults. Parameters apply only to immediate files, never to child directories.
All files named `!#meta` are omitted from the output.

## Excluding files and directories with DELETE

To execute a meta-file but omit it from the output, put exactly `ADELETEB`
on its second line, using the delimiters from its own first-line header:

```text
!#meta[<py>][</py>][0]
<py>DELETE</py>
<py>
memory["service"] = {"name": "api", "port": 8080}
return ""
</py>
```

The remaining body executes normally and can prepare `memory` for later files.
The header and DELETE line are metadata; neither is executed as Python.

To omit an entire directory, put the directive on the second line of its
`!#meta` file, using that file's directory parameters:

```text
[<py>][</py>][0]
<py>DELETE</py>
```

All files and descendants still execute in the usual priority order, sharing
`memory`, but the directory and everything inside it are absent from the output.
Errors inside excluded content still fail the build. A DELETE directive in the
source root's `!#meta` produces an empty destination directory after execution.
The source repository is always unchanged.

For example, keep developer-facing entities and parameters in `Control/`:

```text
source/
  Control/
    !#meta             # [<py>][</py>][0], then <py>DELETE</py>
    service.py         # Python block storing memory["service"]
  configuration/
    !#meta             # [<py>][</py>][10]
    service.json       # renders memory["service"] as JSON
    service.yaml       # renders the same entity as YAML
```

With ascending priorities, `Control/` runs before `configuration/`. Its files
can describe entities in whatever representation is convenient for the author,
then store them in shared memory for other files to use. Only `configuration/`
appears in the output. In `service.py`, use a delimited block such as
`<py>memory["service"] = {"name": "api", "port": 8080}; return ""</py>`;
the filename extension itself does not execute Python.

The directive is case-sensitive, with no extra spaces or text, and must occupy
the entire second line. LF and CRLF line endings are supported, including a
second line without a final newline. It requires a file's own valid meta-header
or full directory parameters `[A][B][n]`; priority-only `[n]` does not define
delimiters. Directory service files otherwise keep their single-line format:
only the optional DELETE line may follow the parameters. The directive is not
inherited by child directories or recognized in ordinary files, later lines,
or generated output.

## Execution order

At each level, files run first, followed by child directories. Each child
directory finishes before the next sibling starts. Files and directories
are sorted separately:

1. Lower priority first by default; higher priority first with `--descending`.
2. Missing priority always comes last, in either direction.
3. Equal priorities are ordered lexicographically by name.

A directory's priority comes from its own `!#meta` file. An absent directory
configuration does not prevent traversal.

For example, keep definitions and generated configurations in sibling directories:

```text
source/
  entities/
    !#meta             # [0]
    service.txt        # own meta-header; stores memory["service"]
  configuration/
    !#meta             # [<py>][</py>][10]
    service.json
    service.yaml
```

With the default ascending order, `entities/` finishes before `configuration/`.
Its meta-file might define `memory["service"] = {"name": "api", "port": 8080}`
and return `""`. The later files render this same value differently, using
`json.dumps` for JSON and appropriate text formatting for YAML. Directory
priorities order siblings; they never move a child directory ahead of files
in its parent. In particular, root-level consumers run before all child directories.

## Python and memory

`memory` starts as `{}` and is shared across all blocks and files. It may
contain JSON-style data, functions, instances, iterators, or any other Python
objects. A block may also replace `memory` entirely.

Blocks execute through `exec` inside a function with `global memory`.
Use `return` for output and `memory` for cross-block state. Ordinary local
variables do not carry over to the next block. Common indentation is removed
with `textwrap.dedent`. Python runs with the current process's permissions;
this is not a sandbox. Process only repositories whose code you trust.

Nested blocks run inside out: the inner result becomes part of the outer
Python source before it is compiled. Use `repr` when generating a string literal:

```text
<py>return "Nested: " + <py>return repr(memory["name"])</py></py>
```

Delimiters are reserved even inside Python string literals and comments.
Choose delimiters that do not otherwise occur in the code. Generated output
is never parsed again.

Meta-files use UTF-8. Ordinary files are copied byte for byte, including
binary files; file modes are preserved. Symbolic links are copied without
following or rendering their contents. Processing errors report the source
file and block location and exit with a nonzero status.

## Reproducible repositories

Treat rendering as a reproducible transformation of the source repository and
explicit initial memory into an output repository. Prefer pure functions that
produce text. Keep deliberate cross-file state in `memory`, and make its
initialization and execution order explicit. The same inputs and supported
Python environment should produce the same output bytes.

For a representation-only refactor, build both revisions into separate new
directories and compare them:

```sh
meta-repo source-before output-before
meta-repo source-after output-after
git diff --no-index --exit-code output-before output-after
```

No diff and exit status `0` establish output equivalence for those inputs.
Keep the same Python environment, initial memory, and priority direction.
Compare the complete output tree, not only selected files. If a refactor is
intended to change generated behavior, review that output diff explicitly
instead of expecting equivalence. With multiple supported input configurations,
repeat the comparison for each one; one comparison is not a proof for every input.

- Use loops, comprehensions, functions, and objects to describe and format data.
- Do not derive output from environment variables, the current directory,
  wall-clock time, randomness, network responses, or machine-specific paths.
- Do not hardcode filesystem writes, shell commands, deployments, or other
  external side effects into blocks. Return text and let `meta-repo` write it.
- Avoid emitting object representations containing memory addresses; render
  explicit fields instead.

### Reading repository data

Read-only access to source files inside the repository is a normal, supported
authoring pattern. A parent-level meta-file can load a directory of JSON files
into `memory` for later consumers. This can be simpler than adding a meta-header
and initialization code to every data file:

```python
from pathlib import Path
import json

data_directory = Path(__file__).parent / "data"
memory["records"] = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in data_directory.glob("*.json")
}
return ""
```

These files are explicit source inputs. They may live in child directories;
reading their original contents does not require waiting for those directories
to be rendered. Resolve paths relative to the current source file and use an
explicit encoding. Keep the inputs unchanged throughout a build.

Blocks should only read source data, never create, modify, or delete files.
Return output text and leave all output writes to `meta-repo`. Do not read mutable
files outside the repository or depend on the partially generated output tree.
These are authoring conventions, not restrictions enforced by a sandbox.

## Python API

```python
from meta_repo import process_repository

final_memory = process_repository(
    "source",
    "output",
    ascending=True,
    memory={"name": "Python"},
)
```

The function returns the final shared memory. Omit `memory` for a fresh `{}`;
an explicit `memory=None` starts with `None`.
