package io.agentflow.api.controller;

import io.agentflow.api.service.EventStreamService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/v1/events")
public class EventsController {

    private final EventStreamService events;

    public EventsController(EventStreamService events) {
        this.events = events;
    }

    @GetMapping(value = "/{runId}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(
            @PathVariable String runId,
            @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
            @RequestParam(value = "last_event_id", required = false) String lastEventIdParam) {
        String after =
                lastEventId != null && !lastEventId.isBlank() ? lastEventId : lastEventIdParam;
        return events.subscribe(runId, after);
    }
}
