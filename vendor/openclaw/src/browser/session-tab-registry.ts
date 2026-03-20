import { browserCloseTab } from "./client.js";

export type TrackedSessionBrowserTab = {
  sessionKey: string;
  targetId: string;
  baseUrl?: string;
  profile?: string;
  trackedAt: number;
  lastActiveAt: number;
  idleTimeoutMs?: number;
  closeTimer?: ReturnType<typeof setTimeout>;
};

const trackedTabsBySession = new Map<string, Map<string, TrackedSessionBrowserTab>>();

function normalizeSessionKey(raw: string): string {
  return raw.trim().toLowerCase();
}

function normalizeTargetId(raw: string): string {
  return raw.trim();
}

function normalizeProfile(raw?: string): string | undefined {
  if (!raw) {
    return undefined;
  }
  const trimmed = raw.trim();
  return trimmed ? trimmed.toLowerCase() : undefined;
}

function normalizeBaseUrl(raw?: string): string | undefined {
  if (!raw) {
    return undefined;
  }
  const trimmed = raw.trim();
  return trimmed ? trimmed : undefined;
}

function toTrackedTabId(params: { targetId: string; baseUrl?: string; profile?: string }): string {
  return `${params.targetId}\u0000${params.baseUrl ?? ""}\u0000${params.profile ?? ""}`;
}

function isIgnorableCloseError(err: unknown): boolean {
  const message = String(err).toLowerCase();
  return (
    message.includes("tab not found") ||
    message.includes("target closed") ||
    message.includes("target not found") ||
    message.includes("no such target")
  );
}

function clearTrackedTabTimer(tab: TrackedSessionBrowserTab) {
  if (!tab.closeTimer) {
    return;
  }
  clearTimeout(tab.closeTimer);
  tab.closeTimer = undefined;
}

function deleteTrackedTab(sessionKey: string, trackedId: string) {
  const trackedForSession = trackedTabsBySession.get(sessionKey);
  if (!trackedForSession) {
    return;
  }
  const tracked = trackedForSession.get(trackedId);
  if (tracked) {
    clearTrackedTabTimer(tracked);
  }
  trackedForSession.delete(trackedId);
  if (trackedForSession.size === 0) {
    trackedTabsBySession.delete(sessionKey);
  }
}

function scheduleTrackedTabClose(tab: TrackedSessionBrowserTab) {
  clearTrackedTabTimer(tab);
  if (!tab.idleTimeoutMs || tab.idleTimeoutMs <= 0) {
    return;
  }
  const trackedId = toTrackedTabId(tab);
  tab.closeTimer = setTimeout(async () => {
    try {
      await browserCloseTab(tab.baseUrl, tab.targetId, {
        profile: tab.profile,
      });
    } catch (err) {
      if (!isIgnorableCloseError(err)) {
        // Ignore non-fatal close errors; timer is best-effort cleanup.
      }
    } finally {
      deleteTrackedTab(tab.sessionKey, trackedId);
    }
  }, tab.idleTimeoutMs);
  tab.closeTimer.unref?.();
}

export function trackSessionBrowserTab(params: {
  sessionKey?: string;
  targetId?: string;
  baseUrl?: string;
  profile?: string;
  idleTimeoutMs?: number;
}): void {
  const sessionKeyRaw = params.sessionKey?.trim();
  const targetIdRaw = params.targetId?.trim();
  if (!sessionKeyRaw || !targetIdRaw) {
    return;
  }
  const sessionKey = normalizeSessionKey(sessionKeyRaw);
  const targetId = normalizeTargetId(targetIdRaw);
  const baseUrl = normalizeBaseUrl(params.baseUrl);
  const profile = normalizeProfile(params.profile);
  const tracked: TrackedSessionBrowserTab = {
    sessionKey,
    targetId,
    baseUrl,
    profile,
    trackedAt: Date.now(),
    lastActiveAt: Date.now(),
    idleTimeoutMs:
      typeof params.idleTimeoutMs === "number" && Number.isFinite(params.idleTimeoutMs)
        ? Math.max(0, Math.floor(params.idleTimeoutMs))
        : undefined,
  };
  const trackedId = toTrackedTabId(tracked);
  let trackedForSession = trackedTabsBySession.get(sessionKey);
  if (!trackedForSession) {
    trackedForSession = new Map();
    trackedTabsBySession.set(sessionKey, trackedForSession);
  }
  const existing = trackedForSession.get(trackedId);
  if (existing) {
    clearTrackedTabTimer(existing);
  }
  trackedForSession.set(trackedId, tracked);
  scheduleTrackedTabClose(tracked);
}

export function touchTrackedBrowserTabsForSession(params: {
  sessionKey?: string;
  idleTimeoutMs?: number;
}): number {
  const sessionKeyRaw = params.sessionKey?.trim();
  if (!sessionKeyRaw) {
    return 0;
  }
  const sessionKey = normalizeSessionKey(sessionKeyRaw);
  const trackedForSession = trackedTabsBySession.get(sessionKey);
  if (!trackedForSession || trackedForSession.size === 0) {
    return 0;
  }
  const now = Date.now();
  for (const tracked of trackedForSession.values()) {
    tracked.lastActiveAt = now;
    if (typeof params.idleTimeoutMs === "number" && Number.isFinite(params.idleTimeoutMs)) {
      tracked.idleTimeoutMs = Math.max(0, Math.floor(params.idleTimeoutMs));
    }
    scheduleTrackedTabClose(tracked);
  }
  return trackedForSession.size;
}

export function untrackSessionBrowserTab(params: {
  sessionKey?: string;
  targetId?: string;
  baseUrl?: string;
  profile?: string;
}): void {
  const sessionKeyRaw = params.sessionKey?.trim();
  const targetIdRaw = params.targetId?.trim();
  if (!sessionKeyRaw || !targetIdRaw) {
    return;
  }
  const sessionKey = normalizeSessionKey(sessionKeyRaw);
  const trackedForSession = trackedTabsBySession.get(sessionKey);
  if (!trackedForSession) {
    return;
  }
  const trackedId = toTrackedTabId({
    targetId: normalizeTargetId(targetIdRaw),
    baseUrl: normalizeBaseUrl(params.baseUrl),
    profile: normalizeProfile(params.profile),
  });
  deleteTrackedTab(sessionKey, trackedId);
}

function takeTrackedTabsForSessionKeys(
  sessionKeys: Array<string | undefined>,
): TrackedSessionBrowserTab[] {
  const uniqueSessionKeys = new Set<string>();
  for (const key of sessionKeys) {
    if (!key?.trim()) {
      continue;
    }
    uniqueSessionKeys.add(normalizeSessionKey(key));
  }
  if (uniqueSessionKeys.size === 0) {
    return [];
  }
  const seenTrackedIds = new Set<string>();
  const tabs: TrackedSessionBrowserTab[] = [];
  for (const sessionKey of uniqueSessionKeys) {
    const trackedForSession = trackedTabsBySession.get(sessionKey);
    if (!trackedForSession || trackedForSession.size === 0) {
      continue;
    }
    trackedTabsBySession.delete(sessionKey);
    for (const tracked of trackedForSession.values()) {
      clearTrackedTabTimer(tracked);
      const trackedId = toTrackedTabId(tracked);
      if (seenTrackedIds.has(trackedId)) {
        continue;
      }
      seenTrackedIds.add(trackedId);
      tabs.push(tracked);
    }
  }
  return tabs;
}

export async function closeTrackedBrowserTabsForSessions(params: {
  sessionKeys: Array<string | undefined>;
  closeTab?: (tab: { targetId: string; baseUrl?: string; profile?: string }) => Promise<void>;
  onWarn?: (message: string) => void;
}): Promise<number> {
  const tabs = takeTrackedTabsForSessionKeys(params.sessionKeys);
  if (tabs.length === 0) {
    return 0;
  }
  const closeTab =
    params.closeTab ??
    (async (tab: { targetId: string; baseUrl?: string; profile?: string }) => {
      await browserCloseTab(tab.baseUrl, tab.targetId, {
        profile: tab.profile,
      });
    });
  let closed = 0;
  for (const tab of tabs) {
    try {
      await closeTab({
        targetId: tab.targetId,
        baseUrl: tab.baseUrl,
        profile: tab.profile,
      });
      closed += 1;
    } catch (err) {
      if (!isIgnorableCloseError(err)) {
        params.onWarn?.(`failed to close tracked browser tab ${tab.targetId}: ${String(err)}`);
      }
    }
  }
  return closed;
}

export function __resetTrackedSessionBrowserTabsForTests(): void {
  for (const trackedForSession of trackedTabsBySession.values()) {
    for (const tracked of trackedForSession.values()) {
      clearTrackedTabTimer(tracked);
    }
  }
  trackedTabsBySession.clear();
}

export function __countTrackedSessionBrowserTabsForTests(sessionKey?: string): number {
  if (typeof sessionKey === "string" && sessionKey.trim()) {
    return trackedTabsBySession.get(normalizeSessionKey(sessionKey))?.size ?? 0;
  }
  let count = 0;
  for (const tracked of trackedTabsBySession.values()) {
    count += tracked.size;
  }
  return count;
}
