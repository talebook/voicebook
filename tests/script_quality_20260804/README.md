# 新剧本质量真实书籍评测

本目录记录 2026-08-04 对 Voicebook 新剧本生产链的真实 EPUB 评测。评测不修改原书，也不读取或迁移已有 `book.script`。

运行方式：

```bash
python scripts/evaluate.py --output reports/result.json /path/to/book1.epub /path/to/book2.epub
```

检查项包括：全书 EPUB 提取后的技术标题与结构化样式残留，以及代表章节重复 inspect 的逐字节确定性、语言感知切片上限、locator key 唯一性与范围合法性、Voicebook 质量计数。默认每本书 inspect 前 5 章，避免把角色归因基准误当成切片性能测试。
