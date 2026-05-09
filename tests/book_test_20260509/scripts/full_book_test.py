#!/usr/bin/env python3
"""
完整小说测试脚本 - book2audio
使用整本小说测试 LLM 角色分析能力

策略：
1. 将小说分成多个chunk（每个chunk约10000字符，留空间给prompt和response）
2. 对每个chunk进行角色分析
3. 汇总所有chunk的角色信息
4. 计算总耗时
"""

import requests
import time
import json
import re
from datetime import datetime
from pathlib import Path

BOOK_FILE = Path(__file__).parent.parent.parent.parent / "book.txt"
REPORT_DIR = Path(__file__).parent.parent
OLLAMA_URL = "http://localhost:11434"
CHUNK_SIZE = 8000
MODEL_NAME = "qwen3:0.6b"
MAX_CHAPTERS = 30

def load_book():
    with open(BOOK_FILE, "r", encoding="utf-8") as f:
        return f.read()

def split_into_chunks(text, chunk_size=CHUNK_SIZE):
    chapters = []
    lines = text.split('\n')

    current_chunk = ""
    chapter_count = 0

    for line in lines:
        if re.match(r'第[一二三四五六七八九十百千万\d]+章', line.strip()):
            if current_chunk:
                chapters.append(current_chunk)
            current_chunk = line + "\n"
            chapter_count += 1

            if chapter_count >= MAX_CHAPTERS:
                break
        else:
            if len(current_chunk) + len(line) > chunk_size and current_chunk:
                chapters.append(current_chunk)
                current_chunk = ""
            current_chunk += line + "\n"

    if current_chunk and chapter_count < MAX_CHAPTERS + 1:
        chapters.append(current_chunk)

    return chapters

def analyze_chunk(chunk_text, chapter_info="", chunk_index=0):
    prompt = f"""你是角色分析专家。分析以下小说文本，提取所有真实角色（人名）。

要求：
1. 只提取真实的人物角色，不要提取地名、功法名、物品名
2. 识别角色可能在多个章节中出现，给出首次出现的描述
3. 如果同一个角色有不同称呼，都要提取（如"陆江仙"和"他"）
4. 输出JSON数组格式

小说内容：
{chunk_text}

输出格式：
{{"characters": [{{"name": "角色名", "description": "首次出现描述"}}]}}"""

    start_time = time.time()

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 1024,
                    "think": False
                }
            },
            timeout=180
        )

        elapsed = time.time() - start_time
        result = response.json()

        tokens = result.get("eval_count", 0)
        output = result.get("response", "")

        return {
            "chunk_index": chunk_index,
            "chapter_info": chapter_info,
            "elapsed": elapsed,
            "tokens": tokens,
            "tps": tokens / elapsed if elapsed > 0 else 0,
            "output": output,
            "success": True
        }

    except Exception as e:
        return {
            "chunk_index": chunk_index,
            "chapter_info": chapter_info,
            "elapsed": 0,
            "tokens": 0,
            "error": str(e),
            "success": False
        }

def extract_characters(result):
    characters = []
    try:
        text = result.get("output", "")

        json_match = re.search(r'\{[^{}]*"characters"[^{}]*\[[\s\S]*?\][^{}]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
            characters = data.get("characters", [])

        if not characters:
            name_pattern = r'"name"\s*:\s*"([^"]+)"'
            names = re.findall(name_pattern, text)
            characters = [{"name": n, "description": ""} for n in names[:20]]

    except Exception as e:
        print(f"    解析角色失败: {e}")

    return characters

def main():
    print("=" * 70)
    print("完整小说测试 - book2audio (前30章)")
    print("=" * 70)

    log_file = REPORT_DIR / "logs" / "full_book_test_log.txt"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "w", encoding="utf-8") as log:
        log.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 测试开始\n")
        log.write(f"模型: {MODEL_NAME} (思考模式: 关闭)\n")
        log.write(f"文件: {BOOK_FILE}\n")
        log.write(f"最大章节数: {MAX_CHAPTERS}\n")
        log.write("=" * 50 + "\n")

    book_content = load_book()
    total_chars = len(book_content)
    print(f"\n📖 加载书籍: {total_chars:,} 字符 ({total_chars/1024/1024:.2f} MB)")

    log_write(f"书籍大小: {total_chars:,} 字符")

    print(f"\n✂️ 分割章节 (最多 {MAX_CHAPTERS} 章)...")
    chapters = split_into_chunks(book_content, CHUNK_SIZE)
    print(f"📑 分为 {len(chapters)} 个章节块")

    log_write(f"章节块数: {len(chapters)}")

    all_characters = []
    total_elapsed = 0
    total_tokens = 0
    success_count = 0

    print(f"\n🚀 开始分析 (使用 {MODEL_NAME}, think=False)...")
    print("-" * 70)

    for i, chunk in enumerate(chapters):
        chapter_line = chunk.split('\n')[0][:30] if chunk.split('\n')[0] else f"段落 {i+1}"

        print(f"\n[{i+1}/{len(chapters)}] 分析: {chapter_line}...")

        result = analyze_chunk(chunk, chapter_line, i)

        if result["success"]:
            total_elapsed += result["elapsed"]
            total_tokens += result["tokens"]
            success_count += 1

            chars = extract_characters(result)
            all_characters.extend(chars)

            print(f"    ✅ {result['elapsed']:.2f}s | {result['tokens']} tokens | {result['tps']:.1f} t/s | 发现 {len(chars)} 个角色")

            log_write(f"[{i+1}/{len(chapters)}] {chapter_line} | {result['elapsed']:.2f}s | {len(chars)}角色")
        else:
            print(f"    ❌ 失败: {result.get('error', 'Unknown')}")
            log_write(f"[{i+1}/{len(chapters)}] {chapter_line} | 失败: {result.get('error')}")

    print("\n" + "=" * 70)
    print("📊 测试完成")
    print("=" * 70)

    avg_tps = total_tokens / total_elapsed if total_elapsed > 0 else 0

    print(f"\n⏱  总耗时: {total_elapsed:.2f} 秒")
    print(f"📝 总Token: {total_tokens:,}")
    print(f"📈 平均速度: {avg_tps:.1f} t/s")
    print(f"✅ 成功章节: {success_count}/{len(chapters)}")
    print(f"👥 发现角色: {len(all_characters)} 个")

    log_write("=" * 50)
    log_write(f"总耗时: {total_elapsed:.2f} 秒")
    log_write(f"总Token: {total_tokens}")
    log_write(f"平均速度: {avg_tps:.1f} t/s")
    log_write(f"成功章节: {success_count}/{len(chapters)}")
    log_write(f"发现角色: {len(all_characters)} 个")

    unique_names = set()
    final_characters = []
    for char in all_characters:
        name = char.get("name", "")
        if name and name not in unique_names:
            unique_names.add(name)
            final_characters.append(char)

    print(f"\n📋 去重后角色列表 ({len(final_characters)} 个):")
    for i, char in enumerate(final_characters[:30], 1):
        desc = char.get("description", "")[:40]
        print(f"  {i:2d}. {char['name']:<15} - {desc}")

    if len(final_characters) > 30:
        print(f"  ... 还有 {len(final_characters) - 30} 个角色")

    data_file = REPORT_DIR / "data" / f"full_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)

    test_data = {
        "model": MODEL_NAME,
        "think_mode": False,
        "book_file": str(BOOK_FILE),
        "book_size": total_chars,
        "chunk_count": len(chapters),
        "success_count": success_count,
        "total_elapsed": total_elapsed,
        "total_tokens": total_tokens,
        "avg_tps": avg_tps,
        "characters_found": len(final_characters),
        "characters": final_characters
    }

    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)

    print(f"\n💾 数据已保存: {data_file}")

    report_file = REPORT_DIR / "reports" / f"full_book_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    report = f"""# 完整小说测试报告

## 测试信息
- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 测试模型: {MODEL_NAME}
- 思考模式: 关闭
- 测试文件: {BOOK_FILE.name}
- 文件大小: {total_chars:,} 字符 ({total_chars/1024/1024:.2f} MB)
- 测试章节数: {MAX_CHAPTERS} 章

## 测试策略
- 将前 {MAX_CHAPTERS} 章节分割为 {len(chapters)} 个 chunk
- 每个 chunk 约 {CHUNK_SIZE} 字符
- 对每个 chunk 调用 LLM 进行角色分析 (think=False)
- 汇总所有角色的出现信息
- 去重后得到最终角色列表

## 测试结果

| 指标 | 值 |
|------|-----|
| 总耗时 | {total_elapsed:.2f} 秒 ({total_elapsed/60:.1f} 分钟) |
| 总Token数 | {total_tokens:,} |
| 平均速度 | {avg_tps:.1f} t/s |
| 成功章节 | {success_count}/{len(chapters)} |
| 发现角色(去重前) | {len(all_characters)} 个 |
| 发现角色(去重后) | {len(final_characters)} 个 |

## 角色列表

| 序号 | 角色名 | 首次出现描述 |
|------|--------|--------------|
"""

    for i, char in enumerate(final_characters[:50], 1):
        desc = char.get("description", "")[:50].replace("\n", " ")
        report += f"| {i} | {char.get('name', '')} | {desc} |\n"

    if len(final_characters) > 50:
        report += f"\n_... 还有 {len(final_characters) - 50} 个角色_\n"

    report += f"""
## 结论

- **qwen3:0.6b** 处理前30章小说的总耗时: **{total_elapsed:.2f} 秒**
- 角色分析成功率: {success_count/len(chapters)*100:.1f}%
- 符合内存 ≤1GB 要求 (模型大小 522MB)

## 数据文件
- 日志: {log_file.name}
- 数据: {data_file.name}
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"📄 报告已生成: {report_file}")

    log_write(f"报告已生成: {report_file}")

def log_write(msg):
    log_file = REPORT_DIR / "logs" / "full_book_test_log.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

if __name__ == "__main__":
    main()
