# DailyBot（助理机器人）

一个智能的科研小助理，能够自动提取、总结和整理聊天记录中的有价值信息到笔记系统。目前支持多种微信登录方式，可跨平台运行。

## 主要功能

### 1. 自动信息提取与整理
- 自动识别聊天记录中的链接（公众号文章、B站视频、arXiv论文等）
- 提取链接前后1分钟内的对话上下文（通过消息持久化存储实现）
- 采用 [Jina AI Reader](https://github.com/jina-ai/reader) 作为核心解析引擎，通过 `https://r.jina.ai/` API，能够稳定、高效地提取任何URL（包括微信公众号、B站、Arxiv及普通网页）的核心内容，并将其转换为对LLM友好的Markdown格式。
- 使用LLM对内容进行智能总结（1-5句话精炼总结）
- 自动分类并保存到笔记系统（支持Obsidian和Google Docs）
- 智能去重，避免重复内容

### 2. 智能问答（非静默模式）
- 个人聊天：以"bot"或"@bot"开头触发
- 群组聊天：被@时触发
- 基于RAG技术，从笔记库中检索相关内容后生成回答

### 3. 白名单管理
- **灵活的白名单配置**：可以分别设置群聊白名单和个人用户白名单。
- 只有白名单中的群聊或个人用户的消息才会被处理。
- 支持通过指令动态管理白名单。
- 新会话加入时自动处理历史消息。

### 4. 智能层级分类管理
- **动态层级分析**: 能够解析笔记后端（如 Google Docs）的完整标题结构（H1, H2, H3 等），形成一个层级树。
- **LLM 决策**: 基于对新内容和现有标题层级树的理解，LLM能够智能决策：
  - 将内容插入到最合适的现有标题下（无论层级）。
  - 在现有标题下创建一个逻辑相关的子标题来存放内容。
  - 当内容主题是全新的时，在顶层创建新的一级标题。
- **自动化组织**: 实现笔记的"自组织"，无需任何手动分类或配置。

### 5. 技术特点
- 支持三种微信通道：JS Wechaty（跨平台）、wcf（Windows）和Mac微信（macOS）
- 采用 Channel 抽象架构，支持多种消息通道扩展
- 使用OpenAI API进行内容理解和生成
- 消息持久化存储（SQLite），确保完整的上下文获取
- 支持Obsidian通过iCloud同步
- 支持Google Docs云端存储
- 可部署在云服务器上

## 笔记格式示例

```markdown
**2024-03 Scaling Robot Data Without Dynamics Simulation**  
[Real2sim2Real的破局之法](https://mp.weixin.qq.com/s/-iqRIMLcMGxEEm9dn65kNw)  
在许多机器人操作任务中，精确的动力学建模可能并非必需，基于几何约束的轨迹生成已经足以支撑有效的策略学习。
```

## 🚨 重要声明

在使用本项目前，请务必了解：

**关于微信登录安全性**：
- 使用第三方微信登录方案存在一定的封号风险
- 免费的web协议（wechaty-puppet-wechat4u）存在较高封号风险
- 强烈建议使用PadLocal等付费协议，或wcf方案（Windows）
- 请务必阅读 [防封号指南](docs/anti_ban_guide.md) 了解最佳实践
- 建议使用小号测试，避免主号被封

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
- 专为macOS设计的原生方案，提供两种运行模式：
- **静默读取模式 (默认)**：定期读取聊天记录数据库，绝对安全、稳定，但有一定消息延迟。是开箱即用的推荐模式。**此模式需要用户提前获取并设置 `WECHAT_DB_KEY` 环境变量。**
- **Hook模式 (实验性)**：依赖用户**手动安装**的第三方工具 [`WeChatTweak-macOS`](https://github.com/sunnyyoung/WeChatTweak-macOS) ，实现实时消息的接收和发送。功能更强大，但需要额外配置且依赖第三方工具的稳定性。**本项目不会尝试自动安装Tweak，仅会检查其是否存在。**
- 详见 [Mac微信通道使用指南](docs/mac_wechat_guide.md)

## 架构说明

### Channel 架构
本项目采用了 Channel 抽象架构，将消息接收、处理、发送的逻辑抽象化：
- **Channel 基类**：定义了统一的消息处理接口
- **JSWechatyChannel**：基于 JavaScript Wechaty 实现的微信通道
- **WcfChannel**：基于 WeChat-Ferry 实现的Windows微信通道
- **MacWeChatChannel**：基于本地数据库读取或集成第三方Hook工具实现的macOS通道
- **可扩展性**：未来可以轻松添加企业微信、飞书、钉钉等其他通道

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
│   ├── mac_wechat_service.py   # Mac微信服务
│   └── rag_service.py          # RAG服务
├── utils/                      # 工具类
│   ├── time_utils.py           # 时间工具
│   ├── video_summarizer.py     # 视频总结工具
│   └── message_storage.py      # 消息持久化存储
├── config/                     # 配置文件目录
│   └── config.example.json     # 配置文件示例
├── data/                       # 数据存储目录
│   ├── messages.db             # 消息数据库
│   └── vector_store/           # 向量数据库
├── logs/                       # 日志目录
├── scripts/                    # 脚本工具
│   ├── start.sh                # 快速启动脚本
│   ├── start_mac.sh            # Mac专用启动脚本
│   └── js_wechaty_server.example.js  # JS Wechaty服务示例
├── docs/                       # 文档目录
├── templates/                  # 模板文件
├── Dockerfile                  # Docker镜像配置
├── docker-compose.yml          # Docker Compose配置
├── requirements.txt            # Python依赖
└── README.md                   # 项目说明文档
```

## 环境要求

- Python 3.8+
- 根据使用的通道有不同要求：
  - JS Wechaty通道：需要Node.js环境
  - WCF通道：仅支持Windows系统
  - Mac微信通道：仅支持macOS系统

### 安装tips

除了requirements.txt里的包，还有很多其他需要的，建议根据报错安装。

pip install pysqlcipher3 之前需要：
- brew install sqlcipher
- brew install openssl
- export SQLCIPHER_PATH="$(brew --prefix sqlcipher)"
- export LIBRARY_PATH="$SQLCIPHER_PATH/lib:$LIBRARY_PATH"
- export C_INCLUDE_PATH="$SQLCIPHER_PATH/include:$C_INCLUDE_PATH"

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
  - 静默模式（默认）：无需特殊配置，在 `config.json` 中设置 `channel_type` 为 `mac_wechat` 即可。**必须在 `.env` 文件或环境变量中设置 `WECHAT_DB_KEY`。**
  - Hook模式：
    1.  用户必须**手动**访问 [WeChatTweak-macOS 官网](https://github.com/sunnyyoung/WeChatTweak-macOS) 并按照其说明进行安装。
    2.  在 `config.json` 中设置 `channel_type` 为 `mac_wechat`，并可在 `mac_wechat` 配置块中将 `mode` 设置为 `hook`。

4. 配置
- 复制 `config/config.example.json` 为 `config/config.json`
- 创建 `.env` 文件并设置API密钥等敏感信息：
  ```bash
  # OpenAI配置
  OPENAI_API_KEY=你的OpenAI_API密钥
  OPENAI_BASE_URL=https://api.openai.com/v1
  
  # Jina AI Reader API Key (用于微信公众号等复杂页面提取)
  JINA_API_KEY=你的Jina_API密钥

  # Mac微信通道（静默模式）配置
  WECHAT_DB_KEY=你的64位数据库密钥
  
  # JS Wechaty配置（如果使用PadLocal）
  WECHATY_PUPPET=wechaty-puppet-padlocal
  WECHATY_PUPPET_SERVICE_TOKEN=你的padlocal_token
  
  # Mac微信Hook模式配置（可选，在config.json中配置）
  # "mac_wechat": { "mode": "hook" }
  ```
- 在 `config.json` 中，确认 `channel_type` 设置正确。

5. 运行
```bash
python app.py
```

## 配置说明

配置文件 `config/config.example.json` 包含了所有支持的配置选项。根据你选择的通道类型（`channel_type`），只需要配置对应的部分即可。

### 基础配置示例

```json
{
  "channel_type": "mac_wechat",  // 选择通道类型：js_wechaty | wcf | mac_wechat
  
  // JS Wechaty配置（跨平台）
  "js_wechaty": {
    "ws_url": "ws://localhost:8788",         // WebSocket服务地址
    "single_chat_prefix": ["bot", "@bot"],   // 私聊触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊触发前缀
    "group_name_white_list": [],             // 群聊白名单
    "user_name_white_list": [],              // 用户白名单
    "message_limit_per_minute": 20,          // 每分钟消息限制
    "min_reply_delay": 2,                    // 最小回复延迟（秒）
    "max_reply_delay": 5                     // 最大回复延迟（秒）
  },
  
  // wcf配置（仅Windows）
  "wcf": {
    "single_chat_prefix": ["bot", "@bot"],   // 私聊触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊触发前缀
    "group_name_white_list": [],             // 群聊白名单
    "user_name_white_list": [],              // 用户白名单
    "group_at_sender": true                  // 群聊是否@发送者
  },
  
  // Mac微信配置（仅macOS）
  "mac_wechat": {
    "mode": "silent",                        // 运行模式: silent | hook
    "poll_interval": 60,                     // 静默模式轮询间隔（秒）
    "single_chat_prefix": ["bot", "@bot"],   // 私聊/Hook模式触发前缀
    "group_chat_prefix": ["@bot"],           // 群聊/Hook模式触发前缀
    "group_name_white_list": [],             // 群聊白名单
    "user_name_white_list": [],               // 用户白名单
    "message_retention_days": 30             // 消息保留天数
  },
  
  "openai": {
    // API密钥和base_url从环境变量读取
    "model": "gpt-4.1",                  // 使用的模型
    "temperature": 0.7,                      // 生成温度
  },
  
  "note_backend": "obsidian",  // 笔记后端：obsidian | google_docs
  
  "note_management": {
    "classification_strategy": "balanced" // 分类策略: diligent_categorizer (努力归档), cautious_filer (谨慎归档), balanced (均衡), aggressive (激进)
  },
  
  "obsidian": {
    "vault_path": "/path/to/your/vault",     // Obsidian仓库路径
    "note_files": [                          // 笔记文件配置
      {
        "name": "AI研究笔记",
        "folder": "AI",                          // 可选，仓库下的子文件夹
        "filename": "AI研究笔记.md",
        "description": "人工智能相关的论文、技术和理论研究"
      },
      {
        "name": "机器人技术",
        "folder": "Robotics",                    // 可选，仓库下的子文件夹
        "filename": "机器人技术.md",
        "description": "机器人、具身智能、操作和控制相关内容"
      }
    ]
  },

  "proxy": {
    "https": "http://127.0.0.1:7890"  // 网络代理
  },
  
  "google_docs": {
    "credentials_file": "config/google_credentials.json",
    "note_files": [                      // Google Docs文档配置
      {
        "name": "DaliyAI笔记本",
        "document_id": "1B6_K3CB0nH1obz2dfltVvwVVFOklKlUPhHHG0aNwLxw",
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
  
  "agent": {
    "enabled": true,                         // 是否启用智能代理（自动搜索增强）
    "max_decision_content": 4000             // 用于决策的原始内容最大字符数
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
  
  "system": {
    "log_level": "INFO",
    "timezone": "Asia/Shanghai",
    "admin_list": [],                        // 管理员列表
    "whitelist_file": "config/group_whitelist.json", // 动态白名单存储文件
    "message_queue_size": 100,               // 待处理消息队列大小
    "auto_save_interval": 300,               // 自动保存间隔（秒）
    "history_batch_size": 50,                // 历史消息处理批次大小
    "history_process_delay": 0.5,            // 处理每条历史消息的延迟（秒）
    "max_history_days": 30,                  // 处理历史消息的最大天数
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

### 白名单管理

#### 配置方式
1. **静态配置**：在 `config.json` 中分别设置 `group_name_white_list` 和 `user_name_white_list`。
   - `group_name_white_list`: `["群聊名称1", "群聊名称2"]`
   - `user_name_white_list`: `["联系人昵称1", "联系人备注1"]`

2. **动态管理**：通过管理命令动态添加/移除（此功能待完善以支持两种列表）
   - 发送私聊消息给机器人：
     - `#add_group 群组名称`: 添加群组到白名单
     - `#add_user 用户名称`: 添加用户到白名单
     - `#list_whitelists`: 查看所有白名单

3. **管理员权限**：在配置中设置 `system.admin_list` 来限制管理命令的使用

#### 历史消息处理
当新的群聊或用户加入白名单时，机器人会自动：
1. 扫描该会话的历史聊天记录（基于已存储的消息）
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
# 使用管理命令：#import_history /path/to/export.txt 会话名称
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
- 支持按时间、会话查询历史消息

### 2. 动态分类管理
- **对于Google Docs和Obsidian**:
  - 引入了先进的动态层级分类功能。机器人会实时解析文档（Google Doc或Markdown文件）的完整标题结构，并由LLM智能决策最佳插入位置。详见下一节。

### 3. 多文件管理和智能分类
- 支持配置多个笔记文件（Obsidian或Google Docs），每个文件可以有不同主题。
- LLM首先会根据内容主题和你在配置中对每个文件的描述，来自动选择最合适的笔记文件。

当有新内容需要存入 **Google Docs** 或 **Obsidian** 时，机器人都会执行统一的、智能的层级分类流程，确保笔记的有机组织和生长。

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
  - 追求**绝对安全和稳定**，且能接受消息有延迟（例如只用于信息归档），请使用默认的**静默模式**。确保已在`.env`文件中正确设置`WECHAT_DB_KEY`。
  - 追求**实时消息和自动回复**，且不介意额外安装一个工具，请在**手动安装** `WeChatTweak-macOS` 后，启用**Hook模式**。本程序只负责与Tweak生成的日志进行通信，不会修改您的微信客户端。
- **Linux/其他用户**：使用JS Wechaty
- **长期稳定运行**：
  - Mac: 默认的静默模式最可靠。
  - 其他: 购买PadLocal协议（JS WeChaty）。

### Q: Mac微信通道的两种模式有什么区别？
A:
- **静默模式 (默认)**:
  - **原理**: 直接解密并读取微信本地数据库。不注入任何代码，不修改微信客户端。
  - **优点**: 绝对安全，不会被微信检测。配置简单，只需提供数据库密钥。
  - **缺点**: 消息有延迟（取决于轮询间隔），无法实现自动回复等实时交互。
- **Hook模式 (实验性)**:
  - **原理**: 依赖一个**已由用户手动安装**的第三方工具 `WeChatTweak-macOS`。本程序通过读取该工具生成的日志来接收消息，通过AppleScript来发送消息。本程序自身不执行任何"Hook"操作。
  - **优点**: 可以实时收发消息，支持自动回复。
  - **缺点**: 需要用户额外安装和维护 `WeChatTweak-macOS`。功能的稳定性依赖于该第三方工具。

### Q: 如何避免封号？
A:
1. 不要使用免费的web协议
2. 控制消息发送频率
3. 使用小号测试
4. 购买付费协议（如PadLocal）可以显著降低风险。
5. Mac用户使用本项目提供的静默模式是当前最安全的选择。
6. 详见 [防封号指南](docs/anti_ban_guide.md)

### Q: 登录失败怎么办？
A: 
- **Mac静默模式**: 检查 `WECHAT_DB_KEY` 环境变量是否已在 `.env` 文件中正确设置且密钥有效。检查系统是否已安装 `sqlcipher` (`brew install sqlcipher`)。
- **Mac Hook模式**: 确认你已经**手动成功安装并运行了 `WeChatTweak-macOS`**。检查本程序的日志，看是否有检测到Tweak已安装的提示。
- **其他通道**: 检查对应的服务是否启动（如JS服务或wcf客户端）。
- 查看日志文件 (`logs/`) 中的具体错误信息。
- 确认 `config.json` 中的配置是否正确。

### Q: 如何处理大量历史消息？
A: 可以使用批量导入功能，或者分批次逐步添加会话到白名单。系统会自动从消息存储中获取上下文。

### Q: 为什么某些链接无法提取内容？
A: 本项目现在依赖 [Jina AI Reader](https://github.com/jina-ai/reader) 进行内容提取，它能处理绝大多数网页。如果遇到特定网站无法提取，可以向 [Jina AI Reader项目](https://github.com/jina-ai/reader/issues) 提出issue，或者在 `services/content_extractor.py` 中实现针对该网站的自定义提取逻辑作为备用方案。

### Q: 如何备份数据？
A: 
- Obsidian笔记通过iCloud自动同步
- 向量数据库在 `data/vector_store` 目录
- 会话白名单在 `config/group_whitelist.json`
- 消息数据库在 `data/messages.db`

### Q: 如何自定义分类？
A: 你几乎不需要手动管理！
- **对于 Google Docs**: 分类是完全动态和自动的。机器人会读取你文档中的所有标题层级，并让 LLM 决定新内容应该放在哪里，或者在哪里创建新标题。你只需要像平时一样在 Google Docs 中通过创建各级标题来组织你的文档，机器人会自动适应。
- **对于 Obsidian**:
  - **使用笔记文件**: 在配置中定义多个笔记文件，机器人会智能选择。在每个文件中，通过二级标题（`## 类别名`）组织内容，机器人会自动识别和使用它们。
  - **使用文件夹**（旧方式）: 在Knowledge Base下创建子文件夹，文件夹名即为分类。

### Q: 如何管理多个主题的笔记？
A: 
1. 在配置文件中设置`note_files`（针对Obsidian和Google Docs），定义多个笔记文件/文档。
2. 每个文件可以有不同的主题和描述，这个描述会帮助LLM选择正确的文件。
3. 之后，机器人会根据内容自动选择合适的文件，并进行智能分类。
4. **Google Docs**: 在每个文档内部，机器人通过分析各级标题（H1, H2, H3...）来自动维护层级分类。
5. **Obsidian**: 在每个文件内部，使用Markdown标题（`#`, `##`, `###` ...）组织内容，机器人会自动识别和使用它们。

### Q: 如何自定义分类结构？
A: 
- **Google Docs / Obsidian**: 直接在你的文档/Markdown文件里维护你想要的标题结构即可。你可以随时新增、删除、修改、调整标题层级，机器人下次运行时会自动识别新的结构。
- **Obsidian (旧版文件夹模式)**: 在知识库文件夹中创建新的子文件夹即可，机器人会自动识别并使用。

## 开发计划

- [x] 基础框架搭建
- [x] 微信消息接收与处理
- [x] 内容提取与总结
- [x] Obsidian笔记集成
- [x] RAG问答系统
- [x] 会话白名单管理
- [x] 历史消息处理
- [x] 消息持久化存储
- [x] 动态分类管理 (支持 Obsidian 文件夹/文件内二级标题)
- [x] **增强的动态层级分类** (支持 Google Docs 完整标题树和 LLM 智能决策)
- [x] 智能去重功能
- [x] Channel 抽象架构，支持三种微信通道
- [x] 稳定、安全的Mac微信静默读取模式
- [x] 采用Jina AI Reader重构内容提取，增强稳定性
- [ ] 更多内容源支持
- [ ] 多模态内容处理
- [ ] 支持企业微信、飞书等更多通道


