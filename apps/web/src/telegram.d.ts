interface TelegramWebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  ready(): void
  expand(): void
  openTelegramLink(url: string): void
  setHeaderColor(color: string): void
}
interface Window {
  Telegram?: { WebApp: TelegramWebApp }
}
