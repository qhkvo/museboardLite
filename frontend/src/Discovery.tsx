import { useEffect, useState } from 'react'
import { api, type BoardImage } from './api'

type Match = BoardImage & { distance: number }
type Result = { results: Match[]; has_more: boolean }

export function Discovery({
  source,
  open,
}: {
  source: BoardImage
  open: (image: BoardImage) => void
}) {
  const [mode, setMode] = useState<'semantic' | 'color' | 'subject' | null>(null)
  const [subject, setSubject] = useState('')
  const [tags, setTags] = useState((source.subject_tags ?? []).join(', '))
  const [saving, setSaving] = useState(false)
  const [tagError, setTagError] = useState('')
  const [tagSaved, setTagSaved] = useState(false)
  const [swatch, setSwatch] = useState<number | null>(null)
  const [result, setResult] = useState<Result>({ results: [], has_more: false })
  const [includeWeak, setIncludeWeak] = useState(false)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (!mode) return

    const controller = new AbortController()
    setLoading(true)
    setError('')

    api<Result>(
      `/images/${source.id}/similar?mode=${mode}&limit=24&offset=${offset}&include_weak=${includeWeak}${mode === 'subject' ? `&subject=${encodeURIComponent(subject)}` : ''}${swatch === null ? '' : `&swatch=${swatch}`}`,
      {
        signal: controller.signal,
      },
    )
      .then((data) => {
        if (!controller.signal.aborted)
          setResult((previous) => ({
            ...data,
            results: offset ? [...previous.results, ...data.results] : data.results,
          }))
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [source.id, mode, offset, retry, includeWeak, swatch, subject])

  function choose(
    next: 'semantic' | 'color' | 'subject',
    selected: number | null = null,
  ) {
    setSwatch(selected)
    setError('')
    setMode(next)
    setIncludeWeak(false)
    setLoading(true)
    setOffset(0)
    setResult({ results: [], has_more: false })
    setRetry((n) => n + 1)
  }

  async function saveTags(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setTagError('')
    setTagSaved(false)
    try {
      const updated = await api<BoardImage>(`/images/${source.id}/subjects`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject_tags: tags
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean),
        }),
      })
      setTags(updated.subject_tags.join(', '))
      setMode(null)
      setSubject('')
      setResult({ results: [], has_more: false })
      open(updated)
      setTagSaved(true)
    } catch (e) {
      setTagError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="discovery" aria-label="Discover related images">
      <form onSubmit={saveTags}>
        <label htmlFor="subject-tags">Subjects (comma-separated)</label>
        <input
          id="subject-tags"
          value={tags}
          disabled={saving}
          placeholder=" e.g. dog, animal"
          onChange={(event) => {
            setTags(event.target.value)
            setTagSaved(false)
          }}
        />
        <button type="submit" className="secondary" disabled={saving}>
          {saving ? 'Saving…' : 'Save subjects'}
        </button>
        <p>
          Add the same tag to related images. Tags are entered by you, not assigned
          automatically. Clear the field and save to remove all tags.
        </p>
        {tagError && <p role="alert">{tagError}</p>}
        {tagSaved && <p role="status">Subjects saved.</p>}
      </form>
      {(source.subject_tags ?? []).length > 0 && (
        <div className="discovery-actions" aria-label="Same subject search">
          <span>Same subject:</span>
          {source.subject_tags.map((tag) => (
            <button
              key={tag}
              className="secondary"
              disabled={
                !source.embedding_ready || source.ai_status !== 'succeeded' || saving
              }
              aria-pressed={mode === 'subject' && subject === tag}
              onClick={() => {
                setSubject(tag)
                choose('subject')
              }}
            >
              {tag}
            </button>
          ))}
        </div>
      )}
      {source.palette && (
        <div>
          <p>Choose a color to find images containing that shade.</p>
          <div className="color-swatches" aria-label="Search by palette color">
            {source.palette.map(
              (color, index) =>
                color.weight > 0 && (
                  <button
                    key={index}
                    type="button"
                    className="color-swatch"
                    disabled={source.cpu_status !== 'succeeded'}
                    aria-label={`Find images containing ${color.hex}`}
                    aria-pressed={mode === 'color' && swatch === index}
                    title={`${color.hex} · ${Math.round(color.weight * 100)}% of image`}
                    onClick={() => choose('color', index)}
                  >
                    <span style={{ backgroundColor: color.hex }} />
                    {color.hex}
                  </button>
                ),
            )}
          </div>
        </div>
      )}
      <div className="discovery-actions">
        <button
          className="secondary"
          aria-pressed={mode === 'semantic'}
          disabled={!source.embedding_ready || source.ai_status !== 'succeeded'}
          onClick={() => choose('semantic')}
        >
          Find similar
        </button>
        <button
          className="secondary"
          aria-pressed={mode === 'color' && swatch === null}
          disabled={!source.palette || source.cpu_status !== 'succeeded'}
          onClick={() => choose('color')}
        >
          Similar palette
        </button>
      </div>
      <p>
        Explore images across all your boards. Search becomes available when processing
        finishes.
      </p>
      {mode && (
        <>
          <h3>
            {mode === 'subject'
              ? `Same subject: ${subject}`
              : mode === 'semantic'
                ? 'Similar images'
                : swatch === null
                  ? 'Similar palette'
                  : `Images containing ${source.palette?.[swatch]?.hex}`}
          </h3>
          {mode === 'color' && swatch === null && (
            <p>Compares the whole image, including background colors.</p>
          )}
          {mode !== 'subject' && (
            <label>
              <input
                type="checkbox"
                checked={includeWeak}
                onChange={(event) => {
                  setIncludeWeak(event.target.checked)
                  setOffset(0)
                  setResult({ results: [], has_more: false })
                  setError('')
                  setLoading(true)
                }}
              />{' '}
              Show weaker matches
            </label>
          )}
          {includeWeak && (
            <p>Showing all ranked images, including results that may be unrelated.</p>
          )}
          {error && (
            <p role="alert">
              {error} <button onClick={() => setRetry((n) => n + 1)}>Try again</button>
            </p>
          )}
          <div className="discovery-grid">
            {result.results.map((image) => (
              <button key={image.id} className="image-card" onClick={() => open(image)}>
                <img
                  src={image.thumbnail_url ?? image.original_url}
                  alt={image.original_filename}
                  loading="lazy"
                />
                <span>{image.original_filename}</span>
              </button>
            ))}
          </div>
          {loading && <p role="status">Finding matches…</p>}
          {!loading && !error && !result.results.length && (
            <p>
              {mode === 'subject'
                ? 'No other processed images have this subject. Add the same tag to related images.'
                : !includeWeak
                  ? mode === 'color'
                    ? 'No close color matches. Choose another swatch or show weaker matches.'
                    : 'No close matches. Try showing weaker matches or add more related images.'
                  : 'No matches yet. Add more images or wait for their processing to finish.'}
            </p>
          )}
          {!loading && !error && result.has_more && (
            <button
              className="secondary"
              onClick={() => setOffset(result.results.length)}
            >
              Load more matches
            </button>
          )}
        </>
      )}
    </section>
  )
}
