"""浙江联通自研产品 Wiki 查询工具。

从本地 markdown 文件中检索产品知识、解决方案案例、行业应用等，
供客户经理数字员工在拜访客户时查询使用。
"""
import re
from pathlib import Path
from langchain.tools import tool

WIKI_DIR = Path("/Users/wrg/coding/zjlt-products-wiki")


def _read_md(file_path: Path) -> str:
    """读取 markdown 文件，去掉 frontmatter，返回正文。"""
    content = file_path.read_text(encoding="utf-8")
    # 去掉 YAML frontmatter（---...---）
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
    return content.strip()


def _search_in_file(file_path: Path, query: str) -> list[tuple[str, str]]:
    """在文件中搜索匹配的行，返回 (匹配行, 上下文) 列表。"""
    content = _read_md(file_path)
    lines = content.split("\n")
    q = query.lower()
    hits = []
    for i, line in enumerate(lines):
        if q in line.lower():
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            context = "\n".join(lines[start:end])
            hits.append((line.strip(), context))
    return hits


@tool
def query_product_wiki(category: str = "", keyword: str = "") -> str:
    """查询浙江联通自研产品知识库，获取产品资料、解决方案、成功案例等信息。

    category 可选值：products（产品介绍）, concepts（行业方案/政策/客户画像）, comparisons（竞品分析）, 空表示全部
    keyword 为搜索关键词，如"云犀"、"智慧园区"、"火焰卫士"、"AI政策"等
    """
    if not keyword and not category:
        return "请提供搜索关键词或分类。"

    # 确定搜索目录
    if category == "products":
        search_dir = WIKI_DIR / "products"
    elif category == "concepts":
        search_dir = WIKI_DIR / "concepts"
    elif category == "comparisons":
        search_dir = WIKI_DIR / "comparisons"
    else:
        search_dir = WIKI_DIR

    results = []
    for f in sorted(search_dir.glob("*.md")):
        if f.name == "index.md" or f.name == "SCHEMA.md" or f.name == "log.md":
            continue
        if keyword:
            hits = _search_in_file(f, keyword)
            if hits:
                name = f.stem.replace("-", " ").title()
                results.append(f"\n### {name}\n")
                for line, ctx in hits[:5]:
                    results.append(ctx + "\n---\n")
        else:
            # 未指定 keyword 时返回文档摘要（前 20 行）
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
    """列出浙江联通自研产品的完整目录，包含产品名称和简要说明。
    适合在拜访客户前快速了解公司有哪些产品可以推荐。"""
    index_file = WIKI_DIR / "index.md"
    if index_file.exists():
        content = _read_md(index_file)
        return content[:3000]
    return "产品目录暂不可用。"