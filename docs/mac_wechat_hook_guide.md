# Mac微信通道使用指南

## 概述

Mac微信通道是专为macOS设计的微信接入方案，提供两种运行模式以满足不同需求：

### 静默读取模式（默认）
- **主要用途**：自动提取聊天记录中的链接和内容，整理到笔记系统
- **工作原理**：定期读取微信数据库，获取新消息并处理
- **优点**：安全稳定，不修改微信程序，无封号风险
- **适用场景**：DailyBot的核心功能 - 笔记整理和知识管理

### Hook模式（可选）
- **主要用途**：实时消息监听，支持自动回复和即时交互
- **工作原理**：通过动态库注入实现消息拦截
- **优点**：实时性强，支持双向交互
- **缺点**：需要关闭SIP，有一定风险
- **适用场景**：需要自动回复或实时处理的场景

## 系统要求

- macOS 10.14+
- 微信Mac版（建议3.6.0或更低版本，3.8.0版本功能受限）
- Python 3.6+
- Xcode命令行工具（用于编译）

## 安装依赖

```bash
# 安装系统依赖
brew install sqlcipher
brew install python3

# 安装Python依赖
pip install pysqlcipher3
```

## 使用方法

### 1. 静默读取模式 - 自动整理笔记（推荐）

这是DailyBot的主要使用方式，用于自动提取聊天记录中的链接和内容，整理到笔记系统。

```python
from channel.channel_factory import create_channel
from bot.message_handler import MessageHandler

# 创建Mac微信通道（默认为静默模式）
channel = create_channel({
    "channel_type": "mac_wechat",
    "mac_wechat": {
        "mode": "silent",
        "poll_interval": 60,  # 每60秒检查一次新消息
        "group_name_white_list": ["AI研究群", "机器人技术交流"]
    }
})

# 创建消息处理器（负责提取链接、整理笔记）
handler = MessageHandler(channel)

# 启动服务
channel.startup()

# 程序会自动：
# 1. 每60秒读取一次微信数据库
# 2. 获取新消息
# 3. 提取其中的链接（公众号文章、论文等）
# 4. 使用LLM总结内容
# 5. 保存到Obsidian或Google Docs
```

### 2. Hook模式 - 实时交互（可选）

```python
from services.mac_wechat_service import MacWeChatService
import logging

logging.basicConfig(level=logging.INFO)

# 创建服务实例
service = MacWeChatService()

# 初始化并启用Hook
if service.initialize() and service.enable_hook():
    
    # 添加自动回复规则
    service.add_auto_reply_rule("你好", "你好！有什么可以帮助你的吗？")
    service.add_auto_reply_rule("在吗", "在的，请说")
    service.add_auto_reply_rule("test", "这是一个测试回复", exact_match=True)
    
    # 添加自定义消息处理器
    def my_message_handler(message):
        print(f"新消息: {message['from']} - {message['content']}")
        
        # 可以在这里添加更复杂的逻辑
        if "重要" in message['content']:
            # 发送通知或执行其他操作
            pass
    
    service.add_message_handler(my_message_handler)
    
    # 保持运行
    try:
        print("Hook已启用，按Ctrl+C退出...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 清理并退出
        service.disable_hook()
```

### 3. 搜索历史消息

```python
# 搜索包含特定关键词的消息
messages = service.search_messages("项目进度", limit=20)

for msg in messages:
    print(f"{msg['timestamp']}: {msg['content']}")
```

### 4. 获取联系人列表

```python
# 获取所有联系人
contacts = service.get_contacts()

# 打印好友列表
friends = [c for c in contacts if c['type'] == 'friend']
for friend in friends:
    print(f"好友: {friend['nickname']} ({friend['username']})")

# 打印群聊列表
groups = [c for c in contacts if c['type'] == 'group']
for group in groups:
    print(f"群聊: {group['nickname']}")
```

## 安全注意事项

### ⚠️ 重要警告

1. **风险提示**：
   - 使用Hook功能可能违反微信服务条款
   - 可能导致账号被封禁
   - 仅供学习研究使用

2. **隐私保护**：
   - 仅在自己的设备上使用
   - 不要获取他人的聊天记录
   - 妥善保管导出的数据

3. **版本兼容**：
   - 微信3.8.0及以上版本可能无法正常工作
   - 建议使用3.6.0或更低版本

## 故障排除

### 1. 无法获取数据库密钥

```bash
# 确保微信正在运行
ps aux | grep WeChat

# 检查SIP状态（需要关闭）
csrutil status

# 如果SIP已启用，需要在恢复模式下关闭
# 重启时按住Command+R，进入恢复模式
# 打开终端执行: csrutil disable
```

### 2. Hook安装失败

```bash
# 检查编译环境
xcode-select --install

# 手动安装insert_dylib
git clone https://github.com/Tyilo/insert_dylib.git
cd insert_dylib
make
sudo cp insert_dylib /usr/local/bin/
```

### 3. 数据库解密失败

- 确保安装了正确版本的sqlcipher
- 确保微信已登录
- 尝试重新获取密钥

## 技术原理

### 数据库解密流程

```
1. 使用LLDB附加到微信进程
2. 在sqlite3_key函数设置断点
3. 登录时触发断点，读取内存中的密钥
4. 使用密钥和sqlcipher解密数据库
```

### Hook实现原理

```
1. 编译Objective-C动态库
2. 使用insert_dylib注入到微信二进制文件
3. 利用Method Swizzling替换关键方法
4. 拦截消息收发，实现自动回复等功能
```

## 常见问题

**Q: 为什么推荐使用低版本微信？**
A: 高版本微信增加了更多安全措施，Hook难度大幅增加。

**Q: 导出的数据在哪里？**
A: 默认在`./wechat_export`目录，包含JSON格式的聊天记录和联系人信息。

**Q: 可以发送图片/文件吗？**
A: 目前主要支持文本消息，图片和文件支持正在开发中。

**Q: 如何卸载Hook？**
A: 调用`service.disable_hook()`或直接恢复备份的微信文件。

## 更新日志

- v1.0.0 (2024-01)
  - 初始版本
  - 支持数据库解密和聊天记录导出
  - 基础的自动回复功能

## 贡献指南

欢迎提交Issue和Pull Request。在提交代码前，请确保：
1. 代码风格符合PEP 8
2. 添加必要的注释和文档
3. 测试通过

## 许可证

本项目仅供学习研究使用，请勿用于商业或非法用途。 