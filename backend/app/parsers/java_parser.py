"""Java/Spring parser for controller and service business logic."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from backend.app.parsers.base import BaseParser, KnowledgeDocument, SourceFile
from backend.app.utils.text import normalize_ws, unique_keep_order


CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
ANNOTATION_RE = re.compile(r"@([A-Za-z_]\w+)(?:\((.*?)\))?", re.DOTALL)
METHOD_RE = re.compile(
    r"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\{",
    re.DOTALL,
)
CALL_RE = re.compile(r"\b([a-z][A-Za-z0-9_]*)\.([A-Za-z_]\w*)\s*\(")
IF_RE = re.compile(r"\bif\s*\((.*?)\)\s*\{?", re.DOTALL)
THROW_RE = re.compile(r"throw\s+new\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;", re.DOTALL)
STRING_RE = re.compile(r'"([^"]+)"')
ROLE_RE = re.compile(r"(?:hasRole|hasAuthority|hasPermission)\s*\(\s*\"([A-Z0-9_:.-]+)\"")
MAPPER_RE = re.compile(r"\b([a-z][A-Za-z0-9_]*Mapper)\.([A-Za-z_]\w*)\s*\(")
SERVICE_RE = re.compile(r"\b([a-z][A-Za-z0-9_]*Service)\.([A-Za-z_]\w*)\s*\(")


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char == '"':
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text) - 1


def _extract_annotations(block: str) -> Dict[str, str]:
    return {name: normalize_ws(args or "") for name, args in ANNOTATION_RE.findall(block)}


def _extract_path(annotation_args: str) -> Optional[str]:
    if not annotation_args:
        return None
    direct = re.search(r'"([^"]+)"', annotation_args)
    if direct:
        return direct.group(1)
    value = re.search(r"value\s*=\s*\"([^\"]+)\"", annotation_args)
    return value.group(1) if value else None


def _mapping_method(annotation_name: str, annotation_args: str) -> Optional[str]:
    mapping = {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "PatchMapping": "PATCH",
        "DeleteMapping": "DELETE",
    }
    if annotation_name in mapping:
        return mapping[annotation_name]
    if annotation_name == "RequestMapping":
        match = re.search(r"RequestMethod\.([A-Z]+)", annotation_args)
        return match.group(1) if match else None
    return None


def _join_paths(prefix: Optional[str], path: Optional[str]) -> Optional[str]:
    if not prefix and not path:
        return None
    left = (prefix or "").rstrip("/")
    right = (path or "").lstrip("/")
    joined = f"{left}/{right}" if right else left
    return joined if joined.startswith("/") else f"/{joined}"


def _iter_methods(text: str) -> Iterable[Tuple[str, str, int, int, str]]:
    for match in METHOD_RE.finditer(text):
        start = match.start()
        annotation_block = _annotation_block_before(text, start)
        open_index = text.find("{", match.start())
        close_index = _find_matching_brace(text, open_index)
        yield match.group(1), text[match.start() : close_index + 1], match.start(), close_index, annotation_block


def _annotation_block_before(text: str, start: int) -> str:
    lines = text[:start].splitlines()
    index = len(lines) - 1
    while index >= 0 and not lines[index].strip():
        index -= 1
    collected: List[str] = []
    while index >= 0 and lines[index].lstrip().startswith("@"):
        collected.insert(0, lines[index])
        index -= 1
    return "\n".join(collected)


def _extract_throw_messages(body: str) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    for exception_type, args in THROW_RE.findall(body):
        strings = STRING_RE.findall(args)
        if strings:
            error_code = strings[0] if len(strings) > 1 and re.match(r"E_[A-Z0-9_]+", strings[0]) else ""
            errors.append(
                {
                    "exception_type": exception_type,
                    "error_code": error_code,
                    "message": strings[-1],
                }
            )
    return errors


def _business_rules(conditions: List[str], roles: List[str], errors: List[Dict[str, str]]) -> List[str]:
    rules: List[str] = []
    for role in roles:
        rules.append(f"{role} 권한이 없으면 처리할 수 없다.")
    for condition in conditions:
        compact = normalize_ws(condition)
        if "getCustomerNo" in compact or "customerNo" in compact:
            rules.append("고객번호가 없으면 처리할 수 없다.")
        elif "CLOSED" in compact:
            rules.append("고객 상태가 CLOSED이면 수정할 수 없다.")
        elif "APPROVE" in compact or "승인" in compact:
            rules.append("승인 권한과 전표 상태를 확인해야 한다.")
        else:
            rules.append(f"{compact} 조건을 확인한다.")
    for error in errors:
        rules.append(f"'{error['message']}' 오류가 발생할 수 있다.")
    return unique_keep_order(rules)


def _possible_errors(
    conditions: List[str], roles: List[str], errors: List[Dict[str, str]]
) -> List[Dict[str, object]]:
    possible: List[Dict[str, object]] = []
    for role in roles:
        possible.append(
            {
                "condition": f"사용자에게 {role} 권한 없음",
                "message": "권한 오류",
                "branch_guide": "업무 권한 담당자 또는 IT부서에 해당 권한 보유 여부를 확인해야 합니다.",
                "confidence": 0.8,
            }
        )
    for index, error in enumerate(errors):
        condition = conditions[index] if index < len(conditions) else "예외 조건 충족"
        message = error["message"]
        possible.append(
            {
                "error_code": error.get("error_code", ""),
                "condition": normalize_ws(condition),
                "message": message,
                "branch_guide": _guide_from_message(message),
                "confidence": 0.85,
            }
        )
    return possible


def _guide_from_message(message: str) -> str:
    if "권한" in message:
        return "해당 업무 처리 권한이 있는지 확인해야 합니다."
    if "고객번호" in message:
        return "고객번호가 정상 입력되었는지 확인해야 합니다."
    if "해지" in message or "CLOSED" in message:
        return "고객 상태가 해지 또는 수정 제한 상태인지 확인해야 합니다."
    if "승인" in message:
        return "전표 승인 권한과 전표 상태를 확인해야 합니다."
    return "화면의 오류 문구와 입력값을 확인한 뒤 IT부서에 전달해야 합니다."


class JavaParser(BaseParser):
    """Extract Spring mappings, method calls, conditions, and exceptions."""

    supported_extensions = [".java"]

    def parse(self, source: SourceFile) -> List[KnowledgeDocument]:
        text = source.text
        class_match = CLASS_RE.search(text)
        class_name = class_match.group(1) if class_match else source.path.stem
        class_annotations = _extract_annotations(text[: class_match.start()] if class_match else text[:500])
        class_path = _extract_path(class_annotations.get("RequestMapping", ""))
        is_controller = "RestController" in class_annotations or "Controller" in class_annotations
        is_service = "Service" in class_annotations or class_name.endswith("Service")
        docs: List[KnowledgeDocument] = []

        for method_name, body, start, end, annotation_block in _iter_methods(text):
            annotations = _extract_annotations(annotation_block)
            mapping_name = next((name for name in annotations if name.endswith("Mapping")), None)
            api_path = None
            http_method = None
            if mapping_name:
                api_path = _join_paths(class_path, _extract_path(annotations.get(mapping_name, "")))
                http_method = _mapping_method(mapping_name, annotations.get(mapping_name, ""))

            calls = unique_keep_order(f"{owner}.{method}" for owner, method in CALL_RE.findall(body))
            mapper_calls = unique_keep_order(f"{owner[0].upper()}{owner[1:]}.{method}" for owner, method in MAPPER_RE.findall(body))
            service_calls = unique_keep_order(
                f"{owner[0].upper()}{owner[1:]}.{method}" for owner, method in SERVICE_RE.findall(body)
            )
            conditions = unique_keep_order(match.group(1).strip() for match in IF_RE.finditer(body))
            errors = _extract_throw_messages(body)
            roles = unique_keep_order(ROLE_RE.findall(body))
            doc_type = "backend_controller" if is_controller or api_path else "backend_service"
            if conditions or errors:
                doc_type = "business_logic" if is_service else doc_type
            summary = _summary(class_name, method_name, api_path, calls, conditions, errors)
            possible_errors = _possible_errors(conditions, roles, errors)
            docs.append(
                KnowledgeDocument(
                    doc_type=doc_type,
                    title=f"{class_name}.{method_name}",
                    summary=summary,
                    source_path=str(source.path),
                    api_path=api_path,
                    http_method=http_method,
                    class_name=class_name,
                    method_name=method_name,
                    error_codes=[error.get("error_code", "") for error in errors if error.get("error_code")],
                    error_messages=[error["message"] for error in errors],
                    business_rules=_business_rules(conditions, roles, errors),
                    possible_errors=possible_errors,
                    branch_guide=_branch_guide(possible_errors),
                    it_guide=f"{class_name}.{method_name} calls: {', '.join(calls)}",
                    code_text=body,
                    start_line=_line_no(text, start),
                    end_line=_line_no(text, end),
                    metadata={
                        "annotations": annotations,
                        "called_methods": calls,
                        "mapper_calls": mapper_calls,
                        "service_calls": service_calls,
                        "if_conditions": conditions,
                        "auth_codes": roles,
                    },
                )
            )
        return docs


def _summary(
    class_name: str,
    method_name: str,
    api_path: Optional[str],
    calls: List[str],
    conditions: List[str],
    errors: List[Dict[str, str]],
) -> str:
    parts = [f"{class_name}.{method_name} 처리 로직"]
    if api_path:
        parts.append(f"{api_path} 요청을 처리한다")
    if calls:
        parts.append("호출: " + ", ".join(calls))
    if conditions:
        parts.append("조건 검증: " + "; ".join(normalize_ws(condition) for condition in conditions))
    if errors:
        parts.append("오류: " + ", ".join(error["message"] for error in errors))
    return ". ".join(parts)


def _branch_guide(possible_errors: List[Dict[str, object]]) -> str:
    guides = unique_keep_order(str(error.get("branch_guide", "")) for error in possible_errors)
    return " ".join(guides)
