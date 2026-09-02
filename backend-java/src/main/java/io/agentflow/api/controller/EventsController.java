package io.agentflow.api.controller;

import io.agentflow.api.service.EventStreamService;
import io.agentflow.api.service.RunService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/v1/events")
@Tag(name = "Events", description = "Server-Sent Events for run lifecycle streaming.")
public class EventsController {

    private final EventStreamService events;
    private final RunService runs;

    public EventsController(EventStreamService events, RunService runs) {
        this.events = events;
        this.runs = runs;
    }

    @GetMapping(value = "/{runId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(
            summary = "Subscribe to run events",
            description =
                    """
                    Opens an SSE stream of RunEvent frames until the run reaches a terminal state.
                    Reconnect with the Last-Event-ID header or last_event_id query parameter to replay
                    missed events from Redis before resuming live delivery.""")
    @ApiResponse(
            responseCode = "200",
            description = "text/event-stream of RunEvent JSON payloads",
            content =
                    @Content(
                            mediaType = MediaType.TEXT_EVENT_STREAM_VALUE,
                            schema = @Schema(implementation = io.agentflow.api.dto.RunEvent.class)))
    public ResponseEntity<SseEmitter> stream(
            @PathVariable String runId,
            @Parameter(description = "Replay events after this SSE id.")
                    @RequestHeader(value = "Last-Event-ID", required = false)
                    String lastEventId,
            @Parameter(description = "Query alias for Last-Event-ID.")
                    @RequestParam(value = "last_event_id", required = false)
                    String lastEventIdParam) {
        runs.requireAccessible(runId);
        String after =
                lastEventId != null && !lastEventId.isBlank() ? lastEventId : lastEventIdParam;
        SseEmitter emitter = events.subscribe(runId, after);
        return ResponseEntity.ok()
                .header("Cache-Control", "no-cache")
                .header("Connection", "keep-alive")
                .header("X-Accel-Buffering", "no")
                .body(emitter);
    }
}
