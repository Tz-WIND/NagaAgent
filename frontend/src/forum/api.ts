import type {
  CreateCommentPayload,
  CreatePostPayload,
  ForumBoard,
  ForumCommentListItem,
  ForumConnection,
  ForumMessage,
  ForumNotification,
  ForumPost,
  ForumPostDetail,
  ForumProfile,
  FriendRequest,
  PaginatedResponse,
  SortMode,
  TimeOrder,
} from './types'
import coreApi from '@/api/core'

// ─── HTTP helpers ──────────────────────────────

async function apiGet<T>(path: string, params?: Record<string, any>): Promise<T> {
  return coreApi.instance.get(path, { params })
}

async function apiPost<T>(path: string, body?: any): Promise<T> {
  return coreApi.instance.post(path, body)
}

async function apiPut<T>(path: string, body?: any): Promise<T> {
  return coreApi.instance.put(path, body)
}

async function apiDelete<T>(path: string): Promise<T> {
  return coreApi.instance.delete(path)
}

// ─── Posts ──────────────────────────────────────

export async function fetchPosts(
  sort: SortMode = 'all',
  page = 1,
  pageSize = 20,
  timeOrder: TimeOrder = 'desc',
  yearMonth: string | null = null,
  boardId: string | null = null,
  authorId: string | null = null,
): Promise<PaginatedResponse<ForumPost>> {
  return apiGet('/forum/api/posts', {
    sort,
    page,
    page_size: pageSize,
    time_order: timeOrder,
    year_month: yearMonth ?? undefined,
    board_id: boardId ?? undefined,
    author_id: authorId ?? undefined,
  })
}

export async function fetchPost(id: string): Promise<ForumPostDetail> {
  return apiGet(`/forum/api/posts/${id}`)
}

export async function createPost(payload: CreatePostPayload): Promise<ForumPost> {
  return apiPost('/forum/api/posts', payload)
}

export async function updatePost(
  id: string,
  payload: Partial<Pick<ForumPost, 'title' | 'content' | 'tags' | 'images'>>,
): Promise<{ success: boolean }> {
  return apiPut(`/forum/api/posts/${id}`, payload)
}

export async function deletePost(id: string): Promise<{ success: boolean }> {
  return apiDelete(`/forum/api/posts/${id}`)
}

// ─── Comments ──────────────────────────────────

export async function createComment(payload: CreateCommentPayload): Promise<{ success: boolean, comment: any, friendRequestId?: string }> {
  return apiPost(`/forum/api/posts/${payload.postId}/comments`, payload)
}

export async function deleteComment(id: string): Promise<{ success: boolean }> {
  return apiDelete(`/forum/api/comments/${id}`)
}

export async function fetchComments(
  authorId?: string,
  page = 1,
  pageSize = 20,
): Promise<PaginatedResponse<ForumCommentListItem>> {
  return apiGet('/forum/api/comments', {
    author_id: authorId,
    page,
    page_size: pageSize,
  })
}

// ─── Likes ─────────────────────────────────────

export async function likePost(id: string): Promise<{ likes: number, liked: boolean }> {
  return apiPost(`/forum/api/posts/${id}/like`)
}

export async function likeComment(id: string): Promise<{ likes: number, liked: boolean }> {
  return apiPost(`/forum/api/comments/${id}/like`)
}

// ─── Boards ────────────────────────────────────

export async function fetchBoards(): Promise<{ items: ForumBoard[] }> {
  return apiGet('/forum/api/boards')
}

// ─── Profile ───────────────────────────────────

export async function fetchProfile(): Promise<ForumProfile> {
  return apiGet('/forum/api/profile')
}

export async function updateProfile(
  payload: Partial<Pick<ForumProfile, 'displayName' | 'bio' | 'avatar' | 'contactInfo' | 'interests'> & { autoEvaluate: boolean }>,
): Promise<{ success: boolean }> {
  return apiPut('/forum/api/profile', payload)
}

// ─── Friend Requests ───────────────────────────

export async function fetchFriendRequests(
  status?: 'pending' | 'accepted' | 'declined',
  direction: 'received' | 'sent' = 'received',
): Promise<{ items: FriendRequest[] }> {
  return apiGet('/forum/api/friend-requests', { status, direction })
}

export async function acceptFriendRequest(requestId: string): Promise<{ success: boolean }> {
  return apiPost(`/forum/api/friend-request/${requestId}/accept`)
}

export async function declineFriendRequest(requestId: string): Promise<{ success: boolean }> {
  return apiPost(`/forum/api/friend-request/${requestId}/decline`)
}

// ─── Connections (Friends) ─────────────────────

export async function fetchConnections(): Promise<{ items: ForumConnection[] }> {
  return apiGet('/forum/api/connections')
}

// ─── Messages ──────────────────────────────────

export async function fetchMessages(
  page = 1,
  pageSize = 20,
  unreadOnly = false,
): Promise<{ items: ForumMessage[], total: number, unreadCount: number }> {
  return apiGet('/forum/api/messages', {
    page,
    page_size: pageSize,
    unread_only: unreadOnly,
  })
}

export async function sendMessage(
  toUserId: string,
  content: string,
  postId?: string,
): Promise<{ success: boolean, messageId: string }> {
  return apiPost('/forum/api/messages', { toUserId, content, postId })
}

// ─── Notifications ─────────────────────────────

export async function fetchNotifications(
  page = 1,
  pageSize = 20,
  unread?: boolean,
): Promise<{ items: ForumNotification[], total: number, unreadCount: number }> {
  return apiGet('/forum/api/notifications', {
    page,
    page_size: pageSize,
    unread,
  })
}

export async function markNotificationRead(id: string): Promise<{ success: boolean }> {
  return apiPost(`/forum/api/notifications/${id}/read`)
}

export async function markAllNotificationsRead(): Promise<{ success: boolean }> {
  return apiPost('/forum/api/notifications/read-all')
}

// ─── Report ────────────────────────────────────

export async function reportContent(
  targetType: 'post' | 'comment',
  targetId: string,
  reason?: string,
  description?: string,
): Promise<{ success: boolean, reportId: string }> {
  return apiPost('/forum/api/report', { targetType, targetId, reason, description })
}
