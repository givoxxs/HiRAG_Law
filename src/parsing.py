import json
import re

# import fitz  # PyMuPDF - Tạm thời comment để tránh lỗi
import docx
import os
from typing import Dict, Any, List


def parse_law_document(file_path: str) -> Dict[str, Any]:
    """
    Phân tích một văn bản luật từ file PDF hoặc DOCX và trả về cấu trúc cây.
    Hỗ trợ cấu trúc thực tế của Bộ luật dân sự 2015: Phần -> Chương -> Mục (nếu có) -> Điều -> Khoản
    """
    file_extension = os.path.splitext(file_path)[1].lower()

    if file_extension == ".pdf":
        return parse_law_from_pdf(file_path)
    elif file_extension == ".docx":
        print("Đang phân tích file DOCX...")
        return parse_law_from_docx(file_path)
    else:
        raise ValueError(f"Định dạng file không được hỗ trợ: {file_extension}")


def parse_law_from_pdf(file_path: str) -> Dict[str, Any]:
    """Phân tích văn bản luật từ file PDF"""
    try:
        # Tạm thời comment để tránh lỗi fitz
        raise Exception(
            "PDF parsing tạm thời bị vô hiệu hóa do lỗi fitz. Vui lòng sử dụng file DOCX."
        )
        # doc = fitz.open(file_path)
        # full_text = ""
        # for page in doc:
        #     full_text += page.get_text() + "\n"
        # doc.close()
        #
        # return parse_law_text(full_text, file_path)
    except Exception as e:
        raise Exception(f"Lỗi khi đọc file PDF: {e}")


def parse_law_from_docx(file_path: str) -> Dict[str, Any]:
    """Phân tích văn bản luật từ file DOCX"""
    try:
        doc = docx.Document(file_path)
        full_text = ""
        for para in doc.paragraphs:
            if para.text.strip():
                full_text += para.text.strip() + "\n"

        return parse_law_text(full_text, file_path)
    except Exception as e:
        raise Exception(f"Lỗi khi đọc file DOCX: {e}")


def parse_law_text(text: str, source_file: str) -> Dict[str, Any]:
    """
    Phân tích nội dung văn bản luật theo cấu trúc thực tế:
    Phần -> Chương -> Mục (nếu có) -> Điều -> Khoản
    """
    print("Đang phân tích nội dung văn bản luật...")
    # Cấu trúc để lưu trữ cây phân cấp
    law_tree = {
        "metadata": {"source": source_file, "title": extract_title(text)},
        "content": {},
    }

    # Tách văn bản thành các dòng
    lines = text.split("\n")

    current_part = None
    current_chapter = None
    current_section = None
    current_article = None
    current_content = []

    # Debug counters
    debug_stats = {
        "parts": 0,
        "chapters": 0,
        "sections": 0,
        "articles": 0,
        "total_lines": len(lines),
    }

    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # Phát hiện PHẦN
        if re.match(r"^PHẦN THỨ [A-Z0-9IVXLCDM]+", line, re.IGNORECASE):
            # Lưu nội dung điều trước đó
            if current_article and current_content:
                save_article_content(
                    law_tree,
                    current_part,
                    current_chapter,
                    current_section,
                    current_article,
                    current_content,
                )

            current_part = line
            current_chapter = None
            current_section = None
            current_article = None
            current_content = []
            debug_stats["parts"] += 1

            if current_part not in law_tree["content"]:
                law_tree["content"][current_part] = {}

        # Phát hiện CHƯƠNG
        elif re.match(r"^CHƯƠNG [A-Z0-9IVXLCDM]+", line, re.IGNORECASE):
            # Lưu nội dung điều trước đó
            if current_article and current_content:
                save_article_content(
                    law_tree,
                    current_part,
                    current_chapter,
                    current_section,
                    current_article,
                    current_content,
                )

            current_chapter = line
            current_section = None
            current_article = None
            current_content = []
            debug_stats["chapters"] += 1

            if (
                current_part
                and current_chapter not in law_tree["content"][current_part]
            ):
                law_tree["content"][current_part][current_chapter] = {}

        # Phát hiện MỤC
        elif re.match(r"^Mục \d+", line, re.IGNORECASE):
            # Lưu nội dung điều trước đó
            if current_article and current_content:
                save_article_content(
                    law_tree,
                    current_part,
                    current_chapter,
                    current_section,
                    current_article,
                    current_content,
                )

            current_section = line
            current_article = None
            current_content = []
            debug_stats["sections"] += 1

            if current_part and current_chapter:
                if (
                    current_section
                    not in law_tree["content"][current_part][current_chapter]
                ):
                    law_tree["content"][current_part][current_chapter][
                        current_section
                    ] = {}

        # Phát hiện ĐIỀU
        elif re.match(r"^Điều \d+\.", line, re.IGNORECASE):
            # Lưu nội dung điều trước đó
            if current_article and current_content:
                save_article_content(
                    law_tree,
                    current_part,
                    current_chapter,
                    current_section,
                    current_article,
                    current_content,
                )

            current_article = line
            current_content = []
            debug_stats["articles"] += 1

        # Nội dung của điều (bao gồm cả tiêu đề mục nếu không có điều trong mục đó)
        else:
            if current_article:
                current_content.append(line)
            # Nếu không có điều hiện tại nhưng có chương hoặc mục, có thể là nội dung mô tả
            elif current_chapter or current_section:
                # Bỏ qua các dòng mô tả không phải nội dung điều
                pass

    # Lưu điều cuối cùng
    if current_article and current_content:
        save_article_content(
            law_tree,
            current_part,
            current_chapter,
            current_section,
            current_article,
            current_content,
        )

    # In debug info
    print(f"Debug parsing stats:")
    print(f"  - Tổng dòng xử lý: {debug_stats['total_lines']}")
    print(f"  - Phần: {debug_stats['parts']}")
    print(f"  - Chương: {debug_stats['chapters']}")
    print(f"  - Mục: {debug_stats['sections']}")
    print(f"  - Điều: {debug_stats['articles']}")

    # lưu cây vào file json
    with open("data/law_tree.json", "w", encoding="utf-8") as f:
        json.dump(law_tree, f, ensure_ascii=False, indent=4)
    print("Đã lưu cây vào file json")

    return law_tree


def extract_title(text: str) -> str:
    """Trích xuất tiêu đề văn bản luật"""
    lines = text.split("\n")
    for line in lines[:10]:  # Tìm trong 10 dòng đầu
        line = line.strip()
        if re.match(r"^BỘ LUẬT|^LUẬT|^NGHỊ ĐỊNH|^THÔNG TƯ", line, re.IGNORECASE):
            return line
    return "Văn bản luật"


def save_article_content(
    law_tree: Dict,
    part: str,
    chapter: str,
    section: str,
    article: str,
    content: List[str],
) -> None:
    """Lưu nội dung điều vào cấu trúc cây"""
    if not part or not chapter or not article:
        return

    # Xử lý nội dung điều, tách thành các khoản
    article_data = parse_article_content(content)

    # Đảm bảo cấu trúc tồn tại
    if part not in law_tree["content"]:
        law_tree["content"][part] = {}
    if chapter not in law_tree["content"][part]:
        law_tree["content"][part][chapter] = {}

    try:
        if section:
            # Có mục - điều nằm trong mục
            if section not in law_tree["content"][part][chapter]:
                law_tree["content"][part][chapter][section] = {}
            law_tree["content"][part][chapter][section][article] = article_data
        else:
            # Không có mục - điều trực tiếp trong chương
            law_tree["content"][part][chapter][article] = article_data

    except Exception as e:
        print(f"Lỗi khi lưu điều {article}: {e}")
        # Backup: lưu trực tiếp vào chương nếu có lỗi
        law_tree["content"][part][chapter][article] = article_data


def parse_article_content(content: List[str]) -> Dict[str, str]:
    """
    Phân tích nội dung điều thành các khoản.
    Các khoản có thể được đánh số hoặc phân biệt bằng đoạn văn.
    """
    if not content:
        return {}

    # Nối tất cả nội dung lại
    full_content = " ".join(content)

    # Cố gắng tách theo khoản được đánh số (1., 2., 3., ...)
    numbered_clauses = re.split(r"(\n?\d+\.\s*)", full_content)

    if len(numbered_clauses) > 1:
        # Có khoản được đánh số
        clauses = {}
        for i in range(1, len(numbered_clauses), 2):
            if i + 1 < len(numbered_clauses):
                clause_num = numbered_clauses[i].strip()
                clause_content = numbered_clauses[i + 1].strip()
                clauses[f"Khoản {clause_num}"] = clause_content
        return clauses
    else:
        # Không có khoản đánh số rõ ràng, coi như một khoản duy nhất
        return {"Khoản 1": full_content.strip()}


if __name__ == "__main__":
    # Ví dụ cách sử dụng
    try:
        # Thử với file DOCX trước
        docx_file = "data/bo_luat_dan_su_2015.docx"
        if os.path.exists(docx_file):
            print("Đang phân tích file DOCX...")
            parsed_data = parse_law_document(docx_file)

            # In một số thống kê
            print(f"Tiêu đề: {parsed_data['metadata']['title']}")
            print(f"Số phần: {len(parsed_data['content'])}")

            # In cấu trúc đầu tiên
            for part_name, part_content in list(parsed_data["content"].items())[:5]:
                print(f"\n{part_name}:")
                for chapter_name, chapter_content in list(part_content.items())[:5]:
                    print(f"  {chapter_name}:")
                    for item_name in list(chapter_content.keys())[:5]:
                        print(f"    {item_name}")
                        for article_name, article_content in list(
                            chapter_content[item_name].items()
                        )[:5]:
                            print(f"      {article_name}")
                            print(f"        {article_content}")

    except Exception as e:
        print(f"Lỗi: {e}")
        import traceback

        traceback.print_exc()
