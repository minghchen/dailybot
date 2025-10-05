## DailyBot 开发者与Agent集成手册（AGENTS）

本手册为AI Coder与人类开发者提供对本项目的系统性理解：整体架构、核心模块职责、消息流与数据流、配置要点、扩展指南、常见陷阱与调试方法。请在进行代码修改或新增能力前先通读本文件。

### 总览
- 目标：在微信生态中自动提取分享/链接的有效信息，结合上下文用LLM生成结构化笔记，并写入 Obsidian 或 Google Docs；可选接入RAG用于对话检索增强。
- 运行入口：`app.py` 创建与装配各服务与通道，注册消息处理回调，驱动运行。
- 核心主线：Channel 接收 -> `MessageHandler` 统一处理 -> `ContentExtractor` 提取/归一化 -> `AgentService` 决策与丰富 -> `NoteManager` 分类与落库 -> 可选 `RAGService` 索引更新。

### 核心架构与模块职责

- `app.py`
  - 负责装配：加载配置(`ConfigLoader`)，初始化 `LLMService`、`NoteManager`、`RAGService`、`ContentExtractor`、`AgentService` 与具体 `Channel` 实例，并注册消息处理器。
  - 处理信号、日志初始化与主事件循环，按顺序：load_config -> setup_logging -> init_services -> register handlers -> 启动通道 -> 启动历史处理。

- `utils/config_loader.py`
  - 合并 `config/config.json` 与环境变量，做必填校验与默认值填充，兼顾路径展开与代理设置。注意：OpenAI 密钥等敏感信息仅从环境变量注入。

- `services/llm_service.py`
  - 对 OpenAI 接口的异步封装；集成 Instructor，使 `.chat.completions.create` 可直接产出 Pydantic 模型（用于结构化输出与严格响应模式）。
  - 提供 `chat` 与 `generate_embedding`（用于RAG）。

- `services/content_extractor.py`
  - 统一入口 `extract(msg, context_messages)`：解析微信 XML/文本，优先识别视频号、B站，默认走 Jina Reader 提取正文，输出归一化内容。
  - 构建对话上下文 `_build_context_with_llm`：将时间窗口内消息转换成可读摘要，用于后续决策与笔记标注。
  - 与 `AgentService` 解耦并相互注入：Extractor 获取正文，交给 Agent 做「决策-丰富-成稿」。

- `services/agent_service.py`
  - 三段式智能流程：
    1) 决策 `_decide_and_enrich`：基于正文决定 SearchAndSummarize/DirectSummarize/Irrelevant，必要时用 DuckDuckGo 搜索补充权威来源，再调用 `ContentExtractor` 读取最佳结果。
    2) 生成结构化笔记 `generate_structured_note`：强约束 Pydantic 模型 `StructuredNote`，包含 `explanation_blog/title/date/link_title/gist`；提示词中包含示例以强化风格与要点提炼。
    3) 组合 enriched 内容与原始上下文后返回给上游。

- `bot/message_handler.py`
  - 路由所有消息：`handle_text_message`、`handle_sharing_message`、历史消息处理与白名单管理。
  - 负责统一持久化消息、构建窗口上下文、在群聊中触发策略、静默模式控制，以及管理员命令（白名单维护与历史回放）。

- `services/note_manager.py`
  - 作为 Facade 对接不同笔记后端：`ObsidianManager`/`GoogleDocsManager`；两步 LLM 决策：选目标文件与决定文件内插入位置（含保守/均衡/积极策略）。
  - 全局查重，按后端文档结构定位插入点，支持在父标题下自动创建“其他”子标题。

- `channel/`
  - `channel.py` 定义 `Channel` 抽象、`Context/Reply/ReplyType`。
  - `channel_factory.py` 按 `channel_type` 装配：`js_wechaty`、`wcf`（Windows）、`mac_wechat`（macOS）。
  - 各具体通道负责与平台交互，标准化消息为 `Context`，并触发注册的处理器异步逻辑。

### 消息流与数据流

1) 通道接收原始消息 -> 构造 `Context` -> 调用 `MessageHandler`。
2) `MessageHandler`：
   - 白名单与触发策略判断；
   - 将消息落库（`utils/message_storage.py`），历史场景按窗口聚合上下文；
   - 对分享或含链接文本调用 `ContentExtractor.extract`。
3) `ContentExtractor`：
   - 解析链接与类型，优先适配视频号/B站；
   - 默认调用 Jina Reader 返回 Markdown 正文与标题；
   - 用 LLM 生成会话上下文摘要；
   - 调用 `AgentService.process_content_to_note` 产生 `StructuredNote`；
   - 返回 `url/structured_note/context/raw_content/...`。
4) `NoteManager.save_content`：
   - 查重 -> 选择目标笔记文件 -> 读取文档结构 -> 决定插入点 -> 执行保存；
   - 若启用 RAG，则调用 `RAGService.add_document` 更新向量库。

### 配置要点

- 主配置：`config/config.json`（示例见 `config/config.example.json`），敏感信息从环境变量注入。
- 关键段：
  - `channel_type`: `js_wechaty | wcf | mac_wechat`
  - `openai`: 需从环境注入 `api_key`，可选 `base_url/model/temperature`
  - `note_backend`: `obsidian | google_docs`；各自必须配置 `note_files`
  - `content_extraction`: `auto_extract_enabled/context_time_window/history_context_time_window/extract_types/silent_mode/max_summary_length`
  - `agent`: `enabled/max_decision_content`
  - `rag`: `enabled/embedding_model/vector_store_path/chunk_size/...`
  - `system`: 日志等级、历史处理批量、持久化路径、白名单文件等

注意：本库不会创建 `.env` 内容，请自行在运行环境设置所需密钥与代理。

### 开发与扩展指引

- 新增通道
  - 在 `channel/` 下实现 `Channel` 子类，标准化平台消息为 `Context`。
  - 在 `channel_factory.py` 注册分支，并按平台做条件导入。

- 新增内容源/解析器
  - 在 `ContentExtractor.extract` 中按域名/特征分流；必要时新增专用抓取函数（参考 B站分支）。
  - 保持输出结构：`{'title','content'}`，并复用 `_build_context_with_llm` 与 Agent 流程。

- 调整智能代理策略
  - 修改 `AgentService._decide_and_enrich` 的判定提示词或增加更多工具；
  - 控制 `SearchAndSummarize` 的搜索条数与代理；
  - 调整 `generate_structured_note` 的输出风格与字段约束。

- 自定义笔记分类策略
  - 通过 `config.note_management.classification_strategy` 切换保守/均衡/积极；
  - 如需更细，修改 `NoteManager._decide_insertion_location_with_llm` 的策略提示与回退规则。

### 运行与调试建议

- 日志：Loguru 已集成，文件落在 `logs/`；可在 `config.system.log_level` 调整到 `DEBUG` 追踪链路。
- 本地调试链路建议：
  1) 先单测 `ContentExtractor._fetch_content_with_reader` 与域名专用抓取；
  2) 本地构造 `msg/context_messages` 验证 `extract()` 输出结构；
  3) 以小段文本喂给 `AgentService.generate_structured_note`，检查结构化输出；
  4) 用 `NoteManager.get_document_structure()` 观察文档树，验证插入定位逻辑；
  5) 最后联通通道与历史处理，观察端到端行为。

### 常见陷阱

- 未提供 OpenAI/Jina/WeChat DB Key 等环境变量导致初始化失败。
- Google Docs 未共享给服务账号或 `document_id` 配置错误。
- RAG 与 Google Docs 同用时的限制：代码中对 GDocs+RAG 做了关闭或告警，请按日志提示处理。
- macOS 静默模式需要 `WECHAT_DB_KEY` 且依赖本地 sqlcipher；Hook 模式需用户手动安装第三方工具，本项目不负责安装。

### 目录结构（开发者视角）

```
dailybot/
├── app.py                      # 入口与装配
├── bot/                        # 机器人逻辑
│   ├── message_handler.py      # 消息处理/白名单/历史
│   └── history_processor.py    # 历史消息回放
├── channel/                    # 通道抽象与实现
│   ├── channel.py              # 抽象/Context/Reply
│   ├── channel_factory.py      # 工厂
│   ├── js_wechaty_channel.py   # JS通道
│   ├── mac_wechat_channel.py   # macOS通道
│   └── wcf_channel.py          # Windows通道
├── services/                   # 服务层
│   ├── content_extractor.py    # 统一内容提取
│   ├── llm_service.py          # LLM封装
│   ├── note_manager.py         # 笔记Facade
│   ├── google_docs_manager.py  # GDocs管理
│   ├── obsidian_manager.py     # Obsidian管理
│   ├── rag_service.py          # RAG
│   └── mac_wechat_service.py   # mac 微信支持
├── utils/                      # 工具/持久化
│   ├── config_loader.py        # 配置聚合
│   ├── message_storage.py      # SQLite存储
│   └── video_summarizer.py     # 视频摘要（可选）
├── config/                     # 配置
├── data/                       # 数据与索引
├── logs/                       # 日志
├── docs/                       # 使用指南
└── AGENTS.md                   # 本开发手册
```

### 面向AI Coder的提示

1. 永远不要尝试创建.env文件，用户自己会手动创建和写入内容（包含openai key和base url）。
2. 写代码时请务必加入细致的comment，尤其对于你在做出一些假设时候写下的代码。
3. 不要想一蹴而就的完成代码！要对没有完全把握的内容（如数据的格式，代码库的输入输出格式）先进行输出查看、独立测试或断点测试，然后再写代码，此时也要输出一些中间内容方便进一步调试。
4. 改代码时要有大局观！要考虑代码库整体的协调与一致，不要因为你改代码时只看到了一个或几个代码文件，就只改看到的文件。应该列出代码库结构，考虑每个文件的职责，然后整体性地改相关的代码文件，不能顾此失彼。

