# Scanning cards: the recognition spike (E7-S32, 2026-10-28)

E7-S32 wants Scan cards on the Collection page: photograph a card with a phone, get its printing, review a pending list, add it as one change. Its first slice was this spike: is recognition practical for Deck Lab, with no build step and standard-library Python? Short answer: **yes, for modern cards, by reading the text on the PC with Windows' own OCR engine**. The prototype is `decklab/lib/scan.py` (`python -m decklab.lib.scan PHOTO`), tested by `decklab/tests/test_scan.py`.

## What a card prints

A card from 2015 on prints its collector number, rarity, set code and language in the bottom-left corner, in three layouts:

| Since | Bottom line | Example |
|---|---|---|
| Foundations (late 2024) | rarity, number; set • language | `R 0107` / `FDN • EN` |
| March of the Machine (2023) | number, rarity; set • language | `0227 C` / `MOM • EN` |
| Magic Origins (2015) | number/total, rarity; set • language | `002/274 C` / `M21 • EN` |

A foil swaps the dot for a star (`FDN ★ EN`). The set code and number name one printing in the card index (`cards.printing(set, number)`); the name at the top says whether it's the right card. Cards before 2015 print only a number (or nothing): for them the name is all there is, and the printing has to be chosen.

## The options checked

| Option | On this PC / the phones | Verdict |
|---|---|---|
| **Windows OCR** (`Windows.Media.Ocr`, part of Windows 10 and 11) through Windows PowerShell 5.1's WinRT bridge | Installed, with the en-GB and en-US recognisers; nothing to install. About 0.3 s a scan, 0.7 s on a 2000-pixel photo, plus PowerShell's start. | **Use it.** Reads the name and bottom line well (results below). Windows only: on Linux it's absent, and the scanner says so and falls back to typing the name. |
| **Tesseract** | Not installed (not on the PATH, no `C:\Program Files\Tesseract-OCR`). | Supported by the prototype when it's on the PATH (`--engine tesseract`, untried); the way to scan on a Linux host (`apt install tesseract-ocr`). Not needed on the PC. |
| **Browser `TextDetector`** (Shape Detection API) | Chrome ships it only behind `#enable-experimental-web-platform-features`; Safari only as an experimental Feature Flag, off by default. | **Not usable**: nobody's phone has it on, and turning flags on isn't a household setup. `BarcodeDetector` is the part that shipped (Android Chrome, macOS), and cards have no barcodes. |
| **`getUserMedia`** (a live camera view in the page) | Needs a secure context: works through https://decklab.example.com, but **not** on the home address (`http://192.0.2.10:8642`), where browsers refuse the camera. | Not for the first build. A live view would also need recognition in the browser, which isn't there (above). |
| **`<input type="file" accept="image/*" capture="environment">`** | Opens the phone's camera app on iOS Safari and Android Chrome, on http and https alike, and hands back the full-resolution photo: 12 to 48 MP, often 3 to 8 MB as JPEG (or HEIC on an iPhone), so over a 4 MiB upload cap. | **Use it, shrunk in the page first.** The page draws the photo on a canvas, its long side at most 2000 px (the resolution of the "made like a phone photo" row below, measured at 82% first), and sends it as a JPEG (quality about 0.85, well under 1 MiB) to the PC. That also turns an iPhone's HEIC into a JPEG, and the browser applies the photo's rotation when drawing it. The upload's cap can then stay at 4 MiB, as the Sleeves & boxes page's **Photo from this device** (`lib/accessory_upload.py`). |
| **Perceptual hashing** against Scryfall's pictures of each candidate printing | Needs the photo decoded: no JPEG decoder in the standard library; Pillow is in this PC's system Python, put there for other projects, not in Deck Lab's `.venv` or CI. Windows' `BitmapDecoder` could decode and shrink a photo to 32×32 through the same PowerShell bridge. It would also need the card found and squared up in the photo (edge and corner finding) and Scryfall's picture of every candidate printing (a name with 30 printings is 30 downloads the first time, cached in `data/images/`). | **Not now.** Heavy for what it adds: it only helps the cards OCR can't place (older cards), where choosing from the name's printings works. Worth another look only if real use shows the name-only cases are common. |
| **ManaBox export, then Import** (E7-S02) | Built. | Stays the route for a big stack, and for anyone off the PC. Scanning in Deck Lab is for a handful of new cards. |

## How the prototype reads a card

`scan.ocr(path)` runs Windows' engine (or Tesseract) and returns the lines read; `scan.propose(lines)` turns them into printings from the card index, best first:

- **Bottom line:** each layout above; common misreadings fixed (`O`, `D` for `0`, `l`, `I`, `|` for `1` in a number; `FON` tried as `FDN`, `MI9` as `M19` in a set code); power and toughness (`2/4`) and names like "Old Man of the Sea" aren't numbers; rules text in capitals isn't a set line.
- **Name:** one of the first two lines (lower down, "Vigilance" is a keyword, not the card), matched exactly, else closely ("Éowynt Lady of Rohan" is Éowyn, Lady of Rohan).
- **Proposals:** `name and number` when the set code (if read) and number name a printing of the card read; `number` when they name a printing but the name differs or wasn't read (flagged "check it's this card"); `name` for the name's paper printings, newest first, when no set code agrees. Finish is foil only when a star was read and the printing has a foil; the language is the one printed (EN, JP, CS...). Unknown condition stays blank.
- Nothing is written and nothing is fetched. A missing engine, a timeout or an unreadable photo is a plain message ending "Type the card's name instead."

## Results

Run on the 175 card pictures in this PC's Scryfall picture cache (`data/images/large`, 672×936), with the card index of 2026-10-28 (the benchmark script isn't committed: it needs Pillow to blur and shrink the pictures):

| Pictures | Right printing first | Right printing offered | Wrong first | Nothing |
|---|---|---|---|---|
| As Scryfall has them | 155 (89%) | 164 (94%) | 9 | 2 |
| Made like a phone photo: about 2000 px tall, blurred, tilted, dimmer, JPEG quality 60 | 144 (82%) | 164 (94%) | 7 | 4 |
| Half size (bottom line about 5 px tall) | 58 (33%) | 153 (87%) | 17 | 5 |

The misses are cards whose bottom line names a different "set" than Scryfall's: tokens (`BLB` printed, Scryfall's `tblb`), The List (`DSK` printed, Scryfall's `plst DSK-3`), Final Fantasy's stylised names, and cards before 2015, where only the name is offered. "Offered" counts the right printing anywhere in the list, mostly among a name's printings. The half-size row is the warning: the name still reads, but the bottom line needs to be at least about 9 pixels tall, so **the card should fill most of the photo**. Shrunk to 2000 px as the page will send it, a card filling the frame has its bottom line about 20 pixels tall; one filling only half the frame is back near the half-size row, so the sheet should say "fill the frame with the card". If real photos read worse than this, raise the shrink to 3000 px (still under 4 MiB as a JPEG at 0.85) before anything else.

Not tried: real phone photos (there's no camera on this PC). Glare on foils and sleeves, and the black-bordered text on a dark frame under poor light, are the likely problems; 20 real photos of the household's cards would settle it.

## Recommendation

Build Scan cards in this order:

1. **Built 2026-10-29** (with step 2's review of copies, finish and condition and its Add, through the import preview; HISTORY.md, "Scan cards on the Collection page"): `POST /api/collection/scan` (one photo, shrunk in the page to at most 2000 px on its long side and sent as a JPEG, at most 4 MiB, the space's own people only, like the Collection page's other writes) runs `scan.ocr` and `scan.propose` on the PC and answers the proposals; the Collection page's **Scan cards** sheet takes photos with the file input above, adds a card to a pending list in the browser when its name and bottom line name exactly one printing (otherwise the visitor chooses from the proposals), and on failure offers the name finder. Photos are kept only while read (a temporary file), never stored.
2. **Partly built 2026-10-29:** the pending list's review (copies, finish, condition) and **Add**, which sends the rows to `import_preview`/`import_apply` as a collection-columns import, so the scan is one change with a raw import kept, as an import is. **Still to do:** each row's printing from the existing printing picker (today it changes only by taking the card out and choosing again) and its language (today only what the photo read).
3. Tokens: try `t` + the code read when the name is a token's, so a token card names its printing (for the Tokens page, not the collection).

Leave out: image matching, a live camera view and any browser OCR, until real use says otherwise.

## Decisions for Matt

- **Windows only, to start:** scanning works on the PC's Windows OCR engine. If Deck Lab moves to the Linux host, it needs `tesseract-ocr` installed there (a system package, not a Python one): agree, or scanning stays a Windows feature.
- **No new Python dependencies:** Pillow, OpenCV and onnxruntime are on this PC for other projects but aren't Deck Lab's; nothing here uses them. Image matching would be the reason to add one, and it isn't recommended.
- **Try it on real photos:** take 10 to 20 photos of cards (a few foils, a few sleeved, one old card) on each phone, copy them to the PC, and run `python -m decklab.lib.scan <photos>`. Run them at full size and shrunk to 2000 px on the long side (as the page will send them), since the page shrinks every photo to keep under the 4 MiB upload cap. If the bottom line reads on most, build the next slice.
- **Which phones:** the file input works on both the iPhone/iPad and Android, at home and through the tunnel; nothing needs the phone's settings changed.
