# Voicebook → Talebook 生成进度契约 v2

适用任务：TB-234；代码版本 voicebook-tool 0.8.0（本 PR 不发布版本）。传输仍为 `voicebook-tool` 的 UTF-8 JSONL stdout；stderr 为日志。
项目音频格式仍为 `voicebook-project` v2、时间轴仍为 v1。

## 启动、版本与兼容

```bash
voicebook-tool generate book.script -o output --resume \
  --progress-format jsonl --progress-version 2 \
  --task-id talebook-job-123 --concurrency 4 --max-retries 2 \
  --cancel-file output/cancel
```

`generate` 和 `convert` 都支持这些选项。`inspect` 支持机器输出、版本、身份和取消选项。
并发范围 1–32；省略时 Edge 为 1、Qwen 为 2。并发 1 是串行兼容路径。
`--max-retries` 是每个唯一片段失败后的额外尝试次数（0–10，默认 2）；
`--retry-backoff` 是指数退避基数（0–30 秒，默认 1）；缺失或无效 Retry-After 时，在指数基数到 1.5 倍之间抖动，基数最多 60 秒。
有效 `Retry-After` 兼容秒数及 HTTP 日期，等待至少其要求的时间，**不截短为固定上限**；
如超过累计等待预算，则结束本次尝试，不能提前重连。429、5xx、超时和连接失败可重试；
参数、已知欠费 Arrearage、本地音频处理失败不自动重试。403 仅在 SDK 能按有效 Date 校时后交给调度器有限重试，其他 403 失败。
生成适配器关闭引擎内部重试，由调度器统一计数。其他引擎调用保留原来的重试默认值。
并发是本次单本调用的上限；Edge 的实际上限还受到下面的跨任务预算约束。其他引擎的多本总额度由宿主调度器控制。

## Edge 共享预算与最终默认值

已核对安装及锁定的 `edge-tts==7.2.8` 源码：WebSocket 握手异常通过 aiohttp 的
`ClientResponseError.status` / `headers` 暴露 HTTP 状态和响应头；响应可能不带 Retry-After。
超时和已知连接异常可单独识别；未知音频/流异常不能归因为 429 或固定 IP 封禁。
SDK 原本会在 stream() 内直接重试 403。受控适配器禁止库内直接重连，校时后的重试回到共享队列。
生成侧锁定此 SDK 版本并用模拟握手测试私有单请求适配边界，升级 SDK 必须重验该适配器。

| 选项 | 默认与含义 |
| --- | --- |
| `--concurrency` | Edge 1、Qwen 2；单本工作上限，范围 1–32 |
| `--edge-max-concurrency` | 1；所有 Edge 任务共享的连接/请求上限，范围 1–32 |
| `--edge-interval` | 5 秒；共享请求启动间隔，独立于连接上限，范围 0–3600 |
| `--edge-budget-path` | `VOICEBOOK_EDGE_BUDGET` 指定的路径，否则当前账户 `~/.cache/voicebook/edge-budget.sqlite3` |
| `--max-retries` | 2；每个逻辑片段的额外生成尝试数 |
| `--max-wait-seconds` | 300 秒；本次尝试累计退避、共享冷却及配额窗口等待上限，范围 0–86400；正常间隔/FIFO/连接排队不扣该预算 |
| `--edge-cooldown-seconds` | 30 秒；连续 3 个瞬时失败触发共享冷却，且不得缩短有效 Retry-After |
| `--edge-request-limit` | 0；不设请求配额，可配置共享窗口的请求启动预算 |
| `--edge-window-seconds` | 3600 秒；可选请求配额的窗口长度，无官方额度含义 |

Edge 默认并发 1、间隔 5 秒来自开发者建议的保守起点，不是经过供应商认证的安全频率。
30–50 次/分钟、可能 5 分钟临时限制、每日 5 万次等经验数值均未实测，不是本实现的承诺或固定配额。

共享 SQLite 文件以事务协调 FIFO、连接租约、启动间隔、配额、429 与连续失败冷却。
所有书籍、每个底层文本块和重试均在获准后才进入工作线程；排队/退避不占用连接或额外等待线程。
请求返回立即释放连接租约。取消移除排队票据并停止后续块，崩溃租约无心跳 120 秒后回收。
规范化、变速、拼接和编码等待及子进程终止回收期间持续检查控制信号、发心跳并续期全部活动请求租约；
续期间隔受租约时长约束，不能由本地慢处理造成仍活跃的请求被当作崩溃回收。
缓存复用不发请求、不消费配额。配置在共享文件中保持一致，配置不同的 worker 明确拒绝执行。

同一主机的多进程必须使用**同一个文件和同一组配置**；多容器须绑定同一支持 SQLite 锁的本地挂载。
多主机、隔离文件系统或同出口的其他客户端不自动共享额度，须由宿主将 Edge 生成集中到同一个调度实例；
不能为每本书/worker 创建预算文件。SQLite 网络文件系统和代理池/IP 轮换不在本次实现范围。
改变持久化预算配置须统一停用原配置的 worker 后由部署方重建预算，不能混用参数静默扩大额度。

默认仍发 `schema=voicebook-progress.v1`，保留原有事件名及字段；新增身份、事件和 `snapshot` 可被旧消费者忽略。
正文的 `segment_completed` 改为在结果真正准备好时立即发送，可能乱序；标题使用 `unit_completed`，不影响旧正文计数。
旧 `chapter_started.total_segments` / `chapter_completed.segment_count` 仍只计正文。
新接入明确选择 `--progress-version 2`，根 `schema` 为 `voicebook-progress.v2`。
两种模式的 `snapshot.schema` 都为 `voicebook-progress.v2`；消费者只解析支持的 schema，忽略新增字段和未知事件。
Talebook 当前依赖固定到 v0.7.1，接入时须先升级到包含本契约实现的 0.8.0 修订（可先固定 PR 提交，不能假定已有 v0.8.0 标签），再传新选项；
面对旧程序继续调用旧参数，展示旧阶段和可获得的工作量，并明确“详细进度不可用”，不能伪造实时完成量。

## 身份、顺序与持久化

每行都有 `schema`、`task_id`、`attempt_id`、`seq`、`event`、`at`。

- `task_id`：宿主的稳定逻辑任务 ID；不传时产生 UUID。
- `attempt_id`：每次 CLI 进程调用的唯一标识，不传时产生新 UUID；宿主可通过 `--attempt-id` 指定，但不得复用。
  单元自动重试不改变它。inspect 和 generate 是两个调用，应使用不同 attempt_id、相同 task_id。
- `seq`：同一次调用严格递增，从 1 开始；**不能跨 attempt_id 比较**。
- `at` / `snapshot.updated_at`：相同的 UTC RFC3339 时间；时间用于显示新鲜度，顺序以 seq 为准。

宿主登记当前 attempt_id 后，只接受匹配任务、匹配当前尝试、seq 大于已接收值的事件；
收到新尝试后清空旧尝试的百分比和错误状态。快照中的计数是绝对值，直接覆盖，不按事件重复累加。
页面刷新读 Talebook 已持久化的最新快照。Voicebook 同时以原子替换写入
`output/.voicebook/progress.v2.json`（完整的最后一行事件，human 模式也写），用于本机恢复和诊断；
manifest 同时记录本次 task_id、attempt_id。一个输出目录必须只有一个宿主拥有写入权，继续使用现有任务租约。

## 生成快照

`generate` 在确认所选章节和可朗读片段后，每行事件附带以下 `snapshot`。
准备阶段若在解析之前失败，或 inspect 事件尚无生成工作集，可没有 snapshot；消费端据 event / job_phase 显示阶段状态。

| 字段 | 含义 |
| --- | --- |
| `status` | `running`、`rate_queued`、`rate_limit_retry`、`retrying`、`cooling_down`、`cancelling`、`completed`、`failed`、`cancelled` |
| `stage` | `preparing`、`synthesizing`、`assembling`、`finalizing`、`completed` |
| `unit` | 固定 `speech_segment`，一个章节标题或一个可朗读的正文逻辑片段 |
| `total` | 本次所选全书的标题数 + 过滤标点空段后的正文片段数，准备完成后固定 |
| `completed` | 音频片段已成功合成、规范化并写入缓存，或验证后复用的逻辑单元数 |
| `active` | 正在渲染的逻辑单元数；相同指纹共用一个请求，可能大于并发上限 |
| `active_requests` / `concurrency` | 正在处理的唯一渲染请求数 / 配置上限；长片段的底层文本分块按序调用 |
| `retrying` | 处于退避等待中的逻辑单元数 |
| `failed` | 本次已耗尽重试或发生不可重试错误的逻辑单元数；合成/写入阶段出错时可为 0 |
| `cancelled` | 被取消或在致命失败后中止的单元数 |
| `pending` | 尚未调度的单元数（也包括后续章节） |
| `queued` | 已准备好、在等待共享预算的逻辑单元数；不是活动连接 |
| `waiting` | 可空对象：`reason`、`unit_id`、`retry_count`、UTC `next_request_at`；未知准确时间时 next_request_at 为 null |
| `wait_seconds` | 本次累计退避/冷却/配额等待秒数 |
| `requests_started` | 本次启动次数；Edge 为底层请求，其他引擎为逻辑渲染任务，不等于收费量 |
| `edge_budget` | 可空共享累计计数：`requests`、`rate_limits`（明确 429）、`retries`（重试单元中的请求）、`cooldowns`（冷却触发/延长次数）、`cooldown_until`（Unix 秒）；不是本书完成量 |
| `retries` | 本次实际安排的额外渲染请求数，不是逻辑单元数 |
| `cache_hits` | 从片段缓存或验证后的整章结果恢复的逻辑单元数 |
| `chapters_total` / `chapters_completed` | 所选章节数 / 音频和时间轴均完成的章节数 |
| `active_units` | 最多 32 个活动单元 ID，供诊断，不是完整任务列表 |
| `updated_at` | 快照更新时间；心跳也刷新，不改变完成计数 |

恒有 `total = completed + active + retrying + failed + cancelled + pending + queued`。
单元 ID 为 `chapter-N:title` 或 `chapter-N:segment-I`，I 从 0 开始，是过滤后正文片段的索引，
与该章时间轴索引一致。单元 ID 在同一脚本/选章配置内稳定；脚本修改后不可跨尝试复用计数。
重复文本仍是不同逻辑单元，但合并相同指纹的请求，成功后各单元只计一次。
整章恢复会一次增加已验证的工作量，属于实际复用，不是旧尝试的进度继承。

`completed/total` 仅为**语音片段完成比例**，不代表耗时、整本完成比例或预计剩余时间。
`assembling` 按章交替出现，即使所有片段已完成，也要继续显示音频合成/写入状态，不能显示任务完成或总进度 100%。
inspect、人工审阅、Talebook 发布阶段由宿主表示；没有可靠分母的阶段显示状态，不合成一个带固定权重的百分比。

## 事件、重试、失败和取消

保留 `phase_started`（`job_phase=INSPECTING/GENERATING`）、`chapter_started`、`segment_completed`、
`chapter_completed`、`completed`、`failed`、`cancelled`。新增 `unit_started`、标题 `unit_completed`、
`unit_retrying`、`unit_failed`、`stage_changed`、`waiting`、`heartbeat`、`cancel_requested`。
所有生成事件的 snapshot 都是消费依据，事件名用于说明刚发生的变化。

- 首个未缓存片段串行探测供应商，成功后最多并行 N 个片段；请求结束即上报，不等整章完成。
- `unit_retrying` 带 `unit_id`、`code`、`retryable=true`、`request_attempt`（失败的请求序号）和 `retry_in_seconds`。
  退避、限速排队、冷却、慢请求、合成和停止中的任务每约 1 秒发 heartbeat。片段完成数在等待/重试中不会增加。
- `rate_queued` 的原因可为 `request_interval`、`fair_queue`、`global_concurrency`、`starting_request`、`request_budget`；
  `rate_limit_retry` 仅用于明确 HTTP 429；`retrying` 的原因区分 `network_error`、`provider_error`、`clock_skew_adjustment`。
  `cooling_down` 的原因为 `shared_cooldown`。`waiting.next_request_at` 是最早计划重试/请求时间，
  可据此显示等待倒计时，不能表示整书剩余时间，也不保证 FIFO 轮到本任务的时间。
- `failed` 带 `code`、`message`、`retryable`，退出码 1；`retryable` 表示错误是否属于瞬时类，
  即使 true 也已耗尽本次额度，需宿主显式发起新尝试。已完成章节和缓存保留，可使用 `--resume`。
- 宿主创建 cancel-file；调度器停止提交，正在执行的同步网络调用到返回/超时后，在安全边界停止，
  不再调用后续文本块。先报告 `cancelling`，回收所有工作线程后发 `cancelled`，退出码 3。
  规范化、变速、拼接和编码子进程可取消并回收；取消和其他单元致命失败都会停止后续媒体处理。
  完成的章节和缓存保留，重试需移除旧 cancel-file 并使用新 attempt_id。
- CLI 被强制杀死、连接断开时可能没有终止事件。宿主结合进程状态、租约、最后收到时间表示“连接中断/状态待确认”，
  不根据快照静默判定完成或失败；静默/未知版本也不增长完成量。

## 完成条件

所有所选单元完成、全部章节 MP3 通过 ffprobe 且时间轴已写入、
最终 `manifest.v2.json.status=completed` 原子写入后，才发 `event=completed`、
`snapshot.status=completed`、`snapshot.stage=completed`，退出码 0。
completed 事件附带 `manifest`、`chapter_count` 和 `duration_ms`。
Talebook 还必须完成自己的结果校验、数据库写入和发布流程，才能将页面任务标为完成/100%。

```json
{"schema":"voicebook-progress.v2","task_id":"talebook-job-123","attempt_id":"new-uuid","seq":8,"event":"segment_completed","at":"2026-10-03T00:00:00Z","unit_id":"chapter-1:segment-1","chapter_number":1,"segment_index":1,"cache_hit":false,"snapshot":{"schema":"voicebook-progress.v2","status":"running","stage":"synthesizing","unit":"speech_segment","total":12,"completed":3,"active":2,"retrying":0,"failed":0,"cancelled":0,"pending":7,"queued":0,"waiting":null,"wait_seconds":0,"requests_started":5,"edge_budget":null,"retries":0,"cache_hits":0,"active_requests":2,"concurrency":2,"chapters_total":2,"chapters_completed":0,"active_units":["chapter-1:segment-0","chapter-1:segment-2"],"updated_at":"2026-10-03T00:00:00Z"}}
```

快捷模式和高级模式继续使用同一生成协议；人工审阅边界保持由 Talebook 管理。
生成侧语音错误消息只包含错误类别、HTTP 状态及安全原因，不包含正文、原始响应体或请求 URL/凭据。
供应商配额、延迟和服务能力决定实际效果，并发上限不是固定加速承诺；本契约不要求真实付费调用。
