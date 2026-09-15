# picdrop-download

Downloads all the photos from a [picdrop](https://www.picdrop.com) gallery link
to your computer, in one command.

Picdrop galleries have no "download everything" button — you would otherwise
have to save each photo by hand. This does it for you.

---

## What you need

- **A computer** running macOS, Linux or Windows.
- **Python 3** (version 3.9 or newer). It is already installed on macOS and
  Linux. On Windows, get it from [python.org](https://www.python.org/downloads/)
  and tick **"Add Python to PATH"** during installation.
- **The gallery link**, and its password if it has one.

To check that Python is there, open a terminal
(macOS: **Terminal**, Windows: **PowerShell**) and type:

```bash
python3 --version
```

You should see something like `Python 3.12.4`. On Windows, use `python`
instead of `python3` in this and every command below.

> Nothing to see? On macOS run `xcode-select --install` and follow the
> prompts, then try again.

---

## Setup

**1. Get the files.** Download this folder to your computer and remember where
you put it — for example `Documents/picdrop-download`.

**2. Open a terminal in that folder.**

- *macOS:* right-click the folder in Finder → **Services** → **New Terminal at
  Folder**. Or type `cd ` (with the space), drag the folder onto the terminal
  window, and press Return.
- *Windows:* right-click inside the folder while holding **Shift** →
  **Open PowerShell window here**.

**3. That's it.** Nothing to install for most galleries.

---

## Using it

Type this, replacing the link with your own:

```bash
python3 picdrop.py https://www.picdrop.com/annasmith/Xy7KpQ2m
```

If the gallery asks for a password, add it at the end:

```bash
python3 picdrop.py https://www.picdrop.com/annasmith/Xy7KpQ2m mypassword
```

If the password is already part of the link, just paste the whole thing in
quotes and leave the password off:

```bash
python3 picdrop.py "https://www.picdrop.com/annasmith/Xy7KpQ2m?password=mypassword"
```

You will see one line per photo as it arrives, and a summary at the end.

### Where the photos go

Into a folder called **`output`**, next to `picdrop.py`. It is created for you.
The photos keep their original file names.

### Stopping and continuing

Press **Ctrl+C** to stop. Run the same command again to pick up where it left
off — photos already downloaded are skipped, not fetched twice.

---

## Extra options

You will probably never need these.

| Option | What it does |
| --- | --- |
| `-o FOLDER` | Save somewhere else, e.g. `-o ~/Desktop/photos` |
| `-j 8` | Download 8 photos at a time instead of 4 |
| `--browser` | Force the slower browser method (see below) |
| `--headful` | Show the browser window while it works |

Example:

```bash
python3 picdrop.py https://www.picdrop.com/annasmith/Xy7KpQ2m -o ~/Desktop/photos
```

---

## If something goes wrong

**"Selenium is needed for this gallery but is not installed"**

Some galleries need a real browser to sign in. Install the extra piece once —
in your terminal, in the same folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows the middle line is `.venv\Scripts\activate` instead.

Then run your download command again. You also need **Google Chrome**
installed; everything else is handled automatically. Next time you open a new
terminal, run the `source .venv/bin/activate` line again first.

**"No images found. Check the URL and the password."**

Open the link in your browser. If it does not show the gallery there either,
the link has expired or the password is wrong — ask whoever sent it to you.

**"The password form is still there after submitting"**

The password is not being accepted. Check it for typos, including capital
letters.

**Lots of lines saying FAILED**

Picdrop's download links expire after a while. Run the same command again —
it continues where it stopped.

**Nothing downloads at all and every line fails**

Your network may be blocking picdrop. Office and school networks often do.
Try again on a different connection.

---

## Good to know

- The photos you get are the largest size the gallery makes available, which
  is usually a high-quality preview rather than the photographer's original
  file. If you need the untouched originals, ask the photographer.
- Downloading a gallery is between you and whoever shared it with you. This
  tool only automates what your browser already does with a link you were
  given.

---

## License

MIT — see [LICENSE](LICENSE). Free to use, change and share.
