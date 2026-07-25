# PDF Summarizer (TAMU AI)

Reads a PDF and writes a three-paragraph summary — methods, data, results — to a
`.txt` file next to it. Summarization runs on Texas A&M's LLM gateway
(`chat-api.tamu.ai`), which is free to TAMU affiliates with a NetID.

## Install

```bash
./install.sh
```

Copies the command into `~/.local/bin`, installs the Finder Quick Action into
`~/Library/Services`, refreshes the Services menu, and warns about anything
missing. Safe to re-run — that is also how you push your local edits to the
installed copies.

You need:

- **macOS** — the Quick Action, notifications, and TextEdit integration are all
  macOS-specific.
- **A TAMU AI API key**, from chat.tamu.ai → Settings → API Key. Put it in
  `~/.zshenv`, **not** `~/.zprofile` (see [Troubleshooting](#troubleshooting)):

  ```bash
  echo "export TAMU_AI_API_KEY='sk-...'" >> ~/.zshenv && chmod 600 ~/.zshenv
  ```

- **Python 3 with `requests` and `pymupdf`** (`pdfplumber` also works for text
  extraction). The wrapper searches miniconda, anaconda, Homebrew, `/usr/local`,
  and `PATH`, picking the first that can import them. Force a specific one with
  `SUMMARIZE_PDF_PYTHON=/path/to/python3`.
- **`tamu_ai.py`**, the TAMU AI gateway client. `summarize_pdf.py` looks for it
  beside itself first, then at `~/.claude/skills/tamu-ai/scripts/tamu_ai.py`.
  Drop a copy in this folder to make the checkout self-contained.

### What's in this repo

| File | Purpose |
|---|---|
| `summarize_pdf.py` | The summarizer. |
| `summarize-pdf` | zsh wrapper: finds Python, notifies, logs. |
| `Summarize PDF with TAMU AI.workflow` | The Finder Quick Action bundle. |
| `install.sh` | Puts all three where macOS expects them. |
| `tamu_ai.py` | TAMU AI gateway client, bundled so a clone works standalone. |
| `LICENSE` | MIT. |

## Installed layout

| Path | What it is |
|---|---|
| `summarize_pdf.py` | The script. **Working copy — edit this one.** |
| `~/.local/bin/summarize_pdf.py` | Installed copy. This is what actually runs. |
| `~/.local/bin/summarize-pdf` | zsh wrapper — the `summarize-pdf` command. Pins the right Python, sends notifications, logs. |
| `~/.local/bin/.summarize-pdf.backup` | Spare copy of the wrapper, for the recovery below. |
| `~/Library/Services/Summarize PDF with TAMU AI.workflow` | The Finder Quick Action. |
| `~/Library/Logs/summarize-pdf.log` | Run log — check here when a Finder run fails silently. |

This folder can live anywhere — move it, rename it, archive it. Nothing that runs
depends on its location. The two files in `~/.local/bin`, however, must stay
together in the same directory: the wrapper looks for the script beside itself.

## After you edit the script

The working copy and the installed copy are independent. Editing
`summarize_pdf.py` in this folder does **not** change what the CLI or the Quick
Action run. Re-run the installer to push your changes:

```bash
./install.sh
```

That handles both files and the Quick Action, and avoids the filename hazard
below. To sync just the script by hand:

```bash
cp summarize_pdf.py ~/.local/bin/summarize_pdf.py
```

Confirm it took:

```bash
diff summarize_pdf.py ~/.local/bin/summarize_pdf.py && echo "in sync"
```

> ### Copy onto `summarize_pdf.py` — never onto `summarize-pdf`
>
> Two different files, two keystrokes apart:
>
> - **`summarize_pdf.py`** — underscore, `.py` extension. The Python script.
>   **This is the copy target.**
> - **`summarize-pdf`** — hyphen, no extension. The zsh wrapper; the command you
>   type. You never need to copy anything onto this.
>
> The filename is identical on both sides of a correct copy — that is the check.
> Overwriting the wrapper with Python code breaks both the `summarize-pdf`
> command and the Finder action, with errors like
> `summarize-pdf:15: command not found: import` — zsh trying to run Python.
>
> Recovery, if that happens:
>
> ```bash
> cp ~/.local/bin/.summarize-pdf.backup ~/.local/bin/summarize-pdf
> ```

## A note on the API key

No script in this repo contains the key — it is read from `TAMU_AI_API_KEY` at
runtime, and `.gitignore` keeps papers and generated summaries out of version
control. 

## Usage

### Terminal

```bash
summarize-pdf paper.pdf
```

Takes several files at once:

```bash
summarize-pdf *.pdf
```

The wrapper forwards flags, so `summarize-pdf -m "protected.Claude Opus 4.8"
paper.pdf` works. To call the script directly, pick an interpreter that has the
libraries — a bare `python3` often is not one:

```bash
~/miniconda3/bin/python3 summarize_pdf.py paper.pdf -o notes.txt
```

| Flag | Meaning |
|---|---|
| `-o`, `--output` | Output path. Default: `<pdf name>_summary.txt` beside the PDF. |
| `-m`, `--model` | TAMU AI model id. Default: `protected.Claude Sonnet 4.6`. |
| `--no-open` | Skip opening the summary in TextEdit. |

Flags also pass through the `summarize-pdf` command:

```bash
summarize-pdf --no-open *.pdf
```

Other reasonable models: `protected.Claude Opus 4.8` for harder papers,
`protected.gpt-5.4-mini` for speed. Ids contain spaces, so quote them.

### Finder

Right-click a PDF → **Quick Actions → Summarize PDF with TAMU AI**. Works on a
multi-file selection. A notification appears when the run finishes.

When each summary is written it opens automatically in **TextEdit**. On a
multi-file selection that means one TextEdit window per PDF — pass `--no-open`
from the command line for large batches.

The action is already installed. The next section is for rebuilding it — on
another Mac, or after changing how it is invoked.

## Making it a Finder Quick Action

1. Open **Automator** (Applications, or Spotlight → "Automator").
2. **File → New**, choose **Quick Action**.
3. At the top of the workflow pane, set:
   - *Workflow receives current* → **PDF files**
   - *in* → **Finder**
4. In the actions list on the left, search for **Run Shell Script** and drag it
   into the empty workflow area on the right.
5. In that action, set:
   - *Shell* → `/bin/zsh`
   - *Pass input* → **as arguments** ← easy to miss, and it fails without it
6. Replace the script body with exactly this:

   ```zsh
   "$HOME/.local/bin/summarize-pdf" "$@"
   ```

7. **File → Save**, name it `Summarize PDF with TAMU AI`. Automator saves it to
   `~/Library/Services/`.

Right-click any PDF in Finder to test. If it does not appear, run:

```bash
/System/Library/CoreServices/pbs -update
```

Finder picks up new Services only after the pasteboard server rescans. If it is
still missing, check **System Settings → Keyboard → Keyboard Shortcuts →
Services** and confirm the action is enabled.

### Testing a Quick Action without clicking

Faster than right-clicking through Finder, and it shows you the errors:

```bash
automator -i /path/to/paper.pdf "$HOME/Library/Services/Summarize PDF with TAMU AI.workflow"
```

## Output

The summary opens in TextEdit as soon as it is written (suppress with
`--no-open`). If TextEdit cannot be launched, the run still succeeds — the file
is already saved, and a warning goes to the log.

Two header lines naming the source PDF and the model, then three unlabeled
paragraphs:

1. **Methods** — design, models, estimation strategy, identifying assumptions.
2. **Data** — sources, variables, time period, coverage, sample size.
3. **Results** — main quantitative findings with numbers, plus stated caveats.

The script warns on stderr if the model returns other than three paragraphs, and
strips markdown artifacts (`\$`, `**bold**`) that would otherwise show up as
literal characters in a plain-text file.

Papers over 300,000 characters are truncated from the middle, keeping the front
(abstract, methods, data) and the back (results, conclusions).

## Troubleshooting

**"No TAMU AI API key found" — but `echo $TAMU_AI_API_KEY` works in my terminal.**
The key is in a file only *login* shells read. Terminal opens a login shell;
Automator and most scripts do not. `~/.zshenv` is sourced by every zsh
invocation, so the export belongs there:

```bash
grep -q TAMU_AI_API_KEY ~/.zshenv && echo "correct file" || echo "move it to ~/.zshenv"
```

**`ModuleNotFoundError: No module named 'requests'` (or `fitz`).**
Wrong Python. Most Macs have several, and the one that wins your PATH in Terminal
(often Homebrew's at `/opt/homebrew/bin/python3`) is frequently not the one
carrying the libraries. The wrapper searches for a working interpreter, so this
usually only bites when you run `summarize_pdf.py` directly. Either install the
libraries where PATH points — `pip3 install pymupdf requests` — or force the
choice:

```bash
export SUMMARIZE_PDF_PYTHON=~/miniconda3/bin/python3
```

**Quick Action does nothing, no notification.**
Check the log:

```bash
tail -20 ~/Library/Logs/summarize-pdf.log
```

**"It is probably a scanned image and needs OCR first."**
The PDF has no text layer. OCR it first — `ocrmypdf in.pdf out.pdf` — then rerun.

**Rebuilding the workflow bundle by hand.** `lsregister` reports error `-10811`
on a `.workflow`; that is expected and harmless, since it is not an app bundle.
Registration goes through `pbs -update` instead.

## License

MIT — see [LICENSE](LICENSE).

## Uninstall

```bash
rm -rf ~/Library/Services/"Summarize PDF with TAMU AI.workflow"
rm -f ~/.local/bin/summarize-pdf ~/.local/bin/summarize_pdf.py
```
