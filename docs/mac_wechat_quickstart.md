# Mac微信通道快速开始

本指南帮助你快速上手Mac微信通道，实现自动提取聊天记录中的链接和内容，整理到笔记系统。

## 主要用途

Mac微信通道的**核心功能**是：
- 定期读取微信聊天记录
- 自动识别和提取链接（公众号文章、论文、视频等）
- 使用AI总结内容
- 整理保存到Obsidian或Google Docs

这一切都在**后台静默运行**，不会影响你正常使用微信。

## 前置条件

1. macOS 10.14+
2. 微信Mac版（任意版本，静默模式不挑版本）
3. Python 3.8+
4. OpenAI API密钥

## 快速开始（5分钟）

### 1. 安装依赖

```bash
# 安装sqlcipher（用于读取微信数据库）
brew install sqlcipher

# 克隆项目
git clone <your-repo-url>
cd dailybot

# 安装Python依赖
pip install -r requirements.txt
```

### 2. 配置

创建 `.env` 文件：
```bash
OPENAI_API_KEY=你的OpenAI密钥
```

复制并修改配置文件：
```bash
cp config/config.example.json config/config.json
```

编辑 `config/config.json`，主要修改：
- `obsidian.vault_path`: 你的Obsidian仓库路径
- `mac_wechat.group_name_white_list`: 要监控的群组列表

### 3. 运行

```bash
python app.py
```

就这么简单！程序会：
1. 每60秒检查一次新消息
2. 自动提取链接和内容
3. 整理到你的笔记系统

## 工作原理

```
微信聊天 -> 读取数据库 -> 提取链接 -> AI总结 -> 保存笔记
```

整个过程完全自动化，你只需要：
1. 保持微信登录状态
2. 让程序在后台运行

## 测试运行

### 测试静默模式（推荐先测试）

```bash
# 测试10秒轮询，看是否能正常读取消息
python scripts/test_mac_wechat.py --mode silent
```

### 测试完整功能

```bash
# 测试完整的笔记整理功能
python scripts/test_mac_wechat.py --mode bot
```

## 实际效果

当群里有人分享链接时：

```
群友A: 这篇文章不错 https://mp.weixin.qq.com/s/xxx
群友B: 确实，讲得很清楚
```

程序会自动在你的笔记中添加：

```markdown
## 2024-01 文章标题
[原文链接](https://mp.weixin.qq.com/s/xxx)
这篇文章主要讲述了...（AI生成的总结）
```

## 常见配置

### 调整检查频率

```json
"mac_wechat": {
  "poll_interval": 30  // 改为30秒检查一次
}
```

### 只监控特定群组

```json
"mac_wechat": {
  "group_name_white_list": ["AI研究群", "论文分享群"]
}
```

### 配置笔记分类

```json
"obsidian": {
  "note_files": [
    {
      "name": "AI研究笔记",
      "filename": "AI研究笔记.md",
      "description": "人工智能相关内容"
    }
  ]
}
```

## 进阶功能

### Hook模式（可选）

如果你需要自动回复功能：

1. 关闭SIP（需要重启进入恢复模式）
2. 使用微信3.6.0或更低版本
3. 设置环境变量：`MAC_WECHAT_USE_HOOK=true`

但对于大多数用户，**静默模式已经足够**。

## 故障排除

### 无法读取数据库？

1. 确保微信已登录
2. 尝试重新登录微信
3. 检查是否安装了sqlcipher

### 程序报错？

查看日志文件 `logs/dailybot.log`，常见问题：
- OpenAI API密钥未设置
- Obsidian路径错误
- 权限问题

### 没有提取到内容？

检查：
- 群组是否在白名单中
- 消息是否包含支持的链接类型
- 时间窗口设置是否合理

## 获取帮助

- 查看[详细文档](mac_wechat_hook_guide.md)
- 提交Issue
- 加入用户群讨论

记住：这个工具的目标是让你的知识管理更轻松，而不是更复杂！ 