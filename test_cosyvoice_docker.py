#!/usr/bin/env python3
"""
CosyVoice 测试脚本
通过 Docker 运行 CosyVoice 服务
"""

import os
import sys
import subprocess
import time

TEST_TEXT = "你好，欢迎收听智能有声书。这是一个测试语音合成效果的示例。"

def check_docker_cosyvoice():
    """检查 CosyVoice Docker 容器"""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=cosyvoice", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"检查 Docker 失败: {e}")
        return None

def run_cosyvoice_test():
    """运行 CosyVoice 测试"""
    print("=" * 60)
    print("CosyVoice Docker 测试")
    print("=" * 60)

    # 检查 Docker 是否可用
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
        print("✅ Docker 已安装")
    except:
        print("❌ Docker 未安装或不可用")
        return None

    # 检查镜像
    print("\n📋 检查 CosyVoice 镜像...")
    result = subprocess.run(
        ["docker", "images", "-q", "modelscope.cn/funaudiollm/cosyvoice2:2.0"],
        capture_output=True, text=True
    )

    if result.stdout.strip():
        print("✅ CosyVoice 镜像已下载")
    else:
        print("📥 正在下载 CosyVoice 镜像...")
        print("   这可能需要几分钟...")

    # 检查容器
    container = check_docker_cosyvoice()
    if container:
        print(f"✅ 找到 CosyVoice 容器: {container}")

    print("\n" + "=" * 60)
    print("CosyVoice Docker 状态检查完成")
    print("=" * 60)
    print("""
如果 Docker 镜像下载完成，可以使用以下命令启动服务：

# 启动 CosyVoice gRPC 服务
docker run -d --gpus all -p 50000:50000 \\
  -v $(pwd)/pretrained_models:/pretrained_models \\
  modelscope.cn/funaudiollm/cosyvoice2:2.0 \\
  /bin/bash -c "cd /opt/CosyVoice/CosyVoice/runtime/python/grpc && \\
  python3 server.py --port 50000 --max_conc 4 --model_dir iic/CosyVoice-300M"

# 然后使用客户端测试
python3 /tmp/CosyVoice/runtime/python/grpc/client.py --port 50000 --mode sft
""")

if __name__ == "__main__":
    run_cosyvoice_test()
