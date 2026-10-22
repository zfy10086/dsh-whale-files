/**
 * dsh-whale-files — Browser half.
 *
 * 在「设置」里加一节「鲸鲸文件箱」：内嵌 iframe 直接用宿主同源的
 * /whale-files/ 页面（上传、下载、移动、预览全在里面），旁边给一个
 * 「在新标签打开」的出口，想用整屏就点它。
 *
 * 首开防黑屏：面板挂载后再给 iframe 设地址（隐藏状态下就加载容易黑屏），
 * 期间显示「载入中」占位；4 秒仍未 onLoad 就自动重载一次（只一次）。
 */

window.__ModuleLoader__.load({
  id: 'dsh-whale-files',
  factory: (require) => {
    const module = { exports: {} }
    const exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    const React = require('react')
    const BASE = '/whale-files/'
    const SLOT = 'settings.section'

    const CSS = `
      .dswf-wrap{display:flex;flex-direction:column;gap:10px;max-width:100%}
      .dswf-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
        flex-wrap:wrap;font-size:13px;color:var(--dsw-alias-label-secondary,#5f6670)}
      .dswf-title{margin:0;font-size:16px;font-weight:600;color:var(--dsw-alias-label-primary,#1f2328)}
      .dswf-actions{display:flex;gap:8px}
      .dswf-actions a,.dswf-actions button{font:inherit;font-size:12.5px;padding:5px 11px;border-radius:8px;
        border:1px solid var(--dsw-alias-border-secondary,rgba(0,0,0,.14));background:transparent;
        color:var(--dsw-alias-label-secondary,#5f6670);cursor:pointer;text-decoration:none}
      .dswf-actions a:hover,.dswf-actions button:hover{border-color:rgba(0,0,0,.28);color:#1f2328}
      .dswf-stage{position:relative;width:100%;height:min(72vh,760px);
        border:1px solid var(--dsw-alias-border-secondary,rgba(0,0,0,.12));border-radius:12px;
        background:#0e1116;overflow:hidden}
      .dswf-frame{display:block;width:100%;height:100%;border:0;background:#0e1116}
      .dswf-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
        gap:8px;font-size:13px;color:#8b94a3;background:#0e1116}
      .dswf-dot{width:8px;height:8px;border-radius:50%;background:#3a7bff;
        animation:dswf-pulse 1s ease-in-out infinite}
      @keyframes dswf-pulse{0%,100%{opacity:.35}50%{opacity:1}}
      .dswf-tip{margin:0;font-size:12px;color:var(--dswf-tip,#8a8f99);line-height:1.6}
    `

    let cssInstalled = false
    function ensureCss() {
      if (cssInstalled) return
      cssInstalled = true
      const style = document.createElement('style')
      style.dataset.plugin = 'dsh-whale-files'
      style.textContent = CSS
      document.head.appendChild(style)
    }

    function WhaleFilesPanel() {
      ensureCss()
      const [src, setSrc] = React.useState('')
      const [loaded, setLoaded] = React.useState(false)
      const tries = React.useRef(0)

      // 面板真正挂载后再设地址：隐藏状态下直接加载容易首开黑屏。
      React.useEffect(() => {
        const timer = setTimeout(() => setSrc(`${BASE}?t=${Date.now()}`), 60)
        return () => clearTimeout(timer)
      }, [])

      // 兜底：4 秒还没加载完就自动重载一次（只重试一次，避免死循环）。
      React.useEffect(() => {
        if (src === '' || loaded) return undefined
        const timer = setTimeout(() => {
          if (tries.current >= 1) return
          tries.current += 1
          setSrc(`${BASE}?t=${Date.now()}`)
        }, 4000)
        return () => clearTimeout(timer)
      }, [src, loaded])

      const reload = () => {
        tries.current = 0
        setLoaded(false)
        setSrc(`${BASE}?t=${Date.now()}`)
      }

      return React.createElement(
        'div',
        { className: 'dswf-wrap' },
        React.createElement(
          'div',
          { className: 'dswf-head' },
          React.createElement('h2', { className: 'dswf-title' }, '鲸鲸文件箱'),
          React.createElement(
            'div',
            { className: 'dswf-actions' },
            React.createElement('button', { type: 'button', onClick: reload }, '刷新'),
            React.createElement('a', { href: BASE, target: '_blank', rel: 'noreferrer' }, '在新标签打开'),
          ),
        ),
        React.createElement(
          'div',
          { className: 'dswf-stage' },
          src === ''
            ? null
            : React.createElement('iframe', {
                className: 'dswf-frame',
                src,
                title: '鲸鲸文件箱',
                allow: 'clipboard-write',
                onLoad: () => setLoaded(true),
              }),
          loaded
            ? null
            : React.createElement(
                'div',
                { className: 'dswf-loading' },
                React.createElement('span', { className: 'dswf-dot' }),
                '文件箱载入中…',
              ),
        ),
        React.createElement(
          'p',
          { className: 'dswf-tip' },
          '传文件：点「上传文件」；传整个文件夹：在文件管理器里把文件夹压缩成 zip 再点「上传 zip」，会自动解压到同名文件夹里。',
        ),
      )
    }

    function apply(ctx) {
      const slots = ctx && typeof ctx.get === 'function' ? ctx.get('slots') : ctx?.slots
      if (!slots || typeof slots.inject !== 'function' || typeof slots.register !== 'function') {
        console.warn('[dsh-whale-files] slots 服务不可用，设置页未注册')
        return
      }
      const dispose = slots.inject(SLOT, () =>
        slots.register(
          { name: SLOT, id: 'whale-files', order: 94, label: () => '鲸鲸文件箱' },
          WhaleFilesPanel,
        ),
      )
      if (typeof ctx.effect === 'function') {
        ctx.effect(() => () => {
          try { dispose() } catch { /* ignore */ }
        })
      }
    }

    module.exports = { name: 'dsh-whale-files', inject: ['slots'], apply }
    return module.exports
  },
})
