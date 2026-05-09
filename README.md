# 小说角色文本画像识别 Demo

基于 **Qwen3-0.6B** 模型的小说角色文本画像识别系统。

## 📋 功能说明

本项目实现了小说角色的**文字画像**识别，可以根据小说章节内容动态分析角色状态：
- 🎂 **年龄阶段**：少年 → 青年 → 中年 → 老年
- 👤 **外貌特征**：体型、相貌、表情、神态
- 🎭 **气质性格**：精神面貌、行为特点
- 🎙️ **音色描述**：用于 TTS 语音合成
- 💭 **情绪状态**：当前章节的情绪表现
- 📝 **重要变化**：与之前相比的显著变化

## 🚀 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 进入项目目录
cd novel-character-profile

# 2. 启动服务（包含 Ollama + API）
docker compose up -d

# 3. 拉取模型（首次需要下载）
docker exec novel-llm ollama pull qwen3:0.6b

# 4. 运行测试
python test_demo.py
```

### 方式二：本地 Ollama（无 Docker）

```bash
# 1. 安装 Ollama（macOS/Linux）
curl -fsSL https://ollama.com/install.sh | sh

# 或 Windows: https://ollama.com/download

# 2. 拉取模型
ollama pull qwen3:0.6b

# 3. 启动服务
ollama serve

# 4. 修改 test_demo.py 中的 OLLAMA_BASE_URL 为:
OLLAMA_BASE_URL = "http://localhost:11434"

# 5. 运行测试
python test_demo.py
```

## 📁 项目结构

```
novel-character-profile/
├── docker-compose.yml     # Docker 编排配置
├── Dockerfile            # API 服务镜像
├── app/
│   └── main.py          # FastAPI 服务（可选）
├── test_demo.py         # 测试脚本（直接运行）
├── data/                # 小说数据目录
└── models/              # Ollama 模型存储
```

## 🎯 测试效果

### 输入示例（《秦吏》第一章）

```python
CHAPTER_1_CONTENT = """
秦王政二十年（公元前227年）九月，秦国南郡安陆县...
黑夫，皮肤黝黑，五官方正，浓眉大眼，是个十七八岁的年轻庶民...
黑夫今年已满17岁...
"""
```

### 输出示例（角色：黑夫）

```json
{
  "age_stage": "少年",
  "appearance": "皮肤黝黑，五官方正，浓眉大眼，颔下无须，约十七八岁",
  "temperament": "谨慎机敏，心思缜密，适应力强，善于思考未来",
  "voice_description": "年轻清澈，略带质朴乡音，说话有条理",
  "emotional_state": "谨慎中带有期待，对未来有所忧虑但保持乐观",
  "key_changes": "从现代警官学院学生穿越成秦国土伍，正面对人生的重大转折"
}
```

## 🔧 API 接口

启动服务后可使用 REST API：

```bash
# 分析章节角色
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "chapter_num": 1,
    "chapter_content": "小说章节内容...",
    "characters": ["黑夫", "季婴"]
  }'

# 获取角色发展轨迹
curl http://localhost:8000/character/黑夫/arc

# 健康检查
curl http://localhost:8000/health
```

## 📊 模型规格

| 模型 | 参数量 | 内存占用 | 上下文 |
|------|--------|----------|--------|
| qwen3:0.6b | 0.6B | ~523MB | 40K |

## ⚠️ 注意事项

1. **首次运行**：需要下载模型，约 523MB
2. **内存要求**：建议 4GB+ RAM（Qwen3-0.6b 本身只需 ~1GB）
3. **CPU/GPU**：支持 CPU 运行，GPU 加速更快
4. **中文支持**：Qwen3 对中文有良好支持

## 🔮 扩展功能

1. **多章节追踪**：批量处理小说所有章节
2. **音色匹配**：与 KOROO TTS 集成，动态调整语音参数
3. **年龄变化**：追踪角色从少年到老年的变化
4. **情绪分析**：实时分析角色情绪用于语音合成

## 📝 License

MIT License
