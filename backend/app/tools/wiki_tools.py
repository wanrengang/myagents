"""浙江联通自研产品 Wiki 查询工具。

从本地 markdown 文件中检索产品知识、解决方案案例、行业应用等，
供客户经理数字员工在拜访客户时查询使用。
"""
import re
from pathlib import Path
from langchain.tools import tool

# 浙江联通自研产品 Wiki 目录路径（markdown 文件）
WIKI_DIR = Path("/Users/wrg/coding/zjlt-products-wiki")


def _read_md(file_path: Path) -> str:
    """读取 markdown 文件，去掉 YAML frontmatter（---...---），只返回正文内容。"""
    content = file_path.read_text(encoding="utf-8")
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    return content.strip()


def _search_in_file(file_path: Path, query: str) -> list[tuple[str, str]]:
    """在单个 markdown 文件中搜索关键词，返回 (匹配行, 前后文) 列表。

    参数:
        file_path: markdown 文件路径
        query: 搜索关键词
    返回:
        list[tuple[str, str]]: 每个元素为 (匹配行文本, 前后各2行组成的上下文)
    """
    content = _read_md(file_path)
    lines = content.split("\n")
    q = query.lower()
    hits = []
    for i, line in enumerate(lines):
        if q in line.lower():
            start = max(0, i - 2)       # 匹配行前2行
            end = min(len(lines), i + 3)  # 匹配行后2行
            context = "\n".join(lines[start:end])
            hits.append((line.strip(), context))
    return hits


@tool
def query_product_wiki(category: str = "", keyword: str = "") -> str:
    """【产品知识库查询】按分类和关键词检索浙江联通自研产品资料。

    客户经理拜访客户前或方案中用此工具获取产品详情、解决方案、行业案例。

    参数:
        category: 分类筛选。products=产品介绍, concepts=行业方案/政策/客户画像, comparisons=竞品分析, 空=全部
        keyword: 搜索关键词，如"云犀"、"智慧园区"、"火焰卫士"、"AI政策"、"安全专线"等
    返回:
        匹配的产品资料文本（最长4000字符）
    """
    if not keyword and not category:
        return "请提供搜索关键词或分类。"

    # 确定搜索目录
    if category == "products":
        search_dir = WIKI_DIR / "products"        # 产品介绍目录
    elif category == "concepts":
        search_dir = WIKI_DIR / "concepts"         # 行业方案/政策/客户画像目录
    elif category == "comparisons":
        search_dir = WIKI_DIR / "comparisons"      # 竞品分析目录
    else:
        search_dir = WIKI_DIR                      # 全部目录

    results = []
    for f in sorted(search_dir.glob("*.md")):
        if f.name in ("index.md", "SCHEMA.md", "log.md"):
            continue  # 跳过索引文件和模板
        if keyword:
            hits = _search_in_file(f, keyword)
            if hits:
                name = f.stem.replace("-", " ").title()
                results.append(f"\n### {name}\n")
                for line, ctx in hits[:5]:         # 最多取5条匹配
                    results.append(ctx + "\n---\n")
        else:
            # 未指定关键词时返回文档前20行作为摘要
            content = _read_md(f)
            title = ""
            for line in content.split("\n")[:3]:
                if line.startswith("#"):
                    title = line.strip("# ")
                    break
            lines = content.split("\n")
            summary = "\n".join(lines[:20])
            results.append(f"\n### {title or f.stem}\n{summary}\n")

    if not results:
        return f"未找到与「{keyword}」相关的产品资料。请换关键词重试，或查询产品目录（category=products）。"

    return "\n".join(results)[:4000]


@tool
def list_product_catalog() -> str:
    """【产品目录总览】列出浙江联通自研产品的完整目录和简要说明。

    客户经理拜访客户前快速了解公司有哪些产品线可推荐时使用。

    返回: 产品分类列表（约3000字符），含产品名称和简要说明。
    """
    index_file = WIKI_DIR / "index.md"
    if index_file.exists():
        content = _read_md(index_file)
        return content[:3000]
    return "产品目录暂不可用。"