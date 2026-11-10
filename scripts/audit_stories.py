"""Count the design model's stories from their header lines and keep its summary tables in step.

Run from any directory: python scripts/audit_stories.py [--check | --write | --sessions].

decklab/design/stories.md's header lines ("**E1-S01** · Persona · must · M · built") are the
only source. From them this works out, per epic, how many stories are built, partial, missing
and not wanted, and compares three hand-readable blocks with that count:

- the table under "## Summary" in decklab/design/stories.md;
- the last four cells of each row of the table under "## The epics" in decklab/design/README.md;
- the "- **N epics, N stories:** ..." line under its "## Headline counts".

Without an option it prints the counts (and the must and should stories by persona, for the
README's hand-written line). --check exits 1 when a block disagrees or a header is malformed;
--write rewrites the blocks and changes nothing when they already agree, so it can be run again
after every merge. Only those blocks are touched: every other line stays as written.

A partial story may carry one "Awaiting: iphone, ipad" line (or "Awaiting: decision") naming
what it still waits for. --sessions lists those waiting checks by device and compares them with
TODO.md's rows.
"""
import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORIES = "decklab/design/stories.md"
README = "decklab/design/README.md"
TODO = "TODO.md"

STATUSES = ("built", "partial", "missing", "not_wanted")
PRIORITIES = ("must", "should", "could", "wont")
SIZES = ("S", "M", "L", "XL")
SUMMARY_HEADER = "| Epic | Stories | Built | Partial | Missing | Not wanted |"
SUMMARY_RULE = "|---|---:|---:|---:|---:|---:|"

_EPIC = re.compile(r"^## (E\d+): (.+?)\s*$")
_STORY_START = re.compile(r"^\*\*(E\d+)-S(\d+)\*\* ·")
_STORY = re.compile(r"^\*\*((E\d+)-S\d+)\*\* · (.+?) · (\S+) · (\S+) · (\S+)\s*$")
_AWAITING = re.compile(r"^(?:\*\*)?Awaiting:(?:\*\*)?\s*(.*?)\s*$")
_AWAITING_ITEM = re.compile(r"^[a-z0-9][a-z0-9 -]*$")
_README_ROW = re.compile(r"^\| (E\d+) \| (.+?) \| (.*) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|\s*$")
_HEADLINE = re.compile(
    r"^- \*\*\d+ epics, \d+ stories:\*\* \d+ built, \d+ partial, \d+ missing and \d+ not wanted"
)
_TODO_ROW = re.compile(r"^\| `([^`]+)` \| ([A-Z]+) \|")


class Story:
    def __init__(self, id, epic, persona, priority, size, status, line):
        self.id, self.epic, self.persona = id, epic, persona
        self.priority, self.size, self.status, self.line = priority, size, status, line
        self.awaiting = []


def parse_stories(text):
    """The epics in file order ([(id, title)]), the stories and what is wrong with the headers."""
    epics, stories, problems, seen = [], [], [], set()
    current = story = None
    for number, line in enumerate(text.splitlines(), 1):
        heading = _EPIC.match(line)
        if heading:
            current, story = heading.group(1), None
            if any(current == epic for epic, _title in epics):
                problems.append(f"{STORIES}:{number}: epic {current} has two headings")
            else:
                epics.append((current, heading.group(2)))
            continue
        if line.startswith("## "):
            current = story = None
            continue
        if _STORY_START.match(line):
            story = None
            header = _STORY.match(line)
            if not header:
                problems.append(
                    f"{STORIES}:{number}: story header isn't "
                    "'**E1-S01** · Persona · priority · size · status'"
                )
                continue
            id, epic, persona, priority, size, status = header.groups()
            wrong = []
            if priority not in PRIORITIES:
                wrong.append(f"priority '{priority}'")
            if size not in SIZES:
                wrong.append(f"size '{size}'")
            if status not in STATUSES:
                wrong.append(f"status '{status}'")
            if epic != current:
                wrong.append(f"it is under {current or 'no epic'}'s heading")
            if id in seen:
                wrong.append("its id is used twice")
            if wrong:
                problems.append(f"{STORIES}:{number}: {id}: " + ", ".join(wrong))
            if status not in STATUSES or id in seen:
                continue
            seen.add(id)
            story = Story(id, epic, persona, priority, size, status, number)
            stories.append(story)
            continue
        waiting = _AWAITING.match(line)
        if waiting and story:
            items = [item.strip() for item in waiting.group(1).split(",")]
            if story.awaiting:
                problems.append(f"{STORIES}:{number}: {story.id} has two Awaiting lines")
            elif story.status != "partial":
                problems.append(
                    f"{STORIES}:{number}: {story.id} is {story.status}; only a partial story has an Awaiting line"
                )
            elif not all(_AWAITING_ITEM.match(item) for item in items) or len(set(items)) != len(items):
                problems.append(
                    f"{STORIES}:{number}: {story.id}'s Awaiting line isn't a comma-separated list "
                    "such as 'iphone, ipad' or 'decision'"
                )
            else:
                story.awaiting = items
    if not epics:
        problems.append(f"{STORIES}: no '## E1: Title' epic heading")
    return epics, stories, problems


def count(epics, stories):
    """{epic: {status: n}} for every epic with a heading, in the headings' order."""
    counts = {epic: dict.fromkeys(STATUSES, 0) for epic, _title in epics}
    for story in stories:
        if story.epic in counts:
            counts[story.epic][story.status] += 1
    return counts


def totals(counts):
    return {status: sum(row[status] for row in counts.values()) for status in STATUSES}


def anchor(heading):
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces as hyphens."""
    kept = "".join(ch for ch in heading.lower() if ch.isalnum() or ch in " -_")
    return kept.replace(" ", "-")


def summary_table(epics, counts):
    lines = [SUMMARY_HEADER, SUMMARY_RULE]
    for epic, title in epics:
        row = counts[epic]
        cells = [sum(row.values())] + [row[status] for status in STATUSES]
        label = f"[{epic}: {title}](#{anchor(f'{epic}: {title}')})"
        lines.append(f"| {label} | " + " | ".join(str(cell) for cell in cells) + " |")
    total = totals(counts)
    cells = [sum(total.values())] + [total[status] for status in STATUSES]
    lines.append("| **Total** | " + " | ".join(f"**{cell}**" for cell in cells) + " |")
    return lines


def _section(lines, heading):
    """(start, end) of the lines under a level-2 heading, or None."""
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return None
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def fix_stories(lines, epics, counts):
    """stories.md's lines with the Summary table as counted, and what can't be rewritten."""
    span = _section(lines, "## Summary")
    if not span:
        return lines, [f"{STORIES}: no '## Summary' heading"]
    table = [i for i in range(*span) if lines[i].startswith("|")]
    if not table or table != list(range(table[0], table[-1] + 1)):
        return lines, [f"{STORIES}: '## Summary' needs exactly one table"]
    return lines[:table[0]] + summary_table(epics, counts) + lines[table[-1] + 1:], []


def fix_readme(lines, epics, counts):
    """The design README's lines with its epic rows and headline as counted, and what can't be."""
    problems = []
    lines = list(lines)
    span = _section(lines, "## The epics")
    if not span:
        problems.append(f"{README}: no '## The epics' heading")
    else:
        titles, rows = dict(epics), []
        for i in range(*span):
            row = _README_ROW.match(lines[i])
            if not row:
                continue
            epic = row.group(1)
            rows.append(epic)
            if epic not in counts:
                problems.append(f"{README}:{i + 1}: {epic} has no heading in {STORIES}")
                continue
            cells = " | ".join(str(counts[epic][status]) for status in STATUSES)
            lines[i] = f"| {epic} | {titles[epic]} | {row.group(3)} | {cells} |"
        if rows != [epic for epic, _title in epics]:
            wanted = ", ".join(epic for epic, _title in epics)
            problems.append(
                f"{README}: the table under '## The epics' needs one row for each of {wanted}, in that order "
                "(add or remove the row by hand: its 'What it covers' cell isn't generated)"
            )
    total = totals(counts)
    headline = (
        f"- **{len(epics)} epics, {sum(total.values())} stories:** {total['built']} built, "
        f"{total['partial']} partial, {total['missing']} missing and {total['not_wanted']} not wanted"
    )
    found = [i for i, line in enumerate(lines) if _HEADLINE.match(line)]
    if len(found) != 1:
        problems.append(
            f"{README}: needs exactly one line starting '- **N epics, N stories:** N built, N partial, "
            "N missing and N not wanted'"
        )
    else:
        lines[found[0]] = _HEADLINE.sub(headline, lines[found[0]], count=1)
    return lines, problems


def differences(name, old, new):
    """One message for each line of a block that isn't as counted."""
    if len(old) != len(new):
        return [f"{name}: the summary table has {abs(len(new) - len(old))} "
                f"{'too few' if len(new) > len(old) else 'too many'} rows for the epics counted"]
    return [
        f"{name}:{i + 1}: is\n    {before[:200]}\n  and the story headers count\n    {after[:200]}"
        for i, (before, after) in enumerate(zip(old, new)) if before != after
    ]


def read(path):
    """A file's lines and its newline, so a rewrite keeps the checkout's line endings."""
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").split("\n"), newline


def write(path, lines, newline):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(newline.join(lines))


def todo_rows(text):
    """{story id: status} from TODO.md's table rows."""
    rows = {}
    for line in text.splitlines():
        row = _TODO_ROW.match(line)
        if row:
            rows.setdefault(row.group(1), row.group(2))
    return rows


def sessions(stories, rows):
    """The report lines for --sessions: waiting checks by device, compared with TODO.md's rows."""
    waiting = [story for story in stories if story.awaiting]
    out = []
    if not waiting:
        out.append("No partial story has an Awaiting line.")
    devices = {}
    for story in waiting:
        for item in story.awaiting:
            devices.setdefault(item, []).append(story)
    for item in sorted(devices):
        out.append(f"{item} ({len(devices[item])}):")
        for story in devices[item]:
            status = rows.get(story.id)
            out.append(f"  {story.id}  TODO.md: {status if status else 'no row'}")
    unlisted = [story.id for story in waiting if story.id not in rows]
    if unlisted:
        out.append("Awaiting a check but without a TODO.md row: " + ", ".join(unlisted))
    partial = {story.id for story in stories if story.status == "partial" and not story.awaiting}
    silent = [id for id, status in rows.items() if status == "DECISION" and id in partial]
    if silent:
        out.append("Partial stories with a DECISION row in TODO.md but no Awaiting line: " + ", ".join(silent))
    return out


def report(epics, stories, counts):
    out = []
    for line in summary_table(epics, counts):
        out.append(line)
    out.append("")
    out.append("Must and should stories by persona (built, partial, missing):")
    personas = {}
    for story in stories:
        if story.priority in ("must", "should"):
            personas.setdefault(story.persona, []).append(story)
    for persona in sorted(personas):
        parts = []
        for status in ("built", "partial", "missing"):
            ids = [story.id for story in personas[persona] if story.status == status]
            if ids:
                listed = f" ({', '.join(ids)})" if status != "built" else ""
                parts.append(f"{len(ids)} {status}{listed}")
        out.append(f"  {persona}: " + ", ".join(parts))
    return out


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when a summary block disagrees with the headers")
    mode.add_argument("--write", action="store_true", help="rewrite the summary blocks from the headers")
    mode.add_argument("--sessions", action="store_true", help="list the partial stories' Awaiting checks by device")
    args = parser.parse_args(argv)
    root = Path(root) if root else ROOT
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    story_lines, story_newline = read(root / STORIES)
    readme_lines, readme_newline = read(root / README)
    epics, stories, problems = parse_stories("\n".join(story_lines))
    for problem in problems:
        print(problem)
    if args.sessions:
        todo = root / TODO
        rows = todo_rows(todo.read_text(encoding="utf-8")) if todo.is_file() else {}
        for line in sessions(stories, rows):
            print(line)
        return int(bool(problems))
    counts = count(epics, stories)
    if problems:
        print("Fix the story headers first; nothing was compared or written.")
        return 1
    new_stories, fixed = fix_stories(story_lines, epics, counts)
    new_readme, more = fix_readme(readme_lines, epics, counts)
    unfixable = fixed + more
    for problem in unfixable:
        print(problem)
    total = totals(counts)
    summary = (
        f"{len(epics)} epics, {len(stories)} stories: {total['built']} built, {total['partial']} partial, "
        f"{total['missing']} missing, {total['not_wanted']} not wanted."
    )
    if args.write:
        if unfixable:
            print("Nothing was written.")
            return 1
        changed = []
        if new_stories != story_lines:
            write(root / STORIES, new_stories, story_newline)
            changed.append(STORIES)
        if new_readme != readme_lines:
            write(root / README, new_readme, readme_newline)
            changed.append(README)
        print(summary)
        print("Rewrote " + " and ".join(changed) + "." if changed else "The summary blocks already agree.")
        return 0
    if args.check:
        stale = differences(STORIES, story_lines, new_stories) + differences(README, readme_lines, new_readme)
        for line in stale:
            print(line)
        print(summary)
        if stale or unfixable:
            print("The summary blocks disagree with the story headers: run python scripts/audit_stories.py --write")
            return 1
        print("The summary blocks agree with the story headers.")
        return 0
    for line in report(epics, stories, counts):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
