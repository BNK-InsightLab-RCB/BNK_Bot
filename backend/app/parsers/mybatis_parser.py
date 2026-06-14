"""MyBatis XML parser."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List

from backend.app.parsers.base import BaseParser, KnowledgeDocument, SourceFile
from backend.app.parsers.sql_parser import analyze_sql, clean_sql


CRUD_TAGS = {"select": "SELECT", "insert": "INSERT", "update": "UPDATE", "delete": "DELETE"}


def _line_for_token(text: str, token: str) -> int:
    index = text.find(token)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def _read_xml(text: str) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(text, parser=parser)


def _tag_name(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


class MyBatisParser(BaseParser):
    """Extract SQL statements from MyBatis mapper XML files."""

    supported_extensions = [".xml"]

    def parse(self, source: SourceFile) -> List[KnowledgeDocument]:
        root = _read_xml(source.text)
        namespace = root.attrib.get("namespace", source.path.stem)
        docs: List[KnowledgeDocument] = []
        for node in root.iter():
            tag = _tag_name(node.tag)
            if tag not in CRUD_TAGS:
                continue
            sql_id = f"{namespace}.{node.attrib.get('id', 'unknown')}"
            sql_text = clean_sql(" ".join(node.itertext()))
            analysis = analyze_sql(sql_text)
            crud = CRUD_TAGS[tag]
            where_rules = [f"WHERE 조건: {condition}" for condition in analysis["where_conditions"]]
            possible_issue = _possible_issue(analysis["where_conditions"])
            business_rules = where_rules + ([possible_issue] if possible_issue else [])
            docs.append(
                KnowledgeDocument(
                    doc_type="sql_mapper",
                    title=sql_id,
                    summary=_summary(sql_id, crud, analysis["tables"], analysis["where_conditions"]),
                    source_path=str(source.path),
                    sql_id=sql_id,
                    tables=analysis["tables"],
                    columns=analysis["columns"],
                    business_rules=business_rules,
                    branch_guide=possible_issue,
                    it_guide=f"{sql_id} {crud} uses {', '.join(analysis['tables'])}",
                    code_text=sql_text,
                    start_line=_line_for_token(source.text, node.attrib.get("id", "")),
                    end_line=_line_for_token(source.text, node.attrib.get("id", "")) + sql_text.count("\n"),
                    metadata={
                        "namespace": namespace,
                        "crud": crud,
                        "parameterType": node.attrib.get("parameterType"),
                        "resultType": node.attrib.get("resultType"),
                        "parameters": analysis["parameters"],
                        "where_conditions": analysis["where_conditions"],
                        "joins": analysis["joins"],
                    },
                )
            )
        return docs


def _summary(sql_id: str, crud: str, tables: List[str], conditions: List[str]) -> str:
    table_part = f"{', '.join(tables)} 테이블" if tables else "테이블"
    condition_part = f" 조건은 {'; '.join(conditions)}" if conditions else ""
    return f"{sql_id}는 {table_part}에 대해 {crud} SQL을 수행한다.{condition_part}"


def _possible_issue(conditions: List[str]) -> str:
    text = " ".join(conditions)
    if re.search(r"USE_YN\s*=\s*'Y'", text, re.IGNORECASE):
        return "고객번호가 존재해도 사용 여부가 Y가 아니면 조회되지 않을 수 있습니다."
    if "STATUS" in text:
        return "상태값 조건에 맞지 않으면 조회 또는 수정 대상에서 제외될 수 있습니다."
    return ""
