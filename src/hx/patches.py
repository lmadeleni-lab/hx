from __future__ import annotations

import difflib
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class PatchFormatError(RuntimeError):
    pass


def _is_git_apply_patch(text: str) -> bool:
    # Heuristic: a minimal unified diff has ---/+++ lines; git-style often has diff --git.
    if "diff --git " in text:
        return True
    has_from = text.startswith("--- ") or "\n--- " in text
    has_to = text.startswith("+++ ") or "\n+++ " in text
    return has_from and has_to


def _is_hx_apply_patch(text: str) -> bool:
    return text.lstrip().startswith("*** Begin Patch")


@dataclass(frozen=True)
class _FileEdit:
    path: str
    before: str | None  # None means did not exist
    after: str | None   # None means deleted


def canonicalize_staged_patch(root: Path, patch_text: str) -> str:
    """
    Normalize user-provided patches into something `git apply` can consume.

    Supported inputs:
    - git/unified diffs (passed through after a check)
    - hx 'apply_patch' style (*** Begin Patch ...) converted into a git/unified diff

    This is intentionally strict: `port.check` and `repo.commit_patch` rely on being able
    to replay the staged patch deterministically using git tooling.
    """
    if _is_git_apply_patch(patch_text):
        _ensure_git_apply_check(root, patch_text)
        return patch_text
    if _is_hx_apply_patch(patch_text):
        edits = _parse_apply_patch(root, patch_text)
        canonical = _edits_to_git_diff(edits)
        _ensure_git_apply_check(root, canonical)
        return canonical
    raise PatchFormatError(
        "repo.stage_patch expects a unified diff that `git apply` can read. "
        "Provide a git-style diff (diff --git / --- a/ +++ b/)."
    )


def _ensure_git_apply_check(root: Path, patch_text: str) -> None:
    # `git apply --check` is read-only; it validates the patch without mutating the repo.
    with tempfile.NamedTemporaryFile(prefix="hx-stage-", suffix=".patch", delete=False) as handle:
        patch_path = Path(handle.name)
        handle.write(patch_text.encode())
    try:
        result = subprocess.run(
            ["git", "apply", "--check", "--unsafe-paths", str(patch_path)],
            cwd=root,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            patch_path.unlink()
        except FileNotFoundError:
            pass
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        hint = "Make sure the patch is a valid unified diff with correct file paths."
        raise PatchFormatError(f"Staged patch failed validation: {stderr or hint}")


def _parse_apply_patch(root: Path, patch_text: str) -> list[_FileEdit]:
    lines = patch_text.splitlines()
    if not lines or not lines[0].startswith("*** Begin Patch"):
        raise PatchFormatError("apply_patch patches must start with '*** Begin Patch'")

    edits: dict[str, _FileEdit] = {}

    idx = 1
    current_kind: str | None = None
    current_path: str | None = None
    update_ops: list[str] = []
    add_lines: list[str] = []

    def flush() -> None:
        nonlocal current_kind, current_path, update_ops, add_lines
        if current_kind is None or current_path is None:
            return
        path = current_path
        before = (root / path).read_text() if (root / path).exists() else None
        if current_kind == "delete":
            edits[path] = _FileEdit(path=path, before=before, after=None)
        elif current_kind == "add":
            after = "\n".join(add_lines) + ("\n" if add_lines else "")
            edits[path] = _FileEdit(path=path, before=before, after=after)
        elif current_kind == "update":
            if before is None:
                raise PatchFormatError(f"apply_patch Update File refers to missing path: {path}")
            after = _apply_unified_ops(before, update_ops, path)
            edits[path] = _FileEdit(path=path, before=before, after=after)
        else:
            raise PatchFormatError(f"Unsupported apply_patch operation: {current_kind}")
        current_kind = None
        current_path = None
        update_ops = []
        add_lines = []

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("*** End Patch"):
            flush()
            break
        if line.startswith("*** Delete File: "):
            flush()
            current_kind = "delete"
            current_path = line[len("*** Delete File: ") :].strip()
            idx += 1
            continue
        if line.startswith("*** Add File: "):
            flush()
            current_kind = "add"
            current_path = line[len("*** Add File: ") :].strip()
            idx += 1
            continue
        if line.startswith("*** Update File: "):
            flush()
            current_kind = "update"
            current_path = line[len("*** Update File: ") :].strip()
            idx += 1
            continue
        if line.startswith("*** Move to: "):
            # MVP: ignore moves during canonicalization; they can be expressed as delete+add.
            idx += 1
            continue

        if current_kind == "add":
            if not line.startswith("+"):
                raise PatchFormatError(
                    f"apply_patch Add File expects '+' lines only (path={current_path})"
                )
            add_lines.append(line[1:])
        elif current_kind == "update":
            # Keep hunks/context lines verbatim for the applier.
            update_ops.append(line)
        elif current_kind == "delete":
            # delete blocks should not have payload lines; tolerate blank lines.
            if line.strip():
                raise PatchFormatError(
                    f"apply_patch Delete File should not have content (path={current_path})"
                )
        else:
            # Outside any operation.
            if line.strip():
                raise PatchFormatError(f"Unexpected line outside file op: {line}")
        idx += 1

    if current_kind is not None:
        flush()

    return [edits[path] for path in sorted(edits)]


def _apply_unified_ops(before: str, ops: list[str], path: str) -> str:
    before_lines = before.splitlines()
    out: list[str] = []
    cursor = 0

    def expect(text: str) -> None:
        nonlocal cursor
        if cursor >= len(before_lines):
            raise PatchFormatError(f"apply_patch failed for {path}: ran past end of file")
        actual = before_lines[cursor]
        if actual != text:
            raise PatchFormatError(
                f"apply_patch failed for {path}: expected '{text}' but found '{actual}'"
            )

    for op in ops:
        if op.startswith("@@"):
            continue
        if not op:
            # Blank line: in apply_patch format, this represents a context line with empty content
            # only if prefixed. Without prefix, it's ambiguous; reject.
            raise PatchFormatError(f"apply_patch failed for {path}: blank op line is ambiguous")
        prefix = op[0]
        text = op[1:] if len(op) > 1 else ""
        if prefix == " ":
            expect(text)
            out.append(before_lines[cursor])
            cursor += 1
        elif prefix == "-":
            expect(text)
            cursor += 1
        elif prefix == "+":
            out.append(text)
        else:
            raise PatchFormatError(
                f"apply_patch failed for {path}: unexpected op prefix '{prefix}'"
            )

    out.extend(before_lines[cursor:])
    return "\n".join(out) + ("\n" if before.endswith("\n") else "")


def _edits_to_git_diff(edits: list[_FileEdit]) -> str:
    blocks: list[str] = []
    for edit in edits:
        a_path = f"a/{edit.path}"
        b_path = f"b/{edit.path}"
        blocks.append(f"diff --git {a_path} {b_path}\n")
        before_lines = [] if edit.before is None else edit.before.splitlines(keepends=True)
        after_lines = [] if edit.after is None else edit.after.splitlines(keepends=True)
        if edit.before is None and edit.after is not None:
            blocks.append("new file mode 100644\n")
        if edit.before is not None and edit.after is None:
            blocks.append("deleted file mode 100644\n")
        fromfile = "/dev/null" if edit.before is None else a_path
        tofile = "/dev/null" if edit.after is None else b_path
        diff_lines = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        )
        blocks.extend(list(diff_lines))
    text = "".join(blocks)
    if not text.endswith("\n"):
        text += "\n"
    return text
