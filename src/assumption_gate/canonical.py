from __future__ import annotations

import json
from typing import Any, Callable

PROFILE_VERSION = "eba.canonical-json/v1"
MAX_SAFE_INTEGER = 9007199254740991


def _validate(value: Any, error: Callable[[str], Exception], path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise error(f"CANONICAL_STRING_INVALID:{path}")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise error(f"CANONICAL_INTEGER_OUT_OF_RANGE:{path}")
        return
    if isinstance(value, float):
        raise error(f"CANONICAL_NON_INTEGER_NUMBER:{path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, error, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise error(f"CANONICAL_OBJECT_KEY_INVALID:{path}")
            _validate(key, error, f"{path}.<key>")
            _validate(item, error, f"{path}.{key}")
        return
    raise error(f"CANONICAL_TYPE_UNSUPPORTED:{path}")


def _string(value: str, error: Callable[[str], Exception]) -> str:
    _validate(value, error)
    rendered = json.dumps(value, ensure_ascii=False)
    return (
        rendered
        .replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


def _text(value: Any, error: Callable[[str], Exception]) -> str:
    _validate(value, error)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value, error)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_text(item, error) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            _string(key, error) + ":" + _text(value[key], error)
            for key in sorted(value)
        ) + "}"
    raise error("CANONICAL_TYPE_UNSUPPORTED")


def canonical_json_bytes(
    value: dict[str, Any],
    *,
    error: Callable[[str], Exception] = ValueError,
) -> bytes:
    if not isinstance(value, dict):
        raise error("CANONICAL_ROOT_MUST_BE_OBJECT")
    return _text(value, error).encode("utf-8")


def strict_json_loads(
    raw: str | bytes | bytearray,
    *,
    error: Callable[[str], Exception] = ValueError,
) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise error(f"CANONICAL_DUPLICATE_KEY:{key}")
            out[key] = value
        return out

    def parse_int(token: str) -> int:
        if token == "-0":
            raise error("CANONICAL_NEGATIVE_ZERO")
        value = int(token, 10)
        if abs(value) > MAX_SAFE_INTEGER:
            raise error("CANONICAL_INTEGER_OUT_OF_RANGE")
        return value

    def reject_number(token: str) -> Any:
        raise error(f"CANONICAL_NON_INTEGER_NUMBER:{token}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=object_pairs,
            parse_int=parse_int,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error("CANONICAL_JSON_INVALID") from exc
    _validate(value, error)
    return value
