import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowUpRight, Check, Images, LoaderCircle, Plus, X } from 'lucide-react'
import { api, uploadImage, type Board, type BoardImage } from './api'
import './style.css'

type UploadItem = { id: string; file: File; preview: string; status: 'waiting' | 'uploading' | 'done' | 'error'; progress: number; error?: string }
const initialBoard = new URLSearchParams(location.search).get('board')
const sizeLabel = (n: number) => n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`

const processing = (image: BoardImage) => [image.cpu_status, image.ai_status].some(s => s === 'pending' || s === 'running')
function Processing({ image }: { image: BoardImage }) {
  return <div className="processing-states" aria-label="Image processing">
    <span data-status={image.cpu_status} title={image.cpu_error ?? undefined}>{image.cpu_status === 'succeeded' ? 'Thumbnail ready' : image.cpu_status === 'failed' ? 'Thumbnail failed' : 'Making thumbnail…'}</span>
    <span data-status={image.ai_status} title={image.ai_error ?? undefined}>{image.ai_status === 'succeeded' ? 'Visual features ready' : image.ai_status === 'failed' ? 'Visual features failed' : 'Finding visual features…'}</span>
  </div>
}

function App() {
  const [boards, setBoards] = useState<Board[]>([])
  const [active, setActive] = useState<string | null>(initialBoard)
  const [images, setImages] = useState<BoardImage[]>([])
  const [loading, setLoading] = useState(true)
  const [boardLoading, setBoardLoading] = useState(false)
  const [error, setError] = useState('')
  const [imageError, setImageError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [more, setMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [creating, setCreating] = useState(false)
  const [formError, setFormError] = useState('')
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [detail, setDetail] = useState<BoardImage | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const boardDialog = useRef<HTMLDialogElement>(null)
  const imageDialog = useRef<HTMLDialogElement>(null)
  const previews = useRef(new Set<string>())
  const currentActive = useRef(active)
  currentActive.current = active
  const board = boards.find(b => b.id === active)

  async function fetchBoards() {
    const result = await api<Board[]>('/boards')
    setBoards(result)
    return result
  }
  useEffect(() => {
    let alive = true
    api<Board[]>('/boards').then(result => {
      if (!alive) return
      setBoards(result)
      if (initialBoard && !result.some(b => b.id === initialBoard)) { setActive(null); history.replaceState(null, '', location.pathname) }
    }).catch(e => { if (alive) setError(e.message) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])
  useEffect(() => {
    const urls = previews.current
    return () => { urls.forEach(url => URL.revokeObjectURL(url)) }
  }, [])
  useEffect(() => {
    if (!active) { setImages([]); setBoardLoading(false); return }
    const controller = new AbortController()
    setBoardLoading(true); setImageError(''); setImages([]); setLoadingMore(false)
    api<BoardImage[]>(`/boards/${active}/images?limit=60`, {signal: controller.signal})
      .then(result => { setImages(result); setMore(result.length === 60) })
      .catch(e => { if (e.name !== 'AbortError') setImageError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setBoardLoading(false) })
    return () => controller.abort()
  }, [active, refresh])
  useEffect(() => { if (detail) imageDialog.current?.showModal() }, [detail])

  // Refresh only pending visible images; preserve pagination and stop when all
  // jobs are terminal. Abort stale requests when the board or image list changes.
  useEffect(() => {
    const pending = images.filter(processing)
    if (!active || boardLoading || !pending.length) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const updated: BoardImage[] = []
        // Bound request concurrency even after many pages have been loaded.
        for (let i = 0; i < pending.length; i += 4) {
          updated.push(...await Promise.all(pending.slice(i, i + 4).map(image =>
            api<BoardImage>(`/images/${image.id}`, {signal: controller.signal}))))
        }
        if (controller.signal.aborted) return
        const byId = new Map(updated.map(image => [image.id, image]))
        setImages(previous => previous.map(image => byId.get(image.id) ?? image))
        setDetail(previous => previous ? byId.get(previous.id) ?? previous : null)
        setImageError('')
      } catch (e) {
        if (!controller.signal.aborted) {
          setImageError((e as Error).message)
          setImages(previous => [...previous]) // Retry polling after a transient error.
        }
      }
    }, 2000)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [active, boardLoading, images])

  function select(id: string | null) {
    clearUploads()
    setActive(id); setError(''); setImageError('')
    history.replaceState(null, '', id ? `?board=${id}` : location.pathname)
  }

  function newBoard() { setFormError(''); boardDialog.current?.showModal() }

  async function createBoard(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setCreating(true); setFormError('')
    try {
      const created = await api<Board>('/boards', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:data.get('name'), description:data.get('description')})})
      setBoards(previous => [created, ...previous]); select(created.id)
      form.reset(); boardDialog.current?.close()
    } catch (e) { setFormError((e as Error).message) }
    finally { setCreating(false) }
  }

  // Load more images
  async function loadMore() {
    const selected = active
    setLoadingMore(true)
    try {
      const result = await api<BoardImage[]>(`/boards/${selected}/images?limit=60&offset=${images.length}`)
      if (currentActive.current === selected) { setImages(previous => [...previous, ...result]); setMore(result.length === 60) }
    } catch (e) { if (currentActive.current === selected) setImageError((e as Error).message) }
    finally { if (currentActive.current === selected) setLoadingMore(false) }
  }

  // Uploads
  function patch(id: string, update: Partial<UploadItem>) { setUploads(previous => previous.map(item => item.id === id ? {...item,...update} : item)) }
  async function runUploads(items: UploadItem[]) {
    if (!active || busy) return
    setBusy(true)
    const target = active
    let cursor = 0
    const worker = async () => {
      while (cursor < items.length) {
        const item = items[cursor++]
        patch(item.id, {status:'uploading', error:undefined, progress:0})
        try {
          await uploadImage(target, item.file, progress => patch(item.id, {progress}))
          patch(item.id, {status:'done', progress:100})
        } catch (e) { patch(item.id, {status:'error', error:(e as Error).message}) }
      }
    }
    try {
      await Promise.all(Array.from({length:Math.min(3,items.length)}, worker))
      await fetchBoards()
    } catch (e) { setError((e as Error).message) }
    finally { setRefresh(n => n+1); setBusy(false) }
  }

  // File selection
  function choose(files: FileList | File[]) {
    if (!active || busy) return
    setError('')
    const items = Array.from(files).slice(0,50).map(file => {
      const valid = /\.(jpe?g|png)$/i.test(file.name)
      const reason = !valid ? 'Only JPEG and PNG files are supported.' : file.size > 20*1024*1024 ? 'Image must be 20 MB or less.' : undefined
      const preview = valid ? URL.createObjectURL(file) : ''
      if (preview) previews.current.add(preview)
      return {id:crypto.randomUUID(), file, preview, status:reason?'error':'waiting',progress:0,error:reason} as UploadItem
    })
    if (files.length > 50) setError('The first 50 files were selected. Add the rest after this batch finishes.')
    setUploads(previous => [...previous,...items])
    const accepted = items.filter(item => item.status === 'waiting')
    if (accepted.length) void runUploads(accepted)
  }

  function clearUploads() {
    uploads.forEach(item => { URL.revokeObjectURL(item.preview); previews.current.delete(item.preview) })
    setUploads([])
  }

  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <header className="archive-header">
      <a className="brand" href="/" onClick={e=>{e.preventDefault(); if(!busy) select(null)}} aria-label="Museboard home">museboard<span>∗</span></a>
      <button className={`header-link ${!active?'current':''}`} onClick={()=>select(null)} disabled={busy}><span aria-hidden="true">o.</span> Boards <sup>{boards.length}</sup></button>
      <div className="collection-picker"><label htmlFor="collection">Collection</label><select id="collection" aria-label="Select a board" value={active ?? ''} disabled={busy} onChange={e=>select(e.target.value || null)}><option value="">All boards</option>{boards.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select></div>
      <button className="header-link" onClick={newBoard} disabled={busy || loading}><span aria-hidden="true">+</span> New board</button>
      <div className="archive-edition"><span>Personal archive</span><span>№ {String(boards.reduce((n,b)=>n+b.image_count,0)).padStart(3,'0')}</span></div>
    </header>
    <main id="main-content">
      <div className="main-content">
        <div className="page-heading"><div><div className="eyebrow">{active?'Selected collection':'Image collections'}</div><h1>{board?.name ?? 'The board index.'}</h1>{active && board?.description && <p>{board.description}</p>}</div>
          {active?<button className="primary" onClick={()=>fileInput.current?.click()} disabled={busy || !board}><Plus size={17}/>{busy?'Uploading…':'Add images'}</button>:<button className="primary" onClick={newBoard} disabled={loading}><Plus size={18}/>New board</button>}
        </div>
        {error && <div className="error-banner" role="alert">{error}<button onClick={()=>{setError('');setLoading(true);fetchBoards().catch(e=>setError(e.message)).finally(()=>setLoading(false))}}>Try again</button></div>}
        {loading ? <div className="loading"><LoaderCircle className="spin"/>Loading your boards…</div> : !active ? <>
          <div className="section-line"><h2>Boards <span>({boards.length})</span></h2><span>Collected, in your own order.</span></div>
          <div className="board-grid">{boards.map((b,index)=><button key={b.id} className="board-card" onClick={()=>select(b.id)}>
            <div className="board-cover">{b.cover_image_id ? <img src={`/api/media/${b.cover_image_id}`} alt="" loading="lazy"/> : <div className="blank-cover"><span className="empty-number">{String(index+1).padStart(2,'0')}</span><span>Empty collection</span></div>}<span className="board-arrow"><ArrowUpRight size={18}/></span></div>
            <div className="board-card-caption"><h3><span className="catalog-number">{String(index+1).padStart(2,'0')} /</span> {b.name}</h3><span>{b.image_count} {b.image_count===1?'image':'images'}</span></div>{b.description && <p>{b.description}</p>}
          </button>)}<button className="create-card" onClick={newBoard}><span><Plus size={25}/></span><h3>Create a board</h3><p>Begin a new collection.</p></button></div>
          {!boards.length && <div className="first-note"><span>01</span><div><h2>Nothing collected. Yet.</h2><p>Create a board to collect images, references, and ideas.</p></div></div>}
        </> : <>
          <input ref={fileInput} className="visually-hidden" type="file" accept="image/jpeg,image/png" multiple aria-label="Choose images" disabled={busy} onChange={e=>{if(e.target.files) choose(e.target.files);e.target.value=''}}/>
          <div className={`dropzone ${dragging?'dragging':''}`} onDragOver={e=>{e.preventDefault();if(!busy)setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={e=>{e.preventDefault();setDragging(false);choose(e.dataTransfer.files)}}>
            <div><strong>Drop images here</strong><p>JPEG / PNG — up to 20 MB each</p></div><button className="secondary" disabled={busy || !board} onClick={()=>fileInput.current?.click()}>Browse files</button>
          </div>
          {uploads.length>0 && <section className="upload-panel" aria-label="Upload progress"><div className="upload-panel-heading"><strong aria-live="polite">{busy?'Adding your images…':`${uploads.filter(u=>u.status==='done').length} uploaded · ${uploads.filter(u=>u.status==='error').length} failed`}</strong><button disabled={busy} onClick={clearUploads}>Dismiss</button></div>{uploads.map(item=><div className="upload-row" key={item.id}>{item.preview?<img src={item.preview} alt=""/>:<Images size={24}/>}<div className="upload-description"><strong>{item.file.name}</strong>{item.status==='error'?<span className="file-error" role="alert">{item.error}</span>:<span>{item.status==='done'?'Added to board':item.status==='uploading'?(item.progress===100?'Checking image…':`${item.progress}% uploaded`):'Waiting…'}</span>}{item.status==='uploading'&&<progress value={item.progress} max={100} aria-label={`Uploading ${item.file.name}`}/>}</div>{item.status==='done'?<Check size={18}/>:item.status==='error'?<button disabled={busy} onClick={()=>void runUploads([item])}>Retry</button>:<LoaderCircle className="spin" size={18}/>}</div>)}</section>}
          <div className="section-line"><h2>Images <span>({board?.image_count ?? 0})</span></h2><span>Newest first</span></div>
          {imageError && <div className="error-banner" role="alert">{imageError}<button onClick={()=>setRefresh(n=>n+1)}>Try again</button></div>}
          {boardLoading?<div className="loading"><LoaderCircle className="spin"/>Loading images…</div>:images.length?<><div className="image-grid">{images.map((image,index)=><button className="image-card" key={image.id} onClick={()=>setDetail(image)}><div className="image-frame"><img src={image.thumbnail_url ?? image.original_url} alt={image.original_filename} width={image.width} height={image.height} loading="lazy"/></div><div className="image-caption"><span className="catalog-number">{String(index+1).padStart(2,'0')} /</span><span>{image.original_filename}</span><ArrowUpRight size={14}/></div><Processing image={image}/></button>)}</div>{more&&<button className="secondary load-more" disabled={loadingMore || busy} onClick={()=>void loadMore()}>{loadingMore?'Loading…':'Load more images'}</button>}</>:!imageError&&<div className="empty-board"><Images size={40} strokeWidth={1}/><h2>An empty collection.</h2><p>Add images to begin.</p></div>}
        </>}
      </div>
    </main>
    <dialog ref={boardDialog} className="modal" onCancel={e=>{if(creating)e.preventDefault()}}><form onSubmit={createBoard}><button type="button" className="close-button" aria-label="Close new board" disabled={creating} onClick={()=>boardDialog.current?.close()}><X size={20}/></button><div className="eyebrow">NEW COLLECTION</div><h2>Create a board</h2><p>A title, a few words, a place to collect.</p><label>Board name<input name="name" placeholder="e.g. Quiet places" maxLength={100} required autoFocus/></label><label>Description <span>(optional)</span><textarea name="description" placeholder="What are you collecting?" maxLength={1000} rows={3}/></label>{formError&&<p className="file-error" role="alert">{formError}</p>}<button type="submit" className="primary" disabled={creating}>{creating?'Creating…':'Create board'}<Plus size={17}/></button></form></dialog>
    <dialog ref={imageDialog} className="image-modal" onClose={()=>setDetail(null)}>{detail&&<><button className="close-button" aria-label="Close image" onClick={()=>imageDialog.current?.close()}><X/></button><img src={detail.original_url} alt={detail.original_filename}/><div><h2>{detail.original_filename}</h2><p>{detail.width} × {detail.height} · {sizeLabel(detail.byte_size)}</p><Processing image={detail}/>{detail.cpu_error && detail.cpu_status === 'failed' && <p className="file-error">Thumbnail: {detail.cpu_error}</p>}{detail.ai_error && detail.ai_status === 'failed' && <p className="file-error">Visual features: {detail.ai_error}</p>}{detail.palette && <div className="palette" aria-label="Dominant colors">{detail.palette.filter(color => color.weight > 0).map((color, index) => <span key={index} style={{backgroundColor: color.hex, flexGrow: color.weight}} title={`${color.hex} · ${Math.round(color.weight * 100)}%`} aria-label={`${color.hex}, ${Math.round(color.weight * 100)} percent`}/>)}</div>}<a href={detail.original_url} target="_blank" rel="noreferrer">Open original <ArrowUpRight size={15}/></a></div></>}</dialog>
  </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>)
