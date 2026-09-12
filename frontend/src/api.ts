export type Board = { id: string; name: string; description: string; created_at: string; image_count: number; cover_image_id: string | null }

export type ProcessingStatus = 'pending' | 'running' | 'succeeded' | 'failed'
export type PaletteColor = { hex: string; lab: [number, number, number]; weight: number }

export type BoardImage = { subject_tags: string[]; id: string; board_id: string; original_filename: string; original_url: string; width: number; height: number; byte_size: number; created_at: string; thumbnail_url: string | null; palette: PaletteColor[] | null; embedding_ready: boolean; model_id: string | null; cpu_status: ProcessingStatus; ai_status: ProcessingStatus; cpu_error: string | null; ai_error: string | null }

export function message(body: unknown, fallback: string): string {
  if (typeof body === 'object' && body && 'detail' in body) {
    const detail = (body as {detail: unknown}).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(d => `${d.loc?.at(-1) ?? 'Value'}: ${d.msg}`).join('; ')
  }
  return fallback
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init)
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(message(body, 'Could not connect to Museboard. Please try again.'))
  return body as T
}

export function uploadImage(board: string, file: File, progress: (n: number) => void): Promise<BoardImage> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    xhr.open('POST', `/api/boards/${board}/images`)
    xhr.timeout = 120000
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)) }
    xhr.onerror = () => reject(new Error('Connection lost. Check whether the image arrived before retrying.'))
    xhr.ontimeout = () => reject(new Error('Upload timed out. Check whether the image arrived before retrying.'))
    xhr.onload = () => {
      let body: unknown
      try { body = JSON.parse(xhr.responseText) } catch { body = null }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as BoardImage)
      else reject(new Error(message(body, 'Upload failed. Please try again.')))
    }
    
    const data = new FormData()
    data.append('file', file)
    xhr.send(data)
  })
}
