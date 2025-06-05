# 微信机器人防封号指南

## 封号风险等级

| 方案 | 风险等级 | 原因 | 建议 |
|------|---------|------|------|
| JS Wechaty (免费puppet) | ⚠️ 高 | 使用网页版协议，易被检测 | 仅用于测试 |
| PadLocal | ✅ 低 | 基于iPad协议，更接近真实设备 | 推荐使用 |
| wcf (Hook) | ⚠️ 中 | Hook技术可能被检测 | Windows用户可选 |

## 防封号最佳实践

### 1. 协议选择

#### 推荐方案
- **PadLocal** (JS Wechaty): 基于iPad协议，最稳定
  - 购买地址：http://pad-local.com
  - 价格：约200元/月
  - 优点：稳定、不易封号、支持所有功能
  - 使用方式：通过JS Wechaty服务

- **wcf** (Windows专用): 基于Hook技术
  - 优点：免费、功能完整
  - 缺点：仅Windows、有一定风险
  - 适合：Windows用户短期使用

#### 配置示例
```bash
# JS Wechaty使用PadLocal
export WECHATY_PUPPET=wechaty-puppet-padlocal
export WECHATY_PUPPET_SERVICE_TOKEN=your_padlocal_token

# 启动JS服务
node scripts/js_wechaty_server.example.js
```

### 2. 行为模拟

#### 消息频率控制
```python
# 在配置文件中设置
"js_wechaty": {
  "message_limit_per_minute": 20,  # 每分钟最多20条
  "min_reply_delay": 2,             # 最小延迟2秒
  "max_reply_delay": 5              # 最大延迟5秒
}
```

#### 工作时间限制
```python
# 设置工作时间
"working_hours": {
  "enabled": true,
  "start": 9,    # 早上9点
  "end": 22      # 晚上10点
}
```

### 3. 账号策略

#### 账号准备
1. **使用小号测试**
   - 不要用主号测试
   - 准备2-3个备用账号
   - 账号最好有一定年龄（注册超过6个月）

2. **账号养护**
   - 保持正常使用痕迹
   - 有真实好友互动
   - 避免新号直接上机器人

#### 登录策略
1. **避免频繁登录**
   - 不要频繁切换设备
   - 保持长时间在线
   - 使用自动重连

2. **IP地址**
   - 使用固定IP
   - 避免使用公共VPS
   - 最好使用家庭宽带

### 4. 功能限制

#### 敏感功能
- ❌ 避免群发消息
- ❌ 避免自动加好友
- ❌ 避免发送营销内容
- ✅ 被动响应为主
- ✅ 控制响应频率

#### 内容审核
建议在LLM服务中加入内容审核，避免生成敏感内容。

### 5. 监控与应急

#### 异常监控
程序已实现自动重连和异常日志记录：
- JS Wechaty：WebSocket断线自动重连
- wcf：自动重试初始化

#### 应急措施
1. **备份策略**
   - 定期备份聊天记录（SQLite数据库）
   - 保存群组白名单配置
   - 准备备用账号

2. **降级方案**
   - 出现异常立即降低活跃度
   - 切换到纯被动响应模式
   - 必要时暂停服务

### 6. 不同方案的具体建议

#### JS Wechaty方案
1. **强烈建议购买PadLocal**
   - 免费puppet风险极高
   - PadLocal基于iPad协议，安全性好

2. **配置建议**
   ```json
   {
     "message_limit_per_minute": 20,
     "min_reply_delay": 3,
     "max_reply_delay": 6,
     "working_hours": {
       "enabled": true,
       "start": 9,
       "end": 22
     }
   }
   ```

3. **运行建议**
   - 使用稳定的网络环境
   - 保持JS服务持续运行
   - 定期检查服务状态

#### wcf方案
1. **使用限制**
   - 需要特定版本微信客户端
   - 仅支持Windows系统
   - 可能触发微信安全检测

2. **安全建议**
   - 控制消息发送频率
   - 避免长时间高频使用
   - 定期观察账号状态

3. **配置建议**
   ```json
   {
     "group_at_sender": true,
     "speech_recognition": false,
     "voice_reply_voice": false
   }
   ```

## 风险等级对比

| 特性 | JS Wechaty (免费) | JS Wechaty (PadLocal) | wcf |
|------|------------------|---------------------|-----|
| 封号风险 | 高 | 低 | 中 |
| 成本 | 免费 | 200元/月 | 免费 |
| 稳定性 | 差 | 优秀 | 良好 |
| 功能完整性 | 一般 | 完整 | 完整 |
| 跨平台 | 是 | 是 | 仅Windows |
| 推荐场景 | 短期测试 | 长期生产使用 | Windows用户 |

## 总结

1. **生产环境务必使用PadLocal**：虽然需要付费，但稳定性和安全性值得
2. **测试环境谨慎使用**：即使是测试，也建议使用小号
3. **行为要自然**：控制频率、添加延迟、遵守作息
4. **功能要克制**：只做必要的功能，避免敏感操作
5. **做好应急预案**：数据备份、账号备用、降级方案

记住：**宁可功能少一些，也要保证账号安全！** 