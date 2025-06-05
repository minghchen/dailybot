/**
 * JS Wechaty WebSocket Server Example
 * 用于与Python端通信的WebSocket服务器示例
 * 
 * 使用方法：
 * 1. npm install wechaty wechaty-puppet-wechat ws
 * 2. 如果使用pad协议: npm install wechaty-puppet-padlocal
 * 3. node js_wechaty_server.example.js
 */

const { Wechaty } = require('wechaty')
const WebSocket = require('ws')

// WebSocket服务器配置
const WS_PORT = process.env.WS_PORT || 8788
const AUTH_TOKEN = process.env.AUTH_TOKEN || '' // 可选的认证token

// Puppet配置
const PUPPET_TYPE = process.env.WECHATY_PUPPET || 'wechaty-puppet-wechat4u' // 默认使用免费协议
const PUPPET_TOKEN = process.env.WECHATY_PUPPET_SERVICE_TOKEN || '' // pad协议的token

// 创建WebSocket服务器
const wss = new WebSocket.Server({ port: WS_PORT })
console.log(`WebSocket server started on port ${WS_PORT}`)

// 存储客户端连接
const clients = new Set()

// 配置Wechaty
const wechatyConfig = {
  name: 'dailybot',
  puppet: PUPPET_TYPE,
}

// 如果使用pad协议，需要配置token
if (PUPPET_TYPE === 'wechaty-puppet-padlocal' && PUPPET_TOKEN) {
  wechatyConfig.puppetOptions = {
    token: PUPPET_TOKEN,
  }
  console.log('Using PadLocal puppet with token')
} else if (PUPPET_TYPE === 'wechaty-puppet-service' && PUPPET_TOKEN) {
  // 使用puppet service（推荐，更稳定）
  wechatyConfig.puppetOptions = {
    token: PUPPET_TOKEN,
    endpoint: process.env.WECHATY_PUPPET_SERVICE_ENDPOINT, // 可选
  }
  console.log('Using Puppet Service')
} else {
  console.warn('⚠️  警告：使用免费的web协议可能存在封号风险！')
  console.warn('⚠️  建议使用以下方式之一：')
  console.warn('   1. 购买PadLocal协议：http://pad-local.com')
  console.warn('   2. 使用Puppet Service')
  console.warn('   3. 自建XP协议（Windows环境）')
}

// 创建Wechaty实例
const bot = new Wechaty(wechatyConfig)

// 添加登录重试和错误处理
let loginRetryCount = 0
const MAX_LOGIN_RETRY = 3

// 广播消息给所有客户端
function broadcast(message) {
  const data = JSON.stringify(message)
  clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(data)
    }
  })
}

// WebSocket连接处理
wss.on('connection', (ws) => {
  console.log('New client connected')
  clients.add(ws)
  
  // 处理客户端消息
  ws.on('message', (data) => {
    try {
      const message = JSON.parse(data)
      
      // 认证（如果配置了token）
      if (message.type === 'auth') {
        if (AUTH_TOKEN && message.token !== AUTH_TOKEN) {
          ws.send(JSON.stringify({ type: 'error', error: 'Invalid token' }))
          ws.close()
          return
        }
        ws.send(JSON.stringify({ type: 'auth_success' }))
        return
      }
      
      // 处理发送消息请求
      if (message.type === 'send') {
        handleSendMessage(message.payload)
      }
      
    } catch (e) {
      console.error('Error handling message:', e)
      ws.send(JSON.stringify({ type: 'error', error: e.message }))
    }
  })
  
  // 客户端断开连接
  ws.on('close', () => {
    console.log('Client disconnected')
    clients.delete(ws)
  })
  
  // 发送当前登录状态
  if (bot.isLoggedIn) {
    const user = bot.currentUser
    ws.send(JSON.stringify({
      type: 'login',
      user: {
        id: user.id,
        name: user.name(),
        avatar: user.avatar()
      }
    }))
  }
})

// 处理发送消息（添加限流）
const messageLimiter = new Map() // 消息限流器
const MESSAGE_LIMIT_WINDOW = 60000 // 1分钟
const MESSAGE_LIMIT_COUNT = 30 // 每分钟最多30条消息

async function handleSendMessage(payload) {
  try {
    const { to, type, content, url, path } = payload
    
    // 消息限流检查
    const now = Date.now()
    const userLimiter = messageLimiter.get(to) || { count: 0, resetTime: now + MESSAGE_LIMIT_WINDOW }
    
    if (now > userLimiter.resetTime) {
      userLimiter.count = 0
      userLimiter.resetTime = now + MESSAGE_LIMIT_WINDOW
    }
    
    if (userLimiter.count >= MESSAGE_LIMIT_COUNT) {
      broadcast({ 
        type: 'warning', 
        message: `消息发送过快，请稍后再试（限制：${MESSAGE_LIMIT_COUNT}条/分钟）` 
      })
      return
    }
    
    userLimiter.count++
    messageLimiter.set(to, userLimiter)
    
    // 查找联系人或群组
    const contact = await bot.Contact.find({ id: to }) || await bot.Room.find({ id: to })
    
    if (!contact) {
      broadcast({ type: 'error', error: `Contact ${to} not found` })
      return
    }
    
    // 根据消息类型发送（添加随机延迟，模拟人工操作）
    const delay = Math.random() * 2000 + 1000 // 1-3秒随机延迟
    await new Promise(resolve => setTimeout(resolve, delay))
    
    switch (type) {
      case 'text':
        await contact.say(content)
        break
      case 'image':
        const FileBox = require('wechaty').FileBox
        if (url) {
          await contact.say(FileBox.fromUrl(url))
        } else if (path) {
          await contact.say(FileBox.fromFile(path))
        }
        break
      case 'file':
        const FileBox2 = require('wechaty').FileBox
        await contact.say(FileBox2.fromFile(path))
        break
      default:
        broadcast({ type: 'error', error: `Unsupported message type: ${type}` })
    }
    
  } catch (e) {
    console.error('Error sending message:', e)
    broadcast({ type: 'error', error: e.message })
  }
}

// Wechaty事件处理
bot
  .on('scan', (qrcode, status) => {
    console.log(`Scan QR Code to login: ${status}\nhttps://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`)
    broadcast({
      type: 'scan',
      qrcode,
      status
    })
  })
  .on('login', user => {
    console.log(`User ${user} logged in`)
    loginRetryCount = 0 // 重置重试计数
    broadcast({
      type: 'login',
      user: {
        id: user.id,
        name: user.name(),
        avatar: user.avatar()
      }
    })
  })
  .on('logout', user => {
    console.log(`User ${user} logged out`)
    broadcast({
      type: 'logout',
      user: {
        id: user.id,
        name: user.name()
      }
    })
    
    // 自动重试登录
    if (loginRetryCount < MAX_LOGIN_RETRY) {
      loginRetryCount++
      console.log(`尝试重新登录 (${loginRetryCount}/${MAX_LOGIN_RETRY})...`)
      setTimeout(() => {
        bot.start().catch(e => {
          console.error('重新登录失败:', e)
        })
      }, 5000) // 5秒后重试
    }
  })
  .on('message', async msg => {
    // 忽略自己发送的消息
    if (msg.self()) return
    
    const from = msg.talker()
    const room = msg.room()
    const text = msg.text()
    const type = msg.type()
    
    // 构建消息数据
    const messageData = {
      type: 'message',
      payload: {
        id: msg.id,
        type: type,
        text: text,
        from: {
          id: from.id,
          name: from.name(),
          alias: await from.alias()
        },
        timestamp: Date.now()
      }
    }
    
    // 如果是群消息，添加群信息
    if (room) {
      messageData.payload.room = {
        id: room.id,
        topic: await room.topic()
      }
      
      // 获取@列表
      const mentionList = await msg.mentionList()
      messageData.payload.mentionList = mentionList.map(c => c.id)
    }
    
    // 广播消息给所有客户端
    broadcast(messageData)
  })
  .on('error', e => {
    console.error('Bot error:', e)
    broadcast({
      type: 'error',
      error: e.message
    })
  })
  .on('friendship', async friendship => {
    // 自动通过好友请求（可配置）
    const autoAcceptFriend = process.env.AUTO_ACCEPT_FRIEND === 'true'
    if (autoAcceptFriend) {
      try {
        await friendship.accept()
        console.log(`接受了好友请求: ${friendship.contact().name()}`)
      } catch (e) {
        console.error('接受好友请求失败:', e)
      }
    }
  })

// 启动机器人
bot.start()
  .then(() => console.log('Bot started'))
  .catch(e => {
    console.error('Bot start error:', e)
    broadcast({
      type: 'error',
      error: `启动失败: ${e.message}`
    })
  })

// 优雅退出
process.on('SIGINT', async () => {
  console.log('Shutting down...')
  
  // 关闭WebSocket服务器
  wss.close(() => {
    console.log('WebSocket server closed')
  })
  
  // 停止机器人
  await bot.stop()
  console.log('Bot stopped')
  
  process.exit(0)
})

// 定期清理消息限流器
setInterval(() => {
  const now = Date.now()
  for (const [key, limiter] of messageLimiter.entries()) {
    if (now > limiter.resetTime + MESSAGE_LIMIT_WINDOW) {
      messageLimiter.delete(key)
    }
  }
}, MESSAGE_LIMIT_WINDOW) 