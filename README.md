# DailyBot - 微信信息整理AI助手

## 项目简介

DailyBot 是一个基于微信的智能信息整理助手，能够自动提取和整理聊天记录中的有价值信息（如论文、文章、视频等），并提供基于RAG（检索增强生成）的智能问答功能。

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
- 自动扫描Obsidian知识库文件夹结构作为分类
- 机器人自动适应用户对分类的手动修改
- 无需在配置文件中预定义分类

### 5. 技术特点
- 基于itchat框架实现微信接口
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

## 项目结构

```
dailybot/
├── bot/                    # 机器人核心逻辑
│   ├── wechat_bot.py      # 微信机器人主类
│   ├── message_handler.py  # 消息处理器
│   └── history_processor.py # 历史消息处理器
├── services/              # 服务层
│   ├── content_extractor.py   # 内容提取服务
│   ├── llm_service.py         # LLM调用服务
│   ├── note_manager.py        # 笔记管理服务
│   ├── google_docs_manager.py # Google Docs管理器
│   └── rag_service.py         # RAG服务
├── utils/                 # 工具类
│   ├── link_parser.py     # 链接解析器
│   ├── time_utils.py      # 时间工具
│   ├── video_summarizer.py # 视频总结工具
│   └── message_storage.py  # 消息持久化存储
├── config/               # 配置文件
│   └── config.json       # 配置文件
├── plugins/              # 插件系统
├── scripts/              # 脚本工具
│   └── upgrade.py        # 升级脚本
├── requirements.txt      # 依赖包
└── app.py               # 主程序入口
```

## 快速开始

1. 克隆项目
```bash
git clone https://github.com/yourusername/dailybot.git
cd dailybot
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置
- 复制 `config/config.example.json` 为 `config/config.json`
- 填写必要的配置信息（OpenAI API Key、Obsidian路径等）

4. 运行升级脚本（如果是从旧版本升级）
```bash
python scripts/upgrade.py
```

5. 运行
```bash
python app.py
```

## 配置说明

### 基础配置
```json
{
  "wechat": {
    "single_chat_prefix": ["bot", "@bot"],  // 私聊触发前缀
    "group_chat_prefix": ["@bot"],          // 群聊触发前缀
    "group_name_white_list": [],            // 群组白名单，空列表表示需手动添加
    "nick_name_black_list": []              // 用户黑名单
  },
  "openai": {
    "api_key": "YOUR_OPENAI_API_KEY",       // OpenAI API密钥
    "model": "gpt-4o-mini",                 // 使用的模型
    "temperature": 0.7                      // 生成温度
  },
  "obsidian": {
    "vault_path": "/path/to/your/vault",    // Obsidian仓库路径
    "daily_notes_folder": "Daily Notes",    // 日记文件夹
    "knowledge_base_folder": "Knowledge Base" // 知识库文件夹
    // 注意：不需要配置categories，系统会自动扫描文件夹
  },
  "system": {
    "message_db_path": "data/messages.db",  // 消息数据库路径
    "message_retention_days": 30            // 消息保留天数
  }
}
```

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

## 新功能说明

### 1. 消息持久化存储
- 所有消息都会自动保存到SQLite数据库
- 确保能获取完整的时间窗口内的上下文
- 支持按时间、群组查询历史消息

### 2. 动态分类管理
- 系统自动扫描Obsidian知识库文件夹作为分类
- 无需在配置文件中定义分类
- 机器人会自动适应用户对文件夹的修改

### 3. 智能去重
- 检测相同URL或标题的内容
- 避免重复保存相同信息
- 支持内容更新而非简单追加

### 4. 改进的笔记格式
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
docker run -d --name dailybot -v /path/to/config:/app/config dailybot
```

## 常见问题

### Q: 如何处理大量历史消息？
A: 可以使用批量导入功能，或者分批次逐步添加群组到白名单。系统会自动从消息存储中获取上下文。

### Q: 为什么某些链接无法提取内容？
A: 可能是网站有反爬虫措施，可以在 `content_extractor.py` 中添加特定的处理逻辑。

### Q: 如何备份数据？
A: 
- Obsidian笔记通过iCloud自动同步
- 向量数据库在 `data/chroma_db` 目录
- 群组白名单在 `config/group_whitelist.json`
- 消息数据库在 `data/messages.db`

### Q: 如何自定义分类？
A: 直接在Obsidian知识库文件夹中创建新的子文件夹即可，机器人会自动识别并使用。

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
- [ ] 更多内容源支持
- [ ] 多模态内容处理

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

MIT License 