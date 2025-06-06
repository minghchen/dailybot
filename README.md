# DailyBot（日报机器人）

一个智能的聊天机器人，能够自动提取、总结和整理聊天记录中的有价值信息到笔记系统。支持多种微信登录方式，可跨平台运行。

## 🚨 重要声明

在使用本项目前，请务必了解：

**关于微信登录安全性**：
- 使用第三方微信登录方案存在一定的封号风险
- 免费的web协议（wechaty-puppet-wechat4u）存在较高封号风险
- 强烈建议使用PadLocal等付费协议，或wcf方案（Windows）
- 请务必阅读 [防封号指南](docs/anti_ban_guide.md) 了解最佳实践
- 建议使用小号测试，避免主号被封

## 主要功能

### 1. 自动信息提取与整理
- 自动识别聊天记录中的链接（公众号文章、B站视频、arXiv论文等）
- 提取链接前后1分钟内的对话上下文（通过消息持久化存储实现）
- 使用LLM对内容进行智能总结（1-5句话精炼总结）
- 自动分类并保存到笔记系统（支持Obsidian和Google Docs）
- 智能去重，避免重复内容

### 2. 智能问答
- 个人聊天：以"bot"或"@bot"开头触发
- 群组聊天：被@时触发
- 基于RAG技术，从笔记库中检索相关内容后生成回答

### 3. 群组白名单管理
- 灵活的群组白名单配置，只有白名单中的群组才会启用功能
- 支持动态添加/移除群组
- 新群组加入时自动处理历史消息
- 支持导入导出的聊天记录处理

### 4. 动态分类管理
- 支持多个笔记文件配置（每个文件可以有不同主题）
- LLM智能选择合适的笔记文件和类别
- 自动扫描笔记文件中的现有类别
- 在合适的类别下插入新内容，或创建新类别

### 5. 技术特点
- 支持三种微信通道：JS Wechaty（跨平台）、wcf（Windows）和Mac微信（macOS）
- 采用 Channel 抽象架构，支持多种消息通道扩展
- 使用OpenAI API进行内容理解和生成
- 消息持久化存储（SQLite），确保完整的上下文获取
- 支持Obsidian通过iCloud同步
- 支持Google Docs云端存储
- 可部署在云服务器上

## 微信登录方案

本项目支持三种微信登录方案：

### 1. JS Wechaty（跨平台）
- 需要运行独立的JavaScript服务
- 通过WebSocket与Python主程序通信
- 支持多种协议（推荐使用PadLocal付费协议）
- 详见 [微信登录方案说明](docs/wechat_login_methods.md#方案一javascript-wechaty)

### 2. WeChat-Ferry (wcf)（仅Windows）
- 基于Hook技术，直接操作微信PC客户端
- 稳定性高，但仅支持Windows系统
- 需要特定版本的微信客户端
- 详见 [微信登录方案说明](docs/wechat_login_methods.md#方案二wechat-ferry-wcf)

### 3. Mac微信通道（仅macOS）🆕
- 专为macOS设计的原生方案
- **静默读取模式**：定期读取聊天记录数据库，安全稳定
- **Hook模式**：实时消息监听和自动回复（需要关闭SIP）
- 详见 [Mac微信通道使用指南](docs/mac_wechat_hook_guide.md)

## 笔记格式示例

```markdown
**2024-03 Scaling Robot Data Without Dynamics Simulation**  
[Real2sim2Real的破局之法](https://mp.weixin.qq.com/s/-iqRIMLcMGxEEm9dn65kNw)  
在许多机器人操作任务中，精确的动力学建模可能并非必需，基于几何约束的轨迹生成已经足以支撑有效的策略学习。
```

## 项目结构

```
dailybot/
├── app.py                      # 主程序入口
├── bot/                        # 机器人核心逻辑
│   ├── message_handler.py      # 消息处理器
│   └── history_processor.py    # 历史消息处理器
├── channel/                    # 消息通道抽象层
│   ├── channel.py              # Channel基类
│   ├── channel_factory.py      # Channel工厂
│   ├── js_wechaty_channel.py   # JS Wechaty通道实现
│   ├── mac_wechat_channel.py   # Mac微信通道实现
│   └── wcf_channel.py          # WeChat-Ferry通道实现
├── services/                   # 服务层
│   ├── content_extractor.py    # 内容提取服务
│   ├── llm_service.py          # LLM调用服务
│   ├── note_manager.py         # 笔记管理服务
│   ├── google_docs_manager.py  # Google Docs管理器
│   └── rag_service.py          # RAG服务
├── utils/                      # 工具类
│   ├── link_parser.py          # 链接解析器
│   ├── time_utils.py           # 时间工具
│   ├── video_summarizer.py     # 视频总结工具
│   └── message_storage.py      # 消息持久化存储
├── config/                     # 配置文件目录
│   └── config.example.json     # 配置文件示例
├── data/                       # 数据存储目录
│   ├── messages.db             # 消息数据库
│   └── vector_store/           # 向量数据库
├── logs/                       # 日志目录
├── plugins/                    # 插件系统
├── scripts/                    # 脚本工具
│   ├── start.sh                # 快速启动脚本
│   ├── start_mac.sh            # Mac专用启动脚本
│   ├── upgrade.py              # 升级脚本
│   └── js_wechaty_server.example.js  # JS Wechaty服务示例
├── docs/                       # 文档目录
├── templates/                  # 模板文件
├── Dockerfile                  # Docker镜像配置
├── docker-compose.yml          # Docker Compose配置
├── requirements.txt            # Python依赖
└── README.md                   # 项目说明文档
```

## 架构说明

### Channel 架构
本项目采用了 Channel 抽象架构，将消息接收、处理、发送的逻辑抽象化：
- **Channel 基类**：定义了统一的消息处理接口
- **JSWechatyChannel**：基于 JavaScript Wechaty 实现的微信通道
- **WcfChannel**：基于 WeChat-Ferry 实现的Windows微信通道
- **可扩展性**：未来可以轻松添加企业微信、飞书、钉钉等其他通道

## 环境要求

- Python 3.8+
- 根据使用的通道有不同要求：
  - JS Wechaty通道：需要Node.js环境
  - WCF通道：仅支持Windows系统
  - Mac微信通道：仅支持macOS系统

## 快速开始

### Mac用户专属快速启动 🆕

```bash
# 克隆项目
git clone https://github.com/yourusername/dailybot.git
cd dailybot

# 运行Mac专用启动脚本
./scripts/start_mac.sh

# 脚本会自动：
# 1. 检查环境依赖
# 2. 安装必要组件
# 3. 创建配置文件
# 4. 引导你选择运行模式
# 5. 启动服务
```

### 方式一：使用快速启动脚本（推荐）

```bash
# 克隆项目
git clone https://github.com/yourusername/dailybot.git
cd dailybot

# 运行快速启动脚本
chmod +x scripts/start.sh
./scripts/start.sh

# 脚本会自动：
# 1. 创建 .env 文件（如果不存在）
# 2. 检查必要的配置
# 3. 创建 config.json（从示例复制）
# 4. 使用 Docker Compose 启动服务
```

### 方式二：手动配置

1. 克隆项目
```bash
git clone https://github.com/yourusername/dailybot.git
cd dailybot
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 选择并配置登录方案
- **JS Wechaty**：参考 [微信登录方案说明](docs/wechat_login_methods.md#方案一javascript-wechaty)
- **wcf**：参考 [微信登录方案说明](docs/wechat_login_methods.md#方案二wechat-ferry-wcf)
- **Mac微信**：
  - 静默模式（默认）：无需特殊配置，设置 `channel_type` 为 `mac_wechat` 即可
  - Hook模式：需要关闭SIP，设置 `MAC_WECHAT_USE_HOOK=true` 环境变量

4. 配置
- 复制 `config/config.example.json` 为 `config/config.json`
- 创建 `.env` 文件并设置API密钥等敏感信息：
  ```bash
  # OpenAI配置
  OPENAI_API_KEY=你的OpenAI_API密钥
  OPENAI_BASE_URL=https://api.openai.com/v1
  
  # JS Wechaty配置（如果使用PadLocal）
  WECHATY_PUPPET=wechaty-puppet-padlocal
  WECHATY_PUPPET_SERVICE_TOKEN=你的padlocal_token
  
  # Mac微信Hook模式配置（可选）
  MAC_WECHAT_USE_HOOK=true
  ```
- 根据你选择的通道类型，在 `config.json` 中设置相应的配置

5. 运行
```bash
python app.py
```

## 配置说明

配置文件 `config/config.example.json` 包含了所有支持的配置选项。根据你选择的通道类型（`channel_type`），只需要配置对应的部分即可。

### 基础配置示例

```json
{
  "channel_type": "js_wechaty",  // 选择通道类型：js_wechaty | wcf | mac_wechat
  
  // JS Wechaty配置（跨平台）
  "js_wechaty": {
    "ws_url": "ws://localhost:8788",         // WebSocket服务地址
    "single_chat_prefix": ["bot", "@bot"],   // 私聊触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊触发前缀
    "group_name_white_list": [],             // 群组白名单
    "message_limit_per_minute": 20,          // 每分钟消息限制
    "min_reply_delay": 2,                    // 最小回复延迟（秒）
    "max_reply_delay": 5                     // 最大回复延迟（秒）
  },
  
  // wcf配置（仅Windows）
  "wcf": {
    "single_chat_prefix": ["bot", "@bot"],   // 私聊触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊触发前缀
    "group_name_white_list": [],             // 群组白名单
    "group_at_sender": true                  // 群聊是否@发送者
  },
  
  // Mac微信配置（仅macOS）
  "mac_wechat": {
    "mode": "silent",                        // 运行模式：silent|hook
    "poll_interval": 60,                     // 静默模式轮询间隔（秒）
    "single_chat_prefix": ["bot", "@bot"],   // 私聊触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊触发前缀
    "group_name_white_list": [],             // 群组白名单
    "enable_hook": false,                    // 是否启用Hook模式
    "auto_reply_rules": {                    // Hook模式自动回复规则
      "你好": "你好！有什么可以帮助你的吗？",
      "在吗": "在的，请说"
    }
  },
  
  "openai": {
    // API密钥和base_url从环境变量读取
    "model": "gpt-4o-mini",                  // 使用的模型
    "temperature": 0.7,                      // 生成温度
    "max_tokens": 2000,                      // 最大生成长度
    "conversation_max_tokens": 1000,         // 对话历史最大长度
    "proxy": ""                              // 代理设置（可选）
  },
  
  "note_backend": "obsidian",  // 笔记后端：obsidian | google_docs
  
  "obsidian": {
    "vault_path": "/path/to/your/vault",     // Obsidian仓库路径
    "daily_notes_folder": "Daily Notes",     // 日记文件夹
    "knowledge_base_folder": "Knowledge Base", // 知识库文件夹
    "template_path": "Templates/Daily Note Template.md", // 日记模板路径
    "note_files": [                          // 笔记文件配置（可选）
      {
        "name": "AI研究笔记",
        "filename": "AI研究笔记.md",
        "description": "人工智能相关的论文、技术和理论研究"
      },
      {
        "name": "机器人技术",
        "filename": "机器人技术.md",
        "description": "机器人、具身智能、操作和控制相关内容"
      }
    ]
  },
  
  "google_docs": {
    "credentials_file": "config/google_credentials.json",
    "note_documents": [                      // Google Docs文档配置
      {
        "name": "AI研究笔记",
        "document_id": "YOUR_DOC_ID",
        "description": "人工智能相关的论文、技术和理论研究"
      }
    ]
  },
  
  "content_extraction": {
    "context_time_window": 60,               // 上下文时间窗口（分钟）
    "auto_extract_enabled": true,            // 是否自动提取
    "extract_types": ["wechat_article", "bilibili_video", "arxiv_paper", "pdf", "web_link"],
    "silent_mode": true,                     // 静默模式
    "max_summary_length": 500                // 最大总结长度
  },
  
  "rag": {
    "enabled": true,                         // 是否启用RAG
    "embedding_model": "text-embedding-ada-002",
    "vector_store_path": "data/vector_store",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "top_k": 5,
    "similarity_threshold": 0.7
  },
  
  "bilibili": {
    "summarizer_api": "",                    // B站视频总结API
    "cookies": ""                            // B站cookies
  },
  
  "system": {
    "log_level": "INFO",
    "message_queue_size": 100,
    "auto_save_interval": 300,
    "timezone": "Asia/Shanghai",
    "admin_list": [],                        // 管理员列表
    "whitelist_file": "config/group_whitelist.json",
    "history_batch_size": 50,
    "history_process_delay": 0.5,
    "max_history_days": 30,
    "message_db_path": "data/messages.db",   // 消息数据库路径
    "message_retention_days": 30             // 消息保留天数
  }
}
```

### 配置优先级
程序会按以下优先级读取配置：
1. 环境变量（最高优先级）
2. config.json 中的配置
3. 默认值（如果都没有配置）

### 群组白名单管理

#### 配置方式
1. **静态配置**：在 `config.json` 中设置 `group_name_white_list`
   - `[]`: 空列表，需要手动添加群组
   - `["群组1", "群组2"]`: 只对指定群组生效

2. **动态管理**：通过管理命令动态添加/移除群组
   - 发送私聊消息给机器人：
     - `#add_group 群组名称`: 添加群组到白名单
     - `#remove_group 群组名称`: 从白名单移除群组
     - `#list_groups`: 查看当前白名单

3. **管理员权限**：在配置中设置 `system.admin_list` 来限制管理命令的使用

#### 历史消息处理
当新群组加入白名单时，机器人会自动：
1. 扫描该群组的历史聊天记录（基于已存储的消息）
2. 提取其中的链接和相关内容
3. 按照正常流程整理到笔记系统中

**注意**：由于微信API限制，历史消息获取功能可能需要：
- 使用导出的聊天记录文件
- 配合其他工具获取历史数据
- 详见 `bot/history_processor.py` 中的实现

#### 导入聊天记录
支持处理导出的聊天记录：
```python
# 支持的格式：txt、json、html
# 使用管理命令：#import_history /path/to/export.txt 群组名称
```

### Google Docs 配置 (可选)

若使用 Google Docs 作为笔记后端，请按以下步骤配置：

1. **Google Cloud 设置**:
   - 在 [Google Cloud Console](https://console.cloud.google.com/) 创建或选择项目
   - 启用 "Google Docs API" 和 "Google Drive API"

2. **服务账号及密钥**:
   - 创建服务账号 (路径一般为 API 和服务 > 凭据)
   - 授予 "编辑者" 角色
   - 为此服务账号生成 JSON 格式的密钥并下载

3. **项目配置**:
   - 将下载的 JSON 密钥文件（通常建议命名为 `google_credentials.json`）放入 `config/` 目录
   - 在 `config/config.json` 文件的 `google_docs` 部分，填写您的Google Docs文档的 `document_id`

4. **共享文档**:
   - 打开您下载的JSON密钥文件，找到并复制 `client_email` 字段的值
   - 打开您的目标Google Docs文档，通过"共享"功能，将此 `client_email` 添加为协作者，并授予"编辑者"权限

## 核心功能说明

### 1. 消息持久化存储
- 所有消息都会自动保存到SQLite数据库
- 确保能获取完整的时间窗口内的上下文
- 支持按时间、群组查询历史消息

### 2. 动态分类管理
- 系统自动扫描Obsidian知识库文件夹作为分类
- 无需在配置文件中定义分类
- 机器人会自动适应用户对文件夹的修改

### 3. 多文件管理和智能分类
- 支持配置多个笔记文件，每个文件有不同主题
- LLM自动选择最合适的笔记文件
- 智能识别或创建合适的类别
- 在类别下正确插入新内容

#### 配置示例
```json
"note_files": [
  {
    "name": "AI研究笔记",
    "filename": "AI研究笔记.md",
    "description": "人工智能相关的论文、技术和理论研究"
  },
  {
    "name": "机器人技术",
    "filename": "机器人技术.md", 
    "description": "机器人、具身智能、操作和控制相关内容"
  }
]
```

当有新内容时，机器人会：
1. 根据内容主题选择合适的笔记文件
2. 分析文件中的现有类别（二级标题）
3. 选择合适的类别或建议新类别
4. 在该类别下插入格式化的内容

### 4. 智能去重
- 检测相同URL或标题的内容
- 避免重复保存相同信息
- 支持内容更新而非简单追加

### 5. 改进的笔记格式
- arXiv论文日期精确到月份（YYYY-MM）
- 确保论文标题完整不被截断
- 更清晰的格式化输出

## 高级功能

### RAG（检索增强生成）
- 自动构建向量数据库索引
- 基于语义相似度检索相关笔记
- 结合检索结果生成更准确的回答

### 内容提取器扩展
可以轻松添加新的内容源支持：
1. 在 `link_parser.py` 中添加链接识别规则
2. 在 `content_extractor.py` 中实现提取逻辑

### 笔记模板自定义
可以通过修改 `note_manager.py` 中的模板来自定义笔记格式

## 部署建议

### 服务器部署
```bash
# 使用nohup后台运行
nohup python app.py > dailybot.log 2>&1 &

# 使用systemd服务（推荐）
sudo cp dailybot.service /etc/systemd/system/
sudo systemctl enable dailybot
sudo systemctl start dailybot
```

### Docker部署
```bash
# 构建镜像
docker build -t dailybot .

# 运行容器
docker run -d --name dailybot \
  -v /path/to/config:/app/config \
  -v /path/to/data:/app/data \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  dailybot
```

### 使用 docker-compose
```bash
# 使用提供的docker-compose.yml
docker-compose up -d
```

## 常见问题

### Q: 如何选择登录方案？
A: 
- **Windows用户**：推荐使用wcf，稳定性高
- **Mac用户**：
  - 推荐使用Mac微信通道的静默模式，安全稳定
  - 如需自动回复功能，可以使用Hook模式或JS Wechaty
- **Linux用户**：使用JS Wechaty
- **长期稳定运行**：
  - Mac: 使用Mac微信通道的静默模式
  - 其他: 购买PadLocal协议（JS Wechaty）

### Q: Mac微信通道的两种模式有什么区别？
A:
- **静默模式**：
  - 定期读取数据库，获取聊天记录
  - 不需要Hook，更安全
  - 适合笔记整理等不需要即时响应的场景
  - 不会被微信检测到第三方修改
- **Hook模式**：
  - 实时监听消息，支持自动回复
  - 需要关闭SIP，可能有封号风险
  - 适合需要即时交互的场景
  - 仅支持微信3.6.0或更低版本

### Q: 如何避免封号？
A:
1. 不要使用免费的web协议
2. 控制消息发送频率
3. 使用小号测试
4. 购买付费协议（如PadLocal）
5. Mac用户使用静默模式最安全
6. 详见 [防封号指南](docs/anti_ban_guide.md)

### Q: 登录失败怎么办？
A: 
1. 检查对应的服务是否启动（JS服务或微信客户端）
2. 查看日志中的具体错误信息
3. 确认配置文件是否正确
4. 尝试重新登录

### Q: 如何处理大量历史消息？
A: 可以使用批量导入功能，或者分批次逐步添加群组到白名单。系统会自动从消息存储中获取上下文。

### Q: 为什么某些链接无法提取内容？
A: 可能是网站有反爬虫措施，可以在 `content_extractor.py` 中添加特定的处理逻辑。

### Q: 如何备份数据？
A: 
- Obsidian笔记通过iCloud自动同步
- 向量数据库在 `data/vector_store` 目录
- 群组白名单在 `config/group_whitelist.json`
- 消息数据库在 `data/messages.db`

### Q: 如何自定义分类？
A: 直接在Obsidian知识库文件夹中创建新的子文件夹即可，机器人会自动识别并使用。

### Q: 如何管理多个主题的笔记？
A: 
1. 在配置文件中设置`note_files`，定义多个笔记文件
2. 每个文件可以有不同的主题和描述
3. 机器人会根据内容自动选择合适的文件
4. 在每个文件内，使用二级标题（##）作为类别

### Q: 如何自定义分类结构？
A: 
- **使用笔记文件**：在配置中定义多个笔记文件，机器人会智能选择
- **使用文件夹**（旧方式）：在Knowledge Base下创建子文件夹
- **文件内分类**：使用二级标题（## 类别名）组织内容

## 开发计划

- [x] 基础框架搭建
- [x] 微信消息接收与处理
- [x] 内容提取与总结
- [x] Obsidian笔记集成
- [x] RAG问答系统
- [x] 群组白名单管理
- [x] 历史消息处理
- [x] 消息持久化存储
- [x] 动态分类管理
- [x] 智能去重功能
- [x] Channel 抽象架构
- [x] 三种微信通道支持
- [x] 防封号措施
- [ ] 更多内容源支持
- [ ] 多模态内容处理
- [ ] 支持企业微信、飞书等更多通道
