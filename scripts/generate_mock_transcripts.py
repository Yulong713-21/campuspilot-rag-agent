from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")


def register_font() -> str:
    font_name = "MicrosoftYaHei"
    pdfmetrics.registerFont(TTFont(font_name, str(FONT_PATH)))
    return font_name


def build_transcript(
    path: Path,
    *,
    institution: str,
    student_name: str,
    student_id: str,
    major: str,
    summary_lines: list[str],
    courses: list[list[str]],
) -> None:
    font_name = register_font()
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font_name
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    story = [
        Paragraph(f"<b>{institution}</b>", styles["Title"]),
        Paragraph("本科生成绩单 / Undergraduate Academic Transcript", styles["Heading2"]),
        Paragraph("模拟数据，仅用于 CampusPilot 解析测试", styles["Normal"]),
        Spacer(1, 6 * mm),
        Table(
            [
                ["姓名", student_name, "学号", student_id],
                ["学校", institution, "专业", major],
            ],
            colWidths=[24 * mm, 56 * mm, 24 * mm, 56 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB7B2")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2EF")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EAF2EF")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 5 * mm),
    ]
    table_data = [["课程代码", "课程名称", "学分", "成绩", "等级"], *courses]
    story.append(
        Table(
            table_data,
            colWidths=[27 * mm, 78 * mm, 18 * mm, 18 * mm, 18 * mm],
            repeatRows=1,
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F7D67")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C5C0")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8F7")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            ),
        )
    )
    story.extend(Spacer(1, 5 * mm) for _ in range(1))
    for line in summary_lines:
        story.append(Paragraph(line, styles["Normal"]))
    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph("本文件为虚构样本，不代表任何真实学生或高校记录。", styles["Normal"]),
        ]
    )
    document.build(story)


def build_scanned_copy(source_pdf: Path, target_pdf: Path) -> None:
    del source_pdf
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(FONT_PATH), 42)
    body_font = ImageFont.truetype(str(FONT_PATH), 24)
    small_font = ImageFont.truetype(str(FONT_PATH), 21)
    draw.text((390, 80), "华东示范大学", fill="#173D34", font=title_font)
    draw.text((330, 145), "本科生成绩单（扫描模拟件）", fill="black", font=body_font)
    draw.text((70, 220), "姓名：测试学生丙    学号：MOCK20260003", fill="black", font=body_font)
    draw.text((70, 270), "学校：华东示范大学  专业：软件工程", fill="black", font=body_font)
    rows = [
        "课程代码    课程名称             学分    成绩    等级",
        "CS101       程序设计基础         3       88      A",
        "CS201       数据结构             3       86      A",
        "CS202       数据库系统           3       82      B+",
        "MA102       高等数学             4       79      B+",
        "ST201       概率论与数理统计     3       84      A-",
    ]
    y = 355
    for index, row in enumerate(rows):
        fill = "#FFFFFF" if index == 0 else "#111111"
        if index == 0:
            draw.rectangle((60, y - 10, 1180, y + 42), fill="#2F7D67")
        draw.text((80, y), row, fill=fill, font=small_font)
        draw.line((60, y + 48, 1180, y + 48), fill="#AAB7B2", width=2)
        y += 72
    draw.text((70, y + 40), "已获学分：60", fill="black", font=body_font)
    draw.text((70, y + 90), "加权平均分：82.35", fill="black", font=body_font)
    draw.text((70, y + 140), "模拟数据，仅用于 CampusPilot OCR 分支测试", fill="#A33A2B", font=body_font)
    image.save(target_pdf, "PDF", resolution=144.0)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    percentage_path = OUTPUT_DIR / "mock_china_percentage_transcript.pdf"
    gpa_path = OUTPUT_DIR / "mock_china_gpa_transcript.pdf"
    scanned_path = OUTPUT_DIR / "mock_china_scanned_transcript.pdf"
    build_transcript(
        percentage_path,
        institution="华东示范大学",
        student_name="测试学生甲",
        student_id="MOCK20260001",
        major="计算机科学与技术",
        summary_lines=["已获学分：60", "加权平均分：82.35", "平均学分绩点：3.45 / 4.0"],
        courses=[
            ["CS101", "程序设计基础", "3", "88", "A"],
            ["CS201", "数据结构", "3", "86", "A"],
            ["CS202", "数据库系统", "3", "82", "B+"],
            ["MA102", "高等数学", "4", "79", "B+"],
            ["ST201", "概率论与数理统计", "3", "84", "A-"],
        ],
    )
    build_transcript(
        gpa_path,
        institution="南方示范学院",
        student_name="测试学生乙",
        student_id="MOCK20260002",
        major="金融学",
        summary_lines=["Completed Credits: 72", "GPA：3.62 / 4.0"],
        courses=[
            ["BUS201", "Financial Accounting", "3", "86", "A-"],
            ["BUS205", "Corporate Finance", "3", "90", "A"],
            ["ECO210", "Microeconomics", "3", "83", "B+"],
            ["STA210", "Business Statistics", "3", "88", "A-"],
        ],
    )
    build_scanned_copy(percentage_path, scanned_path)
    for path in (percentage_path, gpa_path, scanned_path):
        print(path)


if __name__ == "__main__":
    main()
