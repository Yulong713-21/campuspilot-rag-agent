from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.request import urlretrieve

import pandas as pd


MOE_SOURCE_PAGE = (
    "https://www.moe.gov.cn/jyb_xxgk/s5743/s5744/202606/"
    "t20260618_1441074.html"
)
MOE_XLS_URL = (
    "https://www.moe.gov.cn/jyb_xxgk/s5743/s5744/202606/"
    "W020260618416094865984.xls"
)
TEQSA_REGISTER_URL = "https://www.teqsa.gov.au/national-register"
AU_GOVERNMENT_LIST_URL = (
    "https://www.education.gov.au/research-block-grants/"
    "higher-education-providers-eligible-research-block-grants"
)


CHINA_ALIASES = {
    "北京大学": ["北大"],
    "中国人民大学": ["人大"],
    "北京航空航天大学": ["北航"],
    "北京理工大学": ["北理工"],
    "北京科技大学": ["北科", "北科大"],
    "北京邮电大学": ["北邮"],
    "北京师范大学": ["北师大"],
    "北京外国语大学": ["北外"],
    "中央财经大学": ["央财"],
    "对外经济贸易大学": ["对外经贸", "贸大"],
    "中国科学院大学": ["国科大"],
    "上海交通大学": ["上交", "上海交大"],
    "华东师范大学": ["华师大", "华东师大"],
    "上海财经大学": ["上财"],
    "浙江大学": ["浙大"],
    "南京大学": ["南大"],
    "东南大学": ["东大"],
    "中国科学技术大学": ["中科大"],
    "武汉大学": ["武大"],
    "华中科技大学": ["华科", "华科大"],
    "中山大学": ["中大"],
    "华南理工大学": ["华工"],
    "四川大学": ["川大"],
    "电子科技大学": ["成电", "电子科大"],
    "西安交通大学": ["西交", "西安交大"],
    "西北工业大学": ["西工大"],
    "西安电子科技大学": ["西电"],
    "哈尔滨工业大学": ["哈工大"],
    "天津大学": ["天大"],
    "南开大学": ["南开"],
    "山东大学": ["山大"],
    "厦门大学": ["厦大"],
    "吉林大学": ["吉大"],
    "大连理工大学": ["大工"],
    "东北大学": ["东大", "东北大"],
    "湖南大学": ["湖大"],
    "中南大学": ["中南"],
    "重庆大学": ["重大"],
    "兰州大学": ["兰大"],
}


AUSTRALIAN_INSTITUTIONS = [
    ("Adelaide University", "阿德莱德大学", ["Adelaide Uni"]),
    ("Australian Catholic University", "澳大利亚天主教大学", ["ACU"]),
    ("Avondale University", "亚芳代尔大学", ["Avondale"]),
    ("Batchelor Institute of Indigenous Tertiary Education", "巴彻勒原住民高等教育学院", ["Batchelor Institute"]),
    ("Bond University", "邦德大学", ["Bond"]),
    ("Central Queensland University", "中央昆士兰大学", ["CQUniversity", "CQU"]),
    ("Charles Darwin University", "查尔斯达尔文大学", ["CDU"]),
    ("Charles Sturt University", "查尔斯特大学", ["CSU"]),
    ("Curtin University", "科廷大学", ["Curtin"]),
    ("Deakin University", "迪肯大学", ["Deakin"]),
    ("Edith Cowan University", "伊迪斯科文大学", ["ECU"]),
    ("Federation University Australia", "澳大利亚联邦大学", ["Federation University", "FedUni"]),
    ("Flinders University", "弗林德斯大学", ["Flinders"]),
    ("Griffith University", "格里菲斯大学", ["Griffith"]),
    ("James Cook University", "詹姆斯库克大学", ["JCU"]),
    ("La Trobe University", "拉筹伯大学", ["La Trobe"]),
    ("Macquarie University", "麦考瑞大学", ["Macquarie", "MQ"]),
    ("Monash University", "莫纳什大学", ["Monash"]),
    ("Murdoch University", "莫道克大学", ["Murdoch"]),
    ("Queensland University of Technology", "昆士兰科技大学", ["QUT"]),
    ("Royal Melbourne Institute of Technology", "皇家墨尔本理工大学", ["RMIT", "RMIT University"]),
    ("Southern Cross University", "南十字星大学", ["SCU"]),
    ("Swinburne University of Technology", "斯威本科技大学", ["Swinburne"]),
    ("Australian National University", "澳大利亚国立大学", ["The Australian National University", "ANU", "澳国立"]),
    ("The University of Melbourne", "墨尔本大学", ["University of Melbourne", "Melbourne University", "UniMelb"]),
    ("The University of Notre Dame Australia", "澳大利亚圣母大学", ["Notre Dame Australia", "UNDA"]),
    ("The University of Queensland", "昆士兰大学", ["University of Queensland", "UQ", "昆大"]),
    ("The University of Sydney", "悉尼大学", ["University of Sydney", "Sydney University", "USYD"]),
    ("The University of Western Australia", "西澳大学", ["University of Western Australia", "UWA"]),
    ("Torrens University Australia", "澳大利亚托伦斯大学", ["Torrens University"]),
    ("University of Canberra", "堪培拉大学", ["Canberra University", "UC"]),
    ("University of Divinity", "神学大学", ["Melbourne College of Divinity"]),
    ("University of Newcastle", "纽卡斯尔大学", ["The University of Newcastle", "UON"]),
    ("University of New England", "新英格兰大学", ["UNE"]),
    ("University of New South Wales", "新南威尔士大学", ["UNSW", "新南", "The University of New South Wales"]),
    ("University of Southern Queensland", "南昆士兰大学", ["UniSQ", "USQ"]),
    ("University of Tasmania", "塔斯马尼亚大学", ["UTAS", "Tasmania University"]),
    ("University of Technology Sydney", "悉尼科技大学", ["UTS"]),
    ("University of the Sunshine Coast", "阳光海岸大学", ["UniSC", "USC"]),
    ("University of Wollongong", "伍伦贡大学", ["UOW", "卧龙岗大学"]),
    ("Victoria University", "维多利亚大学", ["VU"]),
    ("Western Sydney University", "西悉尼大学", ["WSU", "University of Western Sydney"]),
    ("Australian University of Theology Limited", "澳大利亚神学大学", ["Australian University of Theology", "AUT"]),
]


UNIVERSITY_COLLEGES = [
    ("Alphacrucis University College Ltd", ["Alphacrucis University College", "Alphacrucis College"]),
    ("ACAP University College Pty Ltd", ["ACAP University College", "Australian College of Applied Professions"]),
    ("Australian University College of Divinity Ltd", ["Australian University College of Divinity", "Sydney College of Divinity", "AUCD"]),
    ("Excelsia University College", ["Excelsia"]),
    ("The National Institute of Dramatic Art", ["National Institute of Dramatic Art", "NIDA"]),
    ("Australian Film Television and Radio School", ["AFTRS"]),
    ("Moore Theological College", ["Moore College"]),
    ("SAE Institute Pty Limited", ["SAE University College", "SAE Institute"]),
]


HISTORICAL_AUSTRALIAN_INSTITUTIONS = [
    ("The University of Adelaide", "阿德莱德大学（原）", ["University of Adelaide", "Adelaide Uni"]),
    ("University of South Australia", "南澳大学（原）", ["UniSA", "南澳大"]),
]

VERIFIED_AU_PROVIDER_IDS = {
    "Adelaide University": "PRV14404",
    "Australian University of Theology Limited": "PRV12010",
    "Alphacrucis University College Ltd": "PRV12006",
    "ACAP University College Pty Ltd": "PRV12009",
    "Australian University College of Divinity Ltd": "PRV12045",
    "Excelsia University College": "PRV12064",
    "The National Institute of Dramatic Art": "PRV12052",
    "SAE Institute Pty Limited": "PRV12042",
}


def build_china_records(source_file: Path) -> list[dict]:
    frame = pd.read_excel(source_file, sheet_name=0, header=None)
    province = ""
    records: list[dict] = []
    for row in frame.itertuples(index=False, name=None):
        first = str(row[0]).strip() if pd.notna(row[0]) else ""
        if re.fullmatch(r".+（\d+所）", first):
            province = first.split("（", 1)[0]
            continue
        if len(row) < 6 or str(row[5]).strip() != "本科":
            continue
        name = str(row[1]).strip()
        school_id = str(int(row[2])) if isinstance(row[2], float) else str(row[2]).strip()
        records.append(
            {
                "institution_id": f"cn-{school_id}",
                "country_code": "CN",
                "official_name": name,
                "display_name": name,
                "english_name": None,
                "aliases": CHINA_ALIASES.get(name, []),
                "region": province,
                "city": str(row[4]).strip(),
                "institution_type": "UNDERGRADUATE_INSTITUTION",
                "active": True,
                "source_record_id": school_id,
                "source_url": MOE_SOURCE_PAGE,
            }
        )
    return records


def build_australia_records() -> list[dict]:
    records = []
    for name, display_name, aliases in AUSTRALIAN_INSTITUTIONS:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        records.append(
            {
                "institution_id": f"au-{slug}",
                "country_code": "AU",
                "official_name": name,
                "display_name": display_name,
                "english_name": name,
                "aliases": aliases,
                "region": None,
                "city": None,
                "institution_type": (
                    "SPECIALIST_HIGHER_EDUCATION_PROVIDER"
                    if name.startswith("Batchelor Institute")
                    else "AUSTRALIAN_UNIVERSITY"
                ),
                "active": True,
                "source_record_id": VERIFIED_AU_PROVIDER_IDS.get(name),
                "source_url": TEQSA_REGISTER_URL,
            }
        )
    for name, aliases in UNIVERSITY_COLLEGES:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        records.append(
            {
                "institution_id": f"au-{slug}",
                "country_code": "AU",
                "official_name": name,
                "display_name": name,
                "english_name": name,
                "aliases": aliases,
                "region": None,
                "city": None,
                "institution_type": "UNIVERSITY_COLLEGE",
                "active": True,
                "source_record_id": VERIFIED_AU_PROVIDER_IDS.get(name),
                "source_url": TEQSA_REGISTER_URL,
            }
        )
    for name, display_name, aliases in HISTORICAL_AUSTRALIAN_INSTITUTIONS:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        records.append(
            {
                "institution_id": f"au-{slug}-historical",
                "country_code": "AU",
                "official_name": name,
                "display_name": display_name,
                "english_name": name,
                "aliases": aliases,
                "region": "South Australia",
                "city": "Adelaide",
                "institution_type": "HISTORICAL_UNIVERSITY",
                "active": False,
                "source_record_id": None,
                "source_url": AU_GOVERNMENT_LIST_URL,
                "superseded_by": "Adelaide University",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-xls",
        type=Path,
        default=Path("tmp/institution_catalog/china_2026.xls"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/admissions/institution_catalog_2026.json"),
    )
    args = parser.parse_args()
    args.source_xls.parent.mkdir(parents=True, exist_ok=True)
    if not args.source_xls.exists():
        urlretrieve(MOE_XLS_URL, args.source_xls)
    institutions = [
        *build_china_records(args.source_xls),
        *build_australia_records(),
    ]
    payload = {
        "catalog_version": "2026-08-04",
        "as_of_date": "2026-06-18",
        "coverage": {
            "CN": "教育部2026全国普通高等学校名单中的本科院校，不含港澳台",
            "AU": "TEQSA Australian University、University College及合并历史校名",
        },
        "sources": [
            {"authority": "中华人民共和国教育部", "url": MOE_SOURCE_PAGE},
            {"authority": "TEQSA National Register", "url": TEQSA_REGISTER_URL},
            {"authority": "Australian Government Department of Education", "url": AU_GOVERNMENT_LIST_URL},
        ],
        "counts": {
            "total": len(institutions),
            "CN": sum(item["country_code"] == "CN" for item in institutions),
            "AU": sum(item["country_code"] == "AU" for item in institutions),
            "active": sum(item["active"] for item in institutions),
        },
        "institutions": institutions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
