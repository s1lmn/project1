import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, hasToken, setToken, track } from './api'
import type { Activity, ActivityPage, Level, Lookup, Profile, ResponseItem, UserSport } from './types'

const levels: { id: Level; name: string }[] = [
  { id: 'beginner', name: 'Новичок' },
  { id: 'intermediate', name: 'Средний' },
  { id: 'advanced', name: 'Опытный' },
]
const statusNames: Record<string, string> = {
  active: 'Идёт набор', filled: 'Места набраны', completed: 'Активность завершена',
  cancelled: 'Активность отменена', expired: 'Активность неактуальна', pending: 'Ожидает решения',
  accepted: 'Вы приняты', rejected: 'Отклик отклонён',
}

const participantLimits = [1, 2, 3, 4, 5]

function dateInputValue(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function filterDateLabel(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function placesLabel(value: number) {
  const lastTwo = value % 100
  const last = value % 10
  const word = lastTwo >= 11 && lastTwo <= 14 ? 'мест' : last === 1 ? 'место' : last >= 2 && last <= 4 ? 'места' : 'мест'
  return `${value} ${word}`
}

function ParticipantLimitField({ value, onChange }: { value: number | null; onChange: (value: number | null) => void }) {
  return <label>Сколько участников ищете
    <select required value={value === null ? 'unlimited' : String(value)} onChange={e => onChange(e.target.value === 'unlimited' ? null : Number(e.target.value))}>
      {participantLimits.map(limit => <option key={limit} value={limit}>{limit} {limit === 1 ? 'участник' : limit < 5 ? 'участника' : 'участников'}</option>)}
      <option value="unlimited">Без ограничений</option>
    </select>
    <small className="field-hint">Количество людей без учёта организатора</small>
  </label>
}

function useLookups() {
  const [data, setData] = useState<{ sports: Lookup[]; districts: Lookup[] }>({ sports: [], districts: [] })
  useEffect(() => { api<typeof data>('/lookups').then(setData).catch(() => undefined) }, [])
  return data
}

function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={error ? 'notice error' : 'notice'}>{children}</div>
}

function Loading() { return <main className="center"><div className="loader" /><p>Загружаем…</p></main> }

function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="state"><span className="state-icon">↻</span><h2>Что-то пошло не так</h2><p>{message}</p>{retry && <button onClick={retry}>Попробовать снова</button>}</div>
}

function Avatar({ name, url, large = false }: { name: string; url?: string; large?: boolean }) {
  return <div className={large ? 'avatar large' : 'avatar'}>{url ? <img src={url} alt="" /> : name[0]}</div>
}

function AuthScreen({ onDone }: { onDone: () => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const inTelegram = Boolean(window.Telegram?.WebApp.initData)
  const devAuthEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_AUTH === 'true'
  const signIn = async (dev = false) => {
    setBusy(true); setError('')
    try {
      const result = await api<{ access_token: string }>(dev ? '/auth/dev' : '/auth/telegram', {
        method: 'POST',
        body: JSON.stringify(dev
          ? { telegram_id: Math.floor(9_000_000_000 + Math.random() * 999_999), first_name: 'Тестовый пользователь', username: 'sports_mate_dev' }
          : { init_data: window.Telegram?.WebApp.initData }),
      })
      setToken(result.access_token); onDone()
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось войти') }
    finally { setBusy(false) }
  }
  useEffect(() => { if (inTelegram) void signIn() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <main className="welcome">
    <div className="brand-mark">SM</div>
    <p className="eyebrow">SPORTS MATE</p>
    <h1>Найди компанию<br />для спорта рядом</h1>
    <p>Создавай тренировки, присоединяйся к соседям и встречайся вживую.</p>
    {error && <Notice error>{error}</Notice>}
    {!inTelegram && <>
      <Notice>Откройте приложение из Telegram — так мы безопасно подтвердим ваш профиль.</Notice>
      <a className="button primary" href={`https://t.me/${import.meta.env.VITE_BOT_USERNAME || 'sportssmatebot'}`}>Открыть бота</a>
      {devAuthEnabled && <button className="button ghost" disabled={busy} onClick={() => signIn(true)}>Войти как тестовый пользователь</button>}
    </>}
    {inTelegram && <p className="muted">Подтверждаем вход…</p>}
  </main>
}

function ProfileForm({ profile, onSaved, title = 'Расскажите о себе' }: { profile: Profile; onSaved: (p: Profile) => void; title?: string }) {
  const lookups = useLookups()
  const [age, setAge] = useState(profile.age?.toString() || '')
  const [bio, setBio] = useState(profile.bio || '')
  const [district, setDistrict] = useState(profile.district_id || '')
  const [sports, setSports] = useState<UserSport[]>(profile.sports || [])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!profile.onboarding_completed) void track('onboarding_started') }, [profile.onboarding_completed])
  useEffect(() => {
    if (!district && lookups.districts[0]) setDistrict(lookups.districts[0].id)
  }, [district, lookups.districts])
  const toggleSport = (sport_id: string) => setSports(current => current.some(x => x.sport_id === sport_id)
    ? current.filter(x => x.sport_id !== sport_id)
    : [...current, { sport_id, level: 'beginner' }])
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    const numericAge = Number(age)
    if (!Number.isInteger(numericAge) || numericAge < 18 || numericAge > 100) {
      setError('Укажите возраст от 18 до 100 лет')
      return
    }
    setBusy(true)
    try {
      const updated = await api<Profile>('/me', { method: 'PATCH', body: JSON.stringify({ age: numericAge, bio, district_id: district, sports }) })
      onSaved(updated)
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить') }
    finally { setBusy(false) }
  }
  return <main className="page form-page">
    <p className="eyebrow">Профиль · 1 минута</p><h1>{title}</h1>
    <p className="lead">Это поможет другим понять, подойдёт ли вам тренировка.</p>
    <form onSubmit={save}>
      <label>Возраст<input required type="text" inputMode="numeric" pattern="[0-9]*" value={age} onChange={e => setAge(e.target.value.replace(/\D/g, '').slice(0, 3))} onBlur={() => { if (!age) setAge(profile.age?.toString() || '18') }} placeholder="Например, 24" /></label>
      <label>Пара слов о себе<textarea maxLength={500} value={bio} onChange={e => setBio(e.target.value)} placeholder="Когда обычно тренируетесь, что важно в компании" /></label>
      <label>Район<select required value={district} onChange={e => setDistrict(e.target.value)}><option value="">Выберите район</option>{lookups.districts.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <fieldset><legend>Ваши виды спорта</legend><div className="chips">{lookups.sports.map(sport => <button type="button" key={sport.id} className={sports.some(x => x.sport_id === sport.id) ? 'chip selected' : 'chip'} onClick={() => toggleSport(sport.id)}>{sport.emoji} {sport.name}</button>)}</div></fieldset>
      {sports.map(item => <label key={item.sport_id}>{lookups.sports.find(x => x.id === item.sport_id)?.name}: уровень<select value={item.level} onChange={e => setSports(sports.map(x => x.sport_id === item.sport_id ? { ...x, level: e.target.value as Level } : x))}>{levels.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>)}
      {error && <Notice error>{error}</Notice>}
      <button className="primary wide" disabled={busy || !sports.length}>{busy ? 'Сохраняем…' : 'Сохранить и продолжить'}</button>
    </form>
  </main>
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="shell"><header><Link to="/" className="logo"><span>SM</span> SPORTS MATE</Link></header>{children}<nav className="bottom-nav">
    <Link to="/"><span>⌁</span>Лента</Link><Link to="/mine"><span>◫</span>Мои</Link><Link to="/profile"><span>○</span>Профиль</Link>
  </nav></div>
}

function ActivityCard({ activity }: { activity: Activity }) {
  const date = new Date(activity.starts_at)
  return <Link to={`/activities/${activity.id}`} className="card activity-card">
    <div className="card-top"><span className="sport-icon">{activity.sport_emoji}</span><div><strong>{activity.sport_name}</strong><span>{levels.find(x => x.id === activity.level)?.name}</span></div><span className={`badge ${activity.status}`}>{statusNames[activity.status]}</span></div>
    <div className="activity-main"><div className="date-block"><strong>{date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</strong><span>{date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span></div><div><strong>{activity.place}</strong><span>{activity.district_name}</span></div></div>
    <div className="card-bottom"><span>{activity.author.first_name}, {activity.author.age || '—'} · {activity.author.rating_count ? `★ ${activity.author.rating_average}` : 'без оценок'}</span><b>{activity.remaining_places === null ? 'Без ограничений' : placesLabel(activity.remaining_places)}</b></div>
    {activity.my_response_status && <div className="response-line">Ваш статус: {statusNames[activity.my_response_status] || activity.my_response_status}</div>}
  </Link>
}

function Feed() {
  const lookups = useLookups()
  const [items, setItems] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sport, setSport] = useState('')
  const [level, setLevel] = useState('')
  const [district, setDistrict] = useState('')
  const [day, setDay] = useState('')
  const [timeFrom, setTimeFrom] = useState('')
  const today = dateInputValue(new Date())
  const tomorrowDate = new Date(); tomorrowDate.setDate(tomorrowDate.getDate() + 1)
  const tomorrow = dateInputValue(tomorrowDate)
  const load = useCallback(async () => {
    setLoading(true); setError('')
    const params = new URLSearchParams(); if (sport) params.set('sport_id', sport); if (level) params.set('level', level); if (district) params.set('district_id', district); if (day) params.set('day', day); if (timeFrom) params.set('time_from', timeFrom)
    try { const data = await api<ActivityPage>(`/activities?${params}`); setItems(data.items); void track('feed_viewed', { has_filters: Boolean(sport || level || district || day || timeFrom) }) }
    catch (e) { setError(e instanceof Error ? e.message : 'Ошибка загрузки') }
    finally { setLoading(false) }
  }, [sport, level, district, day, timeFrom])
  useEffect(() => { void load() }, [load])
  return <Shell><main className="page feed"><div className="hero"><p className="eyebrow">Рядом с вами</p><h1>Пора двигаться</h1><p>Выберите тренировку или соберите свою компанию.</p><Link to="/create" className="button primary">＋ Создать активность</Link></div>
    <div className="filters">
      <select aria-label="Вид спорта" value={sport} onChange={e => { setSport(e.target.value); void track('filter_applied', { sport_id: e.target.value }) }}><option value="">Все виды спорта</option>{lookups.sports.map(x => <option key={x.id} value={x.id}>{x.emoji} {x.name}</option>)}</select>
      <select aria-label="Уровень" value={level} onChange={e => { setLevel(e.target.value); void track('filter_applied', { level: e.target.value }) }}><option value="">Любой уровень</option>{levels.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      <select aria-label="Район" value={district} onChange={e => { setDistrict(e.target.value); void track('filter_applied', { district_id: e.target.value }) }}><option value="">Все районы</option>{lookups.districts.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
      <div className="filter-section">
        <span className="filter-label">📅 Дата</span>
        <div className="filter-options">
          <button type="button" className={!day ? 'chip selected' : 'chip'} onClick={() => setDay('')}>Любая</button>
          <button type="button" className={day === today ? 'chip selected' : 'chip'} onClick={() => setDay(today)}>Сегодня</button>
          <button type="button" className={day === tomorrow ? 'chip selected' : 'chip'} onClick={() => setDay(tomorrow)}>Завтра</button>
          <label className={day && day !== today && day !== tomorrow ? 'chip picker-chip selected' : 'chip picker-chip'}>
            {day && day !== today && day !== tomorrow ? filterDateLabel(day) : 'Другая дата'}
            <input aria-label="Выбрать другую дату" type="date" value={day} onChange={e => { setDay(e.target.value); void track('filter_applied', { source: 'day' }) }} />
          </label>
        </div>
      </div>
      <div className="filter-section">
        <span className="filter-label">🕒 Начало не раньше</span>
        <div className="filter-options">
          <button type="button" className={!timeFrom ? 'chip selected' : 'chip'} onClick={() => setTimeFrom('')}>Любое</button>
          <button type="button" className={timeFrom === '09:00' ? 'chip selected' : 'chip'} onClick={() => setTimeFrom('09:00')}>С 09:00</button>
          <button type="button" className={timeFrom === '18:00' ? 'chip selected' : 'chip'} onClick={() => setTimeFrom('18:00')}>С 18:00</button>
          <label className={timeFrom && !['09:00', '18:00'].includes(timeFrom) ? 'chip picker-chip selected' : 'chip picker-chip'}>
            {timeFrom && !['09:00', '18:00'].includes(timeFrom) ? `С ${timeFrom}` : 'Другое время'}
            <input aria-label="Выбрать другое время" type="time" value={timeFrom} onChange={e => { setTimeFrom(e.target.value); void track('filter_applied', { source: 'time_from' }) }} />
          </label>
        </div>
      </div>
    </div>
    {loading ? <Loading /> : error ? <ErrorState message={error} retry={load} /> : items.length ? <div className="cards">{items.map(x => <ActivityCard key={x.id} activity={x} />)}</div> : <div className="state"><span className="state-icon">🏀</span><h2>{sport || level || district || day || timeFrom ? 'Ничего не нашли' : 'Пока тихо'}</h2><p>{sport || level || district || day || timeFrom ? 'Сбросьте фильтры или создайте свою активность.' : 'Станьте первым, кто позовёт соседей на тренировку.'}</p>{sport || level || district || day || timeFrom ? <button onClick={() => { setSport(''); setLevel(''); setDistrict(''); setDay(''); setTimeFrom('') }}>Сбросить фильтры</button> : <Link className="button primary" to="/create">Создать активность</Link>}</div>}
  </main></Shell>
}

function CreateActivity() {
  const nav = useNavigate(); const lookups = useLookups()
  const [clientRequestId] = useState(() => crypto.randomUUID())
  const [form, setForm] = useState<{ sport_id: string; district_id: string; level: string; starts_at: string; place: string; players_needed: number | null; comment: string }>({ sport_id: '', district_id: '', level: 'beginner', starts_at: '', place: '', players_needed: 1, comment: '' })
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { void track('activity_create_started') }, [])
  useEffect(() => { if (!form.sport_id && lookups.sports[0] && lookups.districts[0]) setForm(v => ({ ...v, sport_id: lookups.sports[0].id, district_id: lookups.districts[0].id })) }, [form.sport_id, lookups])
  const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); setError(''); try {
    const item = await api<Activity>('/activities', { method: 'POST', body: JSON.stringify({ ...form, starts_at: new Date(form.starts_at).toISOString(), client_request_id: clientRequestId }) }); nav(`/activities/${item.id}`)
  } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось создать') } finally { setBusy(false) } }
  return <Shell><main className="page form-page"><Link to="/" className="back">← Лента</Link><p className="eyebrow">Новая активность</p><h1>Соберите компанию</h1><form onSubmit={submit}>
    <label>Вид спорта<select required value={form.sport_id} onChange={e => setForm({ ...form, sport_id: e.target.value })}>{lookups.sports.map(x => <option key={x.id} value={x.id}>{x.emoji} {x.name}</option>)}</select></label>
    <label>Уровень<select value={form.level} onChange={e => setForm({ ...form, level: e.target.value })}>{levels.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
    <label>Когда<input required type="datetime-local" value={form.starts_at} onChange={e => setForm({ ...form, starts_at: e.target.value })} /></label>
    <label>Место<input required minLength={2} maxLength={200} value={form.place} onChange={e => setForm({ ...form, place: e.target.value })} placeholder="Площадка у дома, адрес или ориентир" /></label>
    <label>Район<select required value={form.district_id} onChange={e => setForm({ ...form, district_id: e.target.value })}>{lookups.districts.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
    <ParticipantLimitField value={form.players_needed} onChange={players_needed => setForm({ ...form, players_needed })} />
    <label>Комментарий<textarea maxLength={1000} value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} placeholder="Что взять с собой, темп, детали встречи" /></label>
    {error && <Notice error>{error}</Notice>}<button className="primary wide" disabled={busy}>{busy ? 'Создаём…' : 'Создать активность'}</button>
  </form></main></Shell>
}

function toLocalDateTime(value: string) {
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

function EditActivity() {
  const { id = '' } = useParams(); const nav = useNavigate(); const lookups = useLookups()
  const [form, setForm] = useState<{ sport_id: string; district_id: string; level: string; starts_at: string; place: string; players_needed: number | null; comment: string }>()
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  useEffect(() => { api<Activity>(`/activities/${id}`).then(item => { if (!item.is_owner) throw new Error('Редактирование доступно только организатору'); setForm({ sport_id: item.sport_id, district_id: item.district_id, level: item.level, starts_at: toLocalDateTime(item.starts_at), place: item.place, players_needed: item.players_needed, comment: item.comment }) }).catch(e => setError(e instanceof Error ? e.message : 'Не удалось загрузить')) }, [id])
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!form) return; setBusy(true); setError(''); try { await api(`/activities/${id}`, { method: 'PATCH', body: JSON.stringify({ ...form, starts_at: new Date(form.starts_at).toISOString() }) }); nav(`/activities/${id}`) } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось сохранить') } finally { setBusy(false) } }
  if (!form) return <Shell><main className="page">{error ? <ErrorState message={error} /> : <Loading />}</main></Shell>
  return <Shell><main className="page form-page"><Link to={`/activities/${id}`} className="back">← К активности</Link><p className="eyebrow">Редактирование</p><h1>Обновите детали</h1><p className="lead">После первого принятого отклика место, время, район и спорт менять нельзя.</p><form onSubmit={submit}>
    <label>Вид спорта<select value={form.sport_id} onChange={e => setForm({ ...form, sport_id: e.target.value })}>{lookups.sports.map(x => <option key={x.id} value={x.id}>{x.emoji} {x.name}</option>)}</select></label>
    <label>Уровень<select value={form.level} onChange={e => setForm({ ...form, level: e.target.value })}>{levels.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
    <label>Когда<input required type="datetime-local" value={form.starts_at} onChange={e => setForm({ ...form, starts_at: e.target.value })} /></label>
    <label>Место<input required minLength={2} maxLength={200} value={form.place} onChange={e => setForm({ ...form, place: e.target.value })} /></label>
    <label>Район<select value={form.district_id} onChange={e => setForm({ ...form, district_id: e.target.value })}>{lookups.districts.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
    <ParticipantLimitField value={form.players_needed} onChange={players_needed => setForm({ ...form, players_needed })} />
    <label>Комментарий<textarea maxLength={1000} value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} /></label>
    {error && <Notice error>{error}</Notice>}<button className="primary wide" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить изменения'}</button>
  </form></main></Shell>
}

function ActivityDetails() {
  const { id = '' } = useParams(); const nav = useNavigate()
  const [item, setItem] = useState<Activity>(); const [responses, setResponses] = useState<ResponseItem[]>([])
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { const data = await api<Activity>(`/activities/${id}`); setItem(data); void track('activity_viewed', {}, id); if (data.is_owner) setResponses(await api<ResponseItem[]>(`/activities/${id}/responses`)) } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка') } }, [id])
  useEffect(() => { void load() }, [load])
  const action = async (path: string, method = 'POST', body?: object) => { setBusy(true); setError(''); try { await api(path, { method, body: body ? JSON.stringify(body) : undefined }); await load() } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка') } finally { setBusy(false) } }
  const openContact = async (userId: string) => { try { const c = await api<{ telegram_url: string; notice?: string }>(`/activities/${id}/contact/${userId}`); if (c.notice) alert(c.notice); if (window.Telegram) window.Telegram.WebApp.openTelegramLink(c.telegram_url); else window.open(c.telegram_url) } catch (e) { setError(e instanceof Error ? e.message : 'Контакт недоступен') } }
  const submitRating = async (userId: string) => {
    const raw = prompt('Оценка от 1 до 5'); if (!raw) return
    const score = Number(raw); if (!Number.isInteger(score) || score < 1 || score > 5) { setError('Введите целую оценку от 1 до 5'); return }
    const review = prompt('Короткий отзыв — необязательно') || ''
    await action(`/activities/${id}/ratings`, 'POST', { target_user_id: userId, score, review })
  }
  const report = async (userId: string) => {
    if (!confirm('Отправить жалобу на подозрительное поведение?')) return
    await action('/reports', 'POST', { target_user_id: userId, activity_id: id, reason: 'suspicious', details: '' })
  }
  const block = async (userId: string) => {
    if (!confirm('Заблокировать пользователя? Вы перестанете видеть активности друг друга.')) return
    await action('/blocks', 'POST', { target_user_id: userId })
  }
  if (error && !item) return <Shell><main className="page"><ErrorState message={error} retry={load} /></main></Shell>
  if (!item) return <Shell><Loading /></Shell>
  const d = new Date(item.starts_at)
  return <Shell><main className="page detail"><button className="back link-button" onClick={() => nav(-1)}>← Назад</button>
    <div className="detail-hero"><span className="big-icon">{item.sport_emoji}</span><p className="eyebrow">{statusNames[item.status]}</p><h1>{item.sport_name}</h1><p>{levels.find(x => x.id === item.level)?.name}</p></div>
    <section className="detail-grid"><div><span>Когда</span><strong>{d.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}<br />{d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</strong></div><div><span>Где</span><strong>{item.place}<br />{item.district_name}</strong></div><div><span>Компания</span><strong>{item.players_needed === null ? 'Без ограничений' : `Нужно ещё ${placesLabel(item.remaining_places || 0)} из ${item.players_needed}`}</strong></div></section>
    <section className="organizer"><Avatar name={item.author.first_name} url={item.author.photo_url} /><div><span>Организатор</span><Link className="profile-link" to={`/users/${item.author.id}`}>{item.author.first_name}, {item.author.age || 'возраст не указан'}</Link><small>{item.author.rating_count ? `★ ${item.author.rating_average} · ${item.author.rating_count} оценок` : 'Пока нет оценок'}</small></div></section>
    {item.comment && <section><h3>Комментарий</h3><p>{item.comment}</p></section>}
    {error && <Notice error>{error}</Notice>}
    {!item.is_owner && item.can_respond && <button className="primary wide" disabled={busy} onClick={() => action(`/activities/${id}/respond`)}>Откликнуться</button>}
    {!item.is_owner && item.my_response_status === 'pending' && item.my_response_id && <button className="ghost wide" disabled={busy} onClick={() => action(`/responses/${item.my_response_id}/cancel`, 'PATCH')}>Отменить отклик</button>}
    {!item.is_owner && item.my_response_status === 'accepted' && <><button className="primary wide" onClick={() => openContact(item.author.id)}>Написать организатору</button>{item.status === 'completed' && item.meeting_result === 'occurred' && <button className="wide" onClick={() => submitRating(item.author.id)}>★ Оценить организатора</button>}<div className="minor-actions"><button onClick={() => report(item.author.id)}>Пожаловаться</button><button onClick={() => block(item.author.id)}>Заблокировать</button></div></>}
    {item.can_confirm_result && <section className="result"><h3>Встреча состоялась?</h3><div className="split"><button onClick={() => action(`/activities/${id}/confirm-result`, 'POST', { occurred: true })}>Да, всё получилось</button><button className="ghost" onClick={() => action(`/activities/${id}/confirm-result`, 'POST', { occurred: false })}>Нет</button></div></section>}
    {item.meeting_result !== 'unknown' && <Notice>{item.meeting_result === 'occurred' ? 'Встреча состоялась' : item.meeting_result === 'disputed' ? 'Участники указали разные результаты' : 'Встреча не состоялась'}</Notice>}
    {item.is_owner && <section><div className="section-head"><h2>Отклики</h2><span>{responses.length}</span></div>{responses.length ? responses.map(r => <div className="response" key={r.id}><Avatar name={r.user.first_name} url={r.user.photo_url} /><div><Link className="profile-link" to={`/users/${r.user.id}`}>{r.user.first_name}, {r.user.age || '—'}</Link><small>{statusNames[r.status] || r.status}</small></div><div className="response-actions">{r.status === 'pending' && <><button disabled={busy} onClick={() => action(`/responses/${r.id}/accept`, 'PATCH')}>Принять</button><button className="ghost" disabled={busy} onClick={() => action(`/responses/${r.id}/reject`, 'PATCH')}>Отклонить</button></>}{r.status === 'accepted' && <><button onClick={() => openContact(r.user.id)}>Написать</button>{item.status === 'completed' && item.meeting_result === 'occurred' && <button onClick={() => submitRating(r.user.id)}>★ Оценить</button>}<button className="ghost" onClick={() => report(r.user.id)}>Пожаловаться</button><button className="ghost" onClick={() => block(r.user.id)}>Блок</button></>}</div></div>) : <p className="muted">Пока никто не откликнулся.</p>}</section>}
    {item.is_owner && ['active', 'filled'].includes(item.status) && <Link className="button wide" to={`/activities/${id}/edit`}>Редактировать активность</Link>}
    {item.is_owner && ['active', 'filled'].includes(item.status) && <button className="danger wide" onClick={() => confirm('Точно отменить активность? История сохранится.') && action(`/activities/${id}`, 'DELETE')}>Отменить активность</button>}
  </main></Shell>
}

function MyActivities() {
  const [role, setRole] = useState<'organizer' | 'participant'>('organizer'); const [items, setItems] = useState<Activity[]>([]); const [loading, setLoading] = useState(true)
  useEffect(() => { setLoading(true); api<ActivityPage>(`/me/activities?role=${role}`).then(x => setItems(x.items)).finally(() => setLoading(false)) }, [role])
  return <Shell><main className="page"><p className="eyebrow">Личный раздел</p><h1>Мои активности</h1><div className="tabs"><button className={role === 'organizer' ? 'active' : ''} onClick={() => setRole('organizer')}>Организую</button><button className={role === 'participant' ? 'active' : ''} onClick={() => setRole('participant')}>Участвую</button></div>{loading ? <Loading /> : items.length ? <div className="cards">{items.map(x => <ActivityCard key={x.id} activity={x} />)}</div> : <div className="state"><span className="state-icon">◫</span><h2>Здесь пока пусто</h2><p>{role === 'organizer' ? 'Создайте первую активность.' : 'Откликнитесь на тренировку в ленте.'}</p><Link className="button primary" to={role === 'organizer' ? '/create' : '/'}>{role === 'organizer' ? 'Создать' : 'В ленту'}</Link></div>}</main></Shell>
}

function ProfilePage({ profile, setProfile }: { profile: Profile; setProfile: (p: Profile) => void }) {
  const [editing, setEditing] = useState(false); const lookups = useLookups()
  if (editing) return <Shell><ProfileForm profile={profile} title="Редактирование профиля" onSaved={p => { setProfile(p); setEditing(false) }} /></Shell>
  return <Shell><main className="page profile"><div className="profile-head"><Avatar name={profile.first_name} url={profile.photo_url} large /><div><p className="eyebrow">Ваш профиль</p><h1>{profile.first_name} {profile.last_name || ''}</h1><p>{profile.rating_count ? `★ ${profile.rating_average} · ${profile.rating_count} оценок` : 'Пока нет оценок'}</p></div></div><button className="wide" onClick={() => setEditing(true)}>Редактировать профиль</button><section><h3>О себе</h3><p>{profile.age ? `${profile.age} лет` : 'Возраст не указан'} · {lookups.districts.find(x => x.id === profile.district_id)?.name || 'Район не выбран'}</p><p>{profile.bio || 'Описание пока не добавлено.'}</p></section><section><h3>Виды спорта</h3><div className="chips">{profile.sports.map(x => <span className="chip selected" key={x.sport_id}>{lookups.sports.find(s => s.id === x.sport_id)?.emoji} {lookups.sports.find(s => s.id === x.sport_id)?.name} · {levels.find(l => l.id === x.level)?.name}</span>)}</div></section></main></Shell>
}

function PublicProfilePage() {
  const { id = '' } = useParams(); const nav = useNavigate(); const lookups = useLookups()
  const [profile, setProfile] = useState<Profile>(); const [error, setError] = useState(''); const [done, setDone] = useState('')
  useEffect(() => { api<Profile>(`/users/${id}`).then(setProfile).catch(e => setError(e instanceof Error ? e.message : 'Профиль недоступен')) }, [id])
  const report = async () => { if (!confirm('Отправить жалобу на подозрительное поведение?')) return; try { await api('/reports', { method: 'POST', body: JSON.stringify({ target_user_id: id, reason: 'suspicious', details: '' }) }); setDone('Жалоба отправлена команде модерации.') } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось отправить жалобу') } }
  const block = async () => { if (!confirm('Заблокировать пользователя? Вы перестанете видеть активности друг друга.')) return; try { await api('/blocks', { method: 'POST', body: JSON.stringify({ target_user_id: id }) }); nav('/') } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось заблокировать') } }
  if (error && !profile) return <Shell><main className="page"><ErrorState message={error} /></main></Shell>
  if (!profile) return <Shell><Loading /></Shell>
  return <Shell><main className="page profile"><button className="back link-button" onClick={() => nav(-1)}>← Назад</button><div className="profile-head"><Avatar name={profile.first_name} url={profile.photo_url} large /><div><p className="eyebrow">Профиль участника</p><h1>{profile.first_name} {profile.last_name || ''}</h1><p>{profile.rating_count ? `★ ${profile.rating_average} · ${profile.rating_count} оценок` : 'Пока нет оценок'}</p></div></div><section><h3>О себе</h3><p>{profile.age ? `${profile.age} лет` : 'Возраст не указан'} · {lookups.districts.find(x => x.id === profile.district_id)?.name || 'Район не указан'}</p><p>{profile.bio || 'Описание пока не добавлено.'}</p></section><section><h3>Виды спорта</h3><div className="chips">{profile.sports.map(x => <span className="chip selected" key={x.sport_id}>{lookups.sports.find(s => s.id === x.sport_id)?.emoji} {lookups.sports.find(s => s.id === x.sport_id)?.name} · {levels.find(l => l.id === x.level)?.name}</span>)}</div></section>{done && <Notice>{done}</Notice>}{error && <Notice error>{error}</Notice>}<div className="minor-actions"><button onClick={report}>Пожаловаться</button><button onClick={block}>Заблокировать</button></div></main></Shell>
}

type Metrics = {
  registrations: number; onboarding_completed: number; activation_users: number
  activities_created: number; activities_with_response: number; responses_sent: number
  responses_accepted: number; completed_activities: number; successful_matches: number
  cancelled_activities: number; reports: number; notification_queue_pending: number
  notification_queue_failed: number; past_activities: number; pending_responses: number
  system_closed_responses: number; reported_users: number; active_users: number
  no_show_report_activities: number; past_activities_with_accepted: number
  onboarding_completion_rate?: number; activation_rate?: number; activities_with_response_rate?: number
  responses_per_activity?: number; median_first_response_minutes?: number; activities_without_response_rate?: number
  acceptance_rate?: number; pending_response_rate?: number; system_closed_response_rate?: number
  completion_rate?: number; cancellation_rate?: number; reported_users_rate?: number
  no_show_reports_rate?: number; successful_matches_per_week?: number
  retention_d1?: number; retention_d7?: number; retention_d30?: number; cohort_age_days: number
  retention_d1_retained: number; retention_d1_eligible: number; retention_d7_retained: number
  retention_d7_eligible: number; retention_d30_retained: number; retention_d30_eligible: number
  activities_by_day: Record<string, number>; filter_sources: string[]
}

function MetricsPage() {
  const lookups = useLookups()
  const [start, setStart] = useState(() => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10))
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10))
  const [key, setKey] = useState('')
  const [sport, setSport] = useState(''); const [district, setDistrict] = useState('')
  const [level, setLevel] = useState(''); const [source, setSource] = useState('')
  const [data, setData] = useState<Metrics>(); const [error, setError] = useState('')
  const periodDays = Math.max(1, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86400000) + 1)
  const load = async () => { setError(''); const params = new URLSearchParams({ period_start: start, period_end: end }); if (sport) params.set('sport_id', sport); if (district) params.set('district_id', district); if (level) params.set('level', level); if (source) params.set('acquisition_source', source); try { const result = await api<Metrics>(`/internal/metrics?${params}`, { headers: { 'X-Internal-Key': key } }); setData(result) } catch (e) { setError(e instanceof Error ? e.message : 'Метрики недоступны') } }
  const percent = (value?: number) => value == null ? 'Недостаточно данных' : `${(value * 100).toFixed(1)}%`
  const cards = data ? [
    ['Регистрации', String(data.registrations), `возраст когорты: ${data.cohort_age_days} дн.`],
    ['Завершили профиль', percent(data.onboarding_completion_rate), `${data.onboarding_completed}/${data.registrations}`],
    ['Активация', percent(data.activation_rate), `${data.activation_users}/${data.registrations}`],
    ['Активностей в день', (data.activities_created / periodDays).toFixed(2), `${data.activities_created} за ${periodDays} дн.`],
    ['Активности с откликом', percent(data.activities_with_response_rate), `${data.activities_with_response}/${data.activities_created}`],
    ['Откликов на активность', data.responses_per_activity?.toFixed(2) || 'Недостаточно данных', `${data.responses_sent}/${data.activities_created}`],
    ['Медиана первого отклика', data.median_first_response_minutes == null ? 'Недостаточно данных' : `${data.median_first_response_minutes} мин`, `без отклика: ${percent(data.activities_without_response_rate)}`],
    ['Принято откликов', percent(data.acceptance_rate), `${data.responses_accepted}/${data.responses_sent}; pending ${data.pending_responses}`],
    ['Системно закрыто', percent(data.system_closed_response_rate), `${data.system_closed_responses}/${data.responses_sent}`],
    ['Технически завершено', percent(data.completion_rate), `${data.completed_activities}/${data.past_activities}`],
    ['Успешных встреч / нед.', data.successful_matches_per_week?.toFixed(2) || 'Недостаточно данных', `${data.successful_matches} за период`],
    ['D1 retention', percent(data.retention_d1), `${data.retention_d1_retained}/${data.retention_d1_eligible}`],
    ['D7 retention', percent(data.retention_d7), `${data.retention_d7_retained}/${data.retention_d7_eligible}`],
    ['D30 retention', percent(data.retention_d30), `${data.retention_d30_retained}/${data.retention_d30_eligible}`],
    ['Отменено', percent(data.cancellation_rate), `${data.cancelled_activities}/${data.activities_created}`],
    ['Жалобы', String(data.reports), `получили: ${data.reported_users}/${data.active_users} активных`],
    ['Сигнал «не пришёл»', percent(data.no_show_reports_rate), `${data.no_show_report_activities}/${data.past_activities_with_accepted}`],
    ['Очередь уведомлений', String(data.notification_queue_pending), `ошибок: ${data.notification_queue_failed}`],
  ] : []
  return <Shell><main className="page metrics"><p className="eyebrow">Закрытый раздел</p><h1>Метрики MVP</h1><p className="lead">Воронка за период. «Недостаточно данных» означает нулевой знаменатель или незрелую retention-когорту.</p><div className="metric-filters"><label>С<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>По<input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label><label>Спорт<select value={sport} onChange={e => setSport(e.target.value)}><option value="">Все</option>{lookups.sports.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}</select></label><label>Район<select value={district} onChange={e => setDistrict(e.target.value)}><option value="">Все</option>{lookups.districts.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}</select></label><label>Уровень<select value={level} onChange={e => setLevel(e.target.value)}><option value="">Все</option>{levels.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}</select></label><label>Источник<select value={source} onChange={e => setSource(e.target.value)}><option value="">Все</option>{(data?.filter_sources || ['unknown']).map(x => <option value={x} key={x}>{x}</option>)}</select></label><label>Внутренний ключ<input type="password" value={key} onChange={e => setKey(e.target.value)} /></label><button className="primary" onClick={load}>Обновить</button></div>{error && <Notice error>{error}</Notice>}<div className="metric-grid">{cards.map(([label, value, hint]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>)}</div>{data && <section className="daily"><h2>Активности по дням</h2>{Object.keys(data.activities_by_day).length ? Object.entries(data.activities_by_day).map(([date, count]) => <div key={date}><span>{new Date(`${date}T12:00:00`).toLocaleDateString('ru-RU')}</span><strong>{count}</strong></div>) : <p className="muted">За период активностей нет.</p>}</section>}</main></Shell>
}

export default function App() {
  const [profile, setProfile] = useState<Profile>(); const [booting, setBooting] = useState(hasToken()); const [authVersion, setAuthVersion] = useState(0)
  useEffect(() => {
    if (!hasToken()) { setBooting(false); return }
    setBooting(true); api<Profile>('/me').then(setProfile).catch(() => setProfile(undefined)).finally(() => setBooting(false))
  }, [authVersion])
  if (booting) return <Loading />
  if (!hasToken() || !profile) return <AuthScreen onDone={() => setAuthVersion(x => x + 1)} />
  if (!profile.onboarding_completed) return <ProfileForm profile={profile} onSaved={setProfile} />
  return <Routes>
    <Route path="/" element={<Feed />} />
    <Route path="/create" element={<CreateActivity />} />
    <Route path="/activities/:id" element={<ActivityDetails />} />
    <Route path="/activities/:id/edit" element={<EditActivity />} />
    <Route path="/mine" element={<MyActivities />} />
    <Route path="/profile" element={<ProfilePage profile={profile} setProfile={setProfile} />} />
    <Route path="/users/:id" element={<PublicProfilePage />} />
    <Route path="/internal/metrics" element={<MetricsPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
