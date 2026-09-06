export type Level = 'beginner' | 'intermediate' | 'advanced'
export type Lookup = { id: string; name: string; emoji?: string; timezone?: string }
export type UserSport = { sport_id: string; level: Level }
export type Profile = {
  id: string
  first_name: string
  last_name?: string
  username?: string
  photo_url?: string
  age?: number
  bio: string
  district_id?: string
  sports: UserSport[]
  rating_average?: number
  rating_count: number
  onboarding_completed?: boolean
}
export type Activity = {
  id: string
  author: { id: string; first_name: string; age?: number; photo_url?: string; rating_average?: number; rating_count: number }
  sport_id: string
  sport_name: string
  sport_emoji: string
  district_id: string
  district_name: string
  level: Level
  starts_at: string
  timezone: string
  place: string
  players_needed: number | null
  accepted_count: number
  remaining_places: number | null
  response_count: number
  comment: string
  status: string
  is_owner: boolean
  my_response_id?: string
  my_response_status?: string
  can_respond: boolean
  can_confirm_result: boolean
  meeting_result: string
}
export type ActivityPage = { items: Activity[]; page: number; page_size: number; has_more: boolean }
export type ResponseItem = {
  id: string
  status: string
  decision_reason?: string
  created_at: string
  user: Profile
}
