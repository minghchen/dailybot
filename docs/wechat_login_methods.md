# 微信登录方案说明

本项目支持两种微信登录方案，可以根据实际需求选择合适的方案。

## 方案对比

| 方案 | 操作系统 | 稳定性 | 安装难度 | 特点 |
|------|---------|---------|----------|------|
| js_wechaty | 跨平台 | 中 | 中等 | 需要运行JS服务，通过WebSocket通信 |
| wcf | 仅Windows | 高 | 简单 | 基于Hook技术，相对稳定 |

## 方案一：JavaScript Wechaty

### 原理说明

基于 [wangrongding/wechat-bot](https://github.com/wangrongding/wechat-bot) 项目，通过运行JavaScript版的Wechaty服务，Python端通过WebSocket与之通信。

### ⚠️ 封号风险警告

使用免费的web协议（wechaty-puppet-wechat4u）存在较高的封号风险，因为：
- 微信审查日益严格，能够检测到网页版协议的异常行为
- 大量用户反馈收到外挂警告
- 可能导致账号被限制或永久封禁

### 防封号措施

#### 1. 使用Pad协议（推荐）

PadLocal是基于iPad协议的实现，稳定性和安全性都更高：

```bash
# 安装依赖
npm install wechaty-puppet-padlocal

# 设置环境变量
export WECHATY_PUPPET=wechaty-puppet-padlocal
export WECHATY_PUPPET_SERVICE_TOKEN=your_padlocal_token

# 运行服务
node js_wechaty_server.example.js
```

购买渠道：
- 官方渠道：http://pad-local.com
- 价格参考：约200元/月（价格可能有变动）
- 注意：购买需谨慎，建议先小额测试

#### 2. 使用Puppet Service

Puppet Service是官方推荐的方式，可以将puppet运行在其他设备上：

```bash
export WECHATY_PUPPET=wechaty-puppet-service
export WECHATY_PUPPET_SERVICE_TOKEN=your_service_token
export WECHATY_PUPPET_SERVICE_ENDPOINT=your_service_endpoint  # 可选
```

#### 3. 行为模拟

在代码中已实现以下防检测措施：
- **消息限流**：每分钟最多30条消息
- **随机延迟**：发送消息前1-3秒随机延迟
- **登录重试**：掉线后自动重试，最多3次
- **正常作息**：建议设置定时任务，模拟正常作息时间

### 安装步骤

1. **安装Node.js环境**
   ```bash
   # 下载并安装Node.js (推荐v16或以上版本)
   # https://nodejs.org/
   ```

2. **克隆JS Wechaty项目**
   ```bash
   git clone https://github.com/wangrongding/wechat-bot.git
   cd wechat-bot
   npm install
   ```

3. **配置JS服务**
   
   在wechat-bot项目中创建 `.env` 文件：
   ```
   # Wechaty配置
   WECHATY_PUPPET=wechaty-puppet-padlocal  # 推荐使用pad协议
   WECHATY_PUPPET_SERVICE_TOKEN=your-token-here  # pad协议token
   
   # WebSocket服务配置
   WS_PORT=8788
   AUTH_TOKEN=your_auth_token  # 建议设置认证token
   
   # 其他配置
   AUTO_ACCEPT_FRIEND=false  # 是否自动接受好友请求
   ```

4. **启动JS服务**
   ```bash
   npm run start
   ```

5. **配置Python端**
   
   修改 `config/config.example.json`：
   ```json
   {
     "channel_type": "js_wechaty",
     "js_wechaty": {
       "ws_url": "ws://localhost:8788",
       "token": "",
       "reconnect_interval": 5,
       ...
     }
   }
   ```

6. **运行DailyBot**
   ```bash
   python app.py
   ```

### 注意事项

- JS服务需要持续运行
- 可能需要使用代理访问
- 免费版协议可能不稳定，建议购买pad协议

## 方案二：WeChat-Ferry (wcf)

### 原理说明

基于Windows Hook技术，直接操作微信PC客户端，稳定性较高。

### 系统要求

- **操作系统**: Windows 7/8/10/11 (64位)
- **微信版本**: 需要特定版本，详见 [WeChatFerry文档](https://github.com/lich0821/WeChatFerry)

### 安装步骤

1. **安装指定版本微信**
   
   从WeChatFerry项目下载对应版本的微信安装包并安装。

2. **安装Python依赖**
   ```bash
   pip install wcferry
   ```

3. **配置文件**
   
   修改 `config/config.example.json`：
   ```json
   {
     "channel_type": "wcf",
     "wcf": {
       "single_chat_prefix": ["bot", "@bot"],
       "group_name_white_list": ["测试群"],
       "group_at_sender": true,
       ...
     }
   }
   ```

4. **启动步骤**
   
   a. 先启动微信PC客户端并登录
   
   b. 运行DailyBot：
   ```bash
   python app.py
   ```

### 功能支持

- ✅ 文本消息收发
- ✅ 图片消息收发
- ✅ 文件消息收发
- ✅ 语音消息识别
- ✅ @消息处理
- ✅ 群组管理

### 注意事项

- 仅支持Windows系统
- 需要特定版本的微信客户端
- 首次运行可能需要管理员权限
- 可能触发微信安全检测

## 配置说明

### 通用配置项

```json
{
  "channel_type": "js_wechaty|wcf",  // 选择登录方案
  
  // 触发机器人的前缀配置
  "single_chat_prefix": ["bot", "@bot"],     // 私聊触发前缀
  "group_chat_prefix": ["@bot"],             // 群聊触发前缀
  "single_chat_reply_prefix": "[bot] ",      // 私聊回复前缀
  
  // 群组白名单
  "group_name_white_list": ["群名1", "群名2"],
  
  // 语音功能
  "speech_recognition": false,               // 语音识别
  "voice_reply_voice": false                 // 语音回复
}
```

### JS Wechaty特有配置

```json
{
  "js_wechaty": {
    "ws_url": "ws://localhost:8788",       // WebSocket服务地址
    "token": "",                          // 认证token（可选）
    "reconnect_interval": 5,               // 重连间隔（秒）
    "message_limit_per_minute": 20,        // 每分钟消息限制
    "min_reply_delay": 2,                  // 最小回复延迟
    "max_reply_delay": 5,                  // 最大回复延迟
    "working_hours": {                     // 工作时间限制
      "enabled": false,
      "start": 9,
      "end": 22
    }
  }
}
```

### wcf特有配置

```json
{
  "wcf": {
    "group_at_sender": true               // 群聊回复时是否@发送者
  }
}
```

## 常见问题

### Q: 哪种方案更推荐？

A: 
- Windows用户推荐使用wcf方案，稳定性高
- Mac/Linux用户只能使用js_wechaty方案
- 如果需要长期稳定运行，建议购买pad协议

### Q: 遇到登录失败怎么办？

A:
1. 检查微信版本是否正确（wcf方案）
2. 检查网络代理设置
3. 尝试重新登录
4. 查看日志文件获取详细错误信息

### Q: 如何避免封号？

A:
1. 不要频繁登录登出
2. 控制消息发送频率
3. 避免发送敏感内容
4. 使用小号测试

### Q: 语音功能无法使用？

A:
- 确保安装了ffmpeg
- 检查配置文件中的语音设置
- 查看日志中的错误信息

## 进阶使用

### 使用Pad协议（js_wechaty）

1. 购买pad协议token（参考wechaty官方）
2. 修改JS服务配置：
   ```
   WECHATY_PUPPET=wechaty-puppet-padlocal
   WECHATY_PUPPET_SERVICE_TOKEN=your-pad-token
   ```
3. 重启服务

### 自定义消息处理

可以通过继承Channel类来实现自定义功能：

```python
from channel.js_wechaty_channel import JSWechatyChannel

class MyWechatyChannel(JSWechatyChannel):
    def process_message(self, msg_data):
        # 自定义消息处理逻辑
        super().process_message(msg_data)
```

## 相关资源

- [wangrongding/wechat-bot](https://github.com/wangrongding/wechat-bot) - JS版Wechaty实现
- [lich0821/WeChatFerry](https://github.com/lich0821/WeChatFerry) - WeChat-Ferry项目
- [Wechaty官网](https://wechaty.js.org/) - Wechaty官方文档
- [防封号指南](anti_ban_guide.md) - 详细的防封号最佳实践 