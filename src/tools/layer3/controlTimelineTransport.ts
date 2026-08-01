import { z } from "zod";
import { tryEndpoint } from "../../td-client/types.js";
import { buildPayloadScript, parsePythonReport } from "../pythonReport.js";
import { errorResult, guardTd, structuredResult } from "../result.js";
import type { ToolContext, ToolRegistrar } from "../types.js";

export const controlTimelineTransportSchema = z.object({
  action: z
    .enum(["play", "pause", "seek", "cue", "rate"])
    .describe(
      "Transport verb: play — start playback; pause — stop playback; seek — jump to a frame; cue — compatibility verb that directs callers to manage_cue; rate — set timeline frames per second.",
    ),
  frame: z
    .number()
    .int()
    .optional()
    .describe("Target frame for seek (required when action='seek')."),
  rate: z
    .number()
    .positive()
    .optional()
    .describe(
      "Timeline frame rate in frames per second (required when action='rate'; commonly 24, 30, or 60).",
    ),
  cueName: z
    .string()
    .optional()
    .describe("Cue label included in the compatibility error when action='cue'."),
});

export type ControlTimelineTransportArgs = z.infer<typeof controlTimelineTransportSchema>;

export interface TimelineState {
  action: string;
  play: boolean;
  frame: number;
  rate: number;
  startFrame: number;
  endFrame: number;
  fps: number;
}

const PAYLOAD_TEMPLATE = `
import base64, json, sys
_payload_b64 = "__PAYLOAD_B64__"
PAYLOAD = json.loads(base64.b64decode(_payload_b64).decode("utf-8"))

_action = PAYLOAD["action"]
_time = op('/').time

if _action == "play":
    _time.play = True
elif _action == "pause":
    _time.play = False
elif _action == "seek":
    _target = max(_time.start, min(int(PAYLOAD["frame"]), _time.end))
    _time.frame = _target
elif _action == "cue":
    _name = PAYLOAD["cueName"]
    raise RuntimeError(f"TouchDesigner's root timeline has no named-cue API; use manage_cue to recall '{_name}'")
elif _action == "rate":
    _time.rate = float(PAYLOAD["rate"])

import json as _json
result = {
    "action": PAYLOAD["action"],
    "play": bool(_time.play),
    "frame": int(_time.frame),
    "rate": float(_time.rate),
    "startFrame": int(_time.start),
    "endFrame": int(_time.end),
    "fps": float(_time.rate),
}
print(_json.dumps(result))
`.trim();

export async function controlTimelineTransportImpl(
  ctx: ToolContext,
  args: ControlTimelineTransportArgs,
): Promise<ReturnType<typeof structuredResult>> {
  // Cross-field validation
  if (args.action === "seek" && args.frame === undefined) {
    return errorResult("seek requires `frame`");
  }
  if (args.action === "cue" && !args.cueName) {
    return errorResult("cue requires `cueName`");
  }
  if (args.action === "rate" && args.rate === undefined) {
    return errorResult("rate requires `rate`");
  }

  const payload: Record<string, unknown> = { action: args.action };
  if (args.frame !== undefined) payload.frame = args.frame;
  if (args.rate !== undefined) payload.rate = args.rate;
  if (args.cueName !== undefined) payload.cueName = args.cueName;

  const script = buildPayloadScript(PAYLOAD_TEMPLATE, payload);

  return guardTd(
    async () => {
      // 1) First-class endpoint POST /api/transport — survives ALLOW_EXEC=0 and
      //    is the same response shape (TransportStateSchema) the exec path emits.
      // 2) Fall back to exec ONLY when the endpoint is absent on an older bridge;
      //    validation 400s (e.g. unknown cue) surface unchanged via tryEndpoint.
      return tryEndpoint<TimelineState>(
        async () => {
          const endpointPayload: Parameters<typeof ctx.client.controlTimelineTransport>[0] = {
            action: args.action,
          };
          if (args.frame !== undefined) endpointPayload.frame = args.frame;
          if (args.rate !== undefined) endpointPayload.rate = args.rate;
          if (args.cueName !== undefined) endpointPayload.cueName = args.cueName;
          const state = await ctx.client.controlTimelineTransport(endpointPayload);
          return state as TimelineState;
        },
        async () => {
          const res = await ctx.client.executePythonScript(script, true);
          const stdout = (res as { stdout?: string }).stdout;
          return parsePythonReport<TimelineState>(stdout);
        },
      );
    },
    (state) => {
      const msg = `Timeline ${state.action} (frame ${state.frame}, ${state.fps} fps)`;
      return structuredResult(msg, state);
    },
  );
}

export const registerControlTimelineTransport: ToolRegistrar = (server, ctx) =>
  server.registerTool(
    "control_timeline_transport",
    {
      title: "Control Timeline Transport",
      description:
        "Drive TouchDesigner's root timeline: play, pause, seek to a frame, or set its frame rate. The legacy cue verb returns an error because root time has no named-cue API; use manage_cue for scene cues. Returns the resulting timeline state. NOTE: pausing will freeze any downstream motion/feedback/frame-diff chain — expected behaviour, not a bug.",
      inputSchema: controlTimelineTransportSchema.shape,
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    (args) => controlTimelineTransportImpl(ctx, args),
  );
