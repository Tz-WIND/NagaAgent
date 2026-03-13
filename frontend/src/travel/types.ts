export interface TravelDiscovery {
  url: string
  title: string
  summary: string
  foundAt: string
  tags: string[]
}

export interface SocialInteraction {
  type: string
  postId?: string
  contentPreview: string
  timestamp: string
}

export interface TravelSession {
  sessionId: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  createdAt: string
  startedAt?: string
  completedAt?: string
  agentId?: string
  agentName?: string
  timeLimitMinutes: number
  creditLimit: number
  wantFriends: boolean
  friendDescription?: string
  goalPrompt?: string
  postToForum?: boolean
  deliverFullReport?: boolean
  deliverChannel?: string
  deliverTo?: string
  openclawSessionKey?: string
  tokensUsed: number
  creditsUsed: number
  elapsedMinutes: number
  toolStats?: Record<string, number>
  uniqueSources?: number
  wrapUpSent?: boolean
  idlePolls?: number
  discoveries: TravelDiscovery[]
  socialInteractions: SocialInteraction[]
  summary?: string
  forumDigest?: string
  forumPostId?: string
  forumPostStatus?: string
  fullReportDeliveryStatus?: string
  error?: string
}
