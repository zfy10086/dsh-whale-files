/**
 * dsh-whale-files — Host half.
 *
 * 把「鲸鲸文件箱」挂到 DSH 自己的 web 服务器上（同源 3080），并负责引擎保活：
 *   /whale-files/        文件箱页面（代理到本地 Python 引擎）
 *   /whale-files/api/*   引擎的 JSON / 上传 / 下载接口
 *
 * 为什么不直接把页面写进宿主：multipart 流式解析、zip 自动解压、打包下载
 * 这些 Python 标准库写得又短又稳，宿主只做两件事——反代 + 引擎保活，所以
 * 插件本身很薄，引擎随包分发（engine/），不依赖任何外部安装。
 *
 * 引擎与页面就在本包的 engine/ 目录里，生命周期跟着 DSH 宿主走：宿主活着
 * 文件箱就在，App 重启后自动回来。
 */

import { spawn } from 'node:child_process'
import http from 'node:http'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-whale-files'
export const inject = ['webServer']

const HERE = dirname(fileURLToPath(import.meta.url))
const BASE = '/whale-files'
const ENGINE_DIR = process.env.WHALE_FILES_DIR || join(HERE, '..', 'engine')
const ENGINE_SCRIPT = 'files.py'
const ENGINE_HOST = '127.0.0.1'
const ENGINE_PORT = Number(process.env.WHALE_FILES_PORT || 8791)

/**
 * 被管理的根目录。优先级：显式 env > DSHA 的 Documents 约定 > 家目录。
 * 手机端 DSHA 的工作区固定是 ~/Documents/deepseek-harness/default-workspace。
 */
function resolveWorkspace() {
  if (process.env.WHALE_FILES_ROOT) return process.env.WHALE_FILES_ROOT
  const docs = process.env.DSHA_WORKSPACE_DOCUMENTS || join(homedir(), 'Documents')
  const guess = join(docs, 'deepseek-harness', 'default-workspace')
  return existsSync(guess) ? guess : docs
}
const WORKSPACE = resolveWorkspace()
const VERSION = '0.1.0'

let child = null
let healthTimer = null
let starting = null

function log(message) {
  console.log(`[whale-files] ${message}`)
}

/** 询问引擎是否活着。 */
function ping(timeoutMs = 800) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: ENGINE_HOST, port: ENGINE_PORT, path: '/api/ping', timeout: timeoutMs },
      (res) => {
        res.resume()
        resolve(res.statusCode === 200)
      },
    )
    req.on('timeout', () => { req.destroy(); resolve(false) })
    req.on('error', () => resolve(false))
  })
}

/** 引擎没起来就拉起来（带并发去重）。 */
function ensureEngine() {
  if (starting !== null) return starting
  starting = (async () => {
    if (await ping()) return true
    const script = join(ENGINE_DIR, ENGINE_SCRIPT)
    if (!existsSync(script)) {
      log(`找不到引擎脚本 ${script}`)
      return false
    }
    log('引擎未响应，拉起中')
    try {
      child = spawn('python3', [ENGINE_SCRIPT], {
        cwd: ENGINE_DIR,
        env: { ...process.env, ROOT: WORKSPACE, PORT: String(ENGINE_PORT) },
        detached: true,
        stdio: 'ignore',
      })
      child.unref()
    } catch (error) {
      log(`拉起失败：${error instanceof Error ? error.message : String(error)}`)
      return false
    }
    for (let i = 0; i < 20; i += 1) {
      await new Promise((r) => setTimeout(r, 250))
      if (await ping()) {
        log('引擎已就绪')
        return true
      }
    }
    log('引擎启动超时')
    return false
  })().finally(() => { starting = null })
  return starting
}

/** 把请求反代给引擎，路径里的 /whale-files 前缀被剥掉。 */
function proxy(req, res) {
  const url = req.url ?? '/'
  const cut = url.startsWith(BASE) ? url.slice(BASE.length) : url
  const upstreamPath = cut.length === 0 ? '/' : cut.startsWith('/') ? cut : `/${cut}`
  const headers = { ...req.headers, host: `${ENGINE_HOST}:${ENGINE_PORT}` }
  const upstream = http.request(
    { host: ENGINE_HOST, port: ENGINE_PORT, path: upstreamPath, method: req.method, headers },
    (up) => {
      res.writeHead(up.statusCode ?? 502, up.headers)
      up.pipe(res)
    },
  )
  upstream.on('error', async (error) => {
    log(`反代失败 ${upstreamPath}：${error.message}`)
    await ensureEngine()
    if (!res.headersSent) {
      res.writeHead(502, { 'content-type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: false, error: '文件箱引擎暂时不可用，已尝试重新拉起' }))
    } else {
      res.destroy()
    }
  })
  req.pipe(upstream)
}

export function apply(ctx) {
  const disposers = []
  const register = (route) => {
    try {
      disposers.push(ctx.webServer.register(route))
      return true
    } catch (error) {
      log(`路由 ${route.path} 注册失败：${error instanceof Error ? error.message : String(error)}`)
      return false
    }
  }

  register({
    kind: 'exact',
    path: BASE,
    handler: async (req, res) => {
      res.writeHead(302, { location: `${BASE}/` })
      res.end()
    },
  })

  register({
    // 注意：webserver 的 prefix 匹配规则是 pathname === prefix || startsWith(prefix + '/')，
    // 所以这里不能带结尾斜杠，否则 /whale-files/api/* 一个都匹配不上。
    kind: 'prefix',
    path: BASE,
    handler: async (req, res) => {
      if (!(await ping())) await ensureEngine()
      proxy(req, res)
    },
  })

  void ensureEngine()
  healthTimer = setInterval(() => { void ensureEngine() }, 5000)
  healthTimer.unref?.()

  log(`已挂载 ${VERSION}，入口 http://127.0.0.1:3080${BASE}/  根目录 ${WORKSPACE}`)

  ctx.on?.('dispose', () => {
    if (healthTimer !== null) clearInterval(healthTimer)
    for (const dispose of disposers) {
      try { dispose() } catch { /* ignore */ }
    }
  })
}
