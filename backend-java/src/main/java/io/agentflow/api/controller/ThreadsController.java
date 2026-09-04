package io.agentflow.api.controller;

import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.dto.ThreadCreateRequest;
import io.agentflow.api.dto.ThreadMessageResponse;
import io.agentflow.api.dto.ThreadResponse;
import io.agentflow.api.service.ThreadService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/threads")
public class ThreadsController {

    private final ThreadService service;

    public ThreadsController(ThreadService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ThreadResponse create(@Valid @RequestBody ThreadCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping
    public List<ThreadResponse> list(@RequestParam(defaultValue = "50") int limit) {
        return service.list(limit);
    }

    @GetMapping("/{id}")
    public ThreadResponse get(@PathVariable String id) {
        return service.get(id);
    }

    @GetMapping("/{id}/messages")
    public ThreadMessageResponse.Page listMessages(
            @PathVariable String id,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "50") int limit) {
        return service.listMessages(id, cursor, limit);
    }

    @GetMapping("/{id}/runs")
    public List<RunResponse> listRuns(
            @PathVariable String id, @RequestParam(defaultValue = "50") int limit) {
        return service.listRuns(id, limit);
    }
}
