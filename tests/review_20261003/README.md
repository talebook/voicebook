## TB-234 独立评审修复复核

`qa-reproduce-original.py` 是 QA 评论附件 `reproduce.py` 的原样副本。修改前在
`f2340807824169ac25bf71fd4769bab2d7aa98f9` 执行该脚本，结果见 `before.json`：
慢规范化取消延迟 2.258 秒、期间没有事件；共享上限 2 时模拟连接峰值为 3。

修复后运行：

```bash
uv run --locked --offline python tests/review_20261003/reproduce.py
uv run --locked --offline python -m unittest discover -s tests -p 'test_media_control.py'
```

`reproduce.py` 保留附件的 150ms 租约、600ms 媒体处理和竞争任务夹具，
改为断言峰值 2、竞争请求只有一个获准、原网络连接仍活跃及心跳存在。
规范化已从 `subprocess.run` 转为可取消的 Popen，因此取消探针改在 Popen 注入
真实的 30 秒慢子进程；断言取消延迟小于 750ms、处理期间有心跳、所有子进程回收、
缓存临时目录清理、没有完成事件且持久化终态正确。覆盖 Edge/Qwen 的规范化和变速四条路径。
取消夹具将心跳加速为 25ms，在子进程启动 150ms 后创建取消文件；媒体控制默认最多约 100ms 检查一次，
默认心跳仍为约 1 秒。其他单元致命失败时无需 cancel-file 也会终止正在处理的媒体子进程，另有生成链路回归覆盖。
`after.json` 是本机实际执行结果，不是生产延迟承诺。原脚本断言缺陷仍存在，故不应用作修复后的通过条件。

媒体等待和终止回收期间，协调线程按租约的三分之一以内的间隔持续续期所有活动请求；
原 120 秒租约及 CLI/进度字段/默认值均保持不变。

音频顺序复核另见 `tests/concurrency_20261003/`：每个标题/正文片段使用独有音调，
直接解码最终 MP3，检查音调序列和每次出现的时长，不依赖时间轴文字。
`tests/test_audio_content.py` 提供正确序列、乱序、遗漏、重复及无间隔相邻重复的检测回归。
全部探针离线执行，不调用语音供应商。
