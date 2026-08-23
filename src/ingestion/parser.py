import sys
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from loguru import logger

from src.ingestion.table_extractor import TABLE_SETTINGS, extract_markdown


class UnreadableDocumentError(RuntimeError):
    """원본이 파서로 읽을 수 없는 상태(DRM 암호화·포맷 불일치·손상).

    라이브러리 기본 예외("Input document is not valid")는 원인을 알려주지 않아
    운영자가 조치할 수 없다. 적재 리포트만 보고 **무엇을 해야 하는지** 알 수 있도록
    원인을 판별해 메시지에 담는다.
    """


# 파일 선두 시그니처로 판별하는 '읽을 수 없는 원본' 패턴.
# DRM 은 금융/공공 문서에서 흔하다(사내 유출방지 솔루션). 복호화 권한 없이는
# 어떤 파서도 못 읽으므로, **조용히 실패하지 말고 원인을 명시**해야 한다.
_DRM_MARKERS: tuple[tuple[bytes, str], ...] = (
    (b"FasooSecureContainer", "Fasoo DRM 으로 암호화됨"),
    (b"MarkAny", "MarkAny DRM 으로 암호화됨"),
    (b"SoftCamp", "SoftCamp DRM 으로 암호화됨"),
)
_MAGIC = {".pdf": (b"%PDF",), ".docx": (b"PK\x03\x04",)}


def diagnose_unreadable(path: Path) -> str | None:
    """읽을 수 없는 원본이면 사람이 읽을 수 있는 사유, 정상이면 None."""
    try:
        head = path.open("rb").read(512)
    except OSError as e:
        return f"파일을 열 수 없음: {e}"
    for marker, reason in _DRM_MARKERS:
        if marker in head:
            return f"{reason} — 복호화된 사본이 필요(파이프라인에서 처리 불가)"
    expected = _MAGIC.get(path.suffix.lower())
    if expected and not any(head.startswith(m) for m in expected):
        return (
            f"{path.suffix} 확장자지만 실제 포맷이 다름"
            f"(선두 바이트={head[:8]!r}) — 확장자만 바뀐 파일일 수 있음"
        )
    return None


class PDFParser:
    """PDF -> Markdown with a routed strategy.

    Korean financial PDFs (BNK 약관/설명서) are born-digital and wrap content in
    vector-ruled tables. Docling's vision-based TableFormer scrambles those
    line-bordered, merged-cell tables (dropped sub-tables, mismatched
    period<->rate), so for such PDFs we reconstruct tables deterministically
    from the ruling lines via pdfplumber (see ``table_extractor``).

    PDFs without a usable text layer (scanned) or without ruled tables (other
    layouts) fall back to Docling with a Korean OCR backend, keeping the parser
    general-purpose.
    """

    # A page needs at least this many text-layer chars to count as digital.
    MIN_CHARS_PER_PAGE = 50

    # 처리 가능한 원본 포맷. ``.docx`` 는 Docling 이 네이티브로 읽는다 —
    # 실무 자료가 늘 PDF 로만 오지 않아서(예: 개정후 약관이 docx 로만 존재) 필요.
    # docx 는 페이지/괘선 개념이 없으므로 lattice 라우팅을 건너뛰고 바로 Docling.
    SUPPORTED_SUFFIXES = (".pdf", ".docx")

    def __init__(self, output_base_dir: Path):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        # OCR 유무별로 컨버터를 따로 캐시한다(둘 다 무거워 lazy).
        self._docling: dict[bool, object] = {}

    # ----- strategy detection -------------------------------------------------
    def _profile(self, pdf_path: Path) -> tuple[bool, bool]:
        """Return (has_text_layer, has_ruled_tables)."""
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False, False
            chars = sum(len(p.get_text("text").strip()) for p in doc)
            has_text = chars / doc.page_count >= self.MIN_CHARS_PER_PAGE
        has_tables = False
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                if page.find_tables(TABLE_SETTINGS):
                    has_tables = True
                    break
        return has_text, has_tables

    # ----- Docling fallback ---------------------------------------------------
    def _build_docling(self, ocr: bool):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            RapidOcrOptions,
            TableFormerMode,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        po = PdfPipelineOptions()
        po.do_ocr = ocr  # 이미지로 렌더된 글자(스캔·도장) 복구용 — 텍스트레이어가 있으면 불필요
        if ocr:
            po.ocr_options = RapidOcrOptions(lang=["korean", "english"])
        po.do_table_structure = True
        po.table_structure_options.mode = TableFormerMode.ACCURATE
        po.table_structure_options.do_cell_matching = True
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=po)}
        )

    def _parse_with_docling(self, pdf_path: Path, ocr: bool = True) -> str:
        """Docling 변환. ``ocr=False`` 면 OCR 단계를 건너뛴다.

        **왜 조건부인가(성능).** OCR 은 텍스트레이어가 *없을 때* 글자를 복구하는 수단인데,
        무조건 켜두면 born-digital 문서에서도 전 페이지를 렌더·인식한다 = 순수 낭비.
        펀드 약관(평균 26p, 전부 text_layer=True)에서 이 낭비가 치명적이었다 —
        문서당 ~5.5분, 326건이면 30시간 규모. 텍스트레이어가 있으면 끄는 게 맞다.

        한계(정직): 대부분 디지털인 문서에 **일부 스캔 페이지**가 섞여 있으면 그 페이지의
        글자는 못 얻는다. 판정은 `_profile` 의 평균 글자수(페이지당 50자) 기준이라
        문서 단위이지 페이지 단위가 아니다. 스캔 혼재가 문제되면 페이지 단위 판정으로
        올려야 한다(현 코퍼스에선 미발생).
        """
        if ocr not in self._docling:
            logger.info(f"Loading Docling (ocr={ocr})...")
            self._docling[ocr] = self._build_docling(ocr)
        result = self._docling[ocr].convert(pdf_path)
        return result.document.export_to_markdown()

    # ----- public API ---------------------------------------------------------
    def parse(self, pdf_path: str | Path, force: bool = False) -> Path:
        pdf_path = Path(pdf_path)
        result_dir = self.output_base_dir / pdf_path.stem
        result_dir.mkdir(parents=True, exist_ok=True)
        out_md = result_dir / f"{pdf_path.stem}.md"

        # Cache: skip the (slow, esp. Docling) parse if the MD already exists.
        # Makes re-ingestion fast and idempotent. Pass force=True to re-parse.
        if out_md.exists() and not force:
            logger.info(f"{pdf_path.name}: cached MD exists, skip parse")
            return out_md

        # 파싱을 시도하기 전에 '애초에 읽을 수 없는 원본'을 걸러 원인을 명시한다.
        # (DRM 문서를 그냥 던지면 "not valid" 만 남아 운영자가 원인을 못 찾는다.)
        if (reason := diagnose_unreadable(pdf_path)) is not None:
            raise UnreadableDocumentError(f"{pdf_path.name}: {reason}")

        # docx: 페이지·괘선이 없어 라우팅 판정(_profile)이 성립하지 않는다 → 바로 Docling.
        if pdf_path.suffix.lower() == ".docx":
            try:
                md = self._parse_with_docling(pdf_path, ocr=False)  # docx 는 텍스트가 이미 있음
            except Exception as e:
                logger.error(f"Error parsing {pdf_path.name}: {e}")
                raise
            logger.info(f"{pdf_path.name}: docx -> strategy=docling")
            out_md.write_text(md, encoding="utf-8")
            logger.success(f"Converted: {pdf_path.name} -> {out_md} ({len(md)} chars)")
            return out_md

        has_text, has_tables = self._profile(pdf_path)
        try:
            if has_text and has_tables:
                strategy = "lattice (pdfplumber)"
                md = extract_markdown(str(pdf_path))
            else:
                # 텍스트레이어가 있으면 OCR 불필요(순수 낭비) → 있으면 끈다.
                use_ocr = not has_text
                strategy = "docling+rapidocr" if use_ocr else "docling (no-ocr)"
                md = self._parse_with_docling(pdf_path, ocr=use_ocr)
        except Exception as e:
            logger.error(f"Error parsing {pdf_path.name}: {e}")
            raise

        logger.info(
            f"{pdf_path.name}: text_layer={has_text} ruled_tables={has_tables} "
            f"-> strategy={strategy}"
        )
        out_md = result_dir / f"{pdf_path.stem}.md"
        out_md.write_text(md, encoding="utf-8")
        logger.success(f"Converted: {pdf_path.name} -> {out_md} ({len(md)} chars)")
        return out_md


if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from src.config import settings

    parser = PDFParser(settings.processed_dir)
    raw_files = sorted(settings.raw_dir.rglob("*.pdf"))
    if not raw_files:
        logger.warning(f"No PDF files found in {settings.raw_dir}")
    else:
        test_file = next(
            (f for f in raw_files if "마이플랜퇴직연금정기예금" in f.name), raw_files[0]
        )
        logger.info(f"Testing with file: {test_file}")
        parser.parse(test_file)
