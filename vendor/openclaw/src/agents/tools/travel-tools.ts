import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { URL } from "node:url";
import { Type } from "@sinclair/typebox";
import type { AnyAgentTool } from "./common.js";
import { jsonResult, readStringArrayParam, readStringParam, ToolInputError } from "./common.js";

type TravelSessionRecord = {
  session_id?: string;
  status?: string;
  phase?: string;
  goal_prompt?: string;
  agent_id?: string | null;
  agent_name?: string | null;
  openclaw_session_key?: string | null;
  credits_used?: number;
  credit_limit?: number;
  elapsed_minutes?: number;
  time_limit_minutes?: number;
  discoveries?: Array<Record<string, unknown>>;
  progress_events?: Array<Record<string, unknown>>;
  unique_sources?: number;
  sources?: string[];
  summary_report_path?: string | null;
  summary_report_title?: string | null;
};

const TravelProgressToolSchema = Type.Object({
  message: Type.String({ minLength: 1 }),
  level: Type.Optional(Type.Union([Type.Literal("info"), Type.Literal("warn"), Type.Literal("error")])),
});

const TravelDiscoveryToolSchema = Type.Object({
  url: Type.String({ minLength: 1 }),
  title: Type.String({ minLength: 1 }),
  summary: Type.String({ minLength: 1 }),
  tags: Type.Optional(Type.Array(Type.String())),
  source: Type.Optional(Type.String()),
  siteName: Type.Optional(Type.String()),
});

const TravelStateToolSchema = Type.Object({});

const TravelSummaryToolSchema = Type.Object({
  title: Type.String({ minLength: 1 }),
  content: Type.String({ minLength: 1 }),
});

function normalizeTravelSessionKey(raw?: string): string {
  const value = raw?.trim() ?? "";
  if (!value) {
    return "";
  }
  if (value.startsWith("travel:")) {
    return value;
  }
  const idx = value.indexOf("travel:");
  return idx >= 0 ? value.slice(idx) : "";
}

function ensureTravelSessionKey(sessionKey?: string): string {
  const normalized = normalizeTravelSessionKey(sessionKey);
  if (!normalized) {
    throw new ToolInputError("This tool is only available during NagaTravel exploration sessions.");
  }
  return normalized;
}

function resolveTravelDir(): string {
  const stateDir = process.env.OPENCLAW_STATE_DIR?.trim();
  if (stateDir) {
    let cursor = path.resolve(stateDir);
    while (true) {
      if (path.basename(cursor) === "agents") {
        return path.join(path.dirname(cursor), "travel");
      }
      const parent = path.dirname(cursor);
      if (parent === cursor) {
        break;
      }
      cursor = parent;
    }
  }
  const homeDir = process.env.HOME?.trim() || process.cwd();
  return path.join(homeDir, ".naga", "travel");
}

function deriveSourceList(session: TravelSessionRecord): string[] {
  if (Array.isArray(session.sources) && session.sources.length > 0) {
    return session.sources.map((item) => String(item).trim()).filter(Boolean);
  }
  const discoveries = Array.isArray(session.discoveries) ? session.discoveries : [];
  const seen = new Set<string>();
  const sources: string[] = [];
  for (const discovery of discoveries) {
    const rawSiteName = typeof discovery?.site_name === "string" ? discovery.site_name : undefined;
    const rawUrl = typeof discovery?.url === "string" ? discovery.url : "";
    let source = rawSiteName?.trim() ?? "";
    if (!source && rawUrl) {
      try {
        source = new URL(rawUrl).host;
      } catch {
        source = rawUrl;
      }
    }
    if (!source || seen.has(source)) {
      continue;
    }
    seen.add(source);
    sources.push(source);
  }
  return sources;
}

async function loadTravelSessionForKey(sessionKey: string): Promise<TravelSessionRecord> {
  const travelDir = resolveTravelDir();
  const entries = await fs.readdir(travelDir, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) {
      continue;
    }
    if (entry.name === "browser-policies.json") {
      continue;
    }
    const filePath = path.join(travelDir, entry.name);
    try {
      const payload = JSON.parse(await fs.readFile(filePath, "utf-8")) as TravelSessionRecord;
      if ((payload.openclaw_session_key || "").trim() === sessionKey) {
        return payload;
      }
    } catch {
      // ignore malformed travel session files
    }
  }
  throw new ToolInputError(`No travel session found for sessionKey=${sessionKey}`);
}

function buildTravelSummaryMarkdown(params: { title: string; content: string }): string {
  const title = params.title.trim();
  const body = params.content.trim();
  if (!body) {
    return `# ${title}\n`;
  }
  if (body.startsWith("#")) {
    return body.endsWith("\n") ? body : `${body}\n`;
  }
  return `# ${title}\n\n${body}${body.endsWith("\n") ? "" : "\n"}`;
}

export function createTravelProgressTool(opts?: { agentSessionKey?: string }): AnyAgentTool {
  return {
    label: "Travel Progress",
    name: "travel_progress",
    description:
      "Record a short progress update for the current NagaTravel exploration. Use after meaningful steps, pivots, or blockers so the UI can show recent progress.",
    parameters: TravelProgressToolSchema,
    execute: async (_toolCallId, args) => {
      const sessionKey = ensureTravelSessionKey(opts?.agentSessionKey);
      const params = args as Record<string, unknown>;
      const message = readStringParam(params, "message", { required: true });
      const level = readStringParam(params, "level") ?? "info";
      return jsonResult({
        ok: true,
        kind: "travel_progress",
        sessionKey,
        message,
        level,
      });
    },
  };
}

export function createTravelDiscoveryTool(opts?: { agentSessionKey?: string }): AnyAgentTool {
  return {
    label: "Travel Discovery",
    name: "travel_discovery",
    description:
      "Record a confirmed exploration discovery with url/title/summary so NagaTravel can persist it without relying on free-form text extraction.",
    parameters: TravelDiscoveryToolSchema,
    execute: async (_toolCallId, args) => {
      const sessionKey = ensureTravelSessionKey(opts?.agentSessionKey);
      const params = args as Record<string, unknown>;
      const url = readStringParam(params, "url", { required: true });
      const title = readStringParam(params, "title", { required: true });
      const summary = readStringParam(params, "summary", { required: true });
      const tags = readStringArrayParam(params, "tags") ?? [];
      const source = readStringParam(params, "source");
      const siteName = readStringParam(params, "siteName");
      return jsonResult({
        ok: true,
        kind: "travel_discovery",
        sessionKey,
        url,
        title,
        summary,
        tags,
        ...(source ? { source } : {}),
        ...(siteName ? { site_name: siteName } : {}),
      });
    },
  };
}

export function createTravelStateTool(opts?: { agentSessionKey?: string }): AnyAgentTool {
  return {
    label: "Travel State",
    name: "travel_state",
    description:
      "Read the current NagaTravel exploration state: status, progress events, discoveries, and derived source list. Use this when you need the current accumulated travel context.",
    parameters: TravelStateToolSchema,
    execute: async () => {
      const sessionKey = ensureTravelSessionKey(opts?.agentSessionKey);
      const session = await loadTravelSessionForKey(sessionKey);
      const sources = deriveSourceList(session);
      return jsonResult({
        ok: true,
        sessionId: session.session_id,
        sessionKey,
        status: session.status,
        phase: session.phase,
        goalPrompt: session.goal_prompt,
        creditsUsed: session.credits_used ?? 0,
        creditLimit: session.credit_limit ?? 0,
        elapsedMinutes: session.elapsed_minutes ?? 0,
        timeLimitMinutes: session.time_limit_minutes ?? 0,
        discoveries: Array.isArray(session.discoveries) ? session.discoveries : [],
        sources,
        uniqueSources: session.unique_sources ?? sources.length,
        progressEvents: Array.isArray(session.progress_events) ? session.progress_events : [],
      });
    },
  };
}

export function createTravelSummaryTool(opts?: { agentSessionKey?: string }): AnyAgentTool {
  return {
    label: "Travel Summary",
    name: "travel_summary",
    description:
      "Persist the final NagaTravel exploration report as a markdown file inside ~/.naga/travel and return the saved file path. Use this during the wrap-up stage after reviewing travel_state.",
    parameters: TravelSummaryToolSchema,
    execute: async (_toolCallId, args) => {
      const sessionKey = ensureTravelSessionKey(opts?.agentSessionKey);
      const params = args as Record<string, unknown>;
      const title = readStringParam(params, "title", { required: true });
      const content = readStringParam(params, "content", { required: true });
      const travelDir = resolveTravelDir();
      await fs.mkdir(travelDir, { recursive: true });
      const fileName = `${randomUUID()}.md`;
      const filePath = path.join(travelDir, fileName);
      const markdown = buildTravelSummaryMarkdown({ title, content });
      await fs.writeFile(filePath, markdown, "utf-8");
      return jsonResult({
        ok: true,
        kind: "travel_summary",
        sessionKey,
        title,
        file_name: fileName,
        file_path: filePath,
        bytes: Buffer.byteLength(markdown, "utf-8"),
      });
    },
  };
}
