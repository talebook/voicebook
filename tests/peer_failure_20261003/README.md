## TB-234 Edge 同伴失败复核

`qa-original.py` 是 QA 新附件 `edge_peer_failure.py` 的原样副本。
在旧提交 `f3109d00d191066d887b3a76c19d60460bc5b253` 原样复现，数据见 `before.json`：
致命失败后 2.201 秒才返回，2 秒慢媒体子进程自然退出，又调用了“未提交”。

修复后运行：

```bash
uv run --locked --offline python tests/peer_failure_20261003/reproduce.py
uv run --locked --offline python tests/peer_failure_20261003/verify_preserved.py
uv run --locked --offline python -m unittest discover -s tests -p 'test_*.py'
uv run --locked --offline python tests/concurrency_20261003/run_evaluation.py
```

`reproduce.py` 保留原附件的脚本、Edge 单本/共享并发 2、无取消文件，以及
2 秒后调用真实 ffmpeg 产生有效输出的媒体夹具，仅调整通过条件和结果字段。
断言在 750ms 内报告原始失败、媒体子进程被终止并回收、没有后续请求、
保持 failed 而非 cancelled、计数及持久化终态正确、缓存临时目录清理。
实际执行数据见 `after.json`，模拟延迟不能视为生产 SLA。

修复包含媒体轮询中的同伴失败检查、工作线程的停止信号（不写进度）、
新请求之前优先消费已完成 future，并保留原始失败归属，避免将协作停止误报成用户取消。
回归扩展到 Edge/Qwen 的规范化与变速、提交边界上的致命/重试耗尽错误、
准备新生成器时的失败竞态，以及仍有额度的 429 继续重试并成功完成。

`verify_preserved.py` 重跑 QA 压缩包中的同等故障注入方法：原 5 个取消/续租正例通过；
关闭媒体取消检查后的 4 个负例和关闭续租后的 1 个负例仍被原断言检出。
负例子进程等待 1.1 秒后执行实际 ffmpeg，不以缺文件模拟取消失败。
`preserved-probes.json` 保存结果及被测两个生成模块的 SHA-256，便于与最终提交核对。
原 120 秒租约、CLI、进度协议及默认值保持不变；全部离线，无供应商调用。
