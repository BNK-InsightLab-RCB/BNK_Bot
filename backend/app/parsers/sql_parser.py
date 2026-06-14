"""SQL parser for table, column, parameter, and condition extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from backend.app.parsers.base import BaseParser, KnowledgeDocument, SourceFile
from backend.app.utils.text import normalize_ws, unique_keep_order


SQL_COMMENT_RE = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)
PARAM_RE = re.compile(r"[#\$]\{\s*([A-Za-z_][\w.]*)\s*\}")
TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([A-Za-z_][\w.]*)(?:\s+[A-Za-z_][\w]*)?",
    re.IGNORECASE,
)
WHERE_RE = re.compile(
    r"\bWHERE\b(?P<body>.*?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b|$)",
    re.IGNORECASE | re.DOTALL,
)
JOIN_RE = re.compile(r"\bJOIN\s+([A-Za-z_][\w.]*)\s+(?:[A-Za-z_][\w]*)?\s*ON\s+(.*?)(?=\bJOIN\b|\bWHERE\b|$)", re.IGNORECASE | re.DOTALL)


def clean_sql(sql: str) -> str:
    """Remove comments and normalize SQL whitespace."""
    return normalize_ws(SQL_COMMENT_RE.sub(" ", sql or ""))


def extract_crud(sql: str) -> str:
    """Return the leading SQL operation."""
    match = re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE)\b", sql, re.IGNORECASE)
    return match.group(1).upper() if match else "SQL"


def extract_tables(sql: str) -> List[str]:
    """Extract table names after FROM, JOIN, UPDATE, and INTO."""
    return unique_keep_order(match.group(1).split(".")[-1].upper() for match in TABLE_RE.finditer(sql))


def extract_parameters(sql: str) -> List[str]:
    """Extract MyBatis-style SQL parameters."""
    return unique_keep_order(match.group(1) for match in PARAM_RE.finditer(sql))


def extract_where_conditions(sql: str) -> List[str]:
    """Extract simple WHERE conditions split on AND."""
    match = WHERE_RE.search(sql)
    if not match:
        return []
    body = match.group("body").strip().rstrip(";")
    if not body:
        return []
    parts = re.split(r"\s+\bAND\b\s+", body, flags=re.IGNORECASE)
    return unique_keep_order(part.strip(" ()") for part in parts)


def extract_join_conditions(sql: str) -> List[str]:
    """Extract JOIN table and ON condition summaries."""
    joins: List[str] = []
    for match in JOIN_RE.finditer(sql):
        table = match.group(1).split(".")[-1].upper()
        condition = normalize_ws(match.group(2)).strip(" ;")
        joins.append(f"{table} ON {condition}")
    return unique_keep_order(joins)


def extract_columns(sql: str) -> List[str]:
    """Extract likely column names from SELECT and WHERE clauses."""
    columns: List[str] = []
    select_match = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
    if select_match:
        for item in select_match.group(1).split(","):
            token = re.sub(r"\bAS\b\s+\w+$", "", item.strip(), flags=re.IGNORECASE)
            token = token.split(".")[-1].strip()
            token = re.sub(r"[^A-Za-z0-9_]", "", token)
            if token and token != "*":
                columns.append(token.upper())
    for condition in extract_where_conditions(sql):
        left = re.split(r"=|<>|!=|>=|<=|>|<|\bLIKE\b|\bIN\b", condition, flags=re.IGNORECASE)[0]
        token = left.split(".")[-1].strip()
        token = re.sub(r"[^A-Za-z0-9_]", "", token)
        if token:
            columns.append(token.upper())
    return unique_keep_order(columns)


def analyze_sql(sql: str) -> Dict[str, List[str]]:
    """Return SQL analysis fields used by MyBatis and .sql parsing."""
    cleaned = clean_sql(sql)
    return {
        "crud": [extract_crud(cleaned)],
        "tables": extract_tables(cleaned),
        "columns": extract_columns(cleaned),
        "where_conditions": extract_where_conditions(cleaned),
        "parameters": extract_parameters(cleaned),
        "joins": extract_join_conditions(cleaned),
    }


class SqlParser(BaseParser):
    """Parse raw `.sql` files into one document per statement."""

    supported_extensions = [".sql"]

    def parse(self, source: SourceFile) -> List[KnowledgeDocument]:
        statements = [stmt.strip() for stmt in re.split(r";\s*(?:\n|$)", source.text) if stmt.strip()]
        docs: List[KnowledgeDocument] = []
        for index, statement in enumerate(statements, start=1):
            analysis = analyze_sql(statement)
            crud = analysis["crud"][0]
            tables = analysis["tables"]
            title = f"{Path(source.path).name} statement {index}"
            summary = f"{crud} SQL" + (f" uses {', '.join(tables)}." if tables else ".")
            docs.append(
                KnowledgeDocument(
                    doc_type="sql_mapper",
                    title=title,
                    summary=summary,
                    source_path=str(source.path),
                    tables=tables,
                    columns=analysis["columns"],
                    business_rules=[
                        f"WHERE 조건: {condition}" for condition in analysis["where_conditions"]
                    ],
                    code_text=statement,
                    metadata={
                        "crud": crud,
                        "where_conditions": analysis["where_conditions"],
                        "parameters": analysis["parameters"],
                        "joins": analysis["joins"],
                    },
                )
            )
        return docs
