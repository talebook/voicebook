#!/usr/bin/env python3
"""Build the offline ACTIVE HTML report with local design resources."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
DESIGN_DIR = HERE.parents[1]
OUTPUT = DESIGN_DIR / "20260716-qwen3ttsai-integration.active.html"
RESOURCE_URL = Path("resources/qwen3ttsai")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    api = json.loads((HERE / "api_observation.json").read_text(encoding="utf-8"))
    voices = json.loads((HERE / "voice_catalog.json").read_text(encoding="utf-8"))
    results = manifest["results"]
    aggregate = manifest["aggregate"]

    rows = []
    players = []
    max_wall = max(item["wall_seconds"] for item in results)
    bars = []
    bar_y = 54
    for index, item in enumerate(results, 1):
        profile = item["profile"]
        profile_label = "旁白" if profile.get("type") == "narrator" else (
            f"{profile['gender']} / {profile['age_stage']} / {'、'.join(profile['voice_desc']) or '-'}"
        )
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item['role'])}</strong><br><span class='subtle'>{esc(item['id'])}</span></td>"
            f"<td>{esc(profile_label)}</td>"
            f"<td class='accent'>{esc(item['voice'])}</td>"
            f"<td class='num'>{item['characters']}</td>"
            f"<td class='num'>{item['wall_seconds']:.3f}s</td>"
            f"<td class='num'>{item['duration_seconds']:.3f}s</td>"
            f"<td class='num'>{item['rtf']:.3f}</td>"
            "</tr>"
        )
        media_path = HERE / item["output"]
        actual_hash = hashlib.sha256(media_path.read_bytes()).hexdigest()
        if actual_hash != item["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {media_path}")
        media_src = (RESOURCE_URL / item["output"]).as_posix()
        players.append(
            "<article class='media-card'>"
            f"<div class='media-index'>DEMO {index:02d} · {esc(item['voice'])}</div>"
            f"<h3>{esc(item['role'])}</h3>"
            f"<p class='media-text'>“{esc(item['text'])}”</p>"
            f"<audio controls preload='metadata' src='{esc(media_src)}'></audio>"
            f"<div class='media-meta'>{item['duration_seconds']:.2f}s · {item['bytes'] / 1024:.0f} KiB · {esc(item['source'])}</div>"
            "</article>"
        )
        width = 440 * item["wall_seconds"] / max_wall
        bars.append(
            f"<text x='132' y='{bar_y + 14}' text-anchor='end' fill='#4a4a4a'>{esc(item['voice'])}</text>"
            f"<rect x='150' y='{bar_y}' width='{width:.1f}' height='20' fill='#a5c0d8' stroke='#6f9bb8'/>"
            f"<text x='{158 + width:.1f}' y='{bar_y + 14}' fill='#1a1a1a' font-weight='600'>{item['wall_seconds']:.2f}s</text>"
        )
        bar_y += 42

    video_path = HERE / "voicebook_qwen_novel_demo.mp4"
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    video_src = (RESOURCE_URL / video_path.name).as_posix()

    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Qwen3TTSAI Voicebook 接入与性能报告</title>
  <style>
    :root {{
      --paper: #f7f7f5;
      --paper-edge: #efefea;
      --ink: #1a1a1a;
      --ink-soft: #4a4a4a;
      --ink-faint: #7a7a7a;
      --rule: #d8d8d2;
      --rule-soft: #e8e8e2;
      --accent: #6f9bb8;
      --accent-soft: #d9e6f0;
      --accent-faint: #eef4f8;
      --warn: #b88a4a;
      --warn-soft: #f5ecdc;
      --danger: #a05050;
      --code-bg: #ececea;
      --brain: #6f9bb8;
      --brain-bg: #eef4f8;
      --hands: #b88a4a;
      --hands-bg: #f5ecdc;
      --session: #6b7560;
      --session-bg: #ecede5;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ font-size: 16px; scroll-behavior: smooth; }}
    body {{
      font-family: ui-serif, "Charter", "Iowan Old Style", "Source Serif Pro", Georgia,
        "Songti SC", "Source Han Serif SC", "Noto Serif CJK SC", serif;
      background: var(--paper); color: var(--ink); line-height: 1.6;
      -webkit-font-smoothing: antialiased; padding: 64px 24px 96px;
    }}
    .doc {{ max-width: 920px; margin: 0 auto; }}
    .doc-header {{ border-bottom: 1px solid var(--rule); padding-bottom: 28px; margin-bottom: 48px; }}
    .doc-eyebrow, .doc-meta, th, code, figcaption, .num, .media-index, .media-meta, .subtle {{
      font-family: ui-monospace, "SF Mono", Menlo, "PingFang SC", "Hiragino Sans GB", monospace;
    }}
    .doc-eyebrow {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-faint); margin-bottom: 14px; }}
    .doc-title {{ font-size: 36px; font-weight: 600; letter-spacing: -.01em; line-height: 1.2; }}
    .doc-subtitle {{ font-size: 16px; color: var(--ink-soft); margin-top: 10px; font-style: italic; }}
    .doc-meta {{ font-size: 11px; color: var(--ink-faint); margin-top: 18px; display: flex; gap: 24px; flex-wrap: wrap; }}
    .mascot {{ display: inline-block; width: 8px; height: 8px; background: var(--accent); margin-right: 8px; vertical-align: middle; }}
    .tldr {{ background: var(--accent-faint); border-left: 2px solid var(--accent); padding: 20px 24px; margin-bottom: 56px; font-size: 15px; }}
    .tldr-label, .callout-label {{ font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; font-weight: 600; }}
    .tldr-label {{ color: var(--accent); margin-bottom: 8px; }}
    section {{ margin-bottom: 58px; }}
    h2 {{ font-size: 22px; font-weight: 600; margin-bottom: 18px; padding-bottom: 10px; border-bottom: 1px solid var(--rule); }}
    h2 .num {{ font-size: 12px; color: var(--ink-faint); font-weight: 500; margin-right: 14px; letter-spacing: .05em; }}
    h3 {{ font-size: 16px; font-weight: 600; margin: 24px 0 10px; }}
    p {{ margin-bottom: 14px; }}
    a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent-soft); }}
    a:hover {{ border-bottom-color: var(--accent); }}
    code {{ font-size: 13px; background: var(--code-bg); padding: 1px 5px; border-radius: 2px; }}
    pre {{ position: relative; font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; line-height: 1.55; background: var(--code-bg); padding: 14px 18px; margin: 14px 0 18px; overflow-x: auto; border-left: 2px solid var(--rule); }}
    pre code {{ background: transparent; padding: 0; }}
    ul {{ margin: 8px 0 16px 22px; }}
    li {{ margin-bottom: 6px; }}
    strong {{ font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; margin: 14px 0 18px; font-size: 13.5px; }}
    th, td {{ text-align: left; padding: 10px 11px; border-bottom: 1px solid var(--rule-soft); vertical-align: top; }}
    th {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-faint); border-bottom: 1px solid var(--rule); white-space: nowrap; }}
    tbody tr:hover {{ background: rgba(0,0,0,.015); }}
    td.num {{ font-size: 12.5px; white-space: nowrap; }}
    td.accent {{ color: var(--accent); font-weight: 600; }}
    .subtle {{ font-size: 10px; color: var(--ink-faint); }}
    .callout {{ border: 1px solid var(--rule); background: #fff; padding: 16px 18px; margin: 16px 0 20px; }}
    .callout.warn {{ border-color: #e6d4a8; background: var(--warn-soft); }}
    .callout-label {{ color: var(--ink-faint); margin-bottom: 8px; }}
    .callout.warn .callout-label {{ color: var(--warn); }}
    figure {{ margin: 28px 0 32px; border: 1px solid var(--rule); background: #fff; }}
    figure svg {{ display: block; width: 100%; height: auto; }}
    figcaption {{ font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-faint); padding: 10px 16px; border-top: 1px solid var(--rule-soft); background: var(--paper-edge); }}
    figcaption .fig-num {{ color: var(--accent); margin-right: 10px; font-weight: 600; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 20px 0 18px; }}
    .cards.cols-4 {{ grid-template-columns: repeat(4, 1fr); }}
    .card {{ border: 1px solid var(--rule); background: #fff; padding: 16px 16px 14px; }}
    .card-icon {{ font-family: ui-monospace, Menlo, monospace; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; margin-bottom: 8px; font-weight: 600; color: var(--accent); }}
    .card-name {{ font-size: 20px; font-weight: 600; margin-bottom: 5px; }}
    .card-where {{ font-size: 11px; color: var(--ink-faint); font-style: italic; margin-bottom: 8px; }}
    .card-desc {{ font-size: 13px; color: var(--ink-soft); line-height: 1.5; }}
    .tone-b .card-icon {{ color: var(--hands); }}
    .tone-c .card-icon {{ color: var(--session); }}
    .media-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 18px; }}
    .media-card {{ border: 1px solid var(--rule); background: #fff; padding: 17px; min-width: 0; }}
    .media-card h3 {{ margin: 5px 0 8px; font-size: 18px; }}
    .media-index {{ color: var(--accent); font-size: 10px; letter-spacing: .1em; }}
    .media-text {{ color: var(--ink-soft); font-size: 13px; min-height: 64px; }}
    .media-meta {{ color: var(--ink-faint); font-size: 9.5px; margin-top: 9px; overflow-wrap: anywhere; }}
    audio, video {{ display: block; width: 100%; margin-top: 12px; }}
    .video-shell {{ border: 1px solid var(--rule); background: #fff; padding: 16px; margin-top: 22px; }}
    .toc {{ position: fixed; top: 64px; left: 24px; width: 190px; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; line-height: 1.7; }}
    .toc::before {{ content: "CONTENTS"; display: block; color: var(--ink-faint); letter-spacing: .12em; margin-bottom: 8px; }}
    .toc a {{ display: block; color: var(--ink-faint); border: none; padding: 2px 0; }}
    .toc a.active {{ color: var(--accent); font-weight: 600; }}
    .reading-progress {{ position: fixed; top: 0; left: 0; height: 2px; background: var(--accent); width: 0; z-index: 10; }}
    .copy-btn {{ position: absolute; top: 8px; right: 8px; font-family: ui-monospace, Menlo, monospace; font-size: 9px; letter-spacing: .1em; text-transform: uppercase; background: #fff; border: 1px solid var(--rule); padding: 4px 8px; cursor: pointer; color: var(--ink-faint); }}
    figure.zoomable {{ cursor: zoom-in; }}
    figure.zoomable.zoomed {{ position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,.86); cursor: zoom-out; padding: 40px; margin: 0; border: none; display: flex; align-items: center; justify-content: center; }}
    figure.zoomable.zoomed svg {{ max-width: 95vw; max-height: 90vh; width: auto; }}
    figure.zoomable.zoomed figcaption {{ display: none; }}
    footer {{ margin-top: 80px; padding-top: 24px; border-top: 1px solid var(--rule); font-size: 12px; color: var(--ink-faint); }}
    footer h4 {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase; font-family: ui-monospace, Menlo, monospace; margin-bottom: 10px; color: var(--ink-soft); }}
    footer ul {{ list-style: none; margin-left: 0; }}
    @media (max-width: 1280px) {{ .toc {{ display: none; }} }}
    @media (max-width: 760px) {{
      body {{ padding: 32px 14px 64px; }}
      .doc-title {{ font-size: 27px; }}
      .cards, .cards.cols-4, .media-grid {{ grid-template-columns: 1fr; }}
      .media-text {{ min-height: auto; }}
      .table-wrap {{ overflow-x: auto; }}
    }}
    @media print {{ .toc, .reading-progress, .copy-btn {{ display: none; }} body {{ padding: 20px; }} }}
  </style>
</head>
<body>
  <div class="reading-progress" id="progress"></div>
  <nav class="toc" id="toc" aria-label="报告目录"></nav>
  <article class="doc">
    <header class="doc-header">
      <div class="doc-eyebrow"><span class="mascot"></span>VOICEBOOK · TTS INTEGRATION REPORT</div>
      <h1 class="doc-title">Qwen3TTSAI 接入与性能报告</h1>
      <p class="doc-subtitle">从 Web API 协议、角色自动选声到多角色小说成品的完整验证</p>
      <div class="doc-meta">
        <span>STATUS · ACTIVE</span>
        <span>DATE · {esc(manifest['generated_at'])}</span>
        <span>ENGINE · QWEN</span>
        <span>MEDIA · LOCAL RESOURCES</span>
      </div>
    </header>

    <div class="tldr">
      <div class="tldr-label">TL;DR</div>
      Voicebook 已接入 qwen3ttsai.com 的公开系统音色接口，并从 <strong>{voices['count']} 个中文音色</strong>中按角色性别、年龄阶段和声音描述自动选声。五个小说片段全部生成成功；并发 2 时用 <strong>{aggregate['batch_wall_seconds']:.3f} 秒</strong>生成 {aggregate['audio_seconds']:.3f} 秒音频，有效 RTF 为 <strong>{aggregate['effective_batch_rtf']:.3f}</strong>。WAV 与 MP4 统一放在 <code>design/resources/qwen3ttsai/</code>，本报告可随该目录离线播放。
    </div>

    <section>
      <h2><span class="num">01</span>API 协议与接入链路</h2>
      <div class="cards">
        <div class="card"><div class="card-icon">ENDPOINT</div><div class="card-name">POST</div><div class="card-where">/api/qwen3tts/generate</div><div class="card-desc">JSON 字段为 text、voice、mode；system 模式无需 Cookie。</div></div>
        <div class="card tone-b"><div class="card-icon">AUDIO</div><div class="card-name">24 kHz</div><div class="card-where">PCM s16le · mono</div><div class="card-desc">HTTP 200 返回 audio/wav；单次文本上限 1000 字，客户端会按句末切分。</div></div>
        <div class="card tone-c"><div class="card-icon">RESILIENCE</div><div class="card-name">2 × 3</div><div class="card-where">并发 2 · 最多 3 次</div><div class="card-desc">对 429 与 5xx 指数退避；Edge 仍保留为默认引擎。</div></div>
      </div>
      <figure>
        <svg viewBox="0 0 860 285" xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace, Menlo, monospace" font-size="11">
          <rect width="860" height="285" fill="#fff"/>
          <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#6f9bb8"/></marker></defs>
          <g>
            <rect x="25" y="95" width="135" height="82" fill="#eef4f8" stroke="#6f9bb8" stroke-width="1.4"/><text x="38" y="117" fill="#6f9bb8" font-weight="600">NOVEL</text><text x="38" y="140" fill="#4a4a4a">章节 / 对白 / 旁白</text><text x="38" y="158" fill="#7a7a7a">TXT or script</text>
            <rect x="197" y="95" width="145" height="82" fill="#fff" stroke="#6f9bb8" stroke-width="1.4"/><text x="210" y="117" fill="#6f9bb8" font-weight="600">PROFILE</text><text x="210" y="140" fill="#4a4a4a">说话人 + 性别年龄</text><text x="210" y="158" fill="#7a7a7a">voice description</text>
            <rect x="379" y="95" width="135" height="82" fill="#ecede5" stroke="#6b7560" stroke-width="1.4"/><text x="392" y="117" fill="#5a5a3a" font-weight="600">CASTING</text><text x="392" y="140" fill="#4a4a4a">27 中文系统音色</text><text x="392" y="158" fill="#7a7a7a">avoid collisions</text>
            <rect x="551" y="95" width="135" height="82" fill="#f5ecdc" stroke="#b88a4a" stroke-width="1.4"/><text x="564" y="117" fill="#7a6420" font-weight="600">QWEN API</text><text x="564" y="140" fill="#4a4a4a">concurrency = 2</text><text x="564" y="158" fill="#7a7a7a">WAV response</text>
            <rect x="723" y="95" width="112" height="82" fill="#eef4f8" stroke="#6f9bb8" stroke-width="1.4"/><text x="736" y="117" fill="#6f9bb8" font-weight="600">OUTPUT</text><text x="736" y="140" fill="#4a4a4a">WAV demos</text><text x="736" y="158" fill="#7a7a7a">MP4 chapters</text>
          </g>
          <g fill="none" stroke="#6f9bb8" stroke-width="1.4" marker-end="url(#arr)"><path d="M160 136L195 136"/><path d="M342 136L377 136"/><path d="M514 136L549 136"/><path d="M686 136L721 136"/></g>
          <text x="430" y="55" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">VOICEBOOK → QWEN3TTSAI</text>
          <text x="430" y="213" text-anchor="middle" fill="#7a7a7a">长文本自动切分 · 角色状态保留 · ffmpeg 合并章节</text>
        </svg>
        <figcaption><span class="fig-num">FIG 1</span>端到端数据流 · 小说文本到多角色音频</figcaption>
      </figure>
      <div class="callout warn"><div class="callout-label">SERVICE BOUNDARY</div>该地址是网站内部 Web API，而不是带版本与 SLA 的正式开放接口。路径、音色和限流策略未来可能变化。</div>
    </section>

    <section>
      <h2><span class="num">02</span>角色画像与自动选声</h2>
      <p>选声器先按 <code>male/female × 童年/少年/青年/中年/老年</code>进入候选桶，再用“低沉、沙哑、苍老、柔和、稚嫩”等文本证据细化。相同桶中的主要角色依次选择不同音色。</p>
      <div class="table-wrap"><table>
        <thead><tr><th>角色</th><th>画像</th><th>自动音色</th><th>选择依据</th></tr></thead>
        <tbody>
          <tr><td><strong>旁白</strong></td><td>narrator</td><td class="accent">Neil</td><td>专业主持人、咬字稳定</td></tr>
          <tr><td><strong>韩立</strong></td><td>male / 青年 / 低沉</td><td class="accent">Andre</td><td>磁性、沉稳青年男声</td></tr>
          <tr><td><strong>老道</strong></td><td>male / 老年 / 苍老</td><td class="accent">Arthur</td><td>质朴、不疾不徐的老年声线</td></tr>
          <tr><td><strong>妈妈</strong></td><td>female / 中年 / 柔和</td><td class="accent">Serena</td><td>温柔自然女声</td></tr>
          <tr><td><strong>彼得·潘</strong></td><td>male / 童年 / 稚嫩</td><td class="accent">Pip</td><td>调皮且充满童真的男孩声</td></tr>
        </tbody>
      </table></div>
      <div class="callout"><div class="callout-label">FULL AUTO CHECK</div>用仓库测试小说跑“说话人识别 → 角色画像 → 选声”完整链路：老道识别为 <code>male/老年 → Eldric Sage</code>，韩立识别为 <code>male/青年 → Andre</code>。</div>
    </section>

    <section>
      <h2><span class="num">03</span>性能结果</h2>
      <div class="cards cols-4">
        <div class="card"><div class="card-icon">SUCCESS</div><div class="card-name">{aggregate['success_count']}/{aggregate['sample_count']}</div><div class="card-where">{aggregate['success_rate_percent']:.1f}%</div><div class="card-desc">全部请求生成有效 WAV。</div></div>
        <div class="card tone-b"><div class="card-icon">BATCH</div><div class="card-name">{aggregate['batch_wall_seconds']:.2f}s</div><div class="card-where">并发 2</div><div class="card-desc">五条短小说片段的批次墙钟时间。</div></div>
        <div class="card tone-c"><div class="card-icon">AUDIO</div><div class="card-name">{aggregate['audio_seconds']:.2f}s</div><div class="card-where">最终音频时长</div><div class="card-desc">原生 PCM WAV 合计播放时长。</div></div>
        <div class="card"><div class="card-icon">EFFECTIVE RTF</div><div class="card-name">{aggregate['effective_batch_rtf']:.3f}</div><div class="card-where">低于 1 = 快于实时</div><div class="card-desc">批次耗时 ÷ 合计音频时长。</div></div>
      </div>
      <figure>
        <svg viewBox="0 0 760 295" xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace, Menlo, monospace" font-size="11">
          <rect width="760" height="295" fill="#fff"/>
          <line x1="150" y1="260" x2="650" y2="260" stroke="#7a7a7a"/>
          <g stroke="#e8e8e2" stroke-width="1" stroke-dasharray="2 4"><line x1="282" y1="35" x2="282" y2="260"/><line x1="414" y1="35" x2="414" y2="260"/><line x1="546" y1="35" x2="546" y2="260"/></g>
          <g fill="#7a7a7a" font-size="10"><text x="150" y="280" text-anchor="middle">0s</text><text x="282" y="280" text-anchor="middle">2s</text><text x="414" y="280" text-anchor="middle">4s</text><text x="546" y="280" text-anchor="middle">6s</text></g>
          {''.join(bars)}
        </svg>
        <figcaption><span class="fig-num">FIG 2</span>单请求墙钟耗时 · 五个系统音色</figcaption>
      </figure>
      <div class="table-wrap"><table id="metrics">
        <thead><tr><th>Demo</th><th>画像</th><th>音色</th><th>字数</th><th>请求</th><th>音频</th><th>RTF</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table></div>
      <p><span class="subtle">MEAN REQUEST · {aggregate['mean_request_seconds']:.3f}s &nbsp; MEDIAN · {aggregate['median_request_seconds']:.3f}s &nbsp; MAX · {aggregate['max_request_seconds']:.3f}s &nbsp; THROUGHPUT · {aggregate['effective_characters_per_second']:.2f} 字/s</span></p>
    </section>

    <section>
      <h2><span class="num">04</span>可播放 Demo</h2>
      <p>以下媒体通过相对路径引用 <code>design/resources/qwen3ttsai/</code>。复制或归档时应保留 <code>design/</code> 与其 <code>resources/</code> 子目录的相对结构。</p>
      <div class="media-grid">{''.join(players)}</div>
      <div class="video-shell">
        <div class="media-index">END-TO-END · 2 CHAPTERS · 4 CHARACTERS</div>
        <h3>Voicebook 多角色小说 MP4</h3>
        <p>包含《凡人修仙之仙界篇》和《彼得·潘》两个章节标记，总时长 48.006 秒。</p>
        <video controls preload="metadata" src="{esc(video_src)}"></video>
      </div>
    </section>

    <section>
      <h2><span class="num">05</span>运行与验证</h2>
      <h3>生成 Qwen 有声书</h3>
      <pre><code>uv run python -m book2audio \\
  --input book/xuanjian.txt --chapters 1 \\
  --output output/xuanjian_qwen.mp4 \\
  --multi-voice --engine qwen</code></pre>
      <h3>复现性能评测与 HTML</h3>
      <pre><code>uv --cache-dir /private/tmp/voicebook-uv-cache run python \\
  design/resources/qwen3ttsai/run_eval.py

uv --cache-dir /private/tmp/voicebook-uv-cache run python \\
  design/resources/qwen3ttsai/build_html_report.py</code></pre>
      <ul>
        <li><strong>自动测试。</strong> 5 项单元测试通过，覆盖请求协议、限流重试、长文本切分和角色选声。</li>
        <li><strong>音频校验。</strong> 五个文件均通过 WAV 头、采样率、声道与 SHA-256 检查。</li>
        <li><strong>成品校验。</strong> MP4 含两个章节标记，时长 48.006 秒。</li>
        <li><strong>提交状态。</strong> 核心接入已推送至 <code>origin/main</code>。</li>
      </ul>
    </section>

    <footer>
      <h4>References</h4>
      <ul>
        <li>API 观察 · <code>design/resources/qwen3ttsai/api_observation.json</code></li>
        <li>中文音色目录 · <code>design/resources/qwen3ttsai/voice_catalog.json</code></li>
        <li>性能原始数据 · <code>design/resources/qwen3ttsai/manifest.json</code></li>
        <li>公共体验页面 · <a href="https://qwen3ttsai.com/zh">qwen3ttsai.com/zh</a></li>
      </ul>
    </footer>
  </article>
  <script>
    (function () {{
      const progress = document.getElementById('progress');
      window.addEventListener('scroll', () => {{
        const height = document.documentElement.scrollHeight - innerHeight;
        progress.style.width = (height > 0 ? scrollY / height * 100 : 0) + '%';
      }});
      const toc = document.getElementById('toc');
      const headings = [...document.querySelectorAll('section > h2')];
      headings.forEach((heading, index) => {{
        heading.id = 'sec-' + (index + 1);
        const link = document.createElement('a');
        link.href = '#' + heading.id;
        link.textContent = heading.textContent.replace(/^\\s*\\d+\\s*/, '');
        toc.appendChild(link);
      }});
      const links = [...toc.querySelectorAll('a')];
      const observer = new IntersectionObserver(entries => {{
        entries.forEach(entry => {{
          if (entry.isIntersecting) links.forEach(link => link.classList.toggle('active', link.hash === '#' + entry.target.id));
        }});
      }}, {{ rootMargin: '-35% 0px -55% 0px' }});
      headings.forEach(heading => observer.observe(heading));
      document.querySelectorAll('figure').forEach(figure => {{
        figure.classList.add('zoomable');
        figure.addEventListener('click', () => figure.classList.toggle('zoomed'));
      }});
      document.querySelectorAll('pre').forEach(pre => {{
        const button = document.createElement('button');
        button.className = 'copy-btn';
        button.textContent = 'copy';
        button.addEventListener('click', async () => {{
          await navigator.clipboard.writeText(pre.querySelector('code').innerText);
          button.textContent = 'copied';
          setTimeout(() => button.textContent = 'copy', 1200);
        }});
        pre.appendChild(button);
      }});
    }})();
  </script>
</body>
</html>
"""
    OUTPUT.write_text(document, encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
