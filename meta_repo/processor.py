"""Repository processing with embedded Python and shared memory (stdlib only)."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
import os
import re
import shutil
import tempfile
import textwrap
from typing import Any


SERVICE_FILE = "!#meta"
_PARAMETERS = r"\[([^\[\]\r\n]*)\]\[([^\[\]\r\n]*)\]\[([+-]?[0-9]+)\]"
_HEADER = re.compile(r"!#meta" + _PARAMETERS)
_FOLDER = re.compile(_PARAMETERS)
_PRIORITY = re.compile(r"\[([+-]?[0-9]+)\]")
_UNSET = object()


class ProcessingError(Exception):
    """Invalid meta-text, failed Python execution, or nonstring return value."""


@dataclass(frozen=True)
class Settings:
    delimiters: tuple[str, str] | None = None
    priority: int | None = None
    delete: bool = False


@dataclass(frozen=True)
class Block:
    parts: tuple[str | Block, ...]
    line: int


def _settings(match: re.Match[str]) -> Settings:
    return Settings((match[1], match[2]), int(match[3]))


def _is_delete(line: bytes, settings: Settings) -> bool:
    if settings.delimiters is None:
        return False
    opening, closing = settings.delimiters
    return line.removesuffix(b"\r") == f"{opening}DELETE{closing}".encode("utf-8")


def folder_settings(directory: Path) -> Settings:
    service = directory / SERVICE_FILE
    if service.is_symlink() or not service.is_file():
        return Settings()
    header, _, remainder = service.read_bytes().partition(b"\n")
    try:
        text = header.removesuffix(b"\r").decode("utf-8")
    except UnicodeDecodeError:
        return Settings()
    full = _FOLDER.fullmatch(text)
    if full:
        settings = _settings(full)
        if not remainder:
            return settings
        directive, _, extra = remainder.partition(b"\n")
        if not extra and _is_delete(directive, settings):
            return replace(settings, delete=True)
        return Settings()
    if remainder:
        return Settings()
    priority = _PRIORITY.fullmatch(text)
    return Settings(priority=int(priority[1])) if priority else Settings()


def file_settings(data: bytes, defaults: Settings) -> tuple[Settings, bytes, int]:
    """Recognize only the first line; return parameters, body, first body line."""
    header, _, body = data.partition(b"\n")
    try:
        match = _HEADER.fullmatch(header.removesuffix(b"\r").decode("utf-8"))
    except UnicodeDecodeError:
        match = None
    if match:
        settings = _settings(match)
        directive, _, rest = body.partition(b"\n")
        if _is_delete(directive, settings):
            return replace(settings, delete=True), rest, 3
        return settings, body, 2
    return replace(defaults, delete=False), data, 1


def parse_text(
    text: str, delimiters: tuple[str, str], filename: Path, first_line: int = 1
) -> tuple[str | Block, ...]:
    """Markers are reserved, including inside Python string literals."""
    opening, closing = delimiters
    if not opening or not closing or opening.startswith(closing) or closing.startswith(opening):
        raise ProcessingError(f"{filename}: delimiters must be nonempty and prefix-free")

    stack: list[tuple[list[str | Block], int]] = [([], first_line)]
    cursor = 0
    line = first_line
    while cursor < len(text):
        begin = text.find(opening, cursor)
        end = text.find(closing, cursor)
        if begin == -1 and end == -1:
            stack[-1][0].append(text[cursor:])
            break
        is_opening = begin != -1 and (end == -1 or begin < end)
        position = begin if is_opening else end
        if position > cursor:
            stack[-1][0].append(text[cursor:position])
        marker = opening if is_opening else closing
        line += text.count("\n", cursor, position + len(marker))
        if is_opening:
            stack.append(([], line))
        else:
            if len(stack) == 1:
                raise ProcessingError(f"{filename}:{line}: unexpected closing delimiter")
            parts, start_line = stack.pop()
            stack[-1][0].append(Block(tuple(parts), start_line))
        cursor = position + len(marker)
    if len(stack) != 1:
        raise ProcessingError(f"{filename}:{stack[-1][1]}: unclosed Python block")
    return tuple(stack[0][0])


class Context:
    def __init__(self, memory: Any = _UNSET):
        self.namespace = {
            "__name__": "__metarepo__",
            "memory": {} if memory is _UNSET else memory,
        }

    @property
    def memory(self) -> Any:
        return self.namespace["memory"]

    def execute(self, code: str, filename: Path, line: int) -> str:
        try:
            # Wrap the AST rather than indenting source: multiline literals keep
            # their contents, and return is valid inside the generated function.
            parsed = ast.parse(textwrap.dedent(code), filename=str(filename))
            arguments = ast.arguments(
                posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
            )
            function = ast.FunctionDef(
                name="__metarepo_block__",
                args=arguments,
                body=[ast.Global(names=["memory"]), *parsed.body],
                decorator_list=[],
            )
            module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
            self.namespace["__file__"] = str(filename)
            exec(compile(module, str(filename), "exec"), self.namespace)
            result = self.namespace["__metarepo_block__"]()
            if not isinstance(result, str):
                raise TypeError(f"block must return str, got {type(result).__name__}")
            return result
        except Exception as error:
            raise ProcessingError(f"{filename}:{line}: {type(error).__name__}: {error}") from error

    def render(self, parts: tuple[str | Block, ...], filename: Path) -> str:
        result = []
        for part in parts:
            if isinstance(part, str):
                result.append(part)
            else:
                code = self.render(part.parts, filename)
                result.append(self.execute(code, filename, part.line))
        return "".join(result)


def _order(name: str, priority: int | None, ascending: bool) -> tuple[bool, int, str]:
    number = 0 if priority is None else priority
    return priority is None, number if ascending else -number, name


def _process_directory(
    source: Path, output: Path | None, context: Context, ascending: bool
) -> None:
    defaults = folder_settings(source)
    if defaults.delete:
        output = None
    if output is not None:
        output.mkdir()
    files = []
    directories = []
    for entry in source.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            settings = folder_settings(entry)
            directories.append((entry, settings.priority))
        elif entry.name != SERVICE_FILE:
            if entry.is_symlink():
                files.append((entry, defaults, None, 1))
            elif entry.is_file():
                settings, body, line = file_settings(entry.read_bytes(), defaults)
                files.append((entry, settings, body, line))
            else:
                raise ProcessingError(f"{entry}: unsupported filesystem entry")

    files.sort(key=lambda item: _order(item[0].name, item[1].priority, ascending))
    directories.sort(key=lambda item: _order(item[0].name, item[1], ascending))
    for entry, settings, body, first_line in files:
        target = output / entry.name if output is not None and not settings.delete else None
        if entry.is_symlink():
            if target is not None:
                target.symlink_to(os.readlink(entry))
            continue
        if settings.delimiters is not None:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ProcessingError(f"{entry}: meta-text must be UTF-8") from error
            parts = parse_text(text, settings.delimiters, entry, first_line)
            body = context.render(parts, entry).encode("utf-8")
        if target is not None:
            target.write_bytes(body)
            shutil.copymode(entry, target)

    for entry, _ in directories:
        _process_directory(
            entry, output / entry.name if output is not None else None, context, ascending
        )


def process_repository(
    source: str | Path,
    destination: str | Path,
    *,
    ascending: bool = True,
    memory: Any = _UNSET,
) -> Any:
    """Create a new output repository and return its final shared memory."""
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("source and destination directories must not overlap")
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    context = Context(memory)
    # Publish only a fully processed tree. On failure the staged output is removed.
    with tempfile.TemporaryDirectory(prefix=".metarepo-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "output"
        _process_directory(source, staged, context, ascending)
        # A deleted source root still publishes an empty destination directory.
        staged.mkdir(exist_ok=True)
        staged.rename(destination)
    return context.memory
